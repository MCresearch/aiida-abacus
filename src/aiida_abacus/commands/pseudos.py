"""
Pseudopotential and orbital management commands for AiiDA-abacus.

This module provides commands to download, install, and manage ABACUS pseudopotentials
and numerical atomic orbitals from various sources.
"""

import hashlib
import json
import shutil
import tempfile
import traceback
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlretrieve

import click
import tabulate
from aiida import orm as aiida_orm
from aiida.cmdline.utils import echo
from aiida.cmdline.utils.decorators import with_dbenv
from aiida.orm import QueryBuilder, load_group, load_node
from click_spinner import spinner as cli_spinner

from ..group.orb_group import (
    AtomicOrbitalCollection,
    AtomicOrbitalFamily,
    temporary_unzip_folder,
)

# Import the main command group to attach subcommands to it
from . import cmd_aiida_abacus

# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for a downloadable pseudopotential+orbital source."""

    name: str  # e.g. "SG15"
    version: str  # e.g. "v1.0"
    functional: str  # e.g. "PBE"
    url: str  # pinned download URL
    md5: str  # expected archive MD5
    commit: str  # git commit hash for GitHub sources
    description: str


# Pinned commit for ABACUS-orbitals repository
_ABACUS_ORBITALS_COMMIT = "3b634f1618f5c56baa97084a41ae17e801d46ab9"
_ABACUS_ORBITALS_URL = f"https://github.com/abacusmodeling/ABACUS-orbitals/archive/{_ABACUS_ORBITALS_COMMIT}.zip"

SOURCE_CONFIGS = {
    "sg15": SourceConfig(
        name="SG15",
        version="v1.0",
        functional="PBE",
        url=_ABACUS_ORBITALS_URL,
        md5="",  # will be computed on first use / updated manually
        commit=_ABACUS_ORBITALS_COMMIT,
        description="SG15 ONCV pseudopotentials with numerical atomic orbitals",
    ),
    "dojo-sr": SourceConfig(
        name="DOJO",
        version="v0.4",
        functional="PBE",
        url=_ABACUS_ORBITALS_URL,
        md5="",
        commit=_ABACUS_ORBITALS_COMMIT,
        description="PseudoDojo norm-conserving scalar-relativistic pseudopotentials with orbitals",
    ),
    "dojo-fr": SourceConfig(
        name="DOJO",
        version="v0.4",
        functional="PBE",
        url=_ABACUS_ORBITALS_URL,
        md5="",
        commit=_ABACUS_ORBITALS_COMMIT,
        description="PseudoDojo norm-conserving full-relativistic pseudopotentials with orbitals",
    ),
    "apns": SourceConfig(
        name="APNS",
        version="v1",
        functional="PBE",
        url="https://store.aissquare.com/datasets/dc875646-a526-41f1-a180-d54b218fc80a/ABACUS-APNS-PPORBs-v1.zip",
        md5="96cc456911712a81c1db85ba6e8239ce",
        commit="",
        description="APNS pseudopotential and orbital set (v1)",
    ),
}


def _make_label(source: str, version: str, functional: str, tag: str) -> str:
    """Build a family/collection label: SOURCE-vVERSION-FUNCTIONAL-TAG."""
    return f"{source}-{version}-{functional}-{tag}"


def _set_group_extras(group, source: SourceConfig, tag: str, download_url: str):
    """Store version metadata as group extras."""
    group.base.extras.set("source", source.name)
    group.base.extras.set("version", source.version)
    group.base.extras.set("functional", source.functional)
    group.base.extras.set("tag", tag)
    group.base.extras.set("download_url", download_url)
    group.base.extras.set("commit", source.commit)
    group.base.extras.set("install_date", datetime.now().isoformat())


def _check_already_installed(label: str, source: SourceConfig, tag: str, update: bool) -> bool:
    """Check if a family with matching version extras already exists.

    Returns True if the install should be skipped.
    """
    try:
        existing = load_group(label)
        if not update:
            existing_version = existing.base.extras.get("version", None)
            existing_tag = existing.base.extras.get("tag", None)
            if existing_version == source.version and existing_tag == tag:
                echo.echo_info(
                    f"Family '{label}' already installed (version={existing_version}, tag={existing_tag}). "
                    "Use --update to force re-install."
                )
                return True
        else:
            echo.echo_info(f"Removing existing family '{label}' for update...")
            existing.delete()
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Reorganize helpers - convert per-element dirs to flat Pseudopotential/Orbitals
# ---------------------------------------------------------------------------


def _reorganize_github_orbitals(
    source_dir: Path,
    tag: str,
    rcut_json_path: Path | None,
    target_dir: Path,
) -> None:
    """Reorganize the ABACUS-orbitals per-element structure into flat dirs.

    Source layout (e.g. SG15_v1.0/):
        Pseudopotential/Ag_ONCV_PBE-1.0.upf
        Orbitals_v2.0/Ag_DZP/Ag_gga_7au_100Ry_6s3p3d2f.orb

    Target layout:
        Pseudopotential/Ag_ONCV_PBE-1.0.upf
        Orbitals/Ag_gga_7au_100Ry_6s3p3d2f.orb   (one selected .orb per element)
    """
    pp_src = source_dir / "Pseudopotential"
    orb_src = source_dir / "Orbitals_v2.0"
    if not orb_src.exists():
        orb_src = source_dir / "Orbitals"

    if not pp_src.exists():
        raise click.Abort(f"Pseudopotential directory not found: {pp_src}")
    if not orb_src.exists():
        raise click.Abort(f"Orbitals directory not found: {orb_src}")

    # Load standard rcut mapping if available
    rcut_map: dict[str, float] = {}
    if rcut_json_path and rcut_json_path.exists():
        with open(rcut_json_path) as f:
            rcut_map = json.load(f)

    pp_dst = target_dir / "Pseudopotential"
    orb_dst = target_dir / "Orbitals"
    pp_dst.mkdir(parents=True, exist_ok=True)
    orb_dst.mkdir(parents=True, exist_ok=True)

    # Copy all pseudopotentials
    for upf in list(pp_src.glob("*.upf")) + list(pp_src.glob("*.UPF")):
        shutil.copy2(upf, pp_dst / upf.name)

    # Find element dirs matching the tag (e.g. Si_DZP, Si_TZDP)
    tag_lower = tag.lower()
    matched_dirs = [d for d in orb_src.iterdir() if d.is_dir() and d.name.lower().endswith(f"_{tag_lower}")]

    if not matched_dirs:
        raise click.Abort(f"No orbital directories found for tag '{tag}' in {orb_src}")

    for elem_dir in matched_dirs:
        element = elem_dir.name.rsplit("_", 1)[0]  # e.g. "Si" from "Si_DZP"

        # Find all .orb files in this element directory
        orb_files = list(elem_dir.glob("*.orb"))
        if not orb_files:
            echo.echo_warning(f"No .orb files found in {elem_dir}")
            continue

        if len(orb_files) == 1:
            selected = orb_files[0]
        elif element in rcut_map:
            # Use standard rcut to select the best orbital
            target_rcut = rcut_map[element]
            selected = _select_orbital_by_rcut(orb_files, target_rcut)
        elif "Others" in rcut_map:
            target_rcut = rcut_map["Others"]
            selected = _select_orbital_by_rcut(orb_files, target_rcut)
        else:
            # Fallback: pick the smallest rcut (first when sorted)
            selected = sorted(orb_files, key=lambda p: _extract_rcut_from_orb_name(p.name))[0]

        shutil.copy2(selected, orb_dst / selected.name)

    echo.echo_info(f"Reorganized {len(matched_dirs)} element dirs into {pp_dst} and {orb_dst}")


