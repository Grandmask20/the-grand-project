"""The dataset bootstrap's extra icon proposals (bootstrap-dataset-program/icon_proposals.py).

The bootstrap modules import their own ``constants`` module, so, like the other bootstrap tests, each check runs
in a child Python with the program folder on its path.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, timeout: int = 120) -> dict:
    """Run a script in a child Python with the bootstrap program importable and return its printed JSON."""
    environment = os.environ.copy()
    python_paths = [str(PROJECT_ROOT / "bootstrap-dataset-program"), str(PROJECT_ROOT)]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_batched_naming_matches_name_badge() -> None:
    """name_icons gives the same name and distance as the detector's own name_badge, also at the screen edge."""
    result = _run("""
import json
import numpy as np
from grand_project.detect import badges
from icon_proposals import name_icons, picture_book

rng = np.random.default_rng(3)
image = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
image[100:140, 150:190] = rng.integers(120, 256, (40, 40, 3), dtype=np.uint8)
points = np.array([[170, 120], [60, 60], [250, 180], [10, 10], [315, 120], [20, 20], [299, 219]])
names, features = picture_book({"names": [], "F": np.zeros((0, 0), np.float32)})
fast = name_icons(image, points, names, features)
slow = [badges.name_badge(image, float(x), float(y), names, features) for x, y in points]
print(json.dumps({"fast": fast, "slow": slow}))
""")
    for (fast_name, fast_dist), (slow_name, slow_dist) in zip(result["fast"], result["slow"], strict=True):
        assert fast_name == slow_name
        assert fast_dist == pytest.approx(slow_dist, abs=1e-4)


def test_proposal_rules() -> None:
    """Sure matches need only the icon-row position; weak ones must be centred or a row neighbour (chains too)."""
    result = _run("""
import json
import numpy as np
import icon_proposals

# Map nodes at (200, 200) and (400, 200); the classical finder already found the icon at (400, 168).
detection = {"nodes": [{"x": 200, "y": 200}, {"x": 400, "y": 200}], "icons": [{"x": 400, "y": 168}]}
matches = {
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
}
points = np.array(list(matches))
icon_proposals.badges.badge_candidates = lambda image: (points, np.ones(len(points)), np.ones((len(points), 1)))
icon_proposals.picture_book = lambda book: (["x"], np.zeros((1, 1), np.float32))
icon_proposals.name_icons = lambda image, pts, names, features: [matches[tuple(int(v) for v in p)] for p in pts]
found = icon_proposals.propose_icons(np.zeros((400, 600, 3), np.uint8), detection, {})
print(json.dumps(sorted((icon["name"], icon["x"], icon["y"], icon["proposal"]) for icon in found)))
""")
    assert result == [
        ["Abyss", 200.0, 168.0, True],
        ["Delirium", 440.0, 168.0, True],
        ["Essence", 240.0, 168.0, True],
        ["MapBoss", 300.0, 170.0, True],
    ]


def test_faint_map_nodes_support_closer_matches() -> None:
    """Over a fogged map node the finder missed, a weak match counts only when it is close (pairs: their middle)."""
    result = _run("""
import json
import numpy as np
import icon_proposals

detection = {"nodes": [], "icons": []}
spots = np.array([[300.0, 200.0], [500.0, 200.0], [700.0, 200.0]])  # faint map nodes, none found
matches = {
    (300, 168): ("Abyss", 0.09),  # centred over a faint map node, close enough: kept
    (480, 168): ("PlayerOrBookmark", 0.074),  # a pair whose middle stands on a faint map node: both kept
    (520, 168): ("Abyss", 0.093),
    (700, 168): ("AncientTrove", 0.10),  # over a faint map node but not close enough: dropped
}
points = np.array(list(matches))
icon_proposals.badges.badge_candidates = lambda image: (points, np.ones(len(points)), np.ones((len(points), 1)))
icon_proposals.picture_book = lambda book: (["x"], np.zeros((1, 1), np.float32))
icon_proposals.name_icons = lambda image, pts, names, features: [matches[tuple(int(v) for v in p)] for p in pts]
found = icon_proposals.propose_icons(np.zeros((400, 900, 3), np.uint8), detection, {}, spots)
print(json.dumps(sorted((icon["name"], icon["x"]) for icon in found)))
""")
    assert result == [["Abyss", 300.0], ["Abyss", 520.0], ["PlayerOrBookmark", 480.0]]


