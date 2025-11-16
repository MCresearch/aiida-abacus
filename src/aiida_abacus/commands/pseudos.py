"""
Pseudopotential and orbital management commands for AiiDA-abacus.

This module provides commands to download, install, and manage ABACUS pseudopotentials
and numerical atomic orbitals from various sources.
"""

import hashlib
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
from aiida.orm import QueryBuilder, load_group
from click_spinner import spinner as cli_spinner

from ..group.orb_group import AtomicOrbitalFamily, OrbitalFamilyImporter, parse_orb_metadata

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
@with_dbenv()
def install(name: str, force_download: bool, dry_run: bool, verbose: bool) -> None:
    """
    Install a known pseudopotential and orbital set.

    NAME is the name of the pseudopotential set to install.

    Available sets:
    - apns-efficiency/precision-v1: APNS efficiency and precision pseudopotential and orbital set

    This command will:
    1. Download the archive from the specified URL (with caching)
    2. Verify the MD5 checksum
    3. Extract the archive
    4. Create orbital families from the extracted content
    5. Import pseudopotentials and orbitals into AiiDA

    For the APNS set, this will create two orbital families:
    - apns-efficiency-v1: efficiency orbitals with corresponding pseudopotentials
    - apns-precision-v1: precision orbitals with corresponding pseudopotentials
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
        echo.echo_info(f"Downloading {name} from {url}...")

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
        echo.echo_info(f"Using cached file: {cache_file}")

    # Verify MD5 checksum
    echo.echo_info("Verifying MD5 checksum...")
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
    try:
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
            return

        family = family_result[0]

        # Get description and variant choices if available
        description = getattr(family, "description", "No description available")
        variant_choices = family.base.extras.get("variant_choices", {})

        echo.echo_info(f"Family: {family_label}")
        echo.echo(f"Description: {description}")
        echo.echo(f"Number of orbitals: {family.count()}")

        if variant_choices:
            echo.echo_info(f"Variant choices stored: {len(variant_choices)} elements")
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

    except Exception as e:
        echo.echo_error(f"Failed to show family '{family_label}': {e}")
        import traceback

        echo.echo_debug(f"Error details: {traceback.format_exc()}")