def _select_orbital_by_rcut(orb_files: list[Path], target_rcut: float) -> Path:
    """Select the orbital file with rcut closest to target_rcut."""
    best = None
    best_diff = float("inf")
    for orb in orb_files:
        rcut = _extract_rcut_from_orb_name(orb.name)
        diff = abs(rcut - target_rcut)
        if diff < best_diff:
            best_diff = diff
            best = orb
    return best or orb_files[0]


def _extract_rcut_from_orb_name(name: str) -> float:
    """Extract rcut from orbital filename like 'Si_gga_7au_100Ry_2s2p1d.orb'."""
    tokens = Path(name).stem.split("_")
    for t in tokens:
        if t.endswith("au"):
            return float(t[:-2])
    return 0.0


# ---------------------------------------------------------------------------
# Shared install pipeline for all three sources
# ---------------------------------------------------------------------------


def _install_from_source(
    source_key: str,
    tag: str,
    functional: str | None = None,
    update: bool = False,
    dry_run: bool = False,
    source_path: Path | None = None,
    extra_source_dirs: list[Path] | None = None,
) -> None:
    """Shared pipeline: download → reorganize → import collection → create default family.

    Parameters
    ----------
    source_key : str
        Key in SOURCE_CONFIGS ("sg15", "dojo-sr", "dojo-fr", "apns").
    tag : str
        Variant tag, e.g. "dzp", "efficiency", "precision".
    functional : str or None
        Override functional from default.
    update : bool
        Force re-download/re-install.
    dry_run : bool
        Show what would happen.
    source_path : Path or None
        Local path to use instead of downloading (for testing).
    extra_source_dirs : list[Path] or None
        Additional source directories to merge (e.g. La-Series for Dojo).
    """
    config = SOURCE_CONFIGS[source_key]
    func = functional or config.functional
    label = _make_label(config.name, config.version, func, tag)
    collection_label = f"{config.name}-{config.version}-{func}"

    if dry_run:
        echo.echo_info("DRY RUN - would perform the following:")
        echo.echo(f"  Source: {config.name} {config.version}")
        echo.echo(f"  Functional: {func}")
        echo.echo(f"  Tag: {tag}")
        echo.echo(f"  Family label: {label}")
        echo.echo(f"  Collection label: {collection_label}")
        if source_path:
            echo.echo(f"  Local source: {source_path}")
        else:
            echo.echo(f"  Download URL: {config.url}")
        return

    # Check if already installed
    if _check_already_installed(label, config, tag, update):
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: Get the data (download or use local)
        if source_path is not None:
            archive_path = source_path
        else:
            archive_path = _download_and_verify(config.url, config.md5, config.name, update)

        # Step 2: Extract and reorganize
        reorg_dir = tmp / "reorganized" / collection_label
        reorg_dir.mkdir(parents=True)

        if source_key == "apns":
            _reorganize_apns(archive_path, tag, reorg_dir)
        else:
            # GitHub sources: extract, then reorganize
            extract_dir = tmp / "extracted"
            with cli_spinner():
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extract_dir)

            # Find the source subdirectory inside the extracted archive
            # GitHub archives extract as ABACUS-orbitals-<commit>/
            top_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            if len(top_dirs) == 1:
                repo_root = top_dirs[0]
            else:
                repo_root = extract_dir

            # Map source_key to subdirectory name
            subdir_map = {
                "sg15": "SG15_v1.0",
                "dojo-sr": "Dojo-NC-SR",
                "dojo-fr": "Dojo-NC-FR",
            }
            subdir_name = subdir_map.get(source_key)
            if not subdir_name:
                raise click.Abort(f"Unknown source key: {source_key}")

            source_subdir = repo_root / subdir_name
            if not source_subdir.exists():
                raise click.Abort(f"Source subdirectory not found: {source_subdir}")

            # Find rcut JSON
            tag_upper = tag.upper()
            rcut_json = source_subdir / f"Orbitals_v2.0_{tag_upper}_E100_StandardRcut.json"
            if not rcut_json.exists():
                rcut_json = None

            _reorganize_github_orbitals(source_subdir, tag, rcut_json, reorg_dir)

            # Handle extra source dirs (e.g. La-Series for Dojo)
            if extra_source_dirs:
                for extra_dir in extra_source_dirs:
                    extra_subdir = repo_root / extra_dir.name if not extra_dir.exists() else extra_dir
                    if extra_subdir.exists():
                        extra_rcut = extra_subdir / f"Orbitals_v2.0_{tag_upper}_E100_StandardRcut.json"
                        extra_reorg = tmp / "extra_reorg"
                        extra_reorg.mkdir(exist_ok=True)
                        _reorganize_github_orbitals(
                            extra_subdir,
                            tag,
                            extra_rcut if extra_rcut.exists() else None,
                            extra_reorg,
                        )
                        # Merge into main reorg dir
                        for f in (extra_reorg / "Pseudopotential").glob("*.upf"):
                            shutil.copy2(f, reorg_dir / "Pseudopotential" / f.name)
                        for f in (extra_reorg / "Pseudopotential").glob("*.UPF"):
                            shutil.copy2(f, reorg_dir / "Pseudopotential" / f.name)
                        for f in (extra_reorg / "Orbitals").glob("*.orb"):
                            shutil.copy2(f, reorg_dir / "Orbitals" / f.name)

        # Step 3: Import into collection
        echo.echo_info(f"Importing into collection '{collection_label}'...")
        with cli_spinner():
            collection = AtomicOrbitalCollection.import_orbital_set(
                repository=reorg_dir.parent,
                set_name=collection_label,
                dryrun=False,
                group_label=collection_label,
            )

        if collection is None:
            echo.echo_info("Collection already exists, reusing it.")
            collection = load_group(collection_label)

        collection.description = config.description
        _set_group_extras(collection, config, tag, config.url)
        echo.echo_success(f"Collection '{collection_label}': {collection.count()} orbitals")

        # Step 4: Create default family using standard rcut selection
        echo.echo_info(f"Creating default family '{label}'...")
        with cli_spinner():
            family = _create_default_family(collection, label, config, tag)

        _set_group_extras(family, config, tag, config.url)
        echo.echo_success(f"Family '{label}': {family.count()} elements")
        echo.echo(f"  Elements: {', '.join(sorted(n.element for n in family.nodes))}")


