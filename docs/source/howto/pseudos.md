(howto-pseudos)=

# Managing Pseudopotentials and Orbitals

:::{seealso}
For a complete command reference, see the [CLI Documentation](../cli.md).
:::

This guide explains how to use the `aiida-abacus pseudos` command group to manage ABACUS pseudopotentials and numerical atomic orbitals.

## When Do You Need Orbitals?

**Pseudopotentials** (`.upf` files):
- Required for **both** `basis_type: pw` (plane wave) and `basis_type: lcao` (LCAO) calculations
- Can be managed with `aiida-pseudo` for standard DFT calculations

**Numerical Atomic Orbitals** (`.orb` files):
- Required **only** for `basis_type: lcao` calculations
- Must be managed with `aiida-abacus pseudos` commands (this guide)

:::{note}
If you're only running plane wave calculations (`basis_type: pw`), you can use standard pseudopotential families from `aiida-pseudo` and don't need the orbital management features described in this guide.
:::

## Understanding Collections vs Families

ABACUS uses both pseudopotentials (.upf files) and numerical atomic orbitals (.orb files) for calculations. Many elements have multiple orbital variants with different parameters (cutoff radii, energy cutoffs, etc.).

**Collections** store ALL orbital variants:
- Include every .orb file for each element
- Used as a complete repository
- Example: Si might have 6 different orbital variants with different cutoff radii

**Families** contain ONE orbital per element:
- Calculation-ready groups
- Created by selecting specific variants from collections
- Used directly in calculations

The typical workflow is:
```
Known Set or Local Files → install-collection → Collection (all variants)
                                                       ↓
                                 create-family → Family (one per element)
```

## Listing Available Sets

View all known pseudopotential and orbital sets that can be installed:

```console
$ aiida-abacus pseudos list-sets
```

**Example output:**
```
Available pseudopotential sets:
  apns-efficiency/precision-v1: APNS efficiency and precision pseudopotential and orbital set (v1)
    URL: https://store.aissquare.com/datasets/...
    MD5: 96cc456911712a81c1db85ba6e8239ce

You can also install from local directories or ZIP files:
  aiida-abacus pseudos install-collection /path/to/files --label my-collection
  aiida-abacus pseudos install-collection path1.zip path2/ --label combined
```

Known sets are curated collections from trusted sources with verified MD5 checksums.

## Installing Collections

### From Known Sets

Install a known set by name:

```console
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1
```

This will:
1. Download the archive from the URL (or use cached version)
2. Verify the MD5 checksum
3. Extract and import the collections
4. Create two collections: `apns-efficiency-v1` and `apns-precision-v1`

**Options:**
- `--force-download` - Re-download even if cached
- `--dry-run` - Show what would be done without importing

**Example with options:**
```console
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1 --dry-run
```

### From Local Directories

Install from your own orbital files:

```console
$ aiida-abacus pseudos install-collection /path/to/orbitals --label my-collection
```

The command will recursively scan the directory for:
- `.orb` files (orbitals)
- `.upf` or `.UPF` files (pseudopotentials)

**Supported directory structures:**

Nested structure:
```
/path/to/orbitals/
├── Pseudopotential/
│   ├── Si.upf
│   ├── O.upf
│   └── ...
└── Orbitals/
    ├── Si_gga_7au_100Ry_2s2p1d.orb
    ├── Si_gga_8au_100Ry_2s2p1d.orb
    └── ...
```

Flat structure:
```
/path/to/orbitals/
├── Si.upf
├── O.upf
├── Si_gga_7au_100Ry_2s2p1d.orb
└── ...
```

:::{note}
The `--label` option is required when installing from local paths. It becomes the collection name used for later operations.
:::

### From ZIP Archives

Install directly from ZIP files:

```console
$ aiida-abacus pseudos install-collection orbitals.zip --label from-zip
```

### From Multiple Sources

Combine multiple directories and ZIP files into one collection:

```console
$ aiida-abacus pseudos install-collection /path/to/set1 /path/to/set2.zip --label combined
```

## Viewing Collections

### List All Collections

View all imported collections:

```console
$ aiida-abacus pseudos list-collections
```

**Example output:**
```
  PK  Collection Label      Orbitals    Elements  Variants        Description
----  ------------------  ----------  ----------  --------------  ------------------------------------------------------
   9  apns-efficiency-v1          70          69  max=2, avg=1.0  APNS efficiency orbital collection (v1) - all variants
  10  apns-precision-v1           90          69  max=4, avg=1.3  APNS precision orbital collection (v1) - all variants
```

