"""Offline checks for the atlas builder core (no screenshots or detector needed).  pytest tests/test_atlas_builder.py"""

import json
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project import core as C


@pytest.fixture(autouse=True)
def flat_camera(monkeypatch):
    """Synthetic crops of one image are flat: no camera tilt (HORIZON None) for these tests only."""
    monkeypatch.setattr(C.constants, "HORIZON", None)


def make_world(seed=1, w=1500, h=700, n=110):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), (0, 0), 3)
    img = cv2.normalize(img, None, 30, 220, cv2.NORM_MINMAX)
    pts = []
    while len(pts) < n:
        p = rng.uniform([60, 130], [w - 60, h - 130])
        if all(np.hypot(*(p - q)) > 48 for q in pts):
            pts.append(p)
    return img, np.array(pts)


def frame_from(world, pts, x0, x1, name, tmp, jitter=0.6, drop=0.08, ghosts=3, seed=0):
    rng = np.random.default_rng(seed)
    crop = world[:, x0:x1]
    path = str(Path(tmp) / f"{name}.png")
    cv2.imencode(".png", crop)[1].tofile(path)
    inside = [p for p in pts if x0 + 25 < p[0] < x1 - 25]
    keep = [p - [x0, 0] + rng.normal(0, jitter, 2) for p in inside if rng.random() > drop]
    keep += [rng.uniform([40, 130], [x1 - x0 - 40, 570]) for _ in range(ghosts)]
    nodes = [
        {
            "x": int(p[0]),
            "y": int(p[1]),
            "score": 0.9,
            "state": "review",
            "source": "t",
            "hidden": False,
            "unverified": False,
            "tower": False,
            "icon": "",
        }
        for p in keep
    ]
    return C.Frame.from_json(
        {
            "name": name,
            "path": path,
            "sha256": name,
            "width": x1 - x0,
            "height": 700,
            "nodes": nodes,
            "edges": [{"a": 0, "b": 1, "conf": 1.0, "status": "detected"}],
            "landmarks": [{"kind": "Tower", "x": 300, "y": 300, "conf": 0.9, "source": "t"}],
        }
    )


def test_translation_recovered_and_nodes_merged(tmp_path):
    world, pts = make_world()
    a = frame_from(world, pts, 0, 900, "a", tmp_path, seed=1)
    b = frame_from(world, pts, 500, 1500, "b", tmp_path, seed=2)
    at = C.Atlas()
    at.add_frame(a)
    r = at.add_frame(b)
    assert r.ok, r.reason
    assert np.allclose(r.M[:, 2], [500, 0], atol=2) and np.allclose(r.M[:, :2], np.eye(2), atol=0.01)
    both = [n for n in at.nodes if len(set(n["frames"])) == 2]
    assert len(both) >= 20, len(both)  # nodes in the overlap were merged, not duplicated
    assert len(at.landmarks) == 2  # the two towers are 500px apart in atlas space


def test_unrelated_screenshot_is_rejected_and_atlas_untouched(tmp_path):
    w1, p1 = make_world(1)
    w2, p2 = make_world(2)
    at = C.Atlas()
    at.add_frame(frame_from(w1, p1, 0, 900, "a", tmp_path))
    before = json.dumps(at.to_json(), sort_keys=True)
    r = at.add_frame(frame_from(w2, p2, 0, 900, "z", tmp_path, seed=5))
    assert not r.ok
    assert json.dumps(at.to_json(), sort_keys=True) == before


def test_graph_match_with_wrong_terrain_is_rejected(tmp_path):
    """Same node layout but different ground: the pixel check must veto it."""
    w1, p1 = make_world(1)
    w2, _ = make_world(7)
    at = C.Atlas()
    at.add_frame(frame_from(w1, p1, 0, 900, "a", tmp_path))
    r = at.add_frame(frame_from(w2, p1, 500, 1500, "b", tmp_path, seed=3))
    assert not r.ok and "terrain" in r.reason, r.reason


def test_save_load_roundtrip_and_support_counts(tmp_path):
    world, pts = make_world()
    at = C.Atlas()
    at.add_frame(frame_from(world, pts, 0, 900, "a", tmp_path, seed=1))
    at.add_frame(frame_from(world, pts, 500, 1500, "b", tmp_path, seed=2))
    path = tmp_path / "atlas.json"
    at.save(path)
    again = C.Atlas.load(path)
    assert json.dumps(again.to_json(), sort_keys=True) == json.dumps(at.to_json(), sort_keys=True)
    r = again.add_frame(frame_from(world, pts, 250, 1150, "c", tmp_path, seed=4))  # merge after reload
    assert r.ok, r.reason
    assert max(len(set(n["frames"])) for n in again.nodes) == 3


