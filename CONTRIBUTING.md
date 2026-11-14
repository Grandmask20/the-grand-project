# Contributing

Thanks for helping with The Grand Project. Bug reports, detector improvements, code clean-ups and fixes for other
operating systems are all welcome.

## Where changes go

- **`develop`** is where work happens. Open your pull request against `develop`, never `main`.
- **`main`** is the player release. It is protected and only updated from `develop` with `make_release.py` (which
  strips debug options and test files) through a pull request.
- Keep a pull request to one topic, and say in it what you checked (tests run, scores before / after).

## Getting set up

```bash
git clone https://github.com/Grandmask20/the-grand-project.git
cd the-grand-project
pip install -e ".[dev]"
```

The trimmed test data (screenshots and hand-made truth, ~500 MB) is in Git LFS and not downloaded by default:

```bash
git lfs install
git lfs pull --include="atlas_test_data/**"
```

## Before you open a pull request

1. `make lint` (or `ruff check grand_project tools tests` and `ruff format grand_project tools tests`). CI fails on
   lint or formatting errors.
2. `make test`, or at least the tests that touch what you changed (`python -m tests.test_x`). CI runs the offline
   tests on Windows, macOS and Linux.
3. If you changed the detector, compare `python -m grand_project.detect score` before and after and put both in the
   pull request.

## Code conventions

[AGENTS.md](AGENTS.md) lists the conventions (it is written for AI coding agents, but applies to everyone):
tunable numbers go in the package's `constants.py`, everything runs with `python -m`, nothing Windows-only, the
viewer never blocks its window, and no pickled models from outside.

## Reporting bugs

Use the issue templates. Screenshots help a lot (1080p or larger, full game window), and so does the log:
`user_data/atlas_debug.log`. Please don't post screenshots or logs that show anything you'd rather keep private.

By contributing you agree that your contributions are released under the project's [MIT License](LICENSE), and
that you follow the [code of conduct](CODE_OF_CONDUCT.md).