This shows:
- **Orbitals**: Total number of orbital nodes
- **Elements**: Number of unique elements
- **Variants**: Maximum and average variants per element

### Show Collection Details

View detailed information about a specific collection:

```console
$ aiida-abacus pseudos show-collection apns-efficiency-v1
```

**Example output:**
```
Collection: apns-efficiency-v1
Description: APNS efficiency orbital collection (v1) - all variants
Number of orbitals: 70

  Total orbitals: 70
  Unique elements: 69
  Orbital types: gga(1)
  Rcut range: 10.0 - 10.0 au

  2 variant(s): Cs

  PK  Element    Orbital File                    Pseudopotential File
----  ---------  ------------------------------  ----------------------
   1  Ag         Ag_gga_7au_100Ry_4s2p2d1f.orb   Ag.upf
   2  Al         Al_gga_8au_100Ry_2s2p1d.orb     Al.upf
...
```

## Creating Families

Once you have a collection, create calculation-ready families by selecting specific orbital variants.

### Interactive Family Creation

Create a family interactively (recommended):

```console
$ aiida-abacus pseudos create-family apns-efficiency-v1 my-family
```

This launches an interactive process:

1. **Auto-detection**: Detects orbital type from the collection
2. **Element-by-element selection**: For each element:
   - If only one variant exists, it's selected automatically
   - If multiple variants exist, you choose interactively

**Interactive selection example:**
```
Collection: apns-efficiency-v1 (70 orbitals, 69 elements)
Auto-detected orbital type: gga

Orbital selection for 69 elements:
============================================================

Cs: Found 2 orbital variants
------------------------------
  1. Cs_gga_12au_100Ry_4s2p1d.orb
     rcut=12.0au, Ecut=100Ry, config=4s2p1d
  2. Cs_gga_10au_100Ry_4s2p1d.orb
     rcut=10.0au, Ecut=100Ry, config=4s2p1d

Select variant for Cs (1-2) [default=1]: 2
  Selected: Cs_gga_10au_100Ry_4s2p1d.orb

Ag: Only one variant - Ag_gga_7au_100Ry_4s2p2d1f.orb
Al: Only one variant - Al_gga_8au_100Ry_2s2p1d.orb
...
```

After selection, you confirm the creation:
```
============================================================
Summary:
  Collection: apns-efficiency-v1
  Family: my-family
  Orbital type: DZP
  Elements selected: 70

Create family with selected orbitals? [Y/n]: y
```

### Adding Description

Provide a description for the family:

```console
$ aiida-abacus pseudos create-family apns-efficiency-v1 my-family \
    --description "Custom ABACUS family with optimized rcuts"
```

:::{tip}
**Naming convention recommendations:**
- Collections: `<source>-<type>-<version>` (e.g., `apns-efficiency-v1`)
- Families: `<project>-<description>` (e.g., `si-oxides-standard`)
:::

## Viewing Families

### List All Families

View all imported families:

```console
$ aiida-abacus pseudos list-families
```

**Example output:**
```
Imported orbital families:
PK  Family Name       Orbitals  Variants              Description
--  ---------------  ----------  --------------------  ---------------------------
 7  my-family                70  70 elements with...  Custom ABACUS family...
```

### Show Family Details

View details of a specific family:

```console
$ aiida-abacus pseudos show-family my-family
```

**Example output:**
```
Family: my-family
Description: Custom ABACUS family with optimized rcuts
Number of orbitals: 70
Variant choices stored: 70 elements

Orbital and pseudopotential details:
PK    Element  Orbital File                     Pseudopotential File
----  -------  -------------------------------  ---------------------
1235  Si       Si_gga_8au_100Ry_2s2p1d.orb     Si.upf
2456  O        O_gga_6au_100Ry_2s2p1d.orb      O.upf
...

Total: 70 elements in family
```

## Using Families in Calculations

Once you have created a family, use it in your calculation scripts:

```python
from aiida import orm

# Load the family
family = orm.load_group("my-family")

# Get pseudopotentials and orbitals for your structure
structure = orm.load_node(<structure_pk>)
pseudos = family.get_pseudos(structure=structure)

# Use in calculation builder
builder = code.get_builder()
builder.pseudos = pseudos
```

This is essentially the same as using pseudopotential families from `aiida-pseudos`.
The only difference this that each `AtomicOrbitalData` node include both the orbital and the pseudopotential
file.

