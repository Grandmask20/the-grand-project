<!-- Pull requests go to `develop`, not `main` (see CONTRIBUTING.md). -->

## What this changes

## How it was checked

- [ ] `make lint` (ruff check + format) is clean
- [ ] tests that touch this change pass (`make test`, or `pytest tests/test_x.py`)
- [ ] detector changes: `python -m grand_project.detect score` before / after pasted below
- [ ] new tunable numbers are in the package's `constants.py` (see AGENTS.md)
