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
