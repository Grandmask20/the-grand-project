"""The path check's gold dash cache (finalize.traces._gold): kept small, same answers."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from grand_project import gold_paths as gp
from grand_project.finalize import traces


def _screenshot(seed: int) -> np.ndarray:
    """A dark 1080p picture with short gold dashes (HSV hue ~20) scattered over it."""
    rng = np.random.default_rng(seed)
    img = np.full((1080, 1920, 3), 30, np.uint8)
    for x, y in rng.integers(40, [1880, 1040], (300, 2)):
        cv2.line(img, (int(x), int(y)), (int(x) + 4, int(y) + 1), (40, 170, 220), 2)
    return img


def _atlas(images: dict) -> SimpleNamespace:
    reads = []

    def image(path):
        reads.append(path)
        return images.get(path)

    return SimpleNamespace(image=image, reads=reads)


@pytest.fixture(autouse=True)
def _empty_cache():
    traces._GOLD.clear()
    yield
    traces._GOLD.clear()


def test_gold_gives_the_field_it_gave_when_the_field_was_kept():
    img = _screenshot(1)
    atlas = _atlas({"a.png": img})
    gold = gp.gold_stroke_mask(img)
    assert gold.any()
    _, _, _, cen = cv2.connectedComponentsWithStats(gold, 8)
    field = np.minimum(cv2.distanceTransform(255 - gold, cv2.DIST_L2, 3), 255).astype(np.float16)
    for _ in range(2):  # worked out, then from the cache
        got_cen, got_field = traces._gold(atlas, {"path": "a.png"})
        assert np.array_equal(got_cen, cen[1:].astype(float))
        assert got_field.dtype == np.float16 and np.array_equal(got_field, field)
    assert atlas.reads == ["a.png"]  # the picture was read once


def test_gold_keeps_a_packed_mask_not_the_field():
    traces._gold(_atlas({"a.png": _screenshot(2)}), {"path": "a.png"})
    kept = sum(a.nbytes for a in traces._GOLD["a.png"][:2])
    assert kept < 400_000  # (the float16 field was 1920 * 1080 * 2 = 4.1 MB)


def test_gold_keeps_the_most_recently_used(monkeypatch):
    monkeypatch.setattr(traces, "GOLD_CACHE", 2)
    atlas = _atlas({p: _screenshot(i) for i, p in enumerate(["a", "b", "c"])})
    for p in ["a", "b", "a", "c"]:
        traces._gold(atlas, {"path": p})
    assert list(traces._GOLD) == ["a", "c"]  # b, the least recently used, went


def test_gold_of_a_gone_picture_is_none_and_not_kept():
    assert traces._gold(_atlas({}), {"path": "gone.png"}) is None
    assert "gone.png" not in traces._GOLD


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


def test_gold_eviction_tolerates_an_emptied_cache(monkeypatch):
    monkeypatch.setattr(traces, "GOLD_CACHE", 0)  # (every add evicts)
    monkeypatch.setattr(traces, "_GOLD", _EmptiedMeanwhile())
    got = traces._gold(_atlas({"a.png": _screenshot(3)}), {"path": "a.png"})
    assert got is not None  # (no StopIteration: the add goes on)


def test_evict_oldest_keeps_the_most_recent():
    cache = {k: k for k in "abcde"}
    traces._evict_oldest(cache, 2)
    assert list(cache) == ["d", "e"]
    traces._evict_oldest(cache, 5)  # (nothing over: nothing let go)
    assert list(cache) == ["d", "e"]
