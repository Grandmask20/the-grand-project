"""Shared pytest setup for the tests: options, markers and fixtures used by several test modules.

    pytest                                   offline tests + those with test data (skipped without it)
    pytest -m slow                           the long ones (waiting islands, ~10 min)
    pytest -m ""                             everything
    pytest tests/test_drop_placement.py --runs 20 --seed 123      randomised tests: more runs / a fixed seed
    pytest tests/detection_dataset_annotator one group: the dataset annotator (tests/rf_detr: the RF-DETR detector)

Related tests are grouped in subpackages (``tests/detection_dataset_annotator``, ``tests/rf_detr``); a subpackage's
own ``conftest.py`` holds the setup only its tests share, and every fixture here applies to them too.

Markers (declared in pyproject.toml): `data` tests are skipped when the test screenshots are not there (Git LFS:
git lfs pull --include="atlas_test_data/**", or set ATLAS_TEST_DATA).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from grand_project import paths as rc_paths
from grand_project.detect.constants import RF_DETR_USE_ENV


def pytest_addoption(parser):
    """Command-line options of the randomised tests.

    Args:
        parser: pytest's option parser.
    """
    g = parser.getgroup("grand project")
    g.addoption("--runs", type=int, default=None, help="randomised tests: how many runs (each test has a default)")
    g.addoption("--seed", type=int, default=None, help="randomised tests: the seed (default: a new one, printed)")
    g.addoption("--cached", action="store_true", help="test_waiting_islands: reuse the saved detections (quick)")
    g.addoption(
        "--rf-detr",
        action="store_true",
        help="use the optional fine-tuned RF-DETR backend (set GRAND_PROJECT_RF_DETR_MODEL if needed)",
    )


def pytest_configure(config):
    """Enable the optional detector before tests import or call the live pipeline."""
    if config.getoption("--rf-detr"):
        os.environ[RF_DETR_USE_ENV] = "1"
        from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries

        prefer_pip_cuda_libraries()  # restarts pytest once with PyTorch's own cuDNN first (Linux; rf_detr_cuda)


def pytest_collection_modifyitems(config, items):
    """Skip the `data` tests, with the reason, when the test screenshots are missing.

    Args:
        config: pytest config.
        items: the collected tests.
    """
    why = rc_paths.test_data_problem()
    if why:
        skip = pytest.mark.skip(reason=why)
        for item in items:
            if "data" in item.keywords:
                item.add_marker(skip)


# ------------------------------------------------------------------ fixtures
ANNOTATOR_DIR = rc_paths.ROOT / "tools" / "detection_dataset_annotator"
"""The dataset annotator's folder: its review stores (``detection-dataset*/``, local data) and split ledger (git)."""


def _annotator_files() -> dict[Path, str]:
    """The reviewer's own annotator files by SHA-256: every review store below ``ANNOTATOR_DIR`` (its database,
    its write-ahead log, its backups) and the split ledger. The ``-shm`` index is left out: any reader rewrites it."""
    files = [path for path in ANNOTATOR_DIR.glob("detection-dataset*/*.sqlite3*") if not path.name.endswith("-shm")]
    files.append(ANNOTATOR_DIR / "splits.csv")
    out = {}
    for path in files:
        if path.is_file():
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            out[path] = digest.hexdigest()
    return out


