########## PROJECT RECIPES ##########
.PHONY: install install_training install_annotator annotate_dataset lint test test_all evaluate_detector prepare_rf_detr_data train_rf_detr pr_precheck

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

# RF_DETR_DATA_ROOT can point at a full/private truth set; when empty, the tool uses the normal test-data lookup.
RF_DETR_OUTPUT_DIR ?= runs/rf-detr-small
RF_DETR_DATASET_DIR ?= $(RF_DETR_OUTPUT_DIR)/dataset
RF_DETR_DATA_ROOT ?=
RF_DETR_OPTIONS ?=
RF_DETR_ANNOTATOR_MANIFEST ?=
RF_DETR_DATA_ARGS = $(if $(strip $(RF_DETR_DATA_ROOT)),--data-root "$(RF_DETR_DATA_ROOT)",)
RF_DETR_ANNOTATOR_ARGS = $(if $(strip $(RF_DETR_ANNOTATOR_MANIFEST)),--annotator-manifest "$(RF_DETR_ANNOTATOR_MANIFEST)",)

install:
	$(PYTHON) -m pip install -e ".[dev]"

install_training:
	$(PYTHON) -m pip install -e ".[training]"

# the Streamlit detection dataset annotator (tools/detection_dataset_annotator)
install_annotator:
	$(PYTHON) -m pip install -e ".[annotator]"

annotate_dataset:
	$(PYTHON) -m tools.detection_dataset_annotator

prepare_rf_detr_data:
	$(PYTHON) -m tools.train_rf_detr $(RF_DETR_DATA_ARGS) $(RF_DETR_ANNOTATOR_ARGS) --output-dir "$(RF_DETR_OUTPUT_DIR)" --dataset-dir "$(RF_DETR_DATASET_DIR)" --dataset-only --overwrite-dataset $(RF_DETR_OPTIONS)

train_rf_detr: prepare_rf_detr_data
	$(PYTHON) -m tools.train_rf_detr $(RF_DETR_DATA_ARGS) $(RF_DETR_ANNOTATOR_ARGS) --output-dir "$(RF_DETR_OUTPUT_DIR)" --dataset-dir "$(RF_DETR_DATASET_DIR)" --reuse-dataset $(RF_DETR_OPTIONS)

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
