(installation-install)=

# Installation

This guide walks you through installing **aiida-abacus**, configuring AiiDA, and setting up everything you need to run ABACUS calculations.

---

## Requirements

Before you begin, ensure you have:

1. **Python 3.10+**  
2. **AiiDA-core ≥ 2.0** (including a configured profile)  
   ➜ [Follow the AiiDA-core installation guide](https://aiida-core.readthedocs.io/en/latest/intro/get_started.html) if you have not done so.

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

ABACUS calculation requires pseudo potentials, and we use the `aiida-pseudo` package to provide a simple way to manage and use pseudo potentials. It is a dependency of `aiida-abacus` and should be installed when you install `aiida-abacus` with `pip`, or it can be installed with:

```bash
$ pip install aiida-pseudo
```

After that, a pseudo potential _family_ can be installed by:
```bash
$ aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard
```

You may want to use the pseudo potential family later in the script and the corresponding pseudo family can be loaded once installed.
```python
pseudo_family = load_group("PseudoDojo/0.4/PBE/SR/standard/upf")
```

See [aiida-pseudo](https://aiida-pseudo.readthedocs.io/en/latest/index.html) for a complete list of 

## Note

Since [`AiiDA-core`](https://www.aiida.net/) itself is under active development, the installation and configuration may change over time and you should consult the [AiiDA docs](https://aiida.readthedocs.io/projects/aiida-core/en/latest/index.html) for latest details. The guidelines we provide here are for reference only and may be out of date. If so, please [open an issue](https://github.com/MCresearch/aiida-abacus/issue) or [submit a pull request](https://github.com/MCresearch/aiida-abacus/pulls) on our GitHub Repo to update.