def _reorganize_apns(archive_path: Path, tag: str, target_dir: Path) -> None:
    """Reorganize APNS zip into flat Pseudopotential/ and Orbitals/ dirs."""
    with temporary_unzip_folder(archive_path) as extracted:
        # Find the directories
        pp_dir = None
        orb_dir = None
        for d in extracted.iterdir():
            if not d.is_dir():
                continue
            dname = d.name.lower()
            if "pseudopotential" in dname:
                pp_dir = d
            elif f"orbitals-{tag}" in dname:
                orb_dir = d

        if not pp_dir:
            raise click.Abort(
                f"Pseudopotential directory not found in APNS archive. Found: {list(extracted.iterdir())}"
            )
        if not orb_dir:
            raise click.Abort(
                f"Orbitals directory for tag '{tag}' not found in APNS archive. "
                f"Available: {[d.name for d in extracted.iterdir() if d.is_dir()]}"
            )

        pp_dst = target_dir / "Pseudopotential"
        orb_dst = target_dir / "Orbitals"
        pp_dst.mkdir(parents=True, exist_ok=True)
        orb_dst.mkdir(parents=True, exist_ok=True)

        for f in list(pp_dir.rglob("*.upf")) + list(pp_dir.rglob("*.UPF")):
            shutil.copy2(f, pp_dst / f.name)
        for f in orb_dir.rglob("*.orb"):
            shutil.copy2(f, orb_dst / f.name)


def _create_default_family(
    collection: AtomicOrbitalCollection,
    family_label: str,
    config: SourceConfig,
    tag: str,
) -> AtomicOrbitalFamily:
    """Create a default family from a collection by picking one orbital per element."""

    elements = collection.list_elements()
    nodes_to_add = []

    for element in elements:
        variants = collection.list_variants(element)
        if not variants:
            echo.echo_warning(f"No variants for element {element}, skipping")
            continue

        if len(variants) == 1:
            nodes_to_add.append(load_node(variants[0]["pk"]))
            continue

        # Multiple variants: prefer the one with the tag in the orbital type or pick first
        # For APNS, variants differ by rcut; for SG15/Dojo they differ by rcut too
        # Pick the variant whose rcut matches the standard rcut, or the first one
        selected = variants[0]
        for v in variants:
            node = load_node(v["pk"])
            orb_fname = node.base.attributes.get("filename_second", "")
            if tag.lower() in orb_fname.lower():
                selected = v
                break
        nodes_to_add.append(load_node(selected["pk"]))

    try:
        existing = load_group(family_label)

        raise click.Abort(f"Family '{family_label}' already exists (PK={existing.pk})")
    except Exception:
        pass

    family = AtomicOrbitalFamily(label=family_label)
    family.store()
    family.add_nodes(nodes_to_add)
    family.description = f"Default {config.name} {config.version} family ({tag})"
    return family


def select_orbital_variants(element_variants):
    """
    Interactive function to select orbital variants for each element.

    Parameters:
    -----------
    element_variants : dict
        Dictionary mapping elements to lists of orbital file paths

    Returns:
    --------
    dict
        Dictionary mapping elements to selected orbital file paths
    """
    selected_orbitals = {}
    manual_selection = {}

    print(f"\nOrbital variant selection for {len(element_variants)} elements:")
    print("=" * 60)

    for element, variants in sorted(element_variants.items()):
        if len(variants) == 1:
            # Only one variant, select automatically
            selected_orbitals[element] = variants[0]
            print(f"{element}: Only one variant available - {variants[0].name}")
            continue

        print(f"\n{element}: Found {len(variants)} orbital variants")
        print("-" * 30)

        for i, orbital_path in enumerate(variants, 1):
            # Extract key info from filename for better display
            filename = orbital_path.name
            # Parse orbital info from filename for better display
            tokens = Path(filename).stem.split("_")
            if len(tokens) >= 4:
                functional = tokens[1]
                rcut = tokens[2].replace("au", "")
                energy = tokens[3].replace("Ry", "")
                display_name = f"{functional} functional, rcut={rcut}au, Ecut={energy}Ry"
            else:
                display_name = filename

            print(f"  {i}. {display_name}")
            print(f"     File: {filename}")

        # Get user selection
        while True:
            try:
                choice = input(f"\nSelect variant for {element} (1-{len(variants)}) [default=1]: ").strip()

                if not choice:
                    choice_num = 1  # Default to first option
                else:
                    choice_num = int(choice)

                if 1 <= choice_num <= len(variants):
                    selected_orbitals[element] = variants[choice_num - 1]
                    manual_selection[element] = variants[choice_num - 1].name
                    selected_file = variants[choice_num - 1].name
                    print(f"  Selected: {selected_file}")
                    break
                else:
                    print(f"  Invalid choice. Please enter a number between 1 and {len(variants)}")
            except ValueError:
                print(f"  Invalid input. Please enter a number between 1 and {len(variants)}")
            except KeyboardInterrupt:
                print("\nOperation cancelled by user.")
                raise

    return selected_orbitals, manual_selection


