"""The detector models use skops: only the classes a trained model is made of may be loaded."""

import os
import pickle

import pytest
import skops.io as sio

from grand_project import detect as ad


@pytest.mark.parametrize("name", ["maps", "badges", "towers", "fortress"])
def test_shipped_model_loads(name):
    """Every model shipped in the detector database loads through the safe loader."""
    assert ad.load_model(name) is not None


class _PickleSystem:
    """An old-style pickle that would run a command when loaded."""

    def __reduce__(self):
        return (os.system, ("echo this must never run",))


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(b"not a skops model", id="invalid archive"),
        pytest.param(pickle.dumps(_PickleSystem()), id="old pickle with os.system"),
        pytest.param(sio.dumps(os.system), id="skops archive with os.system"),
        pytest.param(sio.dumps({"clf": eval, "names": ["x"]}), id="skops archive with eval inside a model dict"),
    ],
)
def test_tampered_model_is_refused(blob):
    """A model archive with anything but the allowed classes is refused, never loaded."""
    with pytest.raises(ad.UnsafeModel):
        ad.safe_model_loads(blob)


def test_a_database_path_with_reserved_uri_characters_is_read(tmp_path):
    """A "#" in the database path once ended the read-only URI early, and a "%" started an escape: the right file
    must be read, read-only, and no file named after the part before the "#" may appear. ("?" would end it too, but
    Windows file names cannot hold one.)"""
    from sklearn.preprocessing import LabelEncoder

    from grand_project.detect import models

    db = tmp_path / "x#y%41.sqlite3"
    models.save_model("enc", LabelEncoder().fit(["a", "b"]), {}, path=db)

    loaded = models.load_model("enc", db)

    assert list(loaded.classes_) == ["a", "b"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["x#y%41.sqlite3"]
