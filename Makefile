########## PROJECT RECIPES ##########
.PHONY: install lint test evaluate_detector pr_precheck

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

TESTS := \
	tests.test_atlas_builder \
	tests.test_atlas_io \
	tests.test_model_safety \
	tests.test_atlas_folder \
	tests.test_random_sequence \
	tests.test_drop_placement \
	tests.test_false_merge \
	tests.test_detect_pairs \
	tests.test_atlas_viewer

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(RUFF) check grand_project tools tests --fix --config pyproject.toml
	$(RUFF) format grand_project tools tests --config pyproject.toml
	$(RUFF) clean

test:
	@echo Running tests on $(PLATFORM) with $(PYTHON)
	$(foreach test,$(TESTS),$(PYTHON) -m $(test) && )$(PYTHON) -c "pass"

# score the detector on the hand-labelled screenshots (needs the full test data; takes ~15 min).
# Put the numbers from before and after a detector change in the pull request.
evaluate_detector:
	$(PYTHON) -m grand_project.detect score

# everything to run before opening a pull request: lint, the tests, then the detector score
pr_precheck: lint test evaluate_detector
