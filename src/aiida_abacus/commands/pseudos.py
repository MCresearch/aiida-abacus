"""
Pseudopotential and orbital management commands for AiiDA-abacus.

This module provides commands to download, install, and manage ABACUS pseudopotentials
and numerical atomic orbitals from various sources.
"""

import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile
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

from ..group.orb_group import AtomicOrbitalCollection, AtomicOrbitalFamily, OrbitalFamilyImporter, parse_orb_metadata

# Import the main command group to attach subcommands to it
from . import cmd_aiida_abacus


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


@pseudos.command()
@click.argument("name", type=click.Choice(list(KNOWN_SETS.keys())))
@click.option(
    "--force-download",
    is_flag=True,
    default=False,
    help="Force re-download even if cached file exists",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without actually importing",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Show detailed progress information during import",
)
@click.option(
    "--collection-only",
    is_flag=True,
    default=False,
    help=(
        "Import as collections only (recommended). "
        "Use 'create-family' afterwards to create calculation-ready families."
    ),
)
@with_dbenv()
def install(name: str, force_download: bool, dry_run: bool, verbose: bool, collection_only: bool) -> None:
    """
    Install a known pseudopotential and orbital set.

    NAME is the name of the pseudopotential set to install.

    Available sets:
    - apns-efficiency/precision-v1: APNS efficiency and precision pseudopotential and orbital set

    This command will:
    1. Download the archive from the specified URL (with caching)
    2. Verify the MD5 checksum
    3. Extract the archive
    4. Create orbital families from the extracted content (or collections with --collection-only)
    5. Import pseudopotentials and orbitals into AiiDA

    With --collection-only flag (recommended):
    - Creates collections that store ALL orbital variants
    - Use 'create-family' command afterwards to create calculation-ready families
    - More flexible workflow for selecting specific orbitals

    Without --collection-only flag (legacy):
    - Directly creates families (may require interactive variant selection)
    - For the APNS set, creates two orbital families:
      - apns-efficiency-v1: efficiency orbitals with corresponding pseudopotentials
      - apns-precision-v1: precision orbitals with corresponding pseudopotentials
    """
    # If collection-only flag is set, delegate to install_collection
    if collection_only:
        echo.echo_info("Using collection-only mode (recommended workflow)")
        return install_collection(name, force_download, dry_run)

    # Legacy behavior: direct family creation with variant selection
    echo.echo_warning(
        "Using legacy family creation mode. " "Consider using --collection-only flag for more flexible workflow."
    )

    if name not in KNOWN_SETS:
        raise click.Abort(f"Unknown pseudopotential set: {name}")

    set_info = KNOWN_SETS[name]
    url = set_info["url"]
    expected_md5 = set_info["md5"]

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
                return install(name, force_download=True, dry_run=dry_run, verbose=verbose)
        raise click.Abort(f"MD5 checksum verification failed for {cache_file}")

    echo.echo_success("MD5 checksum verified")

    if dry_run:
        echo.echo_info("DRY RUN - Would extract and import the following:")
        echo.echo(f"  Archive: {cache_file}")
        echo.echo("  Expected families:")
        echo.echo("    - apns-efficiency-v1 (efficiency)")
        echo.echo("    - apns-precision-v1 (precision)")
        return

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

        # Define the families to create
        families_to_create = []

        # Always add efficiency family
        families_to_create.append(
            {
                "name": "apns-efficiency-v1",
                "orbital_dir": orbital_efficiency_dir,
                "description": "APNS efficiency orbital family (v1)",
            }
        )

        # Add precision family if precision orbitals are found
        if orbital_precision_dir:
            families_to_create.append(
                {
                    "name": "apns-precision-v1",
                    "orbital_dir": orbital_precision_dir,
                    "description": "APNS precision orbital family (v1)",
                }
            )

        echo.echo_info(f"Will create {len(families_to_create)} orbital families:")
        for family in families_to_create:
            echo.echo(f"  - {family['name']}: {family['description']}")

        # Import each family
        for family in families_to_create:
            family_name = family["name"]
            orbital_dir = family["orbital_dir"]
            description = family["description"]

            # Check if family already exists
            try:
                existing_group = load_group(label=family_name)
                echo.echo_warning(f"Family '{family_name}' already exists with {existing_group.count()} members")
                if click.confirm(f"Do you want to skip importing '{family_name}'?", default=True):
                    continue
                else:
                    echo.echo_info(f"Re-importing '{family_name}' (this may create duplicates)")
            except Exception:
                echo.echo_info(f"Creating new family '{family_name}'")

            with cli_spinner():
                try:
                    # Check for multiple orbital variants and handle selection
                    orbital_files = list(orbital_dir.rglob("*.orb"))

                    # Parse elements from orbital files

                    element_orbitals = {}
                    for orbital_path in orbital_files:
                        try:
                            metadata = parse_orb_metadata(orbital_path)
                            element = metadata.get("Element", "").strip()
                            if element:
                                if element not in element_orbitals:
                                    element_orbitals[element] = []
                                element_orbitals[element].append(orbital_path)
                        except Exception:
                            # Fallback to filename parsing
                            element = orbital_path.stem.split("_")[0]
                            if element and len(element) > 0:
                                if element not in element_orbitals:
                                    element_orbitals[element] = []
                                element_orbitals[element].append(orbital_path)

                    # Check if we have multiple variants
                    has_variants = any(len(variants) > 1 for variants in element_orbitals.values())
                    variant_choices = {}
                    final_family_name = family_name
                    needs_uuid_prefix = False

                    if has_variants and not dry_run:
                        echo.echo(
                            "Multiple orbital variants found - launching interactive selection" f"for {family_name}"
                        )
                        selected_orbitals, manual_selection = select_orbital_variants(element_orbitals)

                        # Store variant choices for group extras
                        for element, orbital_path in selected_orbitals.items():
                            variant_choices[element] = orbital_path.name

                        # Add UUID prefix to family name since we have variants
                        needs_uuid_prefix = True

                    # Update family name with UUID prefix if needed
                    if needs_uuid_prefix:
                        uuid_prefix = str(uuid.uuid4())[:8]
                        final_family_name = f"{family_name}-{uuid_prefix}"
                        echo.echo(f"Created variant-specific family: {final_family_name}")

                    # Import the orbital family
                    group = OrbitalFamilyImporter.import_folder(
                        orbital_path=str(orbital_dir),
                        pseudo_path=str(pseudopotential_dir),
                        label=final_family_name,
                        dryrun=False,
                        stop_if_inconsistent=False,  # Continue on inconsistencies for real-world datasets
                        verbose=verbose,  # Show detailed progress based on user preference
                        variant_choices=selected_orbitals if needs_uuid_prefix else None,
                    )
                    group.description = description

                    if group is not None:
                        # Store variant choices in group extras
                        if variant_choices:
                            group.base.extras.set("variant_choices", manual_selection)

                        echo.echo_success(
                            f"Successfully imported family '{final_family_name}' with {group.count()} orbitals"
                        )
                        if needs_uuid_prefix:
                            echo.echo_info(f"UUID prefix {uuid_prefix} added to distinguish variant selection")
                    else:
                        echo.echo_info(f"Family '{final_family_name}' already up to date (no new nodes)")

                except Exception as e:
                    echo.echo_error(f"Failed to import family '{family_name}': {e}")
                    if not click.confirm("Continue with other families?", default=True):
                        break

        echo.echo_success("Import process completed!")


