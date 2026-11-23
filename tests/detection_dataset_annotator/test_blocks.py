"""Spatial blocks of the screenshots (tools/detection_dataset_annotator/blocks.py): an atlas's screenshots are
grouped by where they lie, so the splits can keep views of the same map nodes together."""

from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

import pytest

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.blocks import Block, frame_middles, screenshot_blocks
from tools.detection_dataset_annotator.state import relative_source


def write_atlas(folder: Path, places: dict[str, tuple[float, float]]) -> None:
    """An atlas file placing a 1920x1080 untilted screenshot per name, its top-left corner at the given atlas spot."""
    folder.mkdir(parents=True, exist_ok=True)
    frames = [
        {"name": name, "path": f"{name}.png", "w": 1920, "h": 1080, "M": [[1, 0, x], [0, 1, y]], "horizon": None}
        for name, (x, y) in places.items()
    ]
    atlas = {"frames": frames, "nodes": [], "edges": [], "landmarks": []}
    (folder / K.ANNOTATOR_ATLAS_FILE).write_text(json.dumps(atlas), encoding="utf-8")


def test_a_frame_middle_is_in_atlas_units(tmp_path: Path) -> None:
    write_atlas(tmp_path, {"a": (100.0, -50.0)})
    assert frame_middles(tmp_path / K.ANNOTATOR_ATLAS_FILE) == {
        PureWindowsPath(str((tmp_path / "a.png").resolve())).parts: pytest.approx((1060.0, 490.0))
    }


def test_a_screenshot_is_placed_by_the_path_its_atlas_saved(tmp_path: Path) -> None:
    """The frame whose saved path ends with the file's own path from the atlas folder places it: also an atlas made on
    Windows (its saved paths are Windows ones, resolving nowhere here), and a screenshot re-encoded since (its bytes
    are no longer the frame's sha: the trimmed test data)."""
    write_atlas(tmp_path, {f"s{i}": (i * 300.0, 0.0) for i in range(4)})
    atlas = json.loads((tmp_path / K.ANNOTATOR_ATLAS_FILE).read_text(encoding="utf-8"))
    for frame in atlas["frames"]:
        frame["path"] = f"C:\\Users\\someone\\atlas_crawl\\{frame['path']}"
    (tmp_path / K.ANNOTATOR_ATLAS_FILE).write_text(json.dumps(atlas), encoding="utf-8")
    (tmp_path / "s3.png").write_bytes(b"re-encoded")
    paths = {f"s{i}": tmp_path / f"s{i}.png" for i in range(4)} | {"other": tmp_path / "other.png"}
    blocks = screenshot_blocks(paths, shots_per_block=4)
    assert {blocks[f"s{i}"] for i in range(4)} == {Block(relative_source(tmp_path), 0)}
    assert blocks["other"] == Block(relative_source(paths["other"]))  # no frame of its name


def test_screenshots_of_one_place_share_a_block(tmp_path: Path) -> None:
    """Two far-apart groups of six screenshots make two blocks of six; a screenshot the atlas does not place, and one
    of a folder without an atlas, are blocks of their own."""
    atlas = tmp_path / "atlas"
    places = {f"west{i}": (i * 300.0, 0.0) for i in range(6)} | {
        f"east{i}": (50000.0 + i * 300.0, 0.0) for i in range(6)
    }
    write_atlas(atlas, places)
    paths = {name: atlas / f"{name}.png" for name in places}
    paths["unplaced"] = atlas / "unplaced.png"
    paths["loose"] = tmp_path / "loose" / "shot.png"
    blocks = screenshot_blocks(paths, shots_per_block=6)
    west = {blocks[f"west{i}"] for i in range(6)}
    east = {blocks[f"east{i}"] for i in range(6)}
    assert len(west) == len(east) == 1 and west != east
    assert {block.atlas for block in west | east} == {relative_source(atlas)}
    assert blocks["unplaced"] == Block(relative_source(paths["unplaced"]))
    assert blocks["loose"] == Block(relative_source(paths["loose"]))


def test_blocks_are_the_same_every_time(tmp_path: Path) -> None:
    write_atlas(tmp_path, {f"s{i}": (float(i % 7) * 900.0, float(i // 7) * 700.0) for i in range(35)})
    paths = {f"s{i}": tmp_path / f"s{i}.png" for i in range(35)}
    first = screenshot_blocks(paths, shots_per_block=5)
    assert first == screenshot_blocks(dict(reversed(list(paths.items()))), shots_per_block=5)
    assert len(set(first.values())) == 7


def test_screenshots_in_folders_below_their_atlas_are_its_blocks(tmp_path: Path) -> None:
    """map_state_change keeps its screenshots in pre-change/, post-change/ ... with atlas.json one folder up: they are
    that atlas's blocks together, not one block each."""
    atlas = tmp_path / "state_change"
    places = {f"pre{i}": (i * 300.0, 0.0) for i in range(4)} | {f"post{i}": (i * 300.0, 100.0) for i in range(4)}
    folder = {name: "pre" if name.startswith("pre") else "post" for name in places}
    write_atlas(atlas, places)
    saved = json.loads((atlas / K.ANNOTATOR_ATLAS_FILE).read_text(encoding="utf-8"))
    for frame in saved["frames"]:  # the atlas saved where it found them (here: as an atlas made on Windows)
        frame["path"] = f"C:\\atlases\\state_change\\{folder[frame['name']]}\\{frame['name']}.png"
    (atlas / K.ANNOTATOR_ATLAS_FILE).write_text(json.dumps(saved), encoding="utf-8")
    paths = {name: atlas / folder[name] / f"{name}.png" for name in places}
    blocks = screenshot_blocks(paths, shots_per_block=8)
    assert set(blocks.values()) == {Block(relative_source(atlas), 0)}


def test_a_file_of_a_frames_name_below_its_atlas_is_not_that_frame(tmp_path: Path) -> None:
    """The atlas placed the screenshot next to it: a file of the same name in a folder below is another screenshot,
    a block of its own (it was given that frame's place by its name)."""
    write_atlas(tmp_path, {f"s{i}": (i * 300.0, 0.0) for i in range(3)})
    paths = {f"s{i}": tmp_path / f"s{i}.png" for i in range(3)} | {"below": tmp_path / "pre" / "s0.png"}
    blocks = screenshot_blocks(paths, shots_per_block=3)
    assert len({blocks[f"s{i}"] for i in range(3)}) == 1
    assert blocks["below"] == Block(relative_source(paths["below"]))
