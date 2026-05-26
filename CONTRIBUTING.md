### Tests

Tests can be run in different ways
```
uv sync --extra testing
uv run pytest
uv run pytest tests/test_parser.py -q
uv run python -m coverage run -m pytest
uv run python -m coverage report
```
You can add arbitrary flags to pytest at the end of the command. For example to run the tests in debug mode use
```
uv run pytest --pdb
```
We use ipdb as debugger backend for autocompletion.

### Static code analysis

To check the formatting and linting run
```
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
```
If you want to automatically fix errors that are fixable run
```
uv run ruff format .
uv run ruff check --fix .
```
If you want to run this command before each commit, please install the pre-commit hook
```
uv sync --extra dev
uv run pre-commit install
```
You can also run the linter and formatter separately
```
uv run ruff format --check .
uv run ruff check .
```

### Building the docs

Please run
```
uv sync --extra docs
uv run sphinx-build -b html docs/source docs/build/html
```

### Build and publishing package

To build and publish a package please use
```
uv build
uv tool run twine upload --repository testpypi dist/*  # test pypi
uv tool run twine upload dist/*  # pypi
```
