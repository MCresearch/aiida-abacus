import json
import pathlib
import tempfile
import typing as t
import zipfile
from collections import Counter
from contextlib import contextmanager
from itertools import chain
from shutil import rmtree

from aiida import orm
from aiida.common.exceptions import MultipleObjectsError, NotExistent
from aiida_pseudo.data.pseudo.upf import parse_element
from aiida_pseudo.groups.family import PseudoPotentialFamily
from tqdm import tqdm

from aiida_abacus.data.orbital import AtomicOrbitalData

FilePath = t.Union[str, pathlib.PurePosixPath]


class AtomicOrbitalCollection(orm.Group):
    """
    Class for importing abacus orbital data
    Data source
    https://github.com/abacusmodeling/ABACUS-orbitals
    """

    @classmethod
    def import_orbital_set(cls, repository: FilePath, set_name: str, dryrun=False, group_label=None):
        """
        Import a specific subset of the orbitals
        """

        pp_path = pathlib.Path(repository) / f"{set_name}/Pseudopotential"
        orb_path = pathlib.Path(repository) / f"{set_name}/Orbitals"
        new_nodes = []
        orbital_files = list(orb_path.glob("*/*.orb"))
        print(f"Number of orbital files found: {len(orbital_files)}")
        for path in tqdm(chain(pp_path.glob("*.upf"), pp_path.glob("*.UPF")), desc="Scanning elements"):
            element = parse_element(path.read_text())
            # Find the corresponding orbital
            for orb_folder in orb_path.glob(f"{element}_*"):
                orb_type = orb_folder.name.split("_")[-1].lower()  # Use lowercase dzp/tdzp etc
                for orb in orbital_files:
                    if not orb.stem.startswith(element + "_"):
                        continue
                    orb_info = parse_orb_filename(orb)
                    orb_node = AtomicOrbitalData.get_or_create(path, orb)
                    orb_element = orb_info.pop("element")
                    orb_info["orbital_type"] = orb_type
                    assert element == orb_element, "Orbital element does not match that of the pseudopotential"
                    orb_node.base.attributes.set_many(orb_info)
                    new_nodes.append(orb_node)
        print(f"About to import {len(new_nodes)} nodes")
        group_label = group_label if group_label is not None else set_name
        group = cls.collection.get_or_create(label=group_label)[0]
        print(f"Number of existing nodes in group {group_label}: {group.count()}")
        if not dryrun:
            for node in tqdm(new_nodes, desc="Storing nodes"):
                node.store()
            group.add_nodes(new_nodes)
        else:
            print("Dry run, not storing any nodes")

    def get_orbital(
        self, element: str, orbital_type: str, rcut: float, cut_off_energy=None, electron_config=None, functional=None
    ):
        """Find an orbital for a given element, rcut, cut_off_energy and element_config"""

        node_filters = {
            "attributes.element": element,
            "attributes.orbital_type": orbital_type,
            "attributes.rcut_au": rcut,
        }

        if cut_off_energy is not None:
            node_filters["attributes.cut_off_energy_ry"] = cut_off_energy
        if electron_config is not None:
            node_filters["attributes.electron_config"] = electron_config
        if functional is not None:
            node_filters["attributes.functional"] = functional
        q = orm.QueryBuilder()
        q.append(
            type(self),
            filters={
                "pk": self.pk,
            },
            tag="group",
        )
        q.append(AtomicOrbitalData, with_group="group", filters=node_filters)
        try:
            node = q.one()[0]
        except MultipleObjectsError as _:
            raise MultipleObjectsError("More than one orbital found for the given parameters")
        except NotExistent as _:
            raise NotExistent("No orbital found for the given parameters")
        return node

    def create_family(self, family_label, orbital_type, rcuts_dict: t.Union[dict, str]):
        """
        Create a PseudopotentialFamily using a given specification
        :param family_label: Label for the family
        :param orbital_type: Type of orbital, usually dzp or tzdp.
        :param rcuts_dict: Dictionary of rcut values for each element or path to a JSON file.
        :return: PseudopotentialFamily created based on the rcuts_dict and the orbital_type.
        """
        if isinstance(rcuts_dict, str):
            rcuts_dict = json.loads(pathlib.Path(rcuts_dict).read_text())
        orbs = []
        # Find all elements
        elements = set([orb.element for orb in self.nodes])
        for element in tqdm(elements, desc="Processing element"):
            rcut = rcuts_dict.get(element)
            if rcut is None:
                rcut = rcuts_dict["Other"]
            orb = None
            # Find suitable cut off distance
            while rcut <= 12:
                try:
                    orb = self.get_orbital(element, orbital_type, rcut)
                except NotExistent as _:
                    print(f"No orbital found for {element} with rcut {rcut},  trying increasing it by 1")
                    rcut += 1
                if orb is not None:
                    break
            if orb is None:
                raise NotExistent(f"No orbital found for {element} with rcut {rcut}")
            orbs.append(orb)
        family = AtomicOrbitalFamily(label=family_label)
        family.store()
        family.add_nodes(orbs)
        return family


