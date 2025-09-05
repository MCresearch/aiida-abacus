[![Build Status][ci-badge]][ci-link]
[![Coverage Status][cov-badge]][cov-link]
[![Docs status][docs-badge]][docs-link]
[![PyPI version][pypi-badge]][pypi-link]
[![Binder][binder-badge]][binder-link]

# aiida-abacus

This is the [AiiDA](https://www.aiida.net/) plugin for the ab-initio software package [ABACUS](https://abacus.ustc.edu.cn/main.htm).

## Quick start

Try this plugin with a live JupyterLab server with Binder!

Click the Binder badge [![Binder][binder-badge]][binder-link] to launch a **zero-install** JupyterLab.  
In two minutes you’ll have AiiDA + ABACUS fully set-up—complete with ready-to-run notebooks that let you submit calculations, track provenance, and visualize results right in your browser.

See [Tutorials](https://aiida-abacus.readthedocs.io/en/latest/tutorials/index.html) for installation locally.

## Installation

<!-- Install using pip:

```shell
pip install aiida-abacus
``` -->

Install from source:
### install using `pip`
```bash
git clone https://github.com/MCresearch/aiida-abacus.git
cd aiida-abacus
pip install .
# or pip install -e .
# if you want to make a change to the plugin
```
### install using `uv`
```bash
uv sync
```

We recommend using `aiida-abacus` with [ABACUS LTS (`v3.10.0`)](https://github.com/deepmodeling/abacus-develop/releases/tag/LTSv3.10.0).
This is a Long-Term Supported stable release. The LTS version will only receive essential bug fixes and performance optimization PRs, without introducing code modifications that might affect computational accuracy and precision, nor changes to input parameter names & output formats.
Note that output format changes introduced by the rapidly iterating `develop` branch (for example, `v3.9.0.3` and later `v3.9.0.x` released after `v3.10.0`) are currently not supported by the `aiida-abacus` parser. It is preferable to use ABACUS LTSv3.10.0 rather than `develop` release to produce data and work with `aiida-abacus`.



### Pseudopotentials
We use the [`aiida-pseudo` plugin](https://pypi.org/project/aiida-pseudo/) to install and manage pseudopotentials.
It is easy to install pseudopotentials by `aiida-pseudo` CLI:
```bash
aiida-pseudo install pseudo-dojo -f upf -v 0.4 -x PBE -r SR -p standard 
```
and load the pseudopotential family installed by calling
`load_group` in the launch script.
```py
pseudo_family = load_group('PseudoDojo/0.4/PBE/SR/standard/upf')
```

At least one pseudo potential family should be installed. For more information on pseudo family, please refer to [AiiDA pseudo plugin Documentation](https://aiida-pseudo.readthedocs.io/en/latest/).

## Documentation

See [our online docs](https://aiida-abacus.readthedocs.io/).

- Quick start

We ofter a [quick start tutorial](https://aiida-abacus.readthedocs.io/en/latest/tutorials/index.html) that provides two ways to get started: try Aiida-ABACUS instantly with our live JupyterLab environment powered by Binder, or follow the step-by-step guide to quickly set up a local installation and begin using the plugin.

See the `examples` directory to learn about how to run this plugin with scripts.

- Get started with [AiiDA](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/index.html). It is strongly recommended that the AiiDA setup and basics tutorials should be read and followed to ensure that the environment is set up correctly, while acquiring the relevant basic knowledge and basic concepts in AiiDA & getting to learn about using `verdi` CLI/APIs.

- Documentation for [ABACUS](https://abacus.deepmodeling.com/en/latest/index.html).


## Usage

Here goes a quick demo of how to submit a calculation using this plugin:
```shell
verdi daemon start      # make sure the daemon is running
cd examples
verdi run example_pw_Si2.py     # run example calculation
verdi process list -a   # check record of calculation
```
* Running calculations on a cluster is essentially the same, except that you need to configure the remote computer.
- We provide simple setup demo config files `remote-slurm-ssh-setup.yml` and `localhost-direct-local-setup.yml` in the `examples` dir. You can follow the guide in [How to set up a computer](https://aiida.readthedocs.io/projects/aiida-core/en/latest/howto/run_codes.html#how-to-set-up-a-computer) to configure a computational resource. Please configure `prepend_text` according to your remote environment if [Intel® oneAPI Toolkit](https://www.intel.com/content/www/us/en/developer/tools/oneapi/toolkits.html) is used to build ABACUS.

- You can also run the interactive Jupyter notebook `binder-example.ipynb` in the `examples` directory locally for a glimpse into `aiida-abacus`.

The plugin also includes verdi commands to inspect its data types:
```shell
verdi data abacus list
verdi data abacus export <PK>
```

## Development

```shell
git clone https://github.com/MCresearch/aiida-abacus .
cd aiida-abacus
pip install --upgrade pip
pip install -e .[pre-commit,testing]  # install extra dependencies
pre-commit install  # install pre-commit hooks
pytest -v  # discover and run all tests
```

### Repository contents

- `src/aiida_abacus`: Main source code of `aiida-abacus` plugin
    - `calculations.py`: The `AbacusCalculation` calcjob class.
    - `parsers.py`: The `abacus.abacus` default parser for `AbacusCalculation`.
- `examples/`: Example of how to submit a calculation using this plugin via a script.
<!-- See [Features](#features) for details. -->
- `tests/`: Basic tests supported by [pytest](https://docs.pytest.org/en/latest/). Install by `pip install -e .[testing]` and run `pytest`.

<!-- See the [developer guide](http://aiida-abacus.readthedocs.io/en/latest/developer_guide/index.html) for more information. -->

<!-- ## Features -->


## License

MIT


[ci-badge]: https://github.com/MCresearch/aiida-abacus/workflows/ci/badge.svg?branch=master
[ci-link]: https://github.com/MCresearch/aiida-abacus/actions
[cov-badge]: https://coveralls.io/repos/github/MCresearch/aiida-abacus/badge.svg?branch=master
[cov-link]: https://coveralls.io/github/MCresearch/aiida-abacus?branch=master
[docs-badge]: https://readthedocs.org/projects/aiida-abacus/badge
[docs-link]: http://aiida-abacus.readthedocs.io/
[pypi-badge]: https://badge.fury.io/py/aiida-abacus.svg
[pypi-link]: https://badge.fury.io/py/aiida-abacus
[binder-badge]: https://mybinder.org/badge_logo.svg
[binder-link]: https://mybinder.org/v2/gh/MCresearch/aiida-abacus/HEAD?urlpath=%2Fdoc%2Ftree%2Fexamples%2Fbinder-example.ipynb
