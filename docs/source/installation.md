(installation-install)=

# Installation

This guide walks you through installing **aiida-abacus**, configuring AiiDA, and setting up everything you need to run ABACUS calculations.

## Quick start

:::{attention}
**No time to install?**  
Click the Binder badge [![Binder][binder-badge]][binder-link] to launch a **zero-install** JupyterLab.  
In two minutes you’ll have AiiDA + ABACUS fully set-up—complete with ready-to-run notebooks that let you submit calculations, track provenance, and visualize results right in your browser.
:::
---


For a one-stop local environment setup and a quick start with running calculations, please see the [Tutorials](#tutorials-quick-start).


## Requirements

Before you begin, ensure you have:

1. **Python 3.10+**  
2. **AiiDA-core ≥ 2.0** (including a configured profile)  
   ➜ [Follow the AiiDA-core installation guide](https://aiida-core.readthedocs.io/en/latest/intro/get_started.html) if you have not done so.
   ➜ A virtual environment of Python is preferred, like [Conda](https://anaconda.org/anaconda/conda).

3. **ABACUS** executable installed on every computer you plan to use (local or remote).  
   ➜ [Official ABACUS installation docs](https://abacus.deepmodeling.com/en/latest/quick_start/easy_install.html)
	- Please use ABACUS LTSv3.10.0 for stable output format.
	- Either local executable or remote `abacus` is fine.
	- This should be configured by [AiiDA code](https://aiida.readthedocs.io/projects/aiida-core/en/latest/howto/run_codes.html#how-to-create-a-code) and specified when a real calculation task is performed. Follow the guide to get it ready.


---

## Installation


To install the plugin from source, first clone the source from GitHub.
```bash
$ git clone https://github.com/MCresearch/aiida-abacus.git
```
Then install by pip.
<!-- We use `pyproject.toml` to control dependencies.  -->
```bash
$ cd aiida-abacus
$ pip install .
```
If you want to make modifications to the source code, install in editable mode instead:
```bash
$ cd aiida-abacus
$ pip install -e .
```
## Setup
### Setup computer

We provide example configuration files in [examples](https://github.com/MCresearch/aiida-abacus/tree/develop/examples) directory.
You can configure the computer by modifying `localhost-direct-local-setup.yml` or `remote-slurm-ssh-setup.yml` as needed.

```bash
$ cd examples
$ verdi computer setup --config localhost-direct-local-setup.yml
```
Just freely edit the configuration [YAML](https://yaml.org/) file or set up a new computer from scratch by:
```console
$ verdi computer setup
```
Note: If ABACUS is built with [the Intel® oneAPI](https://www.intel.cn/content/www/cn/zh/developer/tools/oneapi/base-toolkit-download.html), please change the  `prepend_text` to set up your oneAPI environment, where you can include `bash` commands that will be executed before running the submission script. Just remove the line in the configuration file if not needed.

If you want to do the calculations on the local/remote machine with AiiDA environment, please change `transport` option to `core.local` or `core.ssh` by modifying the configuration YAML file.

```yaml
transport: core.ssh # or core.local for local machine
```

Consult [AiiDA computer-setup](https://aiida.readthedocs.io/projects/aiida-core/en/latest/howto/run_codes.html#computer-setup) for a complete guide.

After the setup you can check the available computer list by
```console
$ verdi computer list
Report: List of configured computers
Report: Use 'verdi computer show COMPUTERLABEL' to display more detailed information
* mycomputer
```

### Setup code

You can use any code on any machine that can be accessed and run. To parse results from ABACUS we now support any version that has consistent output format with [LTSv3.10.0](https://github.com/deepmodeling/abacus-develop/releases/tag/LTSv3.10.0).

When you have a code ready, set up the code in AiiDA:

```console
$ verdi code create core.code.installed \
    --label abacus-3.10.0 \
    --computer mycomputer \
    --filepath-executable ~/.local/bin/abacus
```

It can be referred later with code label like `abacus-3.10.0@mycomputer`.
You can also check whether the given code is usable by
```console
$ verdi code test abacus-3.10.0@mycomputer
```

---
For More detailed information about setting up computer & code, please refer to [aiida-tutorials](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/basics.html#preliminary-setup).


### Setup pseudopotential family

ABACUS calculations require pseudopotentials (for both `basis_type: pw` and `basis_type: lcao`). For LCAO calculations, numerical atomic orbitals are also required. We provide the `aiida-abacus pseudos` command group for managing these resources.

#### Quick start with aiida-pseudo

For standard DFT pseudopotential families (UPF format only), use `aiida-pseudo`:

```bash
$ aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard
```

You can then load the family in your scripts:
```python
from aiida.orm import load_group
pseudo_family = load_group("PseudoDojo/0.4/PBE/SR/standard/upf")
```

#### Using ABACUS-specific pseudopotentials and orbitals

For ABACUS LCAO calculations (`basis_type: lcao`), you need both pseudopotentials (.upf) and numerical atomic orbitals (.orb). Use the `aiida-abacus pseudos` commands to manage these:

```bash
# List available pseudopotential sets
$ aiida-abacus pseudos list-sets

# Install APNS efficiency/precision set (includes both pseudos and orbitals)
$ aiida-abacus pseudos install-collection apns-efficiency/precision-v1

# Create a calculation-ready family from the collection
$ aiida-abacus pseudos create-family apns-efficiency-v1 my-abacus-family
```

:::{tip}
The `aiida-abacus pseudos` workflow:
1. **Collections** store ALL orbital variants for each element
2. **Families** contain ONE orbital per element (ready for calculations)
3. Use `create-family` to select specific variants from a collection
:::

For detailed usage including local file imports and interactive variant selection, see [How to manage pseudopotentials and orbitals](howto/pseudos.md).

See [aiida-pseudo documentation](https://aiida-pseudo.readthedocs.io/en/latest/index.html) for more pseudopotential families.

## Note

Since [`AiiDA-core`](https://www.aiida.net/) itself is under active development, the installation and configuration may change over time and you should consult the [AiiDA docs](https://aiida.readthedocs.io/projects/aiida-core/en/latest/index.html) for latest details. The guidelines we provide here are for reference only and may be out of date. If so, please [open an issue](https://github.com/MCresearch/aiida-abacus/issue) or [submit a pull request](https://github.com/MCresearch/aiida-abacus/pulls) on our GitHub Repo to update.


[binder-badge]: https://mybinder.org/badge_logo.svg
[binder-link]: https://mybinder.org/v2/gh/MCresearch/aiida-abacus/HEAD?urlpath=%2Fdoc%2Ftree%2Fexamples%2Fbinder-example.ipynb