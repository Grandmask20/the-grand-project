"""detect.models"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .constants import DB_PATH


def _skops():
    """skops (and scikit-learn under it), imported when a model is first stored or loaded: imported with this
    module, they held up the app's start by ~3 s before the page could show (user)."""
    import skops.io as sio

    return sio


# ---------------------------------------------------------------- models in the DB
def _db(path: Path | None = None) -> sqlite3.Connection:
    """Open the reference DB for writing, creating the detector_models table if needed.

    Args:
        path: Database file; None uses DB_PATH.

    Returns:
        An open sqlite3 connection.
    """
    c = sqlite3.connect(str(path or DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS detector_models (
                     name TEXT PRIMARY KEY, blob BLOB NOT NULL, info TEXT, created TEXT NOT NULL)""")
    return c


def save_model(name: str, model, info: dict, path: Path | None = None) -> None:
    """Store a trained model in the DB as a skops archive (training mode only).

    Args:
        name: Model name, e.g. "maps", "badges", "towers"; replaces a stored model of that name.
        model: The fitted scikit-learn model.
        info: Extra facts about the training (stored as JSON).
        path: Database file; None uses DB_PATH.
    """
    buf = _skops().dumps(model)
    with _db(path) as c:
        c.execute(
            "INSERT OR REPLACE INTO detector_models VALUES (?, ?, ?, ?)",
            (name, buf, json.dumps(info), datetime.now().isoformat(timespec="seconds")),
        )


# The models are skops archives. Only the classes a trained detector model is made of are trusted; anything
# else is refused before it can be reconstructed.
_MODEL_CLASSES = {
    ("numpy", "dtype"),
    ("numpy", "ndarray"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy.core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"),  # numpy < 2
    ("numpy.random._pcg64", "PCG64"),
    ("numpy.random._pickle", "__bit_generator_ctor"),
    ("numpy.random._pickle", "__generator_ctor"),
    ("numpy.random.bit_generator", "SeedSequence"),
    ("numpy.random.bit_generator", "__pyx_unpickle_SeedSequence"),
    ("sklearn._loss._loss", "CyHalfBinomialLoss"),
    ("sklearn._loss.link", "Interval"),
    ("sklearn._loss.link", "LogitLink"),
    ("sklearn._loss.loss", "HalfBinomialLoss"),
    ("sklearn.ensemble._hist_gradient_boosting.binning", "_BinMapper"),
    ("sklearn.ensemble._hist_gradient_boosting.gradient_boosting", "HistGradientBoostingClassifier"),
    ("sklearn.ensemble._hist_gradient_boosting.predictor", "TreePredictor"),
    ("sklearn.preprocessing._label", "LabelEncoder"),
}


_TRUSTED_MODEL_TYPES = {f"{module}.{name}" for module, name in _MODEL_CLASSES}


class UnsafeModel(Exception):
    """A stored model refers to something that is not part of a trained detector model."""


def safe_model_loads(blob: bytes):
    """Load a detector model without executing arbitrary pickle globals.

    Only the classes in _MODEL_CLASSES are trusted; anything else is refused before it is reconstructed.

    Args:
        blob: skops archive bytes as stored in the detector_models table.

    Returns:
        The loaded model.

    Raises:
        UnsafeModel: The archive is invalid, unsupported, or refers to an untrusted type.
    """
    sio = _skops()
    try:
        untrusted = set(sio.get_untrusted_types(data=blob))
    except Exception as exc:
        raise UnsafeModel("the detector database contains an invalid model archive: refused") from exc
    unexpected = untrusted - _TRUSTED_MODEL_TYPES
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise UnsafeModel(
            f"the detector database contains {names}, which is not part of a detector model: refused "
            "(use the database that came with the program)"
        )
    try:
        return sio.loads(blob, trusted=sorted(_TRUSTED_MODEL_TYPES))
    except Exception as exc:
        raise UnsafeModel("the detector database contains an invalid or unsupported model: refused") from exc


def load_model(name: str, path: Path | None = None):
    """Read a model from the DB (live mode: the DB is opened read-only).

    Args:
        name: Model name, e.g. "maps", "badges", "towers".
        path: Database file; None uses DB_PATH.

    Returns:
        The loaded model, or None when it (or the table) is not in the DB.

    Raises:
        UnsafeModel: The stored archive is not a trusted detector model (see safe_model_loads).
    """
    c = sqlite3.connect(f"file:{Path(path or DB_PATH).as_posix()}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT blob FROM detector_models WHERE name = ?", (name,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        c.close()
    return safe_model_loads(row[0]) if row else None


_models: dict = {}