def test_duplicate_screenshot_ignored(tmp_path):
    world, pts = make_world()
    f = frame_from(world, pts, 0, 900, "a", tmp_path)
    at = C.Atlas()
    at.add_frame(f)
    assert not at.add_frame(f).ok and len(at.frames) == 1


# ------------------------------------------------------------------ screenshots detected at once (detect_uncached)


@pytest.fixture
def quick_detector(monkeypatch):
    """detect_uncached on threads (a stand-in for its worker processes) with a stand-in detector: what it hands back,
    not what it finds. Returns the list of screenshot names the detector was run on."""
    from concurrent.futures import ThreadPoolExecutor

    from grand_project import builder
    from grand_project import detect as atlas_detect

    calls: list[str] = []
    monkeypatch.setattr(builder, "DETECT_WORKERS", 4)  # (1 on a 2-CPU runner: nothing would run at once)
    monkeypatch.setattr(builder.atlas_io, "process_pool", lambda n: ThreadPoolExecutor(n))

    def detect(img):
        calls.append(img.shape)
        if img.shape[0] == 13:  # the "bad" screenshot
            raise RuntimeError("the detector crashed")
        return {"nodes": [], "edges": [], "landmarks": [], "icons": []}

    monkeypatch.setattr(atlas_detect, "detect", detect)
    monkeypatch.setattr(atlas_detect, "dash_record", lambda img: {})
    return calls


def shot(folder: Path, name: str, height: int = 20, value: int = 0) -> Path:
    p = folder / name
    cv2.imwrite(str(p), np.full((height, 30, 3), value, np.uint8))
    return p


def test_screenshots_detected_at_once_report_each_failure_and_every_step(tmp_path, quick_detector):
    from grand_project import builder

    shots = [shot(tmp_path, f"{k}.png", value=k) for k in range(3)] + [shot(tmp_path, "bad.png", height=13)]
    steps: list[tuple[int, int]] = []
    errors = builder.detect_uncached(shots, tmp_path / "f", progress=lambda d, t: steps.append((d, t)))
    assert list(errors) == [str(shots[3])] and "the detector crashed" in errors[str(shots[3])]
    assert steps == [(k, 4) for k in range(1, 5)]  # each screenshot once, whichever finished first
    assert len(list((tmp_path / "f").glob("*.json"))) == 3  # (no cache for the failed one)


def test_screenshots_already_detected_are_not_detected_again(tmp_path, quick_detector):
    from grand_project import builder

    shots = [shot(tmp_path, f"{k}.png", value=k) for k in range(3)]
    builder.extract_frame(shots[0], tmp_path / "f")
    quick_detector.clear()
    assert builder.detect_uncached(shots, tmp_path / "f") == {}
    assert len(quick_detector) == 2
    quick_detector.clear()
    assert builder.detect_uncached(shots, tmp_path / "f") == {} and quick_detector == []  # all cached: no pool


def test_no_worker_processes_leaves_the_screenshots_to_be_detected_one_at_a_time(tmp_path, quick_detector, monkeypatch):
    from grand_project import builder

    def no_pool(n):
        raise OSError("can't start a process")

    monkeypatch.setattr(builder.atlas_io, "process_pool", no_pool)
    lines: list[str] = []
    shots = [shot(tmp_path, f"{k}.png", value=k) for k in range(2)]
    assert builder.detect_uncached(shots, tmp_path / "f", log=lines.append) == {}
    assert lines == ["parallel detection failed (can't start a process); detecting one at a time"]
    assert [builder.extract_frame(p, tmp_path / "f").name for p in shots] == ["0", "1"]


def test_one_picture_saved_twice_and_detected_at_once_leaves_one_whole_cache(tmp_path, quick_detector, monkeypatch):
    # two copies of a screenshot (same bytes, so the same cache file) detected by two workers at the same moment
    from grand_project import builder
    from grand_project import detect as atlas_detect

    real = atlas_detect.detect
    together = threading.Barrier(2)

    def detect(img):
        together.wait(5)  # both are between reading the picture and writing its cache
        return real(img)

    monkeypatch.setattr(atlas_detect, "detect", detect)
    first = shot(tmp_path, "copy 1.png", value=7)
    second = tmp_path / "copy 2.png"
    second.write_bytes(first.read_bytes())
    assert builder.detect_uncached([first, second], tmp_path / "f") == {}
    caches = list((tmp_path / "f").glob("*.json"))
    assert len(caches) == 1 and json.loads(caches[0].read_text())["sha256"]
    assert not [p for p in (tmp_path / "f").iterdir() if p.suffix != ".json"]  # (no temporary file left)
    frames = [builder.extract_frame(p, tmp_path / "f") for p in (first, second)]
    assert [Path(f.path).name for f in frames] == ["copy 1.png", "copy 2.png"]  # each its own path
