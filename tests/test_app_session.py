"""The app's session (app.session.AtlasSession) on hand-made atlases: no screenshots or window needed.

The map image comes from the cache next to the atlas; the tiles, Find, bookmarks, hand edits, the replay, debug marks
and the saved atlases are checked through the session, as the page uses them.
"""

import base64
import json
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

from grand_project import cities, core
from grand_project.app.library import list_dir
from grand_project.app.model import view_model
from grand_project.app.session import AtlasSession
from tests.webmap_data import biome_atlas, make_atlas, read_tile


@pytest.fixture
def session():
    s = AtlasSession(settings={}, worker=False)
    yield s
    s.shutdown()


def settled(session) -> None:
    """Wait for what opening an atlas starts behind it: the locked-stronghold search ends with a model rebuild (a
    filter version), which landed in the middle of a test on a busy machine."""
    t = getattr(session, "_lock_thread", None)
    if t:
        t.join(60)  # (a hang fails here; pytest's faulthandler_timeout prints the stacks of one that doesn't end)
        assert not t.is_alive(), "the locked-stronghold search didn't end"


def points(s: AtlasSession, layer: str, replay: bool = False) -> dict:
    """Every point feature of a vector tile layer at zmax: {id: (atlas x, atlas y, props)} (replay: the timelapse
    tab's tiles)."""
    g = s.grid
    out = {}
    for tx in range(2**g.zmax):
        for ty in range(2**g.zmax):
            for _g, pts, props, fid in read_tile(s.vector_tile(g.zmax, tx, ty, replay)).get(layer, []):
                if len(pts) != 1:
                    continue
                (_c, x, y) = pts[0]
                if 0 <= x < 4096 and 0 <= y < 4096:
                    wx, wy = tx * 256 + x / 16, ty * 256 + y / 16
                    out[fid] = ((wx - g.offset) / g.scale + g.x0, (wy - g.offset) / g.scale + g.y0, props)
    return out


def features(s: AtlasSession, layer: str) -> list:
    """Every feature of a layer at zmax (with buffer copies)."""
    g = s.grid
    return [r for tx in range(2**g.zmax) for ty in range(2**g.zmax)
            for r in read_tile(s.vector_tile(g.zmax, tx, ty)).get(layer, [])]  # fmt: skip


