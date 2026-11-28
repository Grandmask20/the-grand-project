"""detect.cache._per_image: a screenshot's results remembered once, also when the detection's helper threads
(pipeline._prefetch) and the detection itself ask for the same one at once."""

import threading

import numpy as np
import pytest

from grand_project.detect import cache
from grand_project.detect import constants as K


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(cache, "_PER_IMAGE", {})


def test_a_result_asked_for_while_another_thread_works_it_out_is_worked_out_once():
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    @cache._per_image
    def slow(img):
        calls.append(1)
        started.set()
        assert release.wait(10)
        return img * 2

    img = np.arange(6.0)
    got: dict[str, np.ndarray] = {}
    helper = threading.Thread(target=lambda: got.setdefault("helper", slow(img)))
    helper.start()
    assert started.wait(10)
    asker = threading.Thread(target=lambda: got.setdefault("detection", slow(img)))
    asker.start()
    asker.join(0.3)
    assert asker.is_alive()  # waiting for the helper's result, not working it out again
    release.set()
    helper.join(10)
    asker.join(10)
    assert len(calls) == 1
    assert got["helper"] is got["detection"] and not got["detection"].flags.writeable


def test_an_error_reaches_every_caller_waiting_and_is_not_kept():
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    @cache._per_image
    def failing(img):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
            raise ValueError("unreadable")
        return img

    img = np.zeros(3)
    errors: list[Exception] = []

    def ask() -> None:
        try:
            failing(img)
        except ValueError as e:
            errors.append(e)

    first = threading.Thread(target=ask)
    first.start()
    assert started.wait(10)
    second = threading.Thread(target=ask)
    second.start()
    second.join(0.3)
    release.set()
    first.join(10)
    second.join(10)
    assert [str(e) for e in errors] == ["unreadable", "unreadable"]
    assert failing(img) is img and len(calls) == 2  # tried again on the next ask


def test_lists_are_handed_out_as_copies():
    @cache._per_image
    def found(img):
        return [{"x": 1.0, "y": 2.0}]

    img = np.zeros(2)
    a = found(img)
    a[0]["x"] = 99.0  # (a caller adding to or changing what it got)
    a.append({})
    assert found(img) == [{"x": 1.0, "y": 2.0}]


def test_many_threads_asking_for_many_screenshots_get_each_one_s_own(rng, runs):
    calls: dict[int, int] = {}
    lock = threading.Lock()

    @cache._per_image
    def mean(img):
        with lock:
            calls[id(img)] = calls.get(id(img), 0) + 1
        return np.array([img.mean()])

    for _ in range(runs(5)):
        imgs = [np.full(4, float(k)) for k in range(rng.randint(2, 6))]
        askers = rng.randint(2, 8)
        start = threading.Barrier(askers)
        wrong: list[str] = []

        def ask(start=start, imgs=imgs, wrong=wrong) -> None:
            start.wait(5)
            for k in rng.sample(range(len(imgs)), len(imgs)):
                if mean(imgs[k])[0] != k:
                    wrong.append(f"screenshot {k}")

        threads = [threading.Thread(target=ask) for _ in range(askers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert not wrong
        assert all(calls[id(img)] == 1 for img in imgs)  # each worked out once, whoever asked first
        calls.clear()
        cache._PER_IMAGE.clear()


def test_only_the_last_few_results_are_kept():
    @cache._per_image
    def ident(img):
        return img

    imgs = [np.zeros(1) for _ in range(K.DETECT_PER_IMAGE_KEEP + 5)]
    for img in imgs:
        ident(img)
    assert len(cache._PER_IMAGE) == K.DETECT_PER_IMAGE_KEEP
