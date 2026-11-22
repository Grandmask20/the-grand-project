"""What the map's vector tiles are made from (app.tilesource.TileSource): one record, replaced, never changed."""

import dataclasses

import pytest

from grand_project.app.tilesource import TileSource


def test_its_key_is_the_versions_tiles_are_kept_under():
    src = TileSource(model_version=3, filter_version=5, terrain_version=7, replay_token=9)
    assert src.key(steps=False) == (3, 5, 7, 0)  # (the plain tiles don't follow the timelapse plan)
    assert src.key(steps=True) == (3, 5, 7, 9)


def test_a_change_makes_a_new_record_and_leaves_the_one_in_use_as_it_was():
    V = {"nodes": [{"x": 1}], "paths": [], "icons": [], "landmarks": []}
    before = TileSource(V=V, model_version=1)
    after = before.with_(V={"nodes": [], "paths": [], "icons": [], "landmarks": []}, model_version=2)
    assert before.V is V and before.model_version == 1
    assert after.V["nodes"] == [] and after.model_version == 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        after.model_version = 3  # type: ignore[misc]


def test_with_no_atlas_it_holds_nothing():
    src = TileSource()
    assert src.grid is None and src.terrain is None and src.replay is None
    assert src.V["nodes"] == [] and src.D == {}