def select_orbital_files_interactive(collection):
    """
    Interactive function to select orbital files from a collection for family creation.

    Parameters:
    -----------
    collection : AtomicOrbitalCollection
        The collection to select orbitals from

    Returns:
    --------
    dict
        Dictionary mapping elements to selected node PKs
    """
    selected_nodes = {}

    # Get all elements in the collection
    elements = collection.list_elements()

    echo.echo(f"\nOrbital selection for {len(elements)} elements:")
    echo.echo("=" * 60)

    for element in sorted(elements):
        # Get all variants for this element
        variants = collection.list_variants(element)

        if len(variants) == 1:
            # Only one variant, select automatically
            variant = variants[0]
            selected_nodes[element] = variant["pk"]

            # Get the node to extract filename
            node = load_node(variant["pk"])
            filename = node.base.attributes.get("filename_second", "Unknown")
            echo.echo(f"{element}: Only one variant - {filename}")
            continue

        echo.echo(f"\n{element}: Found {len(variants)} orbital variants")
        echo.echo("-" * 30)

        for i, variant in enumerate(variants, 1):
            # Load node to get filename
            node = load_node(variant["pk"])
            filename = node.base.attributes.get("filename_second", "Unknown")

            # Display metadata
            rcut = variant.get("rcut_au", "N/A")
            energy = variant.get("cut_off_energy_ry", "N/A")
            config = variant.get("electron_config", "N/A")

            echo.echo(f"  {i}. {filename}")
            echo.echo(f"     rcut={rcut}au, Ecut={energy}Ry, config={config}")

        # Get user selection
        while True:
            try:
                choice = input(f"\nSelect variant for {element} (1-{len(variants)}) [default=1]: ").strip()

                if not choice:
                    choice_num = 1  # Default to first option
                else:
                    choice_num = int(choice)

                if 1 <= choice_num <= len(variants):
                    selected_nodes[element] = variants[choice_num - 1]["pk"]
                    node = load_node(variants[choice_num - 1]["pk"])
                    filename = node.base.attributes.get("filename_second", "Unknown")
                    echo.echo(f"  Selected: {filename}")
                    break
                else:
                    echo.echo(f"  Invalid choice. Please enter a number between 1 and {len(variants)}")
            except ValueError:
                echo.echo(f"  Invalid input. Please enter a number between 1 and {len(variants)}")
            except KeyboardInterrupt:
                echo.echo("\nOperation cancelled by user.")
                raise

    return selected_nodes


@cmd_aiida_abacus.group("pseudos")
def pseudos() -> None:
    """Top level command for handling ABACUS pseudopotentials and orbitals."""
    pass


# Define known pseudopotential sets
KNOWN_SETS = {
    "apns-efficiency/precision-v1": {
        "url": "https://store.aissquare.com/datasets/dc875646-a526-41f1-a180-d54b218fc80a/ABACUS-APNS-PPORBs-v1.zip",
        "md5": "96cc456911712a81c1db85ba6e8239ce",
        "description": "APNS efficiency and precision pseudopotential and orbital set (v1)",
    },
}


