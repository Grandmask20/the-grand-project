"""A screenshot's ground classes, kept for the re-check (finalize.landmarks.ground_of): small, same classes."""

import gc

import cv2
import numpy as np
import pytest

from grand_project.finalize import landmarks as fl


def _reference(hsv: np.ndarray) -> np.ndarray:
    """The classes as worked out in int64 (before they were kept as int8)."""
    H, S, V = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    out = np.full(H.shape, -1, int)
    out[(H >= 78) & (H <= 112) & (S >= 85) & (V >= 50)] = 0
    out[(H >= 10) & (H <= 30) & (S >= 25) & (S <= 140) & (V >= 135)] = 1
    out[(S < 40) & (V >= 95)] = 2
    out[(H >= 30) & (H <= 55) & (S >= 70) & (V >= 95)] = 3
    out[(H >= 33) & (H <= 90) & (S >= 50) & (V >= 30) & (V < 95)] = 4
    return out


@pytest.fixture(autouse=True)
def _empty_cache():
    fl._OCEAN.clear()
    yield
    fl._OCEAN.clear()


def test_ground_classes_are_int8_and_the_same():
    img = np.random.default_rng(5).integers(0, 255, (270, 480, 3), dtype=np.uint8)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    got = fl._ground_classes(hsv)
    assert got.dtype == np.int8
    assert np.array_equal(got, _reference(hsv))


def test_ground_of_is_kept_without_keeping_the_screenshot():
    img = np.random.default_rng(6).integers(0, 255, (270, 480, 3), dtype=np.uint8)
    cls, bad = fl.ground_of(img)
    assert fl.ground_of(img)[0] is cls  # (kept: the same arrays the second time)
    ref = fl._OCEAN[id(img)][0]
    del img
    gc.collect()
    assert ref() is None  # (the screenshot went: the cache doesn't hold it)


class _EmptiedMeanwhile(dict):
    """A cache the idle release (app.idle) empties while the eviction is at it: once it walks the cache (iter() then
    next(): the dict changes size during iteration) or once it has the keys (before it lets them go)."""

    def __iter__(self):
        it = super().__iter__()
        self.clear()
        return it

    def pop(self, *a):
        self.clear()
        return super().pop(*a)


def test_ground_of_eviction_tolerates_an_emptied_cache(monkeypatch):
    monkeypatch.setattr(fl, "_OCEAN_KEEP", 0)  # (every add evicts)
    monkeypatch.setattr(fl, "_OCEAN", _EmptiedMeanwhile())
    img = np.random.default_rng(7).integers(0, 255, (270, 480, 3), dtype=np.uint8)
    cls, bad = fl.ground_of(img)  # (no StopIteration: the add goes on)
    assert cls.shape == bad.shape == img.shape[:2]
