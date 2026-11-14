########## PROJECT RECIPES ##########
.PHONY: install lint test

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
	tests/test_atlas_builder.py \
	tests/test_atlas_io.py \
	tests/test_model_safety.py \
	tests/test_atlas_folder.py \
	tests/test_random_sequence.py \
	tests/test_drop_placement.py \
	tests/test_false_merge.py \
	tests/test_detect_pairs.py \
	tests/test_atlas_viewer.py

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(RUFF) check program tools tests --fix --config pyproject.toml
	$(RUFF) format program tools tests --config pyproject.toml
	$(RUFF) clean

test:
	@echo Running tests on $(PLATFORM) with $(PYTHON)
	$(foreach test,$(TESTS),$(PYTHON) $(test) && )$(PYTHON) -c "pass"