def get_cache_dir() -> Path:
    """Get the cache directory for downloaded files."""
    cache_dir = Path.home() / ".aiida" / "abacus" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def verify_md5(filepath: Path, expected_md5: str) -> bool:
    """Verify MD5 checksum of a file."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest() == expected_md5.lower()


def _download_and_verify(url: str, expected_md5: str, name: str, force_download: bool) -> Path:
    """
    Download and verify a file from URL.

    Returns the path to the cached file.
    """
    # Parse URL to get filename
    parsed_url = urlparse(url)
    filename = Path(parsed_url.path).name
    cache_file = get_cache_dir() / filename

    # Download file if not cached or force download is requested
    if not cache_file.exists() or force_download:
        echo.echo(f"Downloading {name} from {url}...")

        with cli_spinner():
            try:
                # Download to temporary file first, then move to cache location
                with tempfile.NamedTemporaryFile(delete=False, suffix=filename) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                    urlretrieve(url, tmp_path)
                    shutil.move(tmp_path, cache_file)
            except Exception as e:
                raise click.Abort(f"Failed to download file: {e}")

        echo.echo_success(f"Downloaded to {cache_file}")
    else:
        echo.echo(f"Using cached file: {cache_file}")

    # Verify MD5 checksum
    echo.echo("Verifying MD5 checksum...")
    if not verify_md5(cache_file, expected_md5):
        if not force_download and cache_file.exists():
            echo.echo_warning("MD5 checksum verification failed. The file may be corrupted.")
            if click.confirm("Do you want to re-download the file?"):
                return _download_and_verify(url, expected_md5, name, force_download=True)
        raise click.Abort(f"MD5 checksum verification failed for {cache_file}")

    echo.echo_success("MD5 checksum verified")
    return cache_file


def _import_apns_set(cache_file: Path) -> None:
    """Import APNS pseudopotential set with special multi-collection structure."""
    # Extract and process the archive
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        echo.echo_info(f"Extracting archive to {temp_path}")

        with cli_spinner():
            with zipfile.ZipFile(cache_file, "r") as zip_ref:
                zip_ref.extractall(temp_path)

        # Find the extracted directories
        extracted_dirs = [d for d in temp_path.iterdir() if d.is_dir()]
        echo.echo_info(f"Extracted directories: {[d.name for d in extracted_dirs]}")

        # Look for the expected structure:
        # - apns-orbitals-efficiency-v1/
        # - apns-pseudopotentials-v1/
        # - apns-orbitals-precision-v1/
        orbital_efficiency_dir = None
        pseudopotential_dir = None
        orbital_precision_dir = None

        for dir_path in extracted_dirs:
            dir_name = dir_path.name
            if "orbitals-efficiency" in dir_name:
                orbital_efficiency_dir = dir_path
            elif "pseudopotentials" in dir_name:
                pseudopotential_dir = dir_path
            elif "orbitals-precision" in dir_name:
                orbital_precision_dir = dir_path

        if not orbital_efficiency_dir or not pseudopotential_dir:
            raise click.Abort(
                "Expected directory structure not found. "
                f"Looking for directories containing 'orbitals-efficiency' and 'pseudopotentials'. "
                f"Found: {[d.name for d in extracted_dirs]}"
            )

        echo.echo_success(f"Found orbital directory: {orbital_efficiency_dir.name}")
        echo.echo_success(f"Found pseudopotential directory: {pseudopotential_dir.name}")
        if orbital_precision_dir:
            echo.echo_success(f"Found precision orbital directory: {orbital_precision_dir.name}")

        # Create a temporary structured repository
        # Structure: temp_repo/apns-efficiency-v1/{Pseudopotential/, Orbitals/}
        #            temp_repo/apns-precision-v1/{Pseudopotential/, Orbitals/}
        repo_path = temp_path / "repository"
        repo_path.mkdir()

        collections_to_create = []

        # Efficiency collection
        efficiency_repo = repo_path / "apns-efficiency-v1"
        efficiency_repo.mkdir()
        (efficiency_repo / "Pseudopotential").symlink_to(pseudopotential_dir, target_is_directory=True)
        (efficiency_repo / "Orbitals").symlink_to(orbital_efficiency_dir, target_is_directory=True)
        collections_to_create.append(
            {
                "name": "apns-efficiency-v1",
                "set_name": "apns-efficiency-v1",
                "description": "APNS efficiency orbital collection (v1) - all variants",
            }
        )

        # Precision collection (if available)
        if orbital_precision_dir:
            precision_repo = repo_path / "apns-precision-v1"
            precision_repo.mkdir()
            (precision_repo / "Pseudopotential").symlink_to(pseudopotential_dir, target_is_directory=True)
            (precision_repo / "Orbitals").symlink_to(orbital_precision_dir, target_is_directory=True)
            collections_to_create.append(
                {
                    "name": "apns-precision-v1",
                    "set_name": "apns-precision-v1",
                    "description": "APNS precision orbital collection (v1) - all variants",
                }
            )

        echo.echo_info(f"Will create {len(collections_to_create)} orbital collections")

        # Import each collection
        created_collections = []
        for collection_info in collections_to_create:
            collection_name = collection_info["name"]
            set_name = collection_info["set_name"]
            description = collection_info["description"]

            # Check if collection already exists
            try:
                existing_collection = load_group(label=collection_name)
                echo.echo_warning(
                    f"Collection '{collection_name}' already exists with {existing_collection.count()} orbitals"
                )
                if click.confirm(f"Do you want to skip importing '{collection_name}'?", default=True):
                    continue
                else:
                    echo.echo_info(f"Re-importing '{collection_name}'")
            except Exception:
                echo.echo_info(f"Creating new collection '{collection_name}'")

            try:
                echo.echo(f"Importing {collection_name}...")
                with cli_spinner():
                    collection = AtomicOrbitalCollection.import_orbital_set(
                        repository=repo_path,
                        set_name=set_name,
                        dryrun=False,
                        group_label=collection_name,
                    )

                if collection is not None:
                    collection.description = description
                    created_collections.append((collection_name, collection.count()))
                    echo.echo_success(
                        f"Successfully imported collection '{collection_name}' with {collection.count()} orbitals"
                    )
                else:
                    echo.echo_info(f"Collection '{collection_name}' already up to date")

            except Exception as e:
                echo.echo_error(f"Failed to import collection '{collection_name}': {e}")
                if not click.confirm("Continue with other collections?", default=True):
                    break

        if created_collections:
            echo.echo("")
            echo.echo_success("Import process completed!")
            echo.echo_info("Created collections:")
            for coll_name, count in created_collections:
                echo.echo(f"  - {coll_name}: {count} orbitals")
            echo.echo("")
            echo.echo_info("Next steps:")
            echo.echo("  1. List collections: aiida-abacus pseudos list-collections")
            echo.echo("  2. Show collection details: aiida-abacus pseudos show-collection <label>")
            echo.echo(
                "  3. Create family: aiida-abacus pseudos create-family <collection> <family> "
                "--orbital-type dzp --rcuts <json>"
            )
        else:
            echo.echo_info("No new collections were created")


def _install_from_known_set(name: str, force_download: bool, dry_run: bool) -> None:
    """Install a known pseudopotential and orbital set."""
    if name not in KNOWN_SETS:
        raise click.Abort(f"Unknown pseudopotential set: {name}")

    set_info = KNOWN_SETS[name]
    url = set_info["url"]
    expected_md5 = set_info["md5"]

    # Download and verify using helper
    cache_file = _download_and_verify(url, expected_md5, name, force_download)

    if dry_run:
        echo.echo_info("DRY RUN - Would extract and import the following collections:")
        echo.echo(f"  Archive: {cache_file}")
        # Show what would be imported based on the set type
        if "apns" in name.lower():
            echo.echo("  Expected collections:")
            echo.echo("    - apns-efficiency-v1")
            echo.echo("    - apns-precision-v1")
        else:
            echo.echo(f"  Would create collection: {name}")
        return

    # APNS has special multi-collection structure
    if "apns" in name.lower():
        _import_apns_set(cache_file)
    else:
        # Generic sets - import as single collection using local path import
        _install_from_local_paths(
            paths=(str(cache_file),), label=name, description=set_info.get("description", ""), dry_run=False
        )


def _install_from_local_paths(paths: tuple[str, ...], label: str, description: str, dry_run: bool) -> None:
    """Install collection from local directories or ZIP files."""
    # Validate inputs
    if not label:
        echo.echo_error("--label is required when installing from local paths")
        raise click.Abort()

    # Validate all paths exist
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            echo.echo_error(f"Path does not exist: {path}")
            raise click.Abort()

    echo.echo(f"Installing collection from {len(paths)} local path(s)")
    for path in paths:
        echo.echo(f"  - {path}")
    echo.echo("")

    if dry_run:
        echo.echo_info("DRY RUN - Would scan paths and create collection:")
        echo.echo(f"  Label: {label}")
        echo.echo(f"  Description: {description or '(none)'}")

        # Quick scan to show what would be found
        total_orbs = 0
        total_upfs = 0
        for path_str in paths:
            path = Path(path_str)
            with temporary_unzip_folder(path) as unzipped:
                orb_files = list(unzipped.rglob("*.orb"))
                upf_files = list(unzipped.rglob("*.upf")) + list(unzipped.rglob("*.UPF"))
                total_orbs += len(orb_files)
                total_upfs += len(upf_files)

        echo.echo(f"  Total files: {total_orbs} orbitals, {total_upfs} pseudopotentials")
        return

    # Check if collection already exists
    try:
        existing_collection = load_group(label=label)
        echo.echo_warning(f"Collection '{label}' already exists with {existing_collection.count()} orbitals")
        if not click.confirm("Do you want to continue (may add duplicates)?", default=False):
            raise click.Abort()
    except Exception:
        echo.echo_info(f"Creating new collection '{label}'")

    # Import from paths
    try:
        echo.echo("Importing orbitals from local paths...")
        with cli_spinner():
            collection = AtomicOrbitalCollection.import_from_local_paths(
                paths=list(paths), group_label=label, description=description, dryrun=False
            )

        if collection:
            echo.echo_success(f"Successfully created collection '{label}' with {collection.count()} orbitals")

            # Show statistics
            stats = collection.get_statistics()
            echo.echo("")
            echo.echo_info("Collection statistics:")
            echo.echo(f"  Elements: {stats['element_count']}")
            echo.echo(f"  Total orbitals: {stats['total_orbitals']}")
            echo.echo(f"  Orbital types: {', '.join(f'{k}({v})' for k, v in stats['orbital_types'].items())}")

            # Show elements with multiple variants
            variants_per_elem = stats["variants_per_element"]
            multi_variant = {e: c for e, c in variants_per_elem.items() if c > 1}
            if multi_variant:
                echo.echo(f"  Elements with multiple variants: {len(multi_variant)}")
                for elem, count in sorted(multi_variant.items())[:5]:  # Show first 5
                    echo.echo(f"    {elem}: {count} variants")
                if len(multi_variant) > 5:
                    echo.echo(f"    ... and {len(multi_variant) - 5} more")

            echo.echo("")
            echo.echo_info("Next steps:")
            echo.echo("  1. List collections: aiida-abacus pseudos list-collections")
            echo.echo(f"  2. Show collection details: aiida-abacus pseudos show-collection {label}")
            echo.echo(f"  3. Create family: aiida-abacus pseudos create-family {label} <family-label>")
        else:
            echo.echo_info("Collection already up to date")

    except Exception as e:
        echo.echo_error(f"Failed to import collection: {e}")
        traceback.print_exc()
        raise click.Abort()


@pseudos.command()
def list_sets() -> None:
    """List all available pseudopotential sets that can be installed by name."""
    echo.echo_info("Available pseudopotential sets:")
    for name, info in KNOWN_SETS.items():
        echo.echo(f"  {name}: {info['description']}")
        echo.echo(f"    URL: {info['url']}")
        echo.echo(f"    MD5: {info['md5']}")
        echo.echo("")

    echo.echo_info("You can also install from local directories or ZIP files:")
    echo.echo("  aiida-abacus pseudos install-collection /path/to/files --label my-collection")
    echo.echo("  aiida-abacus pseudos install-collection path1.zip path2/ --label combined")
    echo.echo("")


@pseudos.command("list-families")
@with_dbenv()
def list_families() -> None:
    """List all imported orbital families."""
    try:
        qb = QueryBuilder()
        qb.append(AtomicOrbitalFamily, project=["id", "label", "description"])
        families = qb.all()

        if not families:
            echo.echo_info("No orbital families found. Use 'aiida-abacus pseudos install' to import some.")
            return

        # Prepare data for table
        table_data = []
        for pk, label, description in families:
            # Get count of nodes in the family
            qb_count = QueryBuilder()
            qb_count.append(AtomicOrbitalFamily, filters={"label": label})
            qb_count.append(aiida_orm.Data, with_group=AtomicOrbitalFamily)
            node_count = qb_count.count()

            # Get variant choices if available
            family = load_group(label)
            variant_choices = family.base.extras.get("variant_choices", {})
            if variant_choices:
                variant_info = f"{len(variant_choices)} elements with variants"
            else:
                variant_info = "Default"
            table_data.append([pk, label, node_count, variant_info, description or "No description"])

        # Sort by family name
        table_data.sort(key=lambda x: x[0])

        # Display the table using tabulate
        echo.echo_info("Imported orbital families:")
        headers = ["PK", "Family Name", "Orbitals", "Variants", "Description"]
        echo.echo(tabulate.tabulate(table_data, headers=headers, tablefmt="simple"))

    except Exception as e:
        echo.echo_error(f"Failed to list families: {e}")


@pseudos.command("show-family")
@click.argument("family_label")
@with_dbenv()
def show_family(family_label: str) -> None:
    """Show detailed information about a specific orbital family, including pseudopotentials and orbitals."""
    # Find the family
    qb = QueryBuilder()
    qb.append(AtomicOrbitalFamily, filters={"label": family_label})
    family_result = qb.first()

    if not family_result:
        echo.echo_error(f"Family '{family_label}' not found.")
        echo.echo_info("Available families:")
        qb_all = QueryBuilder()
        qb_all.append(AtomicOrbitalFamily, project=["label"])
        for (label,) in qb_all.all():
            echo.echo(f"  {label}")
        raise click.Abort()

    family = family_result[0]

    # Get description and variant choices if available
    description = getattr(family, "description", "No description available")
    variant_choices = family.base.extras.get("variant_choices", {})

    echo.echo(f"Family: {family_label}")
    echo.echo(f"Description: {description}")
    echo.echo(f"Number of orbitals: {family.count()}")

    if variant_choices:
        echo.echo(f"Variant choices stored: {len(variant_choices)} elements")
        echo.echo("  Selected orbital files:")
        for element, filename in sorted(variant_choices.items()):
            echo.echo(f"    {element}: {filename}")
    echo.echo("")

    # Get all orbital data nodes in the family
    qb_orbitals = QueryBuilder()
    qb_orbitals.append(AtomicOrbitalFamily, filters={"label": family_label})
    qb_orbitals.append(aiida_orm.Data, with_group=AtomicOrbitalFamily)

    orbitals = qb_orbitals.all()

    if not orbitals:
        echo.echo_warning("No orbitals found in this family.")
        return

    # Prepare data for table
    table_data = []
    for (orbital_node,) in orbitals:
        # Get orbital attributes
        element = orbital_node.base.attributes.get("element", "Unknown")
        orbital_filename = orbital_node.base.attributes.get("filename_second", "Unknown")
        upf_filename = orbital_node.base.attributes.get("filename", "Unknown")

        table_data.append([str(orbital_node.pk), element, orbital_filename, upf_filename])

    # Sort by element for better readability
    table_data.sort(key=lambda x: x[1])

    # Display the table using tabulate
    echo.echo_info("Orbital and pseudopotential details:")
    headers = ["PK", "Element", "Orbital File", "Pseudopotential File"]
    echo.echo(tabulate.tabulate(table_data, headers=headers, tablefmt="simple"))

    echo.echo("")
    echo.echo_info(f"Total: {len(orbitals)} elements in family")


@pseudos.command("list-collections")
@with_dbenv()
def list_collections() -> None:
    """List all imported orbital collections."""
    try:
        qb = QueryBuilder()
        qb.append(AtomicOrbitalCollection, project=["id", "label", "description"])
        collections = qb.all()

        if not collections:
            echo.echo_info(
                "No orbital collections found. Use 'aiida-abacus pseudos install-collection' to import some."
            )
            return

        # Prepare data for table
        table_data = []
        for pk, label, description in collections:
            # Load the collection to get statistics
            collection = load_group(label)
            stats = collection.get_statistics()

            # Calculate max variants per element
            variants_per_elem = stats.get("variants_per_element", {})
            max_variants = max(variants_per_elem.values()) if variants_per_elem else 0
            avg_variants = sum(variants_per_elem.values()) / len(variants_per_elem) if variants_per_elem else 0

            variant_info = f"max={max_variants}, avg={avg_variants:.1f}" if max_variants > 1 else "1"

            table_data.append(
                [
                    pk,
                    label,
                    stats.get("total_orbitals", 0),
                    stats.get("element_count", 0),
                    variant_info,
                    description or "No description",
                ]
            )

        # Sort by label
        table_data.sort(key=lambda x: x[1])

        # Display the table using tabulate
        echo.echo_info("Imported orbital collections:")
        headers = ["PK", "Collection Label", "Orbitals", "Elements", "Variants", "Description"]
        echo.echo(tabulate.tabulate(table_data, headers=headers, tablefmt="simple"))

    except Exception as e:
        echo.echo_error(f"Failed to list collections: {e}")


@pseudos.command("show-collection")
@click.argument("collection_label")
@with_dbenv()
def show_collection(collection_label: str) -> None:
    """Show detailed information about a specific orbital collection."""
    # Find the collection
    qb = QueryBuilder()
    qb.append(AtomicOrbitalCollection, filters={"label": collection_label})
    collection_result = qb.first()

    if not collection_result:
        echo.echo_error(f"Collection '{collection_label}' not found.")
        echo.echo_info("Available collections:")
        qb_all = QueryBuilder()
        qb_all.append(AtomicOrbitalCollection, project=["label"])
        for (label,) in qb_all.all():
            echo.echo(f"  {label}")
        raise click.Abort()

    collection = collection_result[0]

    # Get description
    description = getattr(collection, "description", "No description available")

    echo.echo(f"Collection: {collection_label}")
    echo.echo(f"Description: {description}")
    echo.echo(f"Number of orbitals: {collection.count()}")
    echo.echo("")

    # Get statistics
    stats = collection.get_statistics()

    echo.echo_info("Statistics:")
    echo.echo(f"  Total orbitals: {stats['total_orbitals']}")
    echo.echo(f"  Unique elements: {stats['element_count']}")
    echo.echo(f"  Orbital types: {', '.join(f'{k}({v})' for k, v in stats['orbital_types'].items())}")
    rcut_range = stats["rcut_range"]
    if rcut_range["min"] is not None and rcut_range["max"] is not None:
        echo.echo(f"  Rcut range: {rcut_range['min']:.1f} - {rcut_range['max']:.1f} au")
    echo.echo("")

    # Show elements with variant counts
    echo.echo_info("Elements and variant counts:")
    variants_per_elem = stats["variants_per_element"]

    # Group elements by variant count
    by_count = {}
    for elem, count in variants_per_elem.items():
        if count not in by_count:
            by_count[count] = []
        by_count[count].append(elem)

    for count in sorted(by_count.keys(), reverse=True):
        elements = sorted(by_count[count])
        if count == 1:
            continue
        echo.echo(f"  {count} variant(s): {', '.join(elements)}")

    echo.echo("")

    # Get all orbital data nodes in the collection
    qb_orbitals = QueryBuilder()
    qb_orbitals.append(AtomicOrbitalCollection, filters={"label": collection_label})
    qb_orbitals.append(aiida_orm.Data, with_group=AtomicOrbitalCollection)

    orbitals = qb_orbitals.all()

    # Prepare data for table
    table_data = []
    for (orbital_node,) in orbitals:
        # Get orbital attributes
        element = orbital_node.base.attributes.get("element", "Unknown")
        orbital_filename = orbital_node.base.attributes.get("filename_second", "Unknown")
        upf_filename = orbital_node.base.attributes.get("filename", "Unknown")

        table_data.append([str(orbital_node.pk), element, orbital_filename, upf_filename])

    # Sort by element for better readability
    table_data.sort(key=lambda x: x[1])

    # Display the table using tabulate
    echo.echo_info("Orbital and pseudopotential details:")
    headers = ["PK", "Element", "Orbital File", "Pseudopotential File"]
    echo.echo(tabulate.tabulate(table_data, headers=headers, tablefmt="simple"))


@pseudos.command("create-family")
@click.argument("collection_label")
@click.argument("family_label")
@click.option(
    "--description",
    default="",
    help="Description for the created family",
)
@with_dbenv()
def create_family(collection_label: str, family_label: str, description: str) -> None:
    """
    Create an AtomicOrbitalFamily from a collection interactively.

    COLLECTION_LABEL is the label of the source collection.
    FAMILY_LABEL is the label for the new family.

    Example:
        aiida-abacus pseudos create-family apns-efficiency-v1 my-family
    """
    # Check if collection exists
    try:
        collection = load_group(collection_label)
        if not isinstance(collection, AtomicOrbitalCollection):
            echo.echo_error(f"Group '{collection_label}' is not an AtomicOrbitalCollection")
            raise click.Abort()
    except Exception as e:
        echo.echo_error(f"Collection '{collection_label}' not found: {e}")
        echo.echo_info("Available collections:")
        qb = QueryBuilder()
        qb.append(AtomicOrbitalCollection, project=["label"])
        for (label,) in qb.all():
            echo.echo(f"  {label}")
        raise click.Abort()

    # Check if family already exists
    try:
        load_group(family_label)
        echo.echo_error(f"Family '{family_label}' already exists")
        raise click.Abort()
    except Exception:
        pass  # Family doesn't exist, which is what we want

    # Display collection info
    stats = collection.get_statistics()
    echo.echo(
        f"\nCollection: {collection_label} ({stats['total_orbitals']} orbitals, {stats['element_count']} elements)"
    )

    # Auto-detect orbital type
    orbital_types = stats.get("orbital_types", {})
    if len(orbital_types) == 1:
        orbital_type = next(iter(orbital_types.keys()))
        echo.echo(f"Auto-detected orbital type: {orbital_type}")
    elif len(orbital_types) > 1:
        echo.echo_error(f"Multiple orbital types found in collection: {list(orbital_types.keys())}")
        echo.echo_error("Collection must have a single orbital type")
        raise click.Abort()
    else:
        echo.echo_error("No orbital types found in collection")
        raise click.Abort()

    # Interactive mode: let user select orbital files directly
    echo.echo_info("Entering interactive mode - select orbital files for each element")

    try:
        selected_nodes = select_orbital_files_interactive(collection)
    except KeyboardInterrupt:
        echo.echo("\nOperation cancelled by user.")
        raise click.Abort()

    # Show summary
    echo.echo("\n" + "=" * 60)
    echo.echo("Summary:")
    echo.echo(f"  Collection: {collection_label}")
    echo.echo(f"  Family: {family_label}")
    echo.echo(f"  Orbital type: {orbital_type}")
    echo.echo(f"  Elements selected: {len(selected_nodes)}")
    echo.echo("")

    if not click.confirm("Create family with selected orbitals?", default=True):
        echo.echo("Operation cancelled.")
        raise click.Abort()

    # Create family from selected nodes
    echo.echo_info(f"Creating family '{family_label}'...")
    try:
        family = AtomicOrbitalFamily(label=family_label)
        family.store()

        # Load and add selected nodes
        nodes_to_add = [load_node(pk) for pk in selected_nodes.values()]
        family.add_nodes(nodes_to_add)

        if description:
            family.description = description

        echo.echo_success(f"Successfully created family '{family_label}' with {family.count()} orbitals")

        # Show which elements were included
        elements = sorted([node.element for node in family.nodes])
        echo.echo_info(f"Elements included: {', '.join(elements)}")

    except Exception as e:
        echo.echo_error(f"Failed to create family: {e}")
        raise click.Abort()


@pseudos.command("install-sg15")
@click.option("--tag", default="dzp", type=click.Choice(["sz", "dzp", "tzdp"]), help="Basis set tag.")
@click.option("--functional", default="PBE", help="XC functional.")
@click.option("--update", is_flag=True, help="Force re-download and re-install.")
@click.option("--dry-run", is_flag=True, help="Show what would be done.")
@click.option(
    "--source-path",
    default=None,
    type=click.Path(exists=True),
    help="Local path to archive (skip download).",
)
@with_dbenv()
def install_sg15(tag: str, functional: str, update: bool, dry_run: bool, source_path: str | None) -> None:
    """Install SG15 ONCV pseudopotentials with numerical atomic orbitals.

    Downloads the ABACUS-orbitals repository from GitHub (pinned commit) and creates
    both a collection (all variants) and a default family (one orbital per element).

    The default family label follows the pattern: SG15-v1.0-PBE-<tag>
    """
    _install_from_source(
        source_key="sg15",
        tag=tag,
        functional=functional,
        update=update,
        dry_run=dry_run,
        source_path=Path(source_path) if source_path else None,
    )


@pseudos.command("install-dojo")
@click.option("--tag", default="dzp", type=click.Choice(["dzp", "tzdp"]), help="Basis set tag.")
@click.option(
    "--relativistic",
    type=click.Choice(["SR", "FR"]),
    default="SR",
    help="Scalar-relativistic or full-relativistic.",
)
@click.option("--functional", default="PBE", help="XC functional.")
@click.option("--include-lanthanides", is_flag=True, help="Also import Dojo-NC-SR La-Series orbitals.")
@click.option("--update", is_flag=True, help="Force re-download and re-install.")
@click.option("--dry-run", is_flag=True, help="Show what would be done.")
@click.option(
    "--source-path",
    default=None,
    type=click.Path(exists=True),
    help="Local path to archive (skip download).",
)
@with_dbenv()
def install_dojo(
    tag: str,
    relativistic: str,
    functional: str,
    include_lanthanides: bool,
    update: bool,
    dry_run: bool,
    source_path: str | None,
) -> None:
    """Install PseudoDojo norm-conserving pseudopotentials with numerical atomic orbitals.

    Downloads the ABACUS-orbitals repository from GitHub (pinned commit) and creates
    both a collection and a default family.

    The default family label follows the pattern: DOJO-v0.4-PBE-<SR|FR>-<tag>
    """
    source_key = f"dojo-{relativistic.lower()}"
    # Override the functional to include relativistic info in the label
    extra_dirs = None
    if include_lanthanides:
        extra_dirs = [Path("Dojo-NC-SR_La-Series")]

    # We need a custom label that includes the relativistic tag
    config = SOURCE_CONFIGS[source_key]
    func = functional or config.functional
    label = _make_label(config.name, config.version, f"{func}-{relativistic}", tag)
    collection_label = f"{config.name}-{config.version}-{func}-{relativistic}"

    if dry_run:
        echo.echo_info("DRY RUN - would perform the following:")
        echo.echo(f"  Source: PseudoDojo NC-{relativistic} {config.version}")
        echo.echo(f"  Functional: {func}")
        echo.echo(f"  Tag: {tag}")
        echo.echo(f"  Include lanthanides: {include_lanthanides}")
        echo.echo(f"  Family label: {label}")
        echo.echo(f"  Collection label: {collection_label}")
        return

    if _check_already_installed(label, config, tag, update):
        return

    _install_from_source(
        source_key=source_key,
        tag=tag,
        functional=f"{func}-{relativistic}",
        update=update,
        dry_run=False,
        source_path=Path(source_path) if source_path else None,
        extra_source_dirs=extra_dirs,
    )


@pseudos.command("install-apns")
@click.option(
    "--tag",
    default="efficiency",
    type=click.Choice(["efficiency", "precision"]),
    help="Orbital series tag.",
)
@click.option("--functional", default="PBE", help="XC functional.")
@click.option("--update", is_flag=True, help="Force re-download and re-install.")
@click.option("--dry-run", is_flag=True, help="Show what would be done.")
@with_dbenv()
def install_apns(tag: str, functional: str, update: bool, dry_run: bool) -> None:
    """Install APNS pseudopotential and orbital set.

    Downloads from AISS Square and creates both a collection and a default family.

    The default family label follows the pattern: APNS-v1-PBE-<tag>
    """
    _install_from_source(
        source_key="apns",
        tag=tag,
        functional=functional,
        update=update,
        dry_run=dry_run,
    )


@pseudos.command("install-collection")
@click.argument("sources", nargs=-1, required=True)
@click.option(
    "--label",
    "-l",
    type=str,
    default=None,
    help="Label for created collection (required for local paths)",
)
@click.option(
    "--description",
    "-d",
    type=str,
    default="",
    help="Description for the collection",
)
@click.option(
    "--force-download",
    is_flag=True,
    default=False,
    help="Force re-download even if cached file exists (known sets only)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without actually importing",
)
@with_dbenv()
def install_collection(
    sources: tuple[str, ...], label: str, description: str, force_download: bool, dry_run: bool
) -> None:
    """
    Install pseudopotential and orbital collections from known sets or local paths.

    SOURCES can be:
    - A known set name (e.g., 'apns-efficiency/precision-v1')
    - One or more local directory or ZIP file paths

    Examples:

        # Install from known set
        aiida-abacus pseudos install-collection apns-efficiency/precision-v1

        # Install from local directory
        aiida-abacus pseudos install-collection /path/to/orbitals --label my-collection

        # Install from multiple paths
        aiida-abacus pseudos install-collection /path/to/set1 /path/to/set2.zip --label combined

        # Install from ZIP file
        aiida-abacus pseudos install-collection orbitals.zip --label from-zip

    For known sets, this downloads and imports predefined collections.
    For local paths, this recursively scans for .orb and .upf/.UPF files and creates
    a single collection with ALL orbital variants (no selection).

    Collections store ALL orbital variants. Use 'aiida-abacus pseudos create-family'
    to create calculation-ready families from collections.
    """
    # Decision: known set or local paths?
    if len(sources) == 1 and sources[0] in KNOWN_SETS:
        # Existing behavior: known set download
        _install_from_known_set(name=sources[0], force_download=force_download, dry_run=dry_run)
    else:
        # New behavior: local path import
        _install_from_local_paths(paths=sources, label=label, description=description, dry_run=dry_run)