@pseudos.command()
def list_sets() -> None:
    """List all available pseudopotential sets."""
    echo.echo_info("Available pseudopotential sets:")
    for name, info in KNOWN_SETS.items():
        echo.echo(f"  {name}: {info['description']}")
        echo.echo(f"    URL: {info['url']}")
        echo.echo(f"    MD5: {info['md5']}")
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
                "No orbital collections found. " "Use 'aiida-abacus pseudos install-collection' to import some."
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
        echo.echo(f"  {count} variant(s): {', '.join(elements)}")

    echo.echo("")

    # Show detailed orbital list (paginated if too many)
    if collection.count() <= 50:
        # Get all orbital data nodes in the collection
        qb_orbitals = QueryBuilder()
        qb_orbitals.append(AtomicOrbitalCollection, filters={"label": collection_label})
        qb_orbitals.append(aiida_orm.Data, with_group=AtomicOrbitalCollection)

        orbitals = qb_orbitals.all()

        # Prepare data for table
        table_data = []
        for (orbital_node,) in orbitals:
            # Get orbital attributes
            attrs = orbital_node.base.attributes.all
            element = attrs.get("element", "Unknown")
            orbital_type = attrs.get("orbital_type", "Unknown")
            rcut = attrs.get("rcut_au", "N/A")
            energy = attrs.get("cut_off_energy_ry", "N/A")
            config = attrs.get("electron_config", "N/A")

            table_data.append([str(orbital_node.pk), element, orbital_type, f"{rcut}", f"{energy}", config])

        # Sort by element, then rcut
        table_data.sort(key=lambda x: (x[1], float(x[3]) if x[3] != "N/A" else 0))

        # Display the table using tabulate
        echo.echo_info("Orbital details:")
        headers = ["PK", "Element", "Type", "Rcut (au)", "Ecut (Ry)", "Config"]
        echo.echo(tabulate.tabulate(table_data, headers=headers, tablefmt="simple"))
    else:
        echo.echo_info(
            f"Collection has {collection.count()} orbitals (too many to display). "
            "Use list_variants() method to query specific elements."
        )


