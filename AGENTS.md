# Repository Guidelines

## Project Structure & Module Organization
Core plugin code lives in `src/aiida_abacus/`. Key areas are `calculations.py` for the CalcJob, `parsers/` for ABACUS output parsing, `workflows/` for AiiDA work chains, `protocols/` for YAML protocol presets and builders, and `commands/`, `data/`, `group/`, and `common/` for CLI, data classes, group logic, and shared helpers. Tests live in `tests/`, with command and group coverage under `tests/commands/` and `tests/groups/`. User and developer docs are in `docs/source/`. Example launch scripts and notebooks are in `examples/`.

## Build, Test, and Development Commands
Use the repository-local virtual environment at `.venv/bin/activate` for development.
Activate the project environment first with `source .venv/bin/activate`, or use `uv run` directly.
If another repo's virtualenv is already activated in the shell, run `deactivate` first or unset `VIRTUAL_ENV` and `VIRTUAL_ENV_PROMPT` before using this repo's environment.
Use `uv` for local setup and execution, for example `uv sync --group dev-tools` or `uv sync --group testing`.
Prefer `uv run python -m pytest -v` for the default test suite, especially if shell activation state may be contaminated by a neighboring environment.
Use `uv run python -m coverage run -m pytest` followed by `uv run python -m coverage report` for coverage.
Use `uv run ruff format --check .` and `uv run ruff check .` for formatting and lint checks, or `uv run ruff format .` and `uv run ruff check --fix .` to apply safe fixes.
Build docs with `uv sync --group docs-build` and `uv run sphinx-build -b html docs/source docs/build/html`.
Build distributions with `uv build`.

## Coding Style & Naming Conventions
Target Python 3.10+ and follow the Ruff configuration in `pyproject.toml`: 120-character lines, double quotes, and import sorting through `ruff`. Use 4-space indentation. Keep module names lowercase with underscores. Follow existing patterns such as `AbacusCalculation` for classes, `test_parser.py` for tests, and protocol files like `base.yaml` or `relax.yaml`. Keep new logic near the relevant AiiDA entry point instead of adding broad utility modules.

## Testing Guidelines
Pytest is the test runner. The repository is configured to discover `test_*.py` and `example_*.py`. Add focused unit tests beside the nearest existing suite, for example parser changes in `tests/test_parser.py` or workflow changes in `tests/test_builder_updates.py`. Prefer small fixtures from `tests/test_data/`. Run a targeted test first, then the broader suite before opening a PR.

## Commit & Pull Request Guidelines
Recent history favors short, imperative commit subjects such as `Remove noqa` or `Fix all 10 linter errors identified by ruff`, with occasional scoped conventional prefixes like `fix(calculation): ...`. Keep subjects concise, describe behavior changes in the body when needed, and reference issue or PR numbers when relevant. PRs should explain the user-visible change, note test coverage, and mention documentation updates when protocols, CLI behavior, or examples change.

## Configuration Tips
Do not commit cluster credentials, AiiDA profile secrets, or machine-specific paths. Keep ABACUS executable setup and pseudo family configuration outside the codebase and document any required environment assumptions in the PR.