def test_open_shows_the_cached_map_image_and_its_tiles(session, tmp_path):
    path, pts, img = make_atlas(tmp_path)
    session.open_atlas(path)
    assert session.atlas_summary()["maps"] == 15  # the removed one isn't counted
    info = session.map_info()
    assert info["zmax"] == session.grid.zmax and info["zdeep"] >= info["zmax"]
    # the deepest map image tile at a map's spot shows the map image there
    x, y = pts[0]
    wx, wy = session.grid.world_px(x, y)
    tile = cv2.imdecode(np.frombuffer(session.terrain_tile(info["zmax"], int(wx // 256), int(wy // 256)), np.uint8), 1)
    got = tile[int(wy % 256), int(wx % 256)].astype(int)
    assert np.abs(got - img[int(y), int(x)].astype(int)).max() < 40
    assert session.terrain_tile(info["zmax"], 0, 0) is None  # the world's corner: no ground


def test_vector_tiles_hold_the_maps_where_they_are(session, tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    maps = points(session, "maps")
    assert sorted(maps) == list(range(15))  # the removed map node is left out
    for i, (x, y) in enumerate(pts):
        gx, gy, props = maps[i]
        assert abs(gx - x) < 0.1 and abs(gy - y) < 0.1 and props["status"] == "confirmed"
    assert maps[6][2]["icons"] == "|Breach|Delirium|"
    assert not points(session, "removed")
    settled(session)
    v = session.filter_version
    session.set_ui_settings({"layers": {"Removed": True}})
    assert session.filter_version == v + 1 and list(points(session, "removed")) == [15]
    session.set_ui_settings({"ui": {"background": "vector"}, "layers": {"Labels": False}})  # page-only: same tiles
    assert session.filter_version == v + 1


class Job:
    """A job holding the session lock (adding screenshots holds it for minutes), on a thread of its own: `work` runs
    under it once it is taken, then the lock is kept until `end()`."""

    def __init__(self, session, work=lambda: None):
        self.taken, self.done = threading.Event(), threading.Event()

        def run():
            with session._lock:
                work()
                self.taken.set()
                self.done.wait(60)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert self.taken.wait(60)

    def end(self):
        self.done.set()
        self.thread.join(60)


def answered(fn, timeout: float = 20.0):
    """Run fn on a thread of its own; its answer, or fail when it waits (for a job) past the timeout."""
    out: list = []
    t = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    t.start()
    t.join(timeout)
    assert out, "it waited for the job"
    return out[0]


def test_a_filter_changed_during_a_job_shows_on_the_map_at_once(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    settled(session)
    job = Job(session)
    try:
        session.set_ui_settings({"layers": {"Removed": True}})  # (the page's request: no job wait)
        assert list(answered(lambda: points(session, "removed"))) == [15]
        assert answered(lambda: json.loads(session.scene_3d()))["paths"]  # the 3D view's scene too
    finally:
        job.end()


def test_what_a_job_changes_shows_on_the_map_as_it_changes_it(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    settled(session)
    assert 0 in points(session, "maps")

    def remove_map_0():
        session.atlas.final["nodes"][0]["status"] = "removed"
        session.rebuild_model()  # (as adding does after each screenshot, the lock still held)

    job = Job(session, remove_map_0)
    try:
        info = answered(session.map_info)
        maps = answered(lambda: points(session, "maps"))
        assert 0 not in maps and len(maps) == 14
        # the versions the page asks with are those of what it gets: never an address with older tiles in it
        assert session._vector[0][:3] == (info["model_version"], info["filter_version"], info["terrain_version"])
    finally:
        job.end()


def test_the_map_asks_for_the_versions_the_tiles_are_made_from(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    settled(session)
    info = session.map_info()
    session.model_version += 1  # a change under way (a job between bumping the version and putting in the model)
    assert session.map_info()["model_version"] == info["model_version"]  # the page isn't told before the tiles are
    session.rebuild_model()
    assert session.map_info()["model_version"] == session.model_version > info["model_version"]


def test_biomes_ground_icons_and_models(session, tmp_path):
    path, at = biome_atlas(tmp_path)
    session.open_atlas(path)
    kinds = {p["kind"] for _g, _pts, p, _id in features(session, "biomes")}
    assert {"Vaal", "Faridun", "Breach"} <= kinds, kinds
    assert not kinds & {"Forest", "Desert"}  # no icon makes a biome (user: Influence icons drew areas)
    assert all(g == 3 for g, *_ in features(session, "land"))
    icons = points(session, "icons")
    assert sorted(p["name"] for *_xy, p in icons.values()) == sorted(ic["name"] for ic in at.final["icons"])
    # the 3D view's models come whole from scene_3d (not cut into the tiles), each saying what a click on it selects
    models = json.loads(session.scene_3d())["models"]
    assert models and all(m["base"] < m["height"] and len(m["rings"][0]) >= 3 for m in models)
    assert {int(m["pick"][5:]) for m in models if m["pick"].startswith("node:")} == set(range(80))
    assert not features(session, "solids") and not features(session, "icon_rows")
    # the session's biomes are the cities module's own
    got = cities.biomes(at, view_model(at), ground=session.ground())
    assert got["potential"] == session.D["potential"] and got["city_type"] == session.D["city_type"]
    # hiding a type takes it off the map
    session.set_ui_settings({"hidden_types": ["Breach"]})
    assert "Breach" not in {p["name"] for *_xy, p in points(session, "icons").values()}


def test_find_details_and_clicks(session, tmp_path):
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    sections = {s["title"]: [r["label"] for r in s["rows"]] for s in session.types()["sections"]}
    assert "Vaal city" in sections["Places"] and "Breach" in sections["Map icons"]
    hits = session.search("breach")["results"]
    assert any(r["kind"] == "icon" for r in hits) and any(r["kind"] == "landmark" for r in hits)
    assert session.search("220, 400") == {"goto": [220.0, 400.0]}
    row = session.search("#12")["results"][0]
    assert {k: row[k] for k in ("kind", "id", "label", "x", "y", "map")} == {
        "kind": "node",
        "id": 12,
        "label": "Map #12",
        "x": 440.0,
        "y": 200.0,
        "map": 12,
    }  # (and its picture, icons, note: Find's rows)
    assert len(session.list_type("Breach stronghold")) == 2
    info = session.info("landmark", 0)
    assert info["title"] == "Vaal city" and info["city_type"] == "Vaal"  # typed by hand
    assert session.pick(440.0, 200.0, 1.0) == ("node", 12)
    assert session.pick(5000.0, 5000.0, 1.0) is None
    g = session.graph()
    assert len(g["nodes"]) == 80 and len(g["edges"]) == 142
    assert session.sources(0.0, 0.0)[0]["name"] == "a"


def test_bookmarks(session, tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    i = session.add_bookmark(pts[1][0], pts[1][1], "boss", "Farm spot", "every day")
    assert i == 1 and session.add_bookmark(pts[1][0] + 5, pts[1][1], "again") == -1  # one per spot
    session.edit_bookmark(i, "big boss", "Boss", "")
    session.move_bookmarks([0], "Boss")
    groups = {g["name"]: [b["name"] for b in g["items"]] for g in session.bookmarks_payload()["groups"]}
    assert groups == {"Boss": ["big boss", "farm <here>"]}
    fv = session.filter_version

    def drawn():  # what the page draws (it draws the bookmarks itself; the tiles don't hold them)
        return [b["name"] for g in session.bookmarks_payload()["groups"] for b in g["items"] if b["shown"]]

    session.toggle_group("Boss")
    assert drawn() == []  # a hidden group isn't drawn
    session.toggle_bookmark(0)  # shows the group again with only this one
    assert drawn() == ["farm <here>"]
    assert session.filter_version == fv and not points(session, "bookmarks")  # the tiles weren't made again
    assert sorted(session.delete_bookmarks([0, 1])) == ["big boss", "farm <here>"]
    assert core.Atlas.load(path).bookmarks == []  # saved


def test_hand_edits(session, tmp_path):
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    session.set_city_type(1, "Ezomyte")
    assert session.info("landmark", 1)["title"] == "Ezomyte city"
    lm = session.V["landmarks"][1]
    session.set_landmark(lm["x"], lm["y"], "")
    assert session.info("landmark", 1)["removed"]
    poly = [[1700, 1300], [2100, 1300], [2100, 1500], [1700, 1500]]
    assert session.lasso_nodes(poly) and session.set_biome(poly, "Vaal city") == len(session.lasso_nodes(poly))
    assert session.D["potential"][session.lasso_nodes(poly)[0]] == ("Vaal city", 0)
    # a map the filters hide (doubtful, the Doubtful layer off) is still inside: its biome area is drawn all the same
    inside = session.lasso_nodes(poly)
    session.V["nodes"][inside[0]]["status"] = "doubtful"
    session.set_ui_settings({"layers": {"Doubtful": False}, "multi_only": True})
    assert session.lasso_nodes(poly) == inside
    with pytest.raises(ValueError):
        session.set_biome([[9000, 9000], [9100, 9000], [9100, 9100]], "Vaal city")  # no maps inside
    saved = core.Atlas.load(path)
    assert saved.biome_edits[-1]["biome"] == "Vaal city" and saved.landmark_edits


def timed_atlas(folder: Path) -> Path:
    """The hand-made atlas with 4 screenshots taken in two sessions (Steam names), one per quarter of the map."""
    path, _pts, img = make_atlas(folder)
    at = core.Atlas.load(path)
    names = ["2694940_20250101120000_1", "2694940_20250101120100_1", "2694940_20250101180000_1",
             "2694940_20250101180200_1"]  # fmt: skip
    at.frames = [
        {"name": n, "path": str(folder / f"{n}.png"), "w": 960, "h": 540, "stats": {},
         "M": [[1.0, 0, 480 * (k % 2) + 480], [0, 1.0, 270 * (k // 2) + 270]]}
        for k, n in enumerate(names)
    ]  # fmt: skip
    at.save(path)
    png, npz = core.map_image_files(path)
    np.savez_compressed(npz, key=at.terrain_key(), origin=np.array([0.0, 0.0, 1.0]), weight=np.ones(img.shape[:2]))
    return path


def test_a_timelapse_closed_as_its_tiles_are_made_isnt_named_in_their_address(session, tmp_path, monkeypatch):
    path, pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    settled(session)
    g = session.grid
    wx, wy = g.world_px(*pts[0])

    def open_timelapse() -> None:
        """A timelapse open as the page asks for its tab's tiles."""
        with session._source_lock:
            session._source = session._source.with_(replay={"node": [], "icon": [], "landmark": []}, replay_token=5)

    asked = []  # the steps each request asked its build for (after its own look at the timelapse)
    real_vector, real_scene = session._vector_made, session._scene_made

    def closing(real):
        """The timelapse closes between the request's look at it and the build."""

        def made(steps=False):
            asked.append(steps)
            with session._source_lock:
                session._source = session._source.with_(replay=None)
            return real(steps)

        return made

    monkeypatch.setattr(session, "_vector_made", closing(real_vector))
    monkeypatch.setattr(session, "_scene_made", closing(real_scene))
    open_timelapse()
    _data, tile_address = session.vector_tile_made(g.zmax, int(wx // 256), int(wy // 256), replay=True)
    open_timelapse()  # (open again for the scene's own request: the tile's left it closed, CodeRabbit)
    _scene, scene_address = session.scene_3d_made(replay=True)
    assert asked == [True, True]  # each saw it open, then it closed before its build
    # built without steps: not named the timelapse's, so not kept by the browser under its address (CodeRabbit)
    assert tile_address and "&r=" not in tile_address and scene_address and "&r=" not in scene_address


def test_replay_and_colour_by(session, tmp_path):
    session.open_atlas(timed_atlas(tmp_path))
    session.set_replay_settings({"type": "by time", "per_step": 1})
    plan = session.replay_open()
    assert (
        plan["n_steps"] == 4 and plan["step_of"] == [0, 1, 2, 3] and plan["ticks"] == [0, 2, 3]
    )  # a minute apart: one batch
    assert plan["step_session"] == [0, 0, 1, 1] and plan["real"] == "3 min"
    steps = {fid: p["step"] for fid, (*_xy, p) in points(session, "maps", replay=True).items()}
    assert all("step" not in p for *_xy, p in points(session, "maps").values())  # other tabs: the plain tiles
    assert set(steps.values()) <= {0, 1, 2, 3} and len(steps) == 15
    fog = session.replay_fog()["field"]
    cells = np.frombuffer(base64.b64decode(fog["data"]), "<u2").reshape(fog["h"], fog["w"])
    shown = cells[cells < 65535] / 65534 * fog["top"]  # each cell's reveal step: one of the screenshots' steps
    assert fog["top"] == 4 and shown.size and set(np.round(shown).astype(int)) <= {0, 1, 2, 3}
    assert len(fog["corners"]) == 4
    frames = session.frames_payload()
    assert [f["session"] for f in frames["frames"]] == [0, 0, 1, 1] and len(frames["ramp"]) == 256
    png, box = session.heat_png(upto=2)
    assert png[:4] == b"\x89PNG" and box[0] <= 480 and box[2] >= 1440
    # the 3D scene too: the playing tab's models come in with their map node's step (they stood from the start)
    scene = json.loads(session.scene_3d(replay=True))
    pillars = [m for m in scene["models"] if m["pick"].startswith("node:")]
    assert pillars and all(m["step"] == steps[int(m["pick"][5:])] for m in pillars)
    assert all(m["step"] == -1 for m in json.loads(session.scene_3d())["models"])  # other tabs: no steps
    session.replay_close()
    assert all("step" not in p for *_xy, p in points(session, "maps", replay=True).values())  # closed: none


def test_debug_marks(session, tmp_path):
    path, pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    a = session.add_debug_mark("wrong map", "not a map (no base there)", "", maps=[3])
    b = session.add_debug_mark("missing path", "there should be a path", "x", maps=[3, 4])
    assert (a["id"], b["id"]) == (1, 2) and (a["x"], a["y"]) == (round(pts[3][0], 1), round(pts[3][1], 1))
    session.delete_debug_mark(1)
    assert [m["id"] for m in session.debug_marks()] == [2]
    assert session.add_debug_mark("missing map", "other", "", x=5, y=5)["id"] == 3  # never reused
    backup = session.clear_debug_marks()
    assert backup and not session.debug_marks()
    assert len(json.loads((core.atlas_files(path) / backup).read_text())) == 2


def test_saved_atlases_and_folders(session, tmp_path):
    (tmp_path / "one").mkdir()
    path, _pts, _img = make_atlas(tmp_path / "one")
    session.open_atlas(path)
    cards = session.atlases_payload()
    assert [(c["name"], c["open"]) for c in cards] == [("one", True)]
    session.rename_atlas(str(path), "My atlas")
    assert session.known_atlases()[0]["name"] == "My atlas"
    assert session.open_folder(tmp_path / "one")["opened"] == str(path)
    listing = list_dir(str(tmp_path))
    assert [e["name"] for e in listing["entries"] if e["dir"]] == ["one"]
    session.forget_atlas(str(path))
    assert session.atlas is None and session.known_atlases() == []


def test_new_atlas_and_close(session, tmp_path):
    session.new_atlas(tmp_path / "fresh")
    assert session.path == tmp_path / "fresh" / "atlas.json" and session.path.exists()
    with pytest.raises(ValueError):
        session.new_atlas(tmp_path / "fresh" / "atlas.json")  # exists
    session.close()
    assert session.atlas is None and session.map_info() is None


def test_closing_clears_the_map_image_before_saying_no_atlas(session, tmp_path, monkeypatch):
    """The map image goes before the switch to "no atlas", as opening one does (a crop asked for in between was cut
    from the closed atlas's map: CodeRabbit)."""
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    assert session._tile_state[0] is not None  # (its map image tiled)
    seen = []
    real = session._switch

    def switch(*a):
        seen.append(session._tile_state[0])
        return real(*a)

    monkeypatch.setattr(session, "_switch", switch)
    session.close()
    assert seen == [None]


def test_a_settings_change_is_one_log_line():
    from grand_project.app.session import settings_change_text

    text = settings_change_text(
        {
            "style": {"path_freq": 0.35},
            "hidden_types": ["Breach", "Ritual"],
            "near_only": True,
            "layers": {"Paths": False},
        },
        {"Ritual", "Abyss"},
    )
    assert text == (
        "paths drawn by at least 35%, types shown: Abyss, types hidden: Breach, "
        "Find: only potential city maps on, Paths layer off"
    )


def test_drawn_by_at_least_makes_no_tile_again_and_paths_carry_their_share(session, tmp_path):
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    settled(session)  # (macOS CI: the search's model rebuild landed after v was read)
    v = session.filter_version
    session.set_ui_settings({"style": {"path_freq": 0.5}})  # (user: each step remade every tile and the 3D scene)
    assert session.filter_version == v
    shares = [p["share"] for _g, _pts2, p, _id in features(session, "paths")]
    assert shares and all(0 <= s <= 1 for s in shares)
    assert "Changed: paths drawn by at least 50%" in session.events.log_lines[-1]


def test_your_position_reads_in_words_in_the_log():
    from grand_project.app.session import settings_change_text

    assert settings_change_text({"ui": {"player": {"x": 1, "y": 2, "node": 12}}}, set()) == "your position map #12"
    assert settings_change_text({"ui": {"player": None}}, set()) == "your position forgotten"


def test_doubtful_saved_on_goes_off_now_that_it_has_no_button():
    from grand_project.app.session import AtlasSession

    s = AtlasSession(settings={"layers": {"Doubtful": True}}, worker=False)  # (brought up to date as they load)
    try:
        assert s.ui_settings()["layers"]["Doubtful"] is False
    finally:
        s.shutdown()


def test_a_hidden_map_style_saved_before_becomes_the_maps_switch_off():
    from grand_project.app.session import AtlasSession

    s = AtlasSession(settings={"style": {"map_style": "hidden"}}, worker=False)
    try:
        ui = s.ui_settings()
        assert ui["style"]["map_style"] == "circles" and ui["layers"]["Nodes"] is False
    finally:
        s.shutdown()


def test_clearing_a_city_biome_takes_back_the_cities_it_made_not_your_own_edits(session, tmp_path):
    # (GPT audit: clearing the biome left the Hall a City)
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    poly = [[1400, 1000], [1800, 1000], [1800, 1300], [1400, 1300]]
    n = session.V["nodes"][session.lasso_nodes(poly)[0]]
    with session._lock:  # (a Hall the detection found there)
        session.atlas.final["landmarks"].append(
            {"kind": "Hall", "x": n["x"], "y": n["y"], "status": "kept", "n": 3, "could": 3, "conf": 0.9}
        )
    session.rebuild_model()
    session.set_biome(poly, "Vaal city")
    made = [e for e in session.atlas.landmark_edits if e.get("by") == "biome"]
    assert made and made[0]["kind"] == "City"
    assert any(c.get("by") == "biome" and c["type"] == "Vaal" for c in session.atlas.city_types)
    session.set_biome(poly, "")
    assert not [e for e in session.atlas.landmark_edits if e.get("by") == "biome"]
    assert not [c for c in session.atlas.city_types if c.get("by") == "biome"]
    assert {"x": 480.0, "y": 360.0, "type": "Vaal"} in session.atlas.city_types  # the type set by hand stays


def test_undo_puts_back_all_but_your_hand_edits(session, tmp_path):
    # (GPT audit: Undo restored six fields; locked strongholds found in the screenshots it took away stayed)
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    snap = tmp_path / "before.json"
    session.atlas.save(snap)
    before_locks = list(session.atlas.locks)
    session.atlas.locks = [*before_locks, {"x": 1.0, "y": 2.0}]  # (found in the screenshots added)
    session.atlas.lock_scanned = [*session.atlas.lock_scanned, "added.png"]
    b = session.add_bookmark(100, 100, "made after the add")
    session._undo = [{"file": str(snap), "names": ["added.png"]}]
    session._run_undo()
    assert session.atlas.locks == before_locks and "added.png" not in session.atlas.lock_scanned
    assert any(x["uid"] == b for x in session.atlas.bookmarks)  # (yours: kept)


def test_a_map_with_a_landmark_on_it_can_make_it_a_normal_map(session, tmp_path):
    # (user: a click on a City selects its map, whose menu could only make it a landmark, never back)
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    k, v = next(iter(session.D["landmark_node"].items()))
    lm = session.info("node", v)["on_landmark"]
    assert lm["id"] == k and lm["landmark_kind"] == session.V["landmarks"][k]["kind"]
    session.set_landmark(lm["x"], lm["y"], "")  # (what its Normal map does)
    assert session.info("landmark", k)["removed"]
    assert "on_landmark" not in session.info("node", v)


def test_closing_answers_open_questions_no_and_asks_none(session):
    import threading

    session.events._listeners.append(__import__("queue").Queue())  # (a page open, so a question waits for its answer)
    got = []
    t = threading.Thread(target=lambda: got.append(session.events.ask("go on?")))
    t.start()
    for _ in range(200):
        if session.events.open_questions():
            break
        threading.Event().wait(0.01)
    assert session.events.end_questions() == 1
    t.join(2)
    assert got == [False]
    assert session.events.ask("again?") is False  # (none asked while closing)


def test_a_bookmark_made_on_a_landmark_is_its_maps_bookmark(session, tmp_path):
    # (self review: a landmark selects its map now, whose bookmark was only looked for at the map itself)
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    node = session.V["nodes"][3]
    session.set_landmark(node["x"] + 35, node["y"], "Tower", on="map")  # (beside its map, within reach)
    k = next(k for k, lm in enumerate(session.V["landmarks"]) if abs(lm["x"] - node["x"] - 35) < 1)
    assert session.D["landmark_node"][k] == 3
    b = session.add_bookmark(node["x"] + 35, node["y"], "my tower", "Towers")  # (made on the landmark)
    info = session.info("node", 3)
    assert info["bookmark"] == b  # (35 from the map: not its spot, but its landmark's)
    assert info["suggest"]["name"] == session.landmark_name(k)


def test_a_retired_setting_sent_by_an_older_page_is_brought_up_to_date(session):
    session.set_ui_settings({"layers": {"Doubtful": True}})
    assert session.settings["layers"]["Doubtful"] is False


def test_one_job_ending_forgets_only_its_own_logged_steps(session):
    ev = session.events
    ev.set_progress("detecting 5 / 10")
    ev.set_progress("building the map image", owner="map")
    ev.set_progress(None, owner="map")
    before = len(ev.log_lines)
    ev.set_progress("detecting 5 / 10")  # (the same step and tenth: not written again)
    assert len(ev.log_lines) == before


def test_a_city_biome_leaves_a_landmark_you_set_by_hand_alone(session, tmp_path):
    # (CodeRabbit: painting a city biome deleted your own edit there, and clearing it couldn't bring it back)
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    poly = [[1400, 1000], [1800, 1000], [1800, 1300], [1400, 1300]]
    n = session.V["nodes"][session.lasso_nodes(poly)[0]]
    session.set_landmark(n["x"], n["y"], "Hall", on="map")  # (yours)
    session.set_biome(poly, "Vaal city")
    mine = [e for e in session.atlas.landmark_edits if abs(e["x"] - n["x"]) < 1 and abs(e["y"] - n["y"]) < 1]
    assert [e["kind"] for e in mine] == ["Hall"] and not mine[0].get("by")
    session.set_biome(poly, "")
    assert any(e["kind"] == "Hall" and not e.get("by") for e in session.atlas.landmark_edits)


def test_two_landmarks_on_one_map_each_act_as_themselves(session, tmp_path):
    # (CodeRabbit: the City's map selection gave the Hall's actions when both stood on one map)
    path, _pts, _img = make_atlas(tmp_path)
    session.open_atlas(path)
    node = session.V["nodes"][3]
    with session._lock:
        for kind, dx in (("Hall", -20), ("City", 20)):
            session.atlas.final["landmarks"].append(
                {"kind": kind, "x": node["x"] + dx, "y": node["y"], "status": "kept", "n": 3, "could": 3, "conf": 0.9}
            )
    session.rebuild_model()
    ks = {session.V["landmarks"][k]["kind"]: k for k, v in session.D["landmark_node"].items() if v == 3}
    assert set(ks) == {"Hall", "City"}
    for kind, k in ks.items():
        assert session.info("landmark", k)["on_landmark"]["landmark_kind"] == kind


def test_a_city_you_set_by_hand_still_takes_the_biome_s_type(session, tmp_path):
    # (CodeRabbit: the guard for your own edit skipped the type too)
    path, _at = biome_atlas(tmp_path)
    session.open_atlas(path)
    poly = [[1400, 1000], [1800, 1000], [1800, 1300], [1400, 1300]]
    n = session.V["nodes"][session.lasso_nodes(poly)[0]]
    session.set_landmark(n["x"], n["y"], "City", on="map")  # (yours, no type set)
    session.set_biome(poly, "Vaal city")
    assert any(
        c.get("by") == "biome" and c["type"] == "Vaal" and abs(c["x"] - n["x"]) < 30 and abs(c["y"] - n["y"]) < 30
        for c in session.atlas.city_types
    )
    assert [e["kind"] for e in session.atlas.landmark_edits if abs(e["x"] - n["x"]) < 1] == ["City"]