:::{note}
Families are similar to `aiida-pseudo` PseudoPotentialFamily but include both pseudopotentials and numerical atomic orbitals required by ABACUS.
:::

## Complete Workflow Examples

### Example 1: Installing and Using a Known Set

```console
# 1. List available sets
$ aiida-abacus pseudos list-sets

# 2. Install the APNS set
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1

# 3. View imported collections
$ aiida-abacus pseudos list-collections

# 4. Check collection details
$ aiida-abacus pseudos show-collection apns-efficiency-v1

# 5. Create a family interactively
$ aiida-abacus pseudos create-family apns-efficiency-v1 my-abacus-family

# 6. Verify the family
$ aiida-abacus pseudos show-family my-abacus-family
```

Then use in Python:
```python
from aiida.orm import load_group

family = load_group("my-abacus-family")
# Use in your calculations...
```

### Example 2: Using Local Orbital Files

```console
# 1. Install from local directory
$ aiida-abacus pseudos install-collection ~/my-orbitals --label custom-orbitals \
    --description "Custom orbitals for silicon oxides"

# 2. Check what was imported
$ aiida-abacus pseudos show-collection custom-orbitals

# 3. Create family (select variants interactively)
$ aiida-abacus pseudos create-family custom-orbitals si-oxide-family \
    --description "Optimized for SiO2 calculations"

# 4. Use in calculations
```

### Example 3: Combining Multiple Sources

```console
# Combine orbitals from different sources
$ aiida-abacus pseudos install-collection \
    ~/base-orbitals \
    ~/additional-elements.zip \
    --label combined-set \
    --description "Base set plus custom elements"

# Create family from combined collection
$ aiida-abacus pseudos create-family combined-set production-family
```

## Common Workflows

### Quick Start with Defaults

For users who want to get started quickly without customization:

```console
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1
$ aiida-abacus pseudos create-family apns-efficiency-v1 apns-efficiency-v1-Cs-12
# Accept select Cs orbital with 12 Bohr cut off
```

### Researcher Customizing Parameters

For researchers who need specific orbital parameters:

```console
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1
$ aiida-abacus pseudos show-collection apns-efficiency-v1
# Review available variants
$ aiida-abacus pseudos create-family apns-efficiency-v1 apns-efficiency-v1-<label>
# Carefully select variants based on convergence tests
```

### Developer Testing Multiple Families

For developers testing different configurations:

```console
# Create multiple families from same collection
$ aiida-abacus pseudos create-family apns-precision-v1 test-tight-rcut
# Select larger rcut values

$ aiida-abacus pseudos create-family apns-precision-v1 test-loose-rcut
# Select smaller rcut values

# Compare in calculations
$ aiida-abacus pseudos list-families
```

## Troubleshooting

:::{warning}
**NEVER NEVER DELETE pseudopotential or orbital nodes**
This will also delete **ALL** calculations using such potentials/orbitals as AiiDA enforces the provenance.
:::


### Collection Already Exists

If you try to install a collection that already exists:

```console
Collection 'apns-efficiency-v1' already exists with 420 orbitals
Do you want to skip importing 'apns-efficiency-v1'? [Y/n]:
```

Choose 'Y' to skip, or 'n' to re-import (may create duplicates).

### Family Already Exists

If you try to create a family with an existing name:

```console
Family 'my-family' already exists
```

Choose a different name or rename the existing family first.


### Missing Elements

If your collection doesn't have orbitals for all elements in your structure:

```python
# This will raise an error
orbitals = family.get_pseudos(structure=structure)
```

**Solution**: Ensure your family includes orbitals for all elements you need, or create a new family from a more complete collection.

### Incorrect File Structure

If installing from local paths fails to find files:

```console
Warning: No .orb files found in /path/to/orbitals
```

**Solution**: Ensure your directory contains:
- `.orb` files for orbitals
- `.upf` or `.UPF` files for pseudopotentials
- Files follow naming conventions with element symbols

## See Also

- [Installation Guide](../installation.md) - Setting up aiida-abacus
- [Check Results](check.md) - Verifying calculations
- [ABACUS Documentation](https://abacus.deepmodeling.com/) - ABACUS DFT package docs
- [aiida-pseudo](https://aiida-pseudo.readthedocs.io/) - Standard pseudopotential management
- [APNS Database](https://aissquare.com/datasets/detail?pageType=datasets&name=ABACUS-APNS-PPORBs-v1) - ABACUS pseudopotential and orbital database