@pytest.fixture(scope="session", autouse=True)
def annotator_files_unchanged():
    """Fail the run when any test changed, made or removed a real review store or the split ledger: hand reviews
    cannot be made again (``annotator_output_dir`` keeps every test in its own folder; this catches a leak)."""
    before = _annotator_files()
    yield
    after = _annotator_files()
    changed = sorted(str(path.relative_to(rc_paths.ROOT)) for path in before.keys() | after.keys()
                     if before.get(path) != after.get(path))  # fmt: skip
    if changed:
        pytest.fail(
            "the tests changed the annotator's own files (or the annotator page wrote them meanwhile: stop it while "
            f"testing): {', '.join(changed)}",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def annotator_output_dir(tmp_path, monkeypatch) -> Path:
    """Every test's own annotator output folder and split ledger (both read live from the annotator's constants):
    a command or the page run without ``--output-dir`` never opens the reviewer's review store."""
    from tools.detection_dataset_annotator import constants as annotator

    out = tmp_path / "annotator-out"
    monkeypatch.setattr(annotator, "ANNOTATOR_DEFAULT_OUTPUT_DIR", str(out))
    monkeypatch.setattr(annotator, "ANNOTATOR_SPLIT_LEDGER", tmp_path / "ledger" / "splits.csv")
    return out


@pytest.fixture(autouse=True)
def app_settings(tmp_path, monkeypatch) -> Path:
    """Every test keeps the app's settings in its own folder: the player's own settings are never touched."""
    from grand_project.app import settings

    f = tmp_path / "app_settings.json"
    monkeypatch.setattr(settings, "SETTINGS", f)
    return f


@pytest.fixture(scope="session")
def test_data() -> Path:
    """The test data folder (paths.TEST_DATA: local_paths.json, ATLAS_TEST_DATA or ./atlas_test_data)."""
    return rc_paths.TEST_DATA


@pytest.fixture(scope="session")
def crawl(test_data):
    """The finished crawl atlas and its screenshots, the ground truth of the placement tests.

    Returns:
        SimpleNamespace with ``atlas_path``, ``atlas`` (core.Atlas, loaded once per session), ``frames`` (the
        atlas file's frame records), ``pos`` ({screenshot name: (x, y) atlas position}), ``shots`` (crawl
        screenshot paths that are in the atlas, in name = time order) and ``cache`` (its saved detections).
    """
    from grand_project import core

    atlas_path = test_data / "crawl_atlas" / "atlas.json"
    atlas = core.Atlas.load(atlas_path)
    pos = {f["name"]: np.array(f["M"], float)[:, 2] for f in atlas.frames}
    folder = test_data / "screenshots" / "crawl"
    shots = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".png" and p.stem in pos)
    return SimpleNamespace(
        atlas_path=atlas_path,
        atlas=atlas,
        frames=json.loads(atlas_path.read_text(encoding="utf-8"))["frames"],
        pos=pos,
        shots=shots,
        folder=folder,
        cache=atlas_path.with_name(atlas_path.stem + "_frames"),
    )


def detection_cache_name(image: Path) -> str:
    """The file name of a screenshot's saved detection (``<sha256[:16]>_detect1.json``).

    Args:
        image: the screenshot.

    Returns:
        The cache file name.
    """
    return f"{hashlib.sha256(Path(image).read_bytes()).hexdigest()[:16]}_detect1.json"


@pytest.fixture
def copy_cache():
    """Copy screenshots' saved detections into a test atlas's cache folder (no detector run needed).

    Returns:
        A function ``copy(images, src_cache, dst_cache)``.
    """

    def copy(images, src_cache: Path, dst_cache: Path) -> None:
        dst_cache.mkdir(parents=True, exist_ok=True)
        for im in images:
            name = detection_cache_name(im)
            shutil.copy(Path(src_cache) / name, Path(dst_cache) / name)

    return copy


@pytest.fixture
def seed(request) -> int:
    """The seed of a randomised test: --seed, else a new random one. Printed, so a failure can be repeated."""
    s = request.config.getoption("--seed")
    s = random.randrange(10**6) if s is None else s
    print(f"seed {s}  (repeat with --seed {s})")
    return s


@pytest.fixture
def rng(seed) -> random.Random:
    """A random generator seeded with `seed`."""
    return random.Random(seed)


@pytest.fixture
def runs(request):
    """--runs, or None for the test's own default.

    Returns:
        A function ``runs(default)`` giving --runs when set, else ``default``.
    """
    return lambda default: request.config.getoption("--runs") or default


class Checks:
    """Soft checks for scenario tests: every check is printed and the test fails at the end if any failed, so one
    run reports everything that is wrong instead of stopping at the first."""

    def __init__(self):
        self.failed: list[str] = []

    def __call__(self, name: str, ok, extra="") -> bool:
        """Record one check.

        Args:
            name: what is checked, in plain words.
            ok: whether it holds (any truthy value).
            extra: details shown next to it (numbers, the seed).

        Returns:
            bool(ok).
        """
        ok = bool(ok)
        print(("ok   " if ok else "FAIL ") + name + (f"  ({extra})" if extra != "" else ""))
        if not ok:
            self.failed.append(name + (f" ({extra})" if extra != "" else ""))
        return ok


@pytest.fixture
def check():
    """A `Checks` collector; the test fails after it ran when any check failed (see pytest_runtest_call)."""
    return Checks()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """Fail a test that used `check` when any of its checks failed: a failure of the test, not of a fixture.

    Args:
        item: the test being run.
    """
    result = yield
    c = item.funcargs.get("check")
    if isinstance(c, Checks) and c.failed:
        pytest.fail("failed checks:\n  " + "\n  ".join(c.failed), pytrace=False)
    return result