class AtomicOrbitalFamily(PseudoPotentialFamily):
    """A family of orbitals"""

    _pseudo_types = (AtomicOrbitalData,)


def parse_orb_filename(filename: FilePath):
    """Parse information from the filename"""
    key = pathlib.Path(filename).stem
    tokens = key.split("_")
    assert len(tokens) == 5, f"Invalid filename {filename}"
    return {
        "element": tokens[0],
        "functional": tokens[1],
        "rcut_au": float(tokens[2].replace("au", "")),
        "cut_off_energy_ry": float(tokens[3].replace("Ry", "")),
        "electron_config": tokens[4],
    }


class OrbitalFamilyImporter:
    """
    A class for importing atomic orbitals and their corresponding pseudopotential data from a folder/archive.
    A family of atomic orbitals is effectively an one-to-one mapping between elements and AtomicOrbitalData.
    """

    def __init__(self):
        """
        Import a family of orbitals in to the database
        """

    @classmethod
    def import_folder(cls, orbital_path, pseudo_path, label, dryrun=False) -> orm.Group:
        """
        Import the folder
        """
        with temporary_unzip_folder(orbital_path) as orb_path:
            with temporary_unzip_folder(pseudo_path) as pseudo_path:
                return cls._import_folders(orb_path, pseudo_path, label, dryrun)

    @staticmethod
    def _import_folders(
        orbital_path: pathlib.Path, pseudo_path: pathlib.Path, label: str, dryrun: bool = False
    ) -> orm.Group:
        """Inspect and import data"""
        orbital_files = []
        upf_files = []
        for path in orbital_path.rglob("*.orb"):
            metadata = parse_orb_metadata(path)
            orbital_files.append([metadata["Element"], path])

        for path in pseudo_path.rglob("*.upf"):
            element = parse_element(path.read_text())
            upf_files.append([element, path])

        # Check uniqueness of the elements and each orbital has its related UPF file
        orbital_counts = Counter(element for element, _ in orbital_files)
        upf_counts = Counter(element for element, _ in upf_files)
        for element, count in orbital_counts.items():
            if count > 1:
                raise RuntimeError(f"Error: Found {count} orbitals for element {element}!")
            if upf_counts[element] != 1:
                raise RuntimeError(f"Error: Found {upf_counts[element]} UPF files for element {element}!")

        # Create AtomicOrbitalData
        orbitals = {key: value for key, value in orbital_files}
        upfs = {key: value for key, value in upf_files}
        orbital_data = []
        for element, orbital_path in tqdm(orbitals.items(), desc="Orbitals"):
            if element not in upfs:
                raise RuntimeError(f"Error: No UPF file found for element {element}!")
            upf_path = upfs[element]
            if dryrun:
                print("Will import AtomicOrbitalData with:\n" f"Orbital: {orbital_path}\n" f"UPF: {upf_path}\n")
                node = AtomicOrbitalData.get_or_create(upf_path, orbital_path)
                if node.is_stored:
                    print(f"Reusing Node {node.pk} already exists in the database")
                continue

            orbital_data.append(AtomicOrbitalData.get_or_create(upf_path, orbital_path))
        if dryrun:
            return
        # Store and create the family group
        [node.store() for node in orbital_data]
        group = AtomicOrbitalFamily.collection.get_or_create(label=label)[0]
        group.add_nodes(orbital_data)
        return group


@contextmanager
def temporary_unzip_folder(zippath) -> t.Generator[pathlib.Path, None, None]:
    """Unzip a zip file to a temporary folder and yield the path to the folder."""
    if zippath.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmpdirname:
            with zipfile.ZipFile(zippath, "r") as zip_ref:
                zip_ref.extractall(tmpdirname)
            yield pathlib.Path(tmpdirname)
        rmtree(tmpdirname, ignore_errors=True)
    else:
        yield pathlib.Path(zippath)


def parse_orb_metadata(path) -> dict[str, str]:
    """Parse metadata from an orb file"""
    out = {}
    with open(path, mode="r") as fhandle:
        for line in fhandle:
            if "-----" in line:
                continue
            if "SUMMARY" in line and "END" in line:
                break
            tokens = line.strip().split()
            if not tokens:
                continue
            value = tokens[-1]
            key = " ".join(tokens[:-1])
            out[key] = value
    return out
