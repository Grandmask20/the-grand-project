"""The annotator's extra icon and hidden map-node proposals (tools/detection_dataset_annotator/icon_proposals.py)."""

from pathlib import Path

import numpy as np
import pytest

from grand_project.detect import badges
from tools.detection_dataset_annotator import (
    DetectionOptions,
    detection_annotations,
    icon_proposals,
    run_classical_detector,
)

RES_1080 = Path("res_atlases") / "res_1080_100"


def _fake_matches(monkeypatch: pytest.MonkeyPatch, matches: dict[tuple[int, int], tuple[str, float]]) -> None:
    """Make every point of ``matches`` a rim candidate named with the given (name, distance)."""
    points = np.array(list(matches))
    monkeypatch.setattr(
        badges, "badge_candidates", lambda image: (points, np.ones(len(points)), np.ones((len(points), 1)))
    )
    monkeypatch.setattr(icon_proposals, "picture_book", lambda book: (["x"], np.zeros((1, 1), np.float32)))
    monkeypatch.setattr(
        icon_proposals,
        "name_icons",
        lambda image, pts, names, features: [matches[tuple(int(v) for v in p)] for p in pts],
    )


def test_batched_naming_matches_name_badge(seed: int, runs) -> None:
    """name_icons gives the same name and distance as the detector's own name_badge, also at the screen edge."""
    rng = np.random.default_rng(seed)
    points = np.array([[170, 120], [60, 60], [250, 180], [10, 10], [315, 120], [20, 20], [299, 219]])
    names, features = icon_proposals.picture_book({"names": [], "F": np.zeros((0, 0), np.float32)})
    for _ in range(runs(1)):
        image = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
        image[100:140, 150:190] = rng.integers(120, 256, (40, 40, 3), dtype=np.uint8)
        fast = icon_proposals.name_icons(image, points, names, features)
        slow = [badges.name_badge(image, float(x), float(y), names, features) for x, y in points]
        for (fast_name, fast_dist), (slow_name, slow_dist) in zip(fast, slow, strict=True):
            assert fast_name == slow_name
            assert fast_dist == pytest.approx(slow_dist, abs=1e-4)


def test_proposal_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sure matches need only the icon-row position; weak ones must be centred or a row neighbour (chains too)."""
    # Map nodes at (200, 200) and (400, 200); the classical finder already found the icon at (400, 168).
    detection = {"nodes": [{"x": 200, "y": 200}, {"x": 400, "y": 200}], "icons": [{"x": 400, "y": 168}]}
    _fake_matches(
        monkeypatch,
        {
            (300, 170): ("MapBoss", 0.02),  # sure, off-centre: kept
            (200, 168): ("Abyss", 0.09),  # weak, centred over (200, 200): kept
            (240, 168): ("Essence", 0.08),  # weak, row neighbour of the Abyss icon: kept
            (440, 168): ("Delirium", 0.10),  # weak, row neighbour of the classical icon: kept
            (330, 168): ("Corruption", 0.09),  # weak, neither centred nor in a row: dropped
            (404, 170): ("MapBoss", 0.01),  # the classical icon again: dropped
            (360, 168): ("ForestInfluence", 0.01),  # biome influences on a weak circle are terrain: dropped
            (200, 200): ("MapBoss", 0.00),  # the map node's own disc: dropped
            (100, 100): ("MapBoss", 0.00),  # not above any map node: dropped
            (160, 168): ("MapBoss", 0.30),  # too far from every picture: dropped
        },
    )
    found = icon_proposals.propose_icons(np.zeros((400, 600, 3), np.uint8), detection, {})
    assert sorted((icon["name"], icon["x"], icon["y"], icon["proposal"]) for icon in found) == [
        ("Abyss", 200.0, 168.0, True),
        ("Delirium", 440.0, 168.0, True),
        ("Essence", 240.0, 168.0, True),
        ("MapBoss", 300.0, 170.0, True),
    ]


def test_faint_map_nodes_support_closer_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Over a fogged map node the finder missed, a weak match counts only when it is close (pairs: their middle)."""
    spots = np.array([[300.0, 200.0], [500.0, 200.0], [700.0, 200.0]])  # faint map nodes, none found
    _fake_matches(
        monkeypatch,
        {
            (300, 168): ("Abyss", 0.09),  # centred over a faint map node, close enough: kept
            (480, 168): ("PlayerOrBookmark", 0.074),  # a pair whose middle stands on a faint map node: both kept
            (520, 168): ("Abyss", 0.093),
            (700, 168): ("AncientTrove", 0.10),  # over a faint map node but not close enough: dropped
        },
    )
    found = icon_proposals.propose_icons(np.zeros((400, 900, 3), np.uint8), {"nodes": [], "icons": []}, {}, spots)
    assert sorted((icon["name"], icon["x"]) for icon in found) == [
        ("Abyss", 300.0),
        ("Abyss", 520.0),
        ("PlayerOrBookmark", 480.0),
    ]


