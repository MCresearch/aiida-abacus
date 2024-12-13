[![Build Status][ci-badge]][ci-link]
[![Coverage Status][cov-badge]][cov-link]
[![Docs status][docs-badge]][docs-link]
[![PyPI version][pypi-badge]][pypi-link]

# aiida-abacus



This is the [AiiDA](https://www.aiida.net/) plugin for [ABACUS](https://abacus.ustc.edu.cn/main.htm).

## Installation

Install using pip:

```shell
pip install aiida-abacus
```

<!-- Install from source:
```
git clone https://github.com/MCresearch/aiida-abacus.git
pip install aiida-abacus
``` -->

## Documentation

- Quick start

- Get started with [AiiDA](https://aiida-tutorials.readthedocs.io/en/latest/sections/getting_started/index.html).

- Documentation for [ABACUS](https://abacus.deepmodeling.com/en/latest/index.html).

<!-- ## Usage -->

<!-- Here goes a complete example of how to submit a test calculation using this plugin.

A quick demo of how to submit a calculation:
```shell
verdi daemon start     # make sure the daemon is running
cd examples
./example_01.py        # run test calculation
verdi process list -a  # check record of calculation
```

The plugin also includes verdi commands to inspect its data types:
```shell
verdi data abacus list
verdi data abacus export <PK>
``` -->

<!-- ## Development

```shell
git clone https://github.com/MCresearch/aiida-abacus .
cd aiida-abacus
pip install --upgrade pip
pip install -e .[pre-commit,testing]  # install extra dependencies
pre-commit install  # install pre-commit hooks
pytest -v  # discover and run all tests
```

See the [developer guide](http://aiida-abacus.readthedocs.io/en/latest/developer_guide/index.html) for more information. -->

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
