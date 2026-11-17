"""The atlas folder used as the screenshot folder (user's first choice): the atlas's own files must never be
taken for screenshots.

1. 4 consecutive crawl screenshots copied into a folder; atlas.json made in that same folder; added twice
   (the second time nothing may be new: no atlas output counted as a screenshot)
2. everything the atlas wrote besides atlas.json + its detection cache sits in atlas_files/
3. an atlas from before v0.88 (outputs next to atlas.json) gets them moved into atlas_files/ and they are
   ignored as screenshots even where they still lie
4. an image the program wrote, under any name, is never a screenshot (tagged PNG); a plain image still is
"""

import shutil

import cv2
import numpy as np
import pytest

from grand_project import builder as B
from grand_project import core

pytestmark = pytest.mark.data


@pytest.fixture
def folder_atlas(tmp_path, test_data, copy_cache):
    """Four crawl screenshots in a folder with their saved detections, and the atlas path in that folder.

    Returns:
        (folder, the 4 screenshot paths in it, atlas.json path, its detection cache folder).
    """
    crawl = sorted((test_data / "screenshots" / "crawl").glob("*.png"))[100:104]
    for p in crawl:
        shutil.copy2(p, tmp_path / p.name)
    frames_dir = tmp_path / "atlas_frames"
    copy_cache(crawl, test_data / "crawl_atlas" / "atlas_frames", frames_dir)
    return tmp_path, crawl, tmp_path / "atlas.json", frames_dir


def test_atlas_outputs_are_never_screenshots(folder_atlas, check):
    """Building an atlas in its own screenshot folder: only the screenshots count, before and after."""
    work, crawl, atlas_path, frames_dir = folder_atlas
    shots = core.screenshots_in(work)
    check("4 screenshots in the atlas folder", len(shots) == 4, len(shots))
    at = core.Atlas()
    frames = [B.extract_frame(p, frames_dir) for p in shots]
    added, _refused = B.place_frames(at, frames, log=lambda *_: None)
    at.save(atlas_path)
    B.export(at, atlas_path)
    cv2.imencode(".png", np.zeros((3128, 3994, 3), np.uint8))[1].tofile(
        str(core.atlas_files(atlas_path) / "atlas_terrain.png")
    )  # what the viewer's map cache writes
    check("all 4 placed", added == 4, added)
    top = sorted(p.name for p in work.iterdir() if p.is_file())
    check(
        "only the screenshots + atlas.json at the top of the folder",
        top == sorted([p.name for p in crawl] + ["atlas.json"]),
        f"{len(top)} files",
    )
    check(
        "exports + map cache in atlas_files/",
        all(
            (work / "atlas_files" / n).exists()
            for n in ("atlas_composite.png", "atlas_network.png", "atlas_terrain.png")
        ),
    )
    again = core.screenshots_in(work)
    check(
        "adding the folder again finds only the same 4 screenshots", [p.name for p in again] == [p.name for p in shots]
    )


def test_old_outputs_next_to_atlas_are_moved_and_ignored(tmp_path, test_data, check):
    """An atlas from before v0.88: its outputs lie next to atlas.json; they are not screenshots and move."""
    shot = sorted((test_data / "screenshots" / "crawl").glob("*.png"))[100]
    for n in ("atlas_terrain.png", "atlas_composite.png", "atlas_network.png"):
        cv2.imencode(".png", np.zeros((8, 8, 3), np.uint8))[1].tofile(str(tmp_path / n))
    (tmp_path / "atlas_undo").mkdir()
    shutil.copy2(shot, tmp_path / shot.name)
    check(
        "old outputs next to atlas.json are not screenshots",
        [p.name for p in core.screenshots_in(tmp_path)] == [shot.name],
    )
    d = core.atlas_files(tmp_path / "atlas.json")
    check(
        "old outputs moved into atlas_files/",
        sorted(p.name for p in d.iterdir())
        == ["atlas_composite.png", "atlas_network.png", "atlas_terrain.png", "atlas_undo"],
    )
    check("nothing generated left at the top", sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == [shot.name])


def test_images_the_program_wrote_are_not_screenshots(folder_atlas):
    """A tagged PNG under any name is skipped (user: an overview image was added and sat in Waiting)."""
    work, _crawl, _atlas_path, _frames_dir = folder_atlas
    core.write_png(work / "atlas_network_overview.png", np.full((1080, 1920, 3), 60, np.uint8), "overview")
    shots = core.screenshots_in(work)
    (work / "plain_copy.png").write_bytes(shots[0].read_bytes())
    names = [p.name for p in core.screenshots_in(work)]
    assert "atlas_network_overview.png" not in names
    assert "plain_copy.png" in names


def test_old_icon_sheets_are_not_screenshots(tmp_path):
    """Old untagged icon-labelling sheets (<atlas>_badges_<round>.png) are skipped by name (user: auto-add tried
    to add six of them in an old crawl atlas folder)."""
    img = np.full((1080, 1920, 3), 60, np.uint8)
    for name in ("atlas_badges_round3.png", "atlas_badges_after.png", "2694490_20261114092311_1.png"):
        cv2.imwrite(str(tmp_path / name), img)  # plain cv2: untagged, like the old sheets
    assert [p.name for p in core.screenshots_in(tmp_path)] == ["2694490_20261114092311_1.png"]
    assert core.is_atlas_output("atlas_badges_check.png") and not core.is_atlas_output("2694490_20261114092311_1.png")
    assert not core.is_atlas_output("screenshot_badges_session.png"), "only the old sheet names (review)"