def test_hidden_map_nodes_under_icon_rows() -> None:
    """Every icon row without a map node gets one, at the screenshot's measured icon-to-map-node offset."""
    result = _run("""
import json
import numpy as np
from icon_proposals import hidden_nodes

nodes = [{"x": 200, "y": 432}, {"x": 1000, "y": 332}, {"x": 1400, "y": 632}, {"x": 1230, "y": 430}]
icons = [
    {"x": 200, "y": 400}, {"x": 1000, "y": 300}, {"x": 1400, "y": 600},  # on found map nodes: offset 32 px
    {"x": 600, "y": 400},  # alone: a map node at (600, 432)
    {"x": 800, "y": 500}, {"x": 840, "y": 500},  # a pair: under its middle, snapped to the faint glow
    {"x": 1200, "y": 400},  # a visible map node within HIDDEN_SNAP is the row's map node: none
    {"x": 1600, "y": 300, "source": "square button"},  # a ship button stands on water: none
    {"x": 500, "y": 700}, {"x": 500, "y": 732},  # a marker pinned above an icon: only the icon's map node
    {"x": 100, "y": 1000},  # its map node would be on the HUD: none
]
spots = np.array([[823.0, 535.0]])
found = hidden_nodes(np.zeros((1080, 1920, 3), np.uint8), {"nodes": nodes}, icons, spots)
print(json.dumps(sorted((node["x"], node["y"], node["hidden"], node["source"]) for node in found)))
""")
    assert result == [
        [500.0, 764.0, True, "icon row"],
        [600.0, 432.0, True, "icon row"],
        [823.0, 535.0, True, "icon row"],
    ]


def test_proposed_boxes_are_marked_in_annotations() -> None:
    """Proposed icons and map nodes keep their own source, so the editor shows the reviewer where a box came from."""
    result = _run("""
import json
import numpy as np
from dataset_bootstrap import detection_annotations

image = np.zeros((200, 200, 3), dtype=np.uint8)
detection = {
    "nodes": [{"x": 50, "y": 150}, {"x": 120, "y": 150, "hidden": True, "proposal": True}],
    "icons": [{"x": 50, "y": 50, "score": 1.0}, {"x": 120, "y": 50, "score": 0.97, "proposal": True}],
}
annotations = detection_annotations(detection, image, image)
print(json.dumps([[annotation["label"], annotation["source"]] for annotation in annotations]))
""")
    assert result == [
        ["map_node", "classical"],
        ["map_node", "icon_row"],
        ["icon", "classical"],
        ["icon", "icon_match"],
    ]


@pytest.mark.data
def test_res_atlas_icons_are_proposed(test_data: Path) -> None:
    """On a res atlas screenshot the classical finder finds 4 icons; the proposals add the ~30 it misses.

    Measured on res_1080_100's middle screenshot: 32 proposals, of which one (a TwiceLockedBoxes match on terrain)
    is wrong. The bounds leave room for retrained detector models.
    """
    shot = test_data / "res_atlases" / "res_1080_100" / "2694490_20261114092841_1.png"
    if not shot.exists():
        pytest.skip(f"missing {shot}")
    result = _run(
        f"""
import json
from pathlib import Path
from dataset_bootstrap import run_classical_detector

annotations = run_classical_detector(Path({str(shot)!r}))["annotations"]
print(json.dumps([annotation["source"] for annotation in annotations if annotation["label"] == "icon"]))
""",
        timeout=300,
    )
    assert result.count("icon_match") >= 25
    assert len(result) >= 30


@pytest.mark.data
def test_icons_over_fogged_map_nodes(test_data: Path) -> None:
    """The fogged map nodes under Abyss icons in res_1080_100's first screenshot (reviewer's report) get their icons
    and a hidden map node each: a pair at (385, 538) / (424, 538) and a single icon at (296, 626)."""
    shot = test_data / "res_atlases" / "res_1080_100" / "2694490_20261114092839_1.png"
    if not shot.exists():
        pytest.skip(f"missing {shot}")
    result = _run(
        f"""
import json
from pathlib import Path
from dataset_bootstrap import run_classical_detector

annotations = run_classical_detector(Path({str(shot)!r}))["annotations"]
print(json.dumps([
    [annotation["label"], annotation["source"], annotation["bbox"][0] + annotation["bbox"][2] / 2,
     annotation["bbox"][1] + annotation["bbox"][3] / 2]
    for annotation in annotations
]))
""",
        timeout=300,
    )

    def near(label: str, x: float, y: float, tolerance: float) -> bool:
        return any(row[0] == label and abs(row[2] - x) <= tolerance and abs(row[3] - y) <= tolerance for row in result)

    for x, y in ((385, 538), (424, 538), (296, 626)):
        assert near("icon", x, y, 4), (x, y)
    for x, y in ((404, 571), (296, 659)):  # the fogged map nodes' glow, measured on the screenshot
        assert any(
            row[0] == "map_node" and row[1] == "icon_row" and abs(row[2] - x) <= 10 and abs(row[3] - y) <= 10
            for row in result
        ), (x, y)
