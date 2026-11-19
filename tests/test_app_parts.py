"""The map's parts (app.parts): what the page's loading cover waits on instead of a timer."""

from grand_project.app.parts import PARTS, Parts


def test_a_new_atlas_starts_with_every_part_waiting():
    parts = Parts()
    parts.reset(4)
    out = parts.payload()
    assert out["generation"] == 4
    assert {n: p["state"] for n, p in out["parts"].items()} == dict.fromkeys(PARTS, "waiting")


def test_a_part_goes_from_building_to_ready_or_failed_with_its_reason():
    parts = Parts()
    parts.reset(1)
    parts.start("model", 1)
    assert parts.payload()["parts"]["model"]["state"] == "building"
    parts.fail("model", "RuntimeError: bad atlas", 1)
    model = parts.payload()["parts"]["model"]
    assert model["state"] == "failed" and model["error"] == "RuntimeError: bad atlas"
    parts.start("model", 1)  # tried again: the old reason goes
    parts.done("model", 1)
    model = parts.payload()["parts"]["model"]
    assert model["state"] == "ready" and model["error"] is None


def test_a_beat_shows_the_part_is_still_working(monkeypatch):
    import grand_project.app.parts as mod

    now = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    parts = Parts()
    parts.reset(1)
    parts.start("map_image", 1)
    now[0] = 140.0
    assert parts.payload()["parts"]["map_image"]["quiet"] == 40.0  # nothing for 40 s
    parts.beat("map_image", 1)
    now[0] = 141.5
    assert parts.payload()["parts"]["map_image"]["quiet"] == 1.5  # it moved on
    assert parts.payload()["parts"]["map_image"]["state"] == "building"  # (a beat changes nothing else)


def test_work_for_an_atlas_no_longer_open_changes_nothing():
    parts = Parts()
    parts.reset(1)
    parts.reset(2)  # another atlas opened
    parts.fail("map_image", "old build failed", 1)
    parts.done("model", 1)
    out = parts.payload()["parts"]
    assert out["map_image"]["state"] == "waiting" and out["model"]["state"] == "waiting"
