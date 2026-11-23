"""Spatial blocks of the screenshots (tools/detection_dataset_annotator/blocks.py): an atlas's screenshots are
grouped by where they lie, so the splits can keep views of the same map nodes together."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator.blocks import Block, frame_middles, screenshot_blocks
from tools.detection_dataset_annotator.state import relative_source


def _sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def write_atlas(folder: Path, places: dict[str, tuple[float, float]]) -> None:
    """An atlas file placing a 1920x1080 untilted screenshot per name, its top-left corner at the given atlas spot, and
    the screenshots (their bytes: the name) next to it."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in places:
        (folder / f"{name}.png").write_bytes(name.encode())
    frames = [
        {"name": name, "path": f"{name}.png", "sha": _sha(name), "w": 1920, "h": 1080, "M": [[1, 0, x], [0, 1, y]],
         "horizon": None}
        for name, (x, y) in places.items()
    ]  # fmt: skip
    atlas = {"frames": frames, "nodes": [], "edges": [], "landmarks": []}
    (folder / K.ANNOTATOR_ATLAS_FILE).write_text(json.dumps(atlas), encoding="utf-8")


def test_a_frame_middle_is_in_atlas_units(tmp_path: Path) -> None:
    write_atlas(tmp_path, {"a": (100.0, -50.0)})
    assert frame_middles(tmp_path / K.ANNOTATOR_ATLAS_FILE) == {_sha("a"): pytest.approx((1060.0, 490.0))}


def test_a_screenshot_is_placed_by_its_bytes_not_its_name(tmp_path: Path) -> None:
    """The atlas places the very screenshot it was made from: another file under that name is not placed, and the
    atlas's saved paths may be another system's (a Windows atlas read on Linux: none of them resolves)."""
    write_atlas(tmp_path, {f"s{i}": (i * 300.0, 0.0) for i in range(4)})
    (tmp_path / "s3.png").write_bytes(b"another view")
    paths = {f"s{i}": tmp_path / f"s{i}.png" for i in range(4)}
    blocks = screenshot_blocks(paths, shots_per_block=4)
    assert len({blocks[f"s{i}"] for i in range(3)}) == 1
    assert blocks["s3"] == Block(relative_source(paths["s3"]))
    # the digests the caller has (the split ledger's) are used as they are: no file is read again
    assert screenshot_blocks({"s0": tmp_path / "gone.png"}, {"s0": _sha("s0")})["s0"].atlas == relative_source(tmp_path)


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