@pseudos.command("create-family")
@click.argument("collection_label")
@click.argument("family_label")
@click.option(
    "--orbital-type",
    default=None,
    help="Orbital type (e.g., 'gga', 'pbe'). If not provided, will be auto-detected.",
)
@click.option(
    "--rcuts",
    default=None,
    help="Path to JSON file with rcut specifications or inline JSON string. If not provided, enters interactive mode.",
)
@click.option(
    "--description",
    default="",
    help="Description for the created family",
)
@with_dbenv()
def create_family(collection_label: str, family_label: str, orbital_type: str, rcuts: str, description: str) -> None:
    """
    Create an AtomicOrbitalFamily from a collection.

    COLLECTION_LABEL is the label of the source collection.
    FAMILY_LABEL is the label for the new family.

    Example:
        aiida-abacus pseudos create-family apns-efficiency-v1 my-family --orbital-type dzp --rcuts rcuts.json
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

    # Detect orbital type if not provided
    if orbital_type is None:
        orbital_types = stats.get("orbital_types", {})
        if len(orbital_types) == 1:
            orbital_type = next(iter(orbital_types.keys()))
            echo.echo(f"Auto-detected orbital type: {orbital_type}")
        elif len(orbital_types) > 1:
            echo.echo_error(f"Multiple orbital types found in collection: {list(orbital_types.keys())}")
            echo.echo_error("Please specify --orbital-type explicitly")
            raise click.Abort()
        else:
            echo.echo_error("No orbital types found in collection")
            raise click.Abort()

    # Determine mode: interactive or non-interactive
    if rcuts is None:
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

    else:
        # Non-interactive mode: use rcuts specification
        rcuts_dict = {}
        try:
            # Try to load as file first
            rcuts_path = Path(rcuts)
            if rcuts_path.exists():
                rcuts_dict = json.loads(rcuts_path.read_text())
                echo.echo_info(f"Loaded rcut specifications from {rcuts}")
            else:
                # Try to parse as inline JSON
                rcuts_dict = json.loads(rcuts)
                echo.echo_info("Parsed inline rcut specifications")
        except Exception as e:
            echo.echo_error(f"Failed to parse rcut specifications: {e}")
            echo.echo_info("Rcuts should be a JSON file path or inline JSON string like:")
            echo.echo('  {"Si": 7, "O": 6, "Other": 7}')
            raise click.Abort()

        # Create family from collection using rcuts
        echo.echo_info(f"Creating family '{family_label}' from collection '{collection_label}'...")
        echo.echo(f"  Orbital type: {orbital_type}")
        echo.echo(f"  Rcut specification: {len(rcuts_dict)} entries")

        try:
            with cli_spinner():
                family = collection.create_family(family_label, orbital_type, rcuts_dict)

            if description:
                family.description = description

            echo.echo_success(f"Successfully created family '{family_label}' with {family.count()} orbitals")

            # Show which elements were included
            elements = sorted([node.element for node in family.nodes])
            echo.echo_info(f"Elements included: {', '.join(elements)}")

        except Exception as e:
            echo.echo_error(f"Failed to create family: {e}")
            raise click.Abort()


@pseudos.command("install-collection")
@click.argument("name", type=click.Choice(list(KNOWN_SETS.keys())))
@click.option(
    "--force-download",
    is_flag=True,
    default=False,
    help="Force re-download even if cached file exists",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be done without actually importing",
)
@with_dbenv()
def install_collection(name: str, force_download: bool, dry_run: bool) -> None:
    """
    Install a known pseudopotential and orbital set as collections.

    NAME is the name of the pseudopotential set to install.

    This command will:
    1. Download the archive from the specified URL (with caching)
    2. Verify the MD5 checksum
    3. Extract the archive
    4. Create orbital collections (one for each subset found)

    For the APNS set, this will create two orbital collections:
    - apns-efficiency-v1: efficiency orbitals repository
    - apns-precision-v1: precision orbitals repository

    Collections store ALL orbital variants. Use 'aiida-abacus pseudos create-family'
    to create calculation-ready families from collections.
    """
    if name not in KNOWN_SETS:
        raise click.Abort(f"Unknown pseudopotential set: {name}")

    set_info = KNOWN_SETS[name]
    url = set_info["url"]
    expected_md5 = set_info["md5"]

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
                return install_collection(name, force_download=True, dry_run=dry_run)
        raise click.Abort(f"MD5 checksum verification failed for {cache_file}")

    echo.echo_success("MD5 checksum verified")

    if dry_run:
        echo.echo_info("DRY RUN - Would extract and import the following collections:")
        echo.echo(f"  Archive: {cache_file}")
        echo.echo("  Expected collections:")
        echo.echo("    - apns-efficiency-v1")
        echo.echo("    - apns-precision-v1")
        return

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
