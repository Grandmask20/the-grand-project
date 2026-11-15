########## PROJECT RECIPES ##########
.PHONY: install lint test test_all evaluate_detector pr_precheck

# GNU Make exposes OS=Windows_NT on Windows. On Unix-like systems, uname
# distinguishes macOS (Darwin) from Linux; both use the same venv layout.
ifeq ($(OS),Windows_NT)
    PLATFORM := windows
    VENV_BIN := .venv/Scripts
    VENV_PYTHON := .venv/Scripts/python.exe
    PYTHON_DEFAULT := py
else ifeq ($(shell uname -s),Darwin)
    PLATFORM := darwin
    VENV_BIN := .venv/bin
    VENV_PYTHON := .venv/bin/python
    PYTHON_DEFAULT := python3
else
    PLATFORM := linux
    VENV_BIN := .venv/bin
    VENV_PYTHON := .venv/bin/python
    PYTHON_DEFAULT := python3
endif

PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(PYTHON_DEFAULT))
RUFF ?= $(if $(filter windows,$(PLATFORM)),$(VENV_BIN)/ruff.exe,$(VENV_BIN)/ruff)

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(RUFF) check grand_project tools tests --fix --config pyproject.toml
	$(RUFF) format grand_project tools tests --config pyproject.toml
	$(RUFF) clean

# the tests (pytest; markers in pyproject.toml): offline + test-data ones + the viewer window, not the slow ones
test:
	@echo Running tests on $(PLATFORM) with $(PYTHON)
	$(PYTHON) -m pytest -m "not slow"

# every test, the ~10 minute waiting-islands test too
test_all:
	$(PYTHON) -m pytest -m ""

# score the detector on the hand-labelled screenshots (needs the full test data; takes ~15 min).
# Put the numbers from before and after a detector change in the pull request.
evaluate_detector:
	$(PYTHON) -m grand_project.detect score

# everything to run before opening a pull request: lint, the tests, then the detector score
pr_precheck: lint test evaluate_detector
