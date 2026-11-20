########## PROJECT RECIPES ##########
.PHONY: install install_training install_annotator annotate_dataset lint test test_all coverage evaluate_detector prepare_rf_detr_data train_rf_detr pr_precheck page page_test page_coverage e2e

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

# The training data is the dataset annotator's export (reviewed screenshots, their splits): Export dataset there first.
RF_DETR_OUTPUT_DIR ?= runs/rf-detr-small
RF_DETR_DATASET_DIR ?= $(RF_DETR_OUTPUT_DIR)/dataset
RF_DETR_OPTIONS ?=
RF_DETR_ANNOTATOR_MANIFEST ?= tools/detection_dataset_annotator/detection-dataset/manifest.json

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
	$(PYTHON) -m tools.train_rf_detr --annotator-manifest "$(RF_DETR_ANNOTATOR_MANIFEST)" --output-dir "$(RF_DETR_OUTPUT_DIR)" --dataset-dir "$(RF_DETR_DATASET_DIR)" --dataset-only --overwrite-dataset $(RF_DETR_OPTIONS)

train_rf_detr: prepare_rf_detr_data
	$(PYTHON) -m tools.train_rf_detr --output-dir "$(RF_DETR_OUTPUT_DIR)" --dataset-dir "$(RF_DETR_DATASET_DIR)" --reuse-dataset $(RF_DETR_OPTIONS)

lint:
	$(RUFF) check grand_project tools tests --fix --config pyproject.toml
	$(RUFF) format grand_project tools tests --config pyproject.toml
	$(RUFF) clean

# the tests (pytest; markers in pyproject.toml): offline + test-data ones, not the slow ones
test:
	@echo Running tests on $(PLATFORM) with $(PYTHON)
	$(PYTHON) -m pytest -m "not slow"

# every test, the ~10 minute waiting-islands test too
test_all:
	$(PYTHON) -m pytest -m ""

# the tests under coverage (settings in pyproject.toml): a table here, the report in htmlcov/index.html
coverage:
	$(PYTHON) -m coverage erase
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage combine
	$(PYTHON) -m coverage report
	$(PYTHON) -m coverage html

# the app's page (frontend/, needs Node.js 20+): install, then lint, type check, test and build it into frontend/dist
page:
	cd frontend && npm install --no-audit --no-fund && npm run build

page_test:
	cd frontend && npm run lint && npm run typecheck && npm test

# the page's tests under coverage: a summary here, the report in frontend/coverage/index.html
page_coverage:
	cd frontend && npm run coverage

# the browser tests: the real app on a hand-made atlas, driven through the built page (Playwright; once:
# cd frontend && npx playwright install chromium). Screenshots of each step: frontend/test-results/
# PYTHON is handed to the tests by make (no shell syntax: cmd.exe on Windows has none for it); the app starts in
# this folder, so a relative .venv path works
e2e: export PYTHON := $(PYTHON)
e2e: page
	cd frontend && npm run e2e

# score the detector on the hand-labelled screenshots (needs the full test data; takes ~15 min).
# Put the numbers from before and after a detector change in the pull request.
evaluate_detector:
	$(PYTHON) -m grand_project.detect score

# everything to run before opening a pull request: lint, the tests, then the detector score
pr_precheck: lint test evaluate_detector