def test_hidden_map_nodes_under_icon_rows() -> None:
    """Every icon row without a map node gets one, at the screenshot's measured icon-to-map-node offset."""
    nodes = [{"x": 200, "y": 432}, {"x": 1000, "y": 332}, {"x": 1400, "y": 632}, {"x": 1230, "y": 430}]
    icons = [
        {"x": 200, "y": 400}, {"x": 1000, "y": 300}, {"x": 1400, "y": 600},  # on found map nodes: offset 32 px
        {"x": 600, "y": 400},  # alone: a map node at (600, 432)
        {"x": 800, "y": 500}, {"x": 840, "y": 500},  # a pair: under its middle, snapped to the faint glow
        {"x": 1200, "y": 400},  # a visible map node within HIDDEN_SNAP is the row's map node: none
        {"x": 1600, "y": 300, "source": "square button"},  # a ship button stands on water: none
        {"x": 500, "y": 700}, {"x": 500, "y": 732},  # a marker pinned above an icon: only the icon's map node
        {"x": 100, "y": 1000},  # its map node would be on the HUD: none
    ]  # fmt: skip
    spots = np.array([[823.0, 535.0]])
    found = icon_proposals.hidden_nodes(np.zeros((1080, 1920, 3), np.uint8), {"nodes": nodes}, icons, spots)
    assert sorted((node["x"], node["y"], node["hidden"], node["source"]) for node in found) == [
        (500.0, 764.0, True, "icon row"),
        (600.0, 432.0, True, "icon row"),
        (823.0, 535.0, True, "icon row"),
    ]


def test_proposed_boxes_are_marked_in_annotations() -> None:
    """Proposed icons and map nodes keep their own source, so the editor shows the reviewer where a box came from."""
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    detection = {
        "nodes": [{"x": 50, "y": 150}, {"x": 120, "y": 150, "hidden": True, "proposal": True}],
        "icons": [{"x": 50, "y": 50, "score": 1.0}, {"x": 120, "y": 50, "score": 0.97, "proposal": True}],
    }
    annotations = detection_annotations(detection, image, image, DetectionOptions())
    assert [(annotation["label"], annotation["source"]) for annotation in annotations] == [
        ("map_node", "classical"),
        ("map_node", "icon_row"),
        ("icon", "classical"),
        ("icon", "icon_match"),
    ]


def _shot(test_data: Path, name: str) -> Path:
    shot = test_data / RES_1080 / name
    if not shot.exists():
        pytest.skip(f"missing {shot}")
    return shot


@pytest.mark.data
def test_res_atlas_icons_are_proposed(test_data: Path) -> None:
    """On a res atlas screenshot the classical finder finds 4 icons; the proposals add the ~30 it misses.

    Measured on res_1080_100's middle screenshot: 32 proposals, of which one (a TwiceLockedBoxes match on terrain)
    is wrong. The bounds leave room for retrained detector models.
    """
    annotations = run_classical_detector(_shot(test_data, "2694490_20261114092841_1.png"))["annotations"]
    sources = [annotation["source"] for annotation in annotations if annotation["label"] == "icon"]
    assert sources.count("icon_match") >= 25
    assert len(sources) >= 30


@pytest.mark.data
def test_icons_over_fogged_map_nodes(test_data: Path) -> None:
    """The fogged map nodes under Abyss icons in res_1080_100's first screenshot (reviewer's report) get their icons
    and a hidden map node each: a pair at (385, 538) / (424, 538) and a single icon at (296, 626)."""
    annotations = run_classical_detector(_shot(test_data, "2694490_20261114092839_1.png"))["annotations"]
    centres = [
        (a["label"], a["source"], a["bbox"][0] + a["bbox"][2] / 2, a["bbox"][1] + a["bbox"][3] / 2) for a in annotations
    ]

    def near(label: str, x: float, y: float, tolerance: float, source: str | None = None) -> bool:
        return any(
            row[0] == label
            and (source is None or row[1] == source)
            and abs(row[2] - x) <= tolerance
            and abs(row[3] - y) <= tolerance
            for row in centres
        )

    for x, y in ((385, 538), (424, 538), (296, 626)):
        assert near("icon", x, y, 4), (x, y)
    for x, y in ((404, 571), (296, 659)):  # the fogged map nodes' glow, measured on the screenshot
        assert near("map_node", x, y, 10, source="icon_row"), (x, y)


@pytest.mark.data
def test_the_annotator_shares_one_map_finder_run(test_data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_classical_detector`` hands its ``find_maps`` run to the detector instead of running it twice (the
    finder runs once), and the detector's result and the faint map nodes are what two separate runs give."""
    from grand_project import core
    from grand_project.detect import pipeline
    from grand_project.detect.models import _models
    from grand_project.detect.pipeline import detect_classical, ensure_models, find_maps

    shot = _shot(test_data, "2694490_20261114092839_1.png")
    calls: list[int] = []

    def counting_find_maps(*args, **kwargs):
        calls.append(1)
        return find_maps(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "find_maps", counting_find_maps)
        run_classical_detector(shot)
    assert len(calls) == 1

    image = core.read_screenshot(shot)
    ensure_models()
    found = find_maps(image, _models["maps"])

    assert detect_classical(image, found_maps=found) == detect_classical(image)
    _maps, pts, prob = find_maps(image, _models["maps"])
    np.testing.assert_array_equal(icon_proposals.map_spots(found[1], found[2]), icon_proposals.map_spots(pts, prob))


def test_a_lone_icon_at_the_crawl_offset_gets_its_hidden_map_node() -> None:
    """A lone icon stands ROW_DY (24 px) above its map node, closer than ANNOTATOR_ICON_NMS: the row's own icon never
    makes it a marker over another icon. A snap onto a faint glow that would land on a known map node keeps the
    estimate."""
    image = np.zeros((1080, 1920, 3), np.uint8)
    found = icon_proposals.hidden_nodes(image, {"nodes": []}, [{"x": 600, "y": 400}])
    assert [(node["x"], node["y"]) for node in found] == [(600.0, 424.0)]
    known = [{"x": 622.0, "y": 430.0, "hidden": True}]  # 23 px from the estimate, 16 px from the glow
    found = icon_proposals.hidden_nodes(image, {"nodes": known}, [{"x": 600, "y": 400}], np.array([[607.0, 426.0]]))
    assert [(node["x"], node["y"]) for node in found] == [(600.0, 424.0)]
