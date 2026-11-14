"""detect.models (from atlas_detect.py)"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import skops.io as sio

from .constants import DB_PATH


# ---------------------------------------------------------------- models in the DB
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS detector_models (
                     name TEXT PRIMARY KEY, blob BLOB NOT NULL, info TEXT, created TEXT NOT NULL)""")
    return c


def save_model(name: str, model, info: dict) -> None:
    """training mode only"""
    buf = sio.dumps(model)
    with _db() as c:
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
    """a stored model refers to something that is not part of a trained detector model"""


def safe_model_loads(blob: bytes):
    """Load a detector model without executing arbitrary pickle globals."""
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


def load_model(name: str):
    """live mode: read-only"""
    c = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        row = c.execute("SELECT blob FROM detector_models WHERE name = ?", (name,)).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        c.close()
    return safe_model_loads(row[0]) if row else None


_models: dict = {}
