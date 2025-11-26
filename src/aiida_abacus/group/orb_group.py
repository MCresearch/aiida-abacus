import json
import pathlib
import re
import shutil
import tempfile
import typing as t
import zipfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
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

        # Handle both structured repository and flat repository formats
        repo_path = pathlib.Path(repository)

        # Try structured format first: repository/set_name/Pseudopotential
        pp_path = repo_path / f"{set_name}/Pseudopotential"
        orb_path = repo_path / f"{set_name}/Orbitals"

        # If structured format doesn't exist, try flat format: repository/Pseudopotential
        if not pp_path.exists():
            pp_path = repo_path / "Pseudopotential"
            orb_path = repo_path / "Orbitals"

        if not pp_path.exists():
            raise NotExistent(f"Pseudopotential directory not found: {pp_path}")
        if not orb_path.exists():
            raise NotExistent(f"Orbitals directory not found: {orb_path}")

        new_nodes = []
        nodes_to_add = []
        orbital_files = list(orb_path.glob("*.orb")) + list(orb_path.glob("*/*.orb"))
        print(f"Number of orbital files found: {len(orbital_files)}")

        for path in tqdm(chain(pp_path.glob("*.upf"), pp_path.glob("*.UPF")), desc="Scanning elements"):
            element = parse_element(path.read_text())

            # Find the corresponding orbital files for this element
            for orb in orbital_files:
                if not orb.stem.lower().startswith(element.lower() + "_"):
                    continue

                # Extract orbital type from filename (e.g., Si_gga_7au_100Ry_2s2p1d.orb -> gga)
                try:
                    orb_info = parse_orb_filename(orb)
                    orb_type = orb_info.get("functional", "unknown").lower()
                except AssertionError:
                    # If filename doesn't match expected pattern, skip it
                    print(f"Warning: Skipping orbital file with unexpected name format: {orb.name}")
                    continue

                orb_node = AtomicOrbitalData.get_or_create(path, orb)
                # This is the element obtained from the UPF file
                upf_element = orb_node.base.attributes.get("element")
                orb_info["orbital_type"] = orb_type
                assert (
                    element.lower() == upf_element.lower()
                ), f"Orbital element '{upf_element}' does not match pseudopotential element '{element}'"
                # Check if new nodes
                if not orb_node.is_stored:
                    orb_node.base.attributes.set_many(orb_info)
                    new_nodes.append(orb_node)
                nodes_to_add.append(orb_node)

        print(f"About to import {len(nodes_to_add)} nodes, {len(new_nodes)} nodes are new")
        group_label = group_label if group_label is not None else set_name

        if dryrun:
            print("Dry run, not storing any nodes or creating group")
            return None

        group = cls.collection.get_or_create(label=group_label)[0]
        print(f"Number of existing nodes in group {group_label}: {group.count()}")

        for node in tqdm(new_nodes, desc="Storing newly created nodes"):
            node.store()
        group.add_nodes(nodes_to_add)

        return group

    @classmethod
    def import_from_local_paths(
        cls, paths: list[FilePath], group_label: str, description: str = "", dryrun: bool = False
    ) -> t.Optional["AtomicOrbitalCollection"]:
        """
        Import orbitals from one or more local directories or ZIP files.

        This method recursively scans all provided paths for .orb and .upf/.UPF files,
        creates AtomicOrbitalData nodes for ALL variants (no selection), and stores them
        in a single AtomicOrbitalCollection.

        Parameters:
        -----------
        paths : list[FilePath]
            List of local directory or ZIP file paths to import from
        group_label : str
            Label for the created collection
        description : str, default ""
            Description for the collection
        dryrun : bool, default False
            If True, only show what would be imported without actually importing

        Returns:
        --------
        AtomicOrbitalCollection or None
            The created/existing collection, or None if dryrun=True
        """
        # Collect all files from all paths
        all_orbital_files = []
        all_pseudo_files = []

        # Use a persistent temporary directory for ZIP extractions
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            for input_path in paths:
                path = Path(input_path)

                # Handle ZIP extraction
                with temporary_unzip_folder(path) as unzipped_path:
                    # Recursively scan for files
                    orb_files = []
                    pseudo_files = []

                    for orb in unzipped_path.rglob("*.orb"):
                        orb_files.append(orb)

                    for upf in chain(unzipped_path.rglob("*.upf"), unzipped_path.rglob("*.UPF")):
                        pseudo_files.append(upf)

                    # If ZIP, copy files to persistent temp location
                    if path.suffix.lower() == ".zip":
                        persistent_dir = temp_path / f"extracted_{path.stem}"
                        persistent_dir.mkdir(exist_ok=True)

                        for orb in orb_files:
                            dest = persistent_dir / orb.name
                            shutil.copy2(orb, dest)
                            all_orbital_files.append(dest)

                        for upf in pseudo_files:
                            dest = persistent_dir / upf.name
                            shutil.copy2(upf, dest)
                            all_pseudo_files.append(dest)
                    else:
                        all_orbital_files.extend(orb_files)
                        all_pseudo_files.extend(pseudo_files)

            print(f"Total files found: {len(all_orbital_files)} orbitals, {len(all_pseudo_files)} pseudopotentials")

            # Parse and match files by element
            element_orbitals = defaultdict(list)
            element_pseudos = {}

            # Parse orbital files
            for orb_path in tqdm(all_orbital_files, desc="Parsing orbital files"):
                try:
                    metadata = parse_orb_metadata(orb_path)
                    element = metadata.get("Element", "").strip()
                    if element:
                        element_orbitals[element].append(orb_path)
                    else:
                        print(f"Warning: No element found in {orb_path}")
                except Exception as e:
                    print(f"Warning: Failed to parse {orb_path}: {e}")

            # Parse pseudopotential files
            for upf_path in tqdm(all_pseudo_files, desc="Parsing pseudopotential files"):
                try:
                    element = parse_element(upf_path.read_text())
                    if element in element_pseudos:
                        print(f"Warning: Multiple pseudopotentials found for {element}")
                    element_pseudos[element] = upf_path
                except Exception as e:
                    print(f"Warning: Failed to parse {upf_path}: {e}")

            # Match elements and create nodes
            new_nodes = []
            nodes_to_add = []

            for element in sorted(element_orbitals.keys()):
                if element not in element_pseudos:
                    print(f"Warning: No pseudopotential found for element {element}, skipping")
                    continue

                upf_path = element_pseudos[element]
                orb_paths = element_orbitals[element]

                print(f"{element}: {len(orb_paths)} orbital variant(s)")

                # Create node for EACH variant
                for orb_path in orb_paths:
                    try:
                        # Parse orbital filename info
                        orb_info = parse_orb_filename(orb_path)
                        orb_type = orb_info.get("functional", "unknown").lower()
                        orb_info["orbital_type"] = orb_type

                        # Create or get existing node
                        orb_node = AtomicOrbitalData.get_or_create(upf_path, orb_path)

                        # Set attributes for new nodes
                        if not orb_node.is_stored:
                            orb_node.base.attributes.set_many(orb_info)
                            new_nodes.append(orb_node)

                        nodes_to_add.append(orb_node)

                    except Exception as e:
                        print(f"Warning: Failed to create node for {element} / {orb_path.name}: {e}")

            print(f"Prepared {len(nodes_to_add)} nodes ({len(new_nodes)} new)")

            if dryrun:
                print("DRY RUN - Not storing nodes or creating collection")
                return None

            # Check if collection already exists
            try:
                existing = cls.collection.get(label=group_label)
                print(f"Collection '{group_label}' already exists with {existing.count()} nodes")
                return existing
            except NotExistent:
                pass

            # Store new nodes and create collection
            group = cls.collection.get_or_create(label=group_label)[0]

            for node in tqdm(new_nodes, desc="Storing new nodes"):
                node.store()

            group.add_nodes(nodes_to_add)

            if description:
                group.description = description

            return group

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
            raise MultipleObjectsError(
                f"More than one orbital found for element={element}, " f"orbital_type={orbital_type}, rcut={rcut}"
            )
        except NotExistent as _:
            # Provide more detailed error message
            available_elements = set()
            for node in self.nodes:
                attrs = node.base.attributes.all
                available_elements.add(attrs.get("element", "Unknown"))

            raise NotExistent(
                f"No orbital found for element={element}, orbital_type={orbital_type}, rcut={rcut}. "
                f"Available elements: {sorted(available_elements)}"
            )
        return node

    def get_statistics(self) -> dict:
        """
        Get statistics about the orbitals in this collection.

        Returns:
            dict: Dictionary containing:
                - element_count: Number of unique elements
                - total_orbitals: Total number of orbitals
                - elements: List of element symbols
                - orbital_types: Counter of orbital types
                - rcut_range: Dict with min and max rcut values
                - variants_per_element: Dict mapping elements to number of variants
        """
        elements = set()
        orbital_types = Counter()
        rcuts = []
        element_variants = defaultdict(list)

        for node in self.nodes:
            attrs = node.base.attributes.all
            element = attrs.get("element")
            orbital_type = attrs.get("orbital_type")
            rcut = attrs.get("rcut_au")

            if element:
                elements.add(element)
                element_variants[element].append(node.pk)
            if orbital_type:
                orbital_types[orbital_type] += 1
            if rcut is not None:
                rcuts.append(rcut)

        variants_per_element = {elem: len(variants) for elem, variants in element_variants.items()}

        return {
            "element_count": len(elements),
            "total_orbitals": self.count(),
            "elements": sorted(elements),
            "orbital_types": dict(orbital_types),
            "rcut_range": {"min": min(rcuts) if rcuts else None, "max": max(rcuts) if rcuts else None},
            "variants_per_element": variants_per_element,
        }

    def list_elements(self) -> list[str]:
        """
        Get a list of all unique elements in this collection.

        Returns:
            list[str]: Sorted list of element symbols
        """
        elements = set()
        for node in self.nodes:
            element = node.base.attributes.get("element")
            if element:
                elements.add(element)
        return sorted(elements)

    def list_variants(self, element: str) -> list[dict]:
        """
        Get all orbital variants for a given element.

        Args:
            element: Element symbol

        Returns:
            list[dict]: List of dictionaries containing orbital information:
                - pk: Node PK
                - orbital_type: Type of orbital
                - rcut_au: Cutoff radius in atomic units
                - cut_off_energy_ry: Energy cutoff in Rydberg
                - electron_config: Electronic configuration
                - functional: Functional type
        """
        variants = []

        q = orm.QueryBuilder()
        q.append(
            type(self),
            filters={"id": self.pk},
            tag="group",
        )
        q.append(
            AtomicOrbitalData,
            with_group="group",
            filters={"attributes.element": element},
        )

        for (node,) in q.all():
            attrs = node.base.attributes.all
            variants.append(
                {
                    "pk": node.pk,
                    "orbital_type": attrs.get("orbital_type"),
                    "rcut_au": attrs.get("rcut_au"),
                    "cut_off_energy_ry": attrs.get("cut_off_energy_ry"),
                    "electron_config": attrs.get("electron_config"),
                    "functional": attrs.get("functional"),
                }
            )

        return variants

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
                if "Other" not in rcuts_dict:
                    raise NotExistent(
                        f"No rcut specified for element '{element}' and no 'Other' fallback found in rcuts_dict"
                    )
                rcut = rcuts_dict["Other"]
            orb = None
            # Find suitable cut off distance with reasonable bounds
            max_rcut = 20.0  # Set reasonable upper bound
            while rcut <= max_rcut:
                try:
                    orb = self.get_orbital(element, orbital_type, rcut)
                except NotExistent as _:
                    print(f"No orbital found for {element} with rcut {rcut}, trying increasing it by 1")
                    rcut += 1
                if orb is not None:
                    break
            if orb is None:
                raise NotExistent(f"No orbital found for {element} with rcut up to {max_rcut}")
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
    def import_folder(
        cls,
        orbital_path,
        pseudo_path,
        label,
        dryrun=False,
        stop_if_inconsistent=True,
        verbose=False,
        variant_choices=None,
    ) -> orm.Group:
        """
        Import the folder with configurable consistency checking.

        Parameters:
        -----------
        orbital_path : str or Path
            Path to orbital files or archive
        pseudo_path : str or Path
            Path to pseudopotential files or archive
        label : str
            Label for the created family
        dryrun : bool, default False
            If True, only show what would be imported without actually importing
        stop_if_inconsistent : bool, default True
            If True, stop execution for any inconsistencies (original behavior)
            If False, warn about inconsistencies but continue importing
        verbose : bool, default False
            If True, show detailed progress information
        variant_choices : dict, default None
            Dictionary mapping elements to selected orbital file paths
        """
        with temporary_unzip_folder(orbital_path) as orb_path:
            with temporary_unzip_folder(pseudo_path) as pseudo_path:
                return cls._import_folders(
                    orb_path, pseudo_path, label, dryrun, stop_if_inconsistent, verbose, variant_choices
                )

    @staticmethod
    def _import_folders(
        orbital_path: pathlib.Path,
        pseudo_path: pathlib.Path,
        label: str,
        dryrun: bool = False,
        stop_if_inconsistent: bool = True,
        verbose: bool = False,
        variant_choices=None,
    ) -> orm.Group:
        """Inspect and import data with configurable consistency checking."""

        def log_info(message):
            """Print info if verbose is enabled"""
            if verbose:
                print(message)

        def log_warning(message):
            """Print warning"""
            print(f"Warning: {message}")

        orbital_files = []
        upf_files = []

        # Find all orbital files and extract element information
        # Find all orbital files and extract element information
        for path in orbital_path.rglob("*.orb"):
            try:
                metadata = parse_orb_metadata(path)
                element = metadata.get("Element", "").strip()
                if element:
                    orbital_files.append([element, path])
                else:
                    log_warning(f"No element found in orbital metadata for {path}")
            except Exception as e:
                log_warning(f"Failed to parse orbital metadata from {path}: {e}")
                continue
        if variant_choices:
            selected = []
            # Find matching elements
            for element, path in orbital_files:
                # Find if this element has a variant choice
                if element in variant_choices:
                    if Path(variant_choices[element]).resolve() == Path(path).resolve():
                        # Only select if paths match if the element exists in the variant choices
                        selected.append([element, Path(path)])
                else:
                    selected.append([element, path])
            orbital_files = selected

        # Find all UPF files with both case patterns and extract element information
        for path in chain(
            pseudo_path.rglob("*.upf"),
            pseudo_path.rglob("*.UPF"),
        ):
            try:
                element = parse_element(path.read_text())
                if element:
                    upf_files.append([element, path])
            except Exception as e:
                log_warning(f"Failed to parse UPF file {path}: {e}")
                # Try to extract element from filename as fallback
                filename = path.name
                # Extract element from patterns like "Te.PD04.PBE.UPF" or "Ag.upf"
                element_match = re.match(r"^([A-Z][a-z]?)", filename)
                if element_match:
                    element = element_match.group(1)
                    upf_files.append([element, path])
                    log_info(f"Extracted element '{element}' from filename {filename}")

        log_info(f"Found {len(orbital_files)} orbital files and {len(upf_files)} UPF files")

        # Check for true duplicates (identical filenames) and multiple orbital variants
        orbital_counts = Counter(elem for elem, _ in orbital_files)
        upf_counts = Counter(elem for elem, _ in upf_files)

        # Check for true duplicate files (same filename) - this indicates corrupted archive
        orbital_paths = [path.name for _, path in orbital_files]
        upf_paths = [path.name for _, path in upf_files]

        duplicate_orbital_files = {name: count for name, count in Counter(orbital_paths).items() if count > 1}
        duplicate_upf_files = {name: count for name, count in Counter(upf_paths).items() if count > 1}

        if duplicate_orbital_files:
            error_msg = f"Duplicate orbital FILES found (corrupted archive): {duplicate_orbital_files}"
            raise RuntimeError(f"Error: {error_msg}")

        if duplicate_upf_files:
            error_msg = f"Duplicate UPF FILES found (corrupted archive): {duplicate_upf_files}"
            raise RuntimeError(f"Error: {error_msg}")

        # Report multiple orbital variants per element (this is normal, not an error)
        multiple_orbital_variants = {elem: count for elem, count in orbital_counts.items() if count > 1}
        if multiple_orbital_variants:
            log_info(f"Multiple orbital variants found for elements: {multiple_orbital_variants}")
            log_info("These variants should be selected by the CLI layer before calling this import function")

        # UPF files should have exactly 1 per element in non-corrupted archives
        multiple_upf_variants = {elem: count for elem, count in upf_counts.items() if count > 1}
        if multiple_upf_variants:
            error_msg = f"Multiple UPF files found for elements (possible archive issue): {multiple_upf_variants}"
            raise RuntimeError(f"Error: {error_msg}")

        # Create mapping of elements (case-insensitive)
        orbitals = {elem.lower(): (elem, path) for elem, path in orbital_files}
        upfs = {elem.lower(): (elem, path) for elem, path in upf_files}

        # Find matches and mismatches
        matched_elements = []
        unmatched_orbitals = []
        unmatched_upfs = []

        for elem_lower, (orig_elem, orb_path) in orbitals.items():
            if elem_lower in upfs:
                matched_elements.append((orig_elem, orb_path, upfs[elem_lower][1]))
            else:
                unmatched_orbitals.append(orig_elem)

        for elem_lower, (orig_elem, upf_path) in upfs.items():
            if elem_lower not in orbitals:
                unmatched_upfs.append(orig_elem)

        # Report findings
        if unmatched_orbitals:
            message = f"Orbitals without matching UPFs: {unmatched_orbitals}"
            if stop_if_inconsistent:
                raise RuntimeError(f"Error: {message}")
            else:
                log_warning(message)

        if unmatched_upfs:
            message = f"UPFs without matching orbitals: {unmatched_upfs}"
            if stop_if_inconsistent:
                raise RuntimeError(f"Error: {message}")
            else:
                log_info(message)

        # Consistency checking: check for exact 1:1 mapping (duplicates already checked above)
        if stop_if_inconsistent:
            for element, count in upf_counts.items():
                if count != 1 and element not in multiple_upf_variants:
                    raise RuntimeError(f"Error: Found {count} UPF files for element {element}!")

        if not matched_elements:
            raise RuntimeError("No matching orbital-UPF pairs found!")

        log_info(f"Found {len(matched_elements)} matching element pairs")

        # Create AtomicOrbitalData nodes
        orbital_data = []
        new_orbital_data = []
        for orig_elem, orb_path, upf_path in matched_elements:
            try:
                node = AtomicOrbitalData.get_or_create(str(upf_path), str(orb_path))
                if node.is_stored:
                    log_info(f"Reusing existing node {node.pk} for element {orig_elem}")
                else:
                    log_info(f"Created node for element {orig_elem}")
                    new_orbital_data.append(node)
                orbital_data.append(node)
            except Exception as e:
                error_msg = f"Failed to create node for element {orig_elem}: {e}"
                if stop_if_inconsistent:
                    raise RuntimeError(error_msg)
                else:
                    print(f"Error: {error_msg}")
                    continue

        if not orbital_data:
            if dryrun:
                return None
            log_warning("No nodes to import (all may already exist)")
            return None

        if dryrun:
            log_info("DRY RUN - Would import the following pairs:")
            for orig_elem, orb_path, upf_path in matched_elements:
                print(f"  {orig_elem}: {orb_path.name} + {upf_path.name}")
            return None

        # Store and create the family group
        log_info(f"Storing {len(new_orbital_data)} new nodes...")
        for node in new_orbital_data:
            node.store()

        group = AtomicOrbitalFamily.collection.get_or_create(label=label)[0]
        group.add_nodes(orbital_data)
        return group


@contextmanager
def temporary_unzip_folder(zippath) -> t.Generator[pathlib.Path, None, None]:
    """Unzip a zip file to a temporary folder and yield the path to the folder."""
    zippath = Path(zippath)
    if zippath.suffix == ".zip":
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
