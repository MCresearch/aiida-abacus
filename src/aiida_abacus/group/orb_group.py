import json
import pathlib
import typing as t

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
        for path in tqdm(list(pp_path.glob("*.upf")), desc="Scanning elements"):
            element = parse_element(path.read_text())
            # Find the corresponding orbital
            for orb_folder in orb_path.glob(f"{element}_*"):
                orb_type = orb_folder.name.split("_")[-1].lower()  # Use lowercase dzp/tdzp etc
                for orb in orb_folder.glob("*.orb"):
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
