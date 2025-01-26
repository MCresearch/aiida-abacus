[![Build Status][ci-badge]][ci-link]
[![Coverage Status][cov-badge]][cov-link]
[![Docs status][docs-badge]][docs-link]
[![PyPI version][pypi-badge]][pypi-link]

# aiida-abacus



This is the [AiiDA](https://www.aiida.net/) plugin for [ABACUS](https://abacus.ustc.edu.cn/main.htm).

## Installation

<!-- Install using pip:

```shell
pip install aiida-abacus
``` -->

Install from source:
```bash
git clone https://github.com/MCresearch/aiida-abacus.git
cd aiida-abacus
pip install .
# or pip install -e .
# if you want to make a change to the plugin
```
<!-- ```
git clone https://github.com/MCresearch/aiida-abacus.git
pip install aiida-abacus
``` -->

## Documentation

- Quick start

See the `examples` directory to learn about how to run this plugin with scripts.

- Get started with [AiiDA](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/index.html).

- Documentation for [ABACUS](https://abacus.deepmodeling.com/en/latest/index.html).



## Development

```shell
git clone https://github.com/MCresearch/aiida-abacus .
cd aiida-abacus
pip install --upgrade pip
pip install -e .[pre-commit,testing]  # install extra dependencies
pre-commit install  # install pre-commit hooks
pytest -v  # discover and run all tests
```

Developer guide is still under construction.

### Repository contents

- `src/aiida_abacus`: Main source code of `aiida-abacus` plugin
    - `calculations.py`: The `AbacusCalculation` calcjob class.
    - `parsers.py`: The `abacus.abacus` default parser for `AbacusCalculation`.
- `examples/`: Example of how to submit a calculation using this plugin via a script.
<!-- See [Features](#features) for details. -->
- `tests/`: Basic tests supported by [pytest](https://docs.pytest.org/en/latest/). Install by `pip install -e .[testing]` and run `pytest`.

<!-- See the [developer guide](http://aiida-abacus.readthedocs.io/en/latest/developer_guide/index.html) for more information. -->

<!-- ## Features -->

## Usage

Here goes a quick demo of how to submit a calculation using this plugin:
```shell
verdi daemon start     # make sure the daemon is running
cd examples
./launch.py        # run example calculation
verdi process list -a  # check record of calculation
```

<!-- The plugin also includes verdi commands to inspect its data types:
```shell
verdi data abacus list
verdi data abacus export <PK>
``` -->

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
