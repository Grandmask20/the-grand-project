"""Re-check choices (you: "when re-check atlas finishes, it should prompt you what changed in groups, and you can tick
which things to update ... things that aren't ticked don't get updated from recheck and just use the pre-checked
choices linked to each map it was on beforehand"): the change list per group, the merge of the groups you take,
the biomes kept as they were, the box's answer and your ticks kept for every atlas."""

import copy
import json
import threading

import pytest

from grand_project import cities, core
from grand_project import finalize as atlas_finalize
from grand_project.app import constants as K
from grand_project.app import recheck_choices as rc
from grand_project.app.events import Events
from grand_project.app.session import AtlasSession
from tests.webmap_data import biome_atlas


def grid_final() -> dict:
    """A 4 x 3 grid of maps with paths, a tower, a Hall, an icon on map 5."""
    nodes = []
    for r in range(3):
        for c in range(4):
            nodes.append({"id": len(nodes), "x": c * 200.0, "y": r * 200.0, "status": "confirmed", "seen": 2,
                          "could": 2, "frames": ["a"], "tower": False, "origin": "detected", "icons": [],
                          "abyss": "", "why": ""})  # fmt: skip
    nodes[5]["icons"] = ["Breach"]
    nodes[9]["tower"] = True
    paths = [{"a": i, "b": i + 1, "frames": 2} for i in range(12) if i % 4 < 3]
    paths += [{"a": i, "b": i + 4, "frames": 2} for i in range(8)]
    landmarks = [
        {"kind": "Hall", "x": 400.0, "y": 0.0, "status": "kept"},
        {"kind": "Tower", "x": 200.0, "y": 400.0, "status": "kept"},
    ]
    icons = [{"name": "Breach", "x": 200.0, "y": 176.0, "bx": 200.0, "by": 200.0, "n": 2}]
    return {"nodes": nodes, "paths": paths, "landmarks": landmarks, "icons": icons, "stats": {}}


def changed_final(old: dict) -> dict:
    """The grid after a "re-check": map 3 gone (with its paths), map 5 moved 10 units (its icon with it), a new map,
    the Hall now a Deadly boss map, a new tower, path 0-1 gone, a new path 10-11 kept, an icon added on map 0."""
    new = copy.deepcopy(old)
    new["nodes"][3]["status"] = "removed"
    new["paths"] = [p for p in new["paths"] if 3 not in (p["a"], p["b"]) and (p["a"], p["b"]) != (0, 1)]
    new["nodes"][5]["x"] += 10
    new["icons"][0]["x"] += 10
    new["icons"][0]["bx"] += 10
    new["nodes"].append({**new["nodes"][0], "id": 12, "x": 900.0, "y": 0.0, "icons": []})
    new["paths"].append({"a": 11, "b": 12, "frames": 2})
    new["landmarks"][0]["kind"] = "Deadly boss map"
    new["landmarks"].append({"kind": "Tower", "x": 600.0, "y": 400.0, "status": "kept"})
    new["icons"].append({"name": "Ritual", "x": 0.0, "y": -24.0, "bx": 0.0, "by": 0.0, "n": 2})
    new["nodes"][0]["icons"] = ["Ritual"]
    new["stats"] = {"paths": len(new["paths"])}
    return new


def texts(ch: dict, group: str) -> list[str]:
    return [it["text"] for it in ch[group]["items"]]


def test_the_changes_are_listed_per_group_and_named():
    old = grid_final()
    new = changed_final(old)
    ch = rc.changes(old, new, {0: None, 1: "Vaal city"}, {0: "Vaal city", 1: "Vaal city"})
    assert set(ch) == set(rc.GROUPS)
    assert texts(ch, "maps") == ["Map #3 removed", "Map #5 moved 10 units", "New map"]
    assert "Path #0 – #1 removed" in texts(ch, "paths") and "Path #11 – a new map added" in texts(ch, "paths")
    assert texts(ch, "landmarks") == ["Hall → Deadly boss map"]
    assert texts(ch, "towers") == ["Tower added"]
    assert texts(ch, "biomes") == ["Map #0: no biome → Vaal city"]
    assert texts(ch, "icons") == ["Ritual added"]  # (the Breach icon moved with its map: the same icon)
    assert (ch["maps"]["added"], ch["maps"]["removed"], ch["maps"]["changed"]) == (1, 1, 1)
    assert ch["biomes"]["added"] == 1 and ch["landmarks"]["changed"] == 1
    item = ch["maps"]["items"][0]
    assert (item["x"], item["y"]) == (600.0, 0.0)  # (where it is, for the page's "show it on the map")


def test_nothing_changed_lists_nothing():
    old = grid_final()
    ch = rc.changes(old, copy.deepcopy(old), {}, {})
    assert all(g["count"] == 0 and not g["items"] for g in ch.values())


def test_only_the_first_changes_are_listed_but_all_are_counted(monkeypatch):
    monkeypatch.setattr(rc.K, "RECHECK_ITEMS_SHOWN", 2)
    old = grid_final()
    new = copy.deepcopy(old)
    new["paths"] = []
    ch = rc.changes(old, new, {}, {})
    assert ch["paths"]["count"] == len(old["paths"]) and len(ch["paths"]["items"]) == 2


def same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_every_group_ticked_is_the_new_result_and_none_ticked_the_old_one():
    old = grid_final()
    new = changed_final(old)
    every = rc.merge(old, new, set(rc.GROUPS))
    assert every["stats"]["recheck_kept"] == []
    for k in ("nodes", "paths", "landmarks", "icons"):
        assert same(every[k], new[k]), k
    assert every["stats"]["paths"] == len(new["paths"])  # (the accepted numbers, for the atlas card)
    none = rc.merge(old, new, set())
    for k in ("nodes", "paths", "landmarks", "icons"):
        assert same(none[k], old[k]), k


def test_unticked_groups_stay_on_the_maps_they_were_on():
    old = grid_final()
    new = changed_final(old)
    out = rc.merge(old, new, {"maps"})  # the new maps; everything else as it was
    alive = [i for i, n in enumerate(out["nodes"]) if n["status"] != "removed"]
    assert 3 not in alive and 12 in alive
    pairs = {(p["a"], p["b"]) for p in out["paths"]}
    assert (0, 1) in pairs  # an old path between two maps that are still there stays
    assert not any(3 in p for p in pairs)  # one to a map that's gone goes
    assert (11, 12) not in pairs  # the new path isn't taken
    assert out["nodes"][0]["icons"] == [] and out["nodes"][5]["icons"] == ["Breach"]
    assert out["nodes"][12]["icons"] == []  # (a new map had nothing before)
    assert [lm["kind"] for lm in out["landmarks"]] == ["Hall", "Tower"]
    assert [ic["name"] for ic in out["icons"]] == ["Breach"]
    assert out["icons"][0]["bx"] == 210.0  # (moved with its map)
    assert out["stats"]["recheck_kept"] == sorted(set(rc.GROUPS) - {"maps"})


def test_new_paths_and_landmarks_on_the_old_maps():
    old = grid_final()
    new = changed_final(old)
    out = rc.merge(old, new, {"paths", "landmarks", "towers", "icons"})  # the maps as they were
    assert out["nodes"][3]["status"] == "confirmed" and len(out["nodes"]) == len(old["nodes"])
    pairs = {(p["a"], p["b"]) for p in out["paths"]}
    assert (0, 1) not in pairs and (2, 3) not in pairs  # gone in the re-check
    assert (11, 12) not in pairs and all(max(p) < len(old["nodes"]) for p in pairs)  # (no map for its end)
    assert sorted(lm["kind"] for lm in out["landmarks"]) == ["Deadly boss map", "Tower", "Tower"]
    assert out["nodes"][0]["icons"] == ["Ritual"] and out["nodes"][5]["icons"] == ["Breach"]
    breach = next(ic for ic in out["icons"] if ic["name"] == "Breach")
    assert breach["bx"] == 200.0  # (on the old map's spot)


def test_a_tower_flag_follows_the_towers_group():
    old = grid_final()
    new = copy.deepcopy(old)
    new["nodes"][9]["tower"] = False
    ch = rc.changes(old, new, {}, {})
    assert texts(ch, "towers") == ["Map #9 no longer a tower's map"]
    assert rc.merge(old, new, {"maps"})["nodes"][9]["tower"] is True
    assert rc.merge(old, new, {"maps", "towers"})["nodes"][9]["tower"] is False


def test_kept_biomes_hold_the_old_ones_where_they_would_change():
    old = grid_final()
    merged = copy.deepcopy(old)
    merged["nodes"][1]["x"] += 4
    kept = rc.kept_biomes(merged, old, {0: "Vaal city", 1: None}, {0: "Vaal city", 1: "Faridun city"}, [])
    assert kept == [{"x": 204.0, "y": 0.0, "biome": "Faridun city"}]
    # one kept before at the same spot is replaced, others stay
    again = rc.kept_biomes(merged, old, {1: "Vaal city"}, {1: None}, [*kept, {"x": 999.0, "y": 0.0, "biome": ""}])
    assert again == [{"x": 999.0, "y": 0.0, "biome": ""}, {"x": 204.0, "y": 0.0, "biome": ""}]


def test_a_kept_biome_wins_over_the_worked_out_one_and_a_hand_drawn_one_over_both(tmp_path):
    path, _at = biome_atlas(tmp_path)
    at = core.Atlas.load(path)
    from grand_project.app.model import view_model

    V = view_model(at)
    before = cities.biomes(at, V)["potential"]
    city_map = next(i for i, (lab, _st) in before.items() if lab == "Vaal city")
    n = V["nodes"][city_map]
    at.biome_kept = [{"x": n["x"], "y": n["y"], "biome": ""}, {"x": 0.0, "y": 0.0, "biome": "Ezomyte city"}]
    after = cities.biomes(at, V)["potential"]
    assert city_map not in after  # kept as it was: no biome
    assert after[0][0] == "Faridun city"  # (your hand-drawn biome there stays on top)
    assert cities.biomes(at, V, kept=False)["potential"][city_map][0] == "Vaal city"


# ------------------------------------------------------------------ the box
def test_a_question_with_ticks_waits_for_a_page_and_takes_only_its_own_groups():
    ev = Events()
    got = []
    groups = [{"id": "maps", "name": "Maps", "count": 2, "items": [], "ticked": True}]
    t = threading.Thread(target=lambda: got.append(ev.ask_choices("Tick", {"groups": groups})), daemon=True)
    t.start()
    try:  # (a failed check before the answer would leave the question waiting, and pytest with it: CodeRabbit)
        assert _wait(lambda: ev.open_questions())  # (no page open: it waits for one, unlike a yes / no question)
        q = ev.open_questions()[0]
        assert q["choices"]["groups"][0]["id"] == "maps"
        assert not ev.answer(q["id"], False)  # (no plain No: only its button answers it)
        assert not ev.answer(q["id"], True)  # (with no ticks sent)
        assert ev.answer(q["id"], True, picked=["maps", "nonsense", 3])
    finally:
        t.join(5)
        ev.end_questions()
        t.join(5)
    assert got == [["maps"]]


def test_a_question_with_ticks_is_none_when_the_app_closes():
    ev = Events()
    got = []
    t = threading.Thread(target=lambda: got.append(ev.ask_choices("Tick", {"groups": []})), daemon=True)
    t.start()
    try:
        assert _wait(lambda: ev.open_questions())
        assert ev.end_questions() == 1
    finally:
        ev.end_questions()
        t.join(5)
    assert got == [None]
    assert ev.ask_choices("again?", {"groups": []}) is None  # (closing: none is asked any more)


def _wait(cond, timeout=5.0) -> bool:
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ the whole Re-check in the app
@pytest.fixture
def rechecked(tmp_path, monkeypatch):
    """A session on the biome atlas whose "re-check" removes map 0 and the second City; the box's answer is set by
    the test (session.picks)."""
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    path, _at = biome_atlas(tmp_path)
    s = AtlasSession(settings={}, worker=False)
    s.open_atlas(path)
    s.wait_idle(30)

    def fake_finalize(atlas, log=None):
        new = copy.deepcopy(atlas.final)
        new["nodes"][0]["status"] = "removed"
        new["landmarks"] = [lm for lm in new["landmarks"] if (lm["x"], lm["y"]) != (1580.0, 1160.0)]
        atlas.final = new

    monkeypatch.setattr(atlas_finalize, "finalize", fake_finalize)
    monkeypatch.setattr(type(s.atlas), "rebuild_icons", lambda self, frames: None)
    asked = []

    def answer(question, choices, labels=None):
        asked.append(choices)
        return s.picks

    monkeypatch.setattr(s.events, "ask_choices", answer)
    s.asked = asked
    yield s, path
    s.shutdown()


def test_the_recheck_asks_and_keeps_what_you_left_unticked(rechecked):
    s, path = rechecked
    before = copy.deepcopy(s.atlas.final)
    # the biomes before, taken now: read after the re-check, its kept biomes would shape both sides (CodeRabbit)
    old = {i: lab for i, (lab, _st) in s.D["potential"].items()}
    s.picks = ["maps", "paths", "landmarks"]  # the City goes; its biome stays as it was
    s._run_recheck()
    groups = {g["id"]: g for g in s.asked[0]["groups"]}
    assert groups["maps"]["count"] == 1 and groups["landmarks"]["count"] == 1 and groups["biomes"]["count"] > 0
    assert all(g["ticked"] == (g["count"] > 0) for g in groups.values())  # (first time: everything that changed)
    assert groups["paths"]["count"] == 2  # (the paths of the map that went)
    assert groups["towers"]["count"] == 0 and not groups["towers"]["ticked"]  # (no changes: nothing to tick)
    saved = core.Atlas.load(path)
    assert saved.final["nodes"][0]["status"] == "removed"
    assert len(saved.final["landmarks"]) == len(before["landmarks"]) - 1
    assert saved.biome_kept  # the biomes it would have changed are held as they were
    s.rebuild_model()
    shown = {i: lab for i, (lab, _st) in s.D["potential"].items()}
    assert {i: v for i, v in shown.items() if i != 0} == {i: v for i, v in old.items() if i != 0}
    # your ticks are kept for every atlas, the next box starts with them
    assert s.ui_settings()["recheck_update"] == {g: g != "biomes" for g in rc.GROUPS}


def test_kept_landmarks_keep_their_biome_with_nothing_held(rechecked):
    s, path = rechecked
    before = copy.deepcopy(s.atlas.final)
    s.picks = ["maps", "paths"]  # the City stays, so its biome does too
    s._run_recheck()
    saved = core.Atlas.load(path)
    assert len(saved.final["landmarks"]) == len(before["landmarks"]) and saved.biome_kept == []
    assert s.ui_settings()["recheck_update"]["landmarks"] is False


def test_the_recheck_with_everything_ticked_takes_it_all(rechecked):
    s, path = rechecked
    s.atlas.biome_kept = [{"x": 0.0, "y": 200.0, "biome": "Vaal city"}]  # (held by an earlier re-check)
    s.picks = list(rc.GROUPS)
    s._run_recheck()
    saved = core.Atlas.load(path)
    assert len(saved.final["landmarks"]) == 3 and saved.biome_kept == []


def test_nothing_is_changed_when_the_app_closes_before_you_choose(rechecked):
    s, path = rechecked
    before = copy.deepcopy(core.Atlas.load(path).final)
    s.picks = None
    s._run_recheck()
    assert same(s.atlas.final, before) and same(core.Atlas.load(path).final, before)
    assert "Re-check not applied" in s.events.status


def test_no_box_when_nothing_changed(rechecked, monkeypatch):
    s, _path = rechecked
    monkeypatch.setattr(atlas_finalize, "finalize", lambda atlas, log=None: None)
    s.picks = []
    s._run_recheck()
    assert not s.asked and s.events.status.endswith("nothing changed")


# ------------------------------------------------------------------ Re-check from an atlas's card
def test_recheck_from_a_card_opens_that_atlas_and_queues_its_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _at = biome_atlas(tmp_path / "a")
    b, _at = biome_atlas(tmp_path / "b")
    s = AtlasSession(settings={}, worker=False)
    try:
        s.open_atlas(a)
        s.wait_idle(30)
        while not s._jobs.empty():  # (auto-add's catch-up, if any)
            s._jobs.get_nowait()
            s._jobs.task_done()
        s.recheck_atlas(b)  # (its route belongs to no atlas, like Open: GEN_FREE)
        assert s.path == b
        paths, mode, gen = s._jobs.get_nowait()
        assert mode == "recheck_all" and gen == s.generation  # (for B, not the A the page saw: not skipped)
        s._jobs.task_done()
        s.recheck_atlas(b)  # the open one: no switch
        assert s._jobs.get_nowait()[2] == s.generation
        s._jobs.task_done()
        s._jobs.put(([], "recheck_all", s.generation))  # work running: another atlas isn't opened
        with pytest.raises(ValueError):
            s.recheck_atlas(a)
        assert s.path == b
    finally:
        s._jobs = type(s._jobs)()
        s.shutdown()


# ------------------------------------------------------------------ what the Re-check prompt says
def _cache(folder, sha: str, models: str, version=None, when=None) -> None:
    from grand_project import builder

    head = {"name": "x", "path": "x", "sha256": sha, "detector": builder.NEW_DETECTOR_ID, "models": models}
    if version is not None:
        head["version"] = version
    if when is not None:
        head["detected_at"] = when
    (folder / f"{sha[:16]}_{builder.NEW_DETECTOR_ID}.json").write_text(json.dumps({**head, "nodes": []}))


def test_the_prompt_groups_screenshots_by_version_and_counts_what_is_detected_again(tmp_path, monkeypatch):
    from grand_project import builder

    monkeypatch.setattr(cities, "find_locks", lambda atlas, todo: [])
    monkeypatch.setattr(builder, "detector_stamp", lambda: "now")
    path, _at = biome_atlas(tmp_path)
    at = core.Atlas.load(path)
    frames_dir = path.with_name(path.stem + "_frames")
    frames_dir.mkdir(exist_ok=True)
    at.frames = []
    for k in range(5):
        shot = tmp_path / f"s{k}.png"
        if k != 4:
            shot.write_bytes(b"png")  # (s4's file is gone)
        at.frames.append({"name": f"s{k}", "path": str(shot), "sha": str(k) * 64, "w": 1920, "h": 1080,
                          "M": [[1, 0, 0], [0, 1, 0]], "stats": {}})  # fmt: skip
    _cache(frames_dir, "0" * 64, "now", "1.23", 2000.0)
    _cache(frames_dir, "1" * 64, "now", "1.23", 3000.0)
    _cache(frames_dir, "2" * 64, "old")  # (before versions were kept: the file's time)
    # s3 has no detection; s4's file is gone and its detection old
    _cache(frames_dir, "4" * 64, "old")
    at.last_check = {"time": 1234.0, "version": "1.23"}
    at.save(path)
    s = AtlasSession(settings={}, worker=False)
    try:
        info = s.recheck_info(path)  # (not open: read from its file)
        assert info["last_check"] == {"time": 1234.0, "version": "1.23"}
        assert (info["shots"], info["detect"], info["missing"]) == (5, 2, 1)  # s2 (old) and s3 (none); s4 gone
        new, old = info["groups"] if info["groups"][0]["version"] == "1.23" else info["groups"][::-1]
        assert new == {"version": "1.23", "fresh": True, "count": 2, "newest": 3000.0, "oldest": 2000.0}
        assert old["version"] is None and not old["fresh"] and old["count"] == 2
        assert info["estimate_s"] == round(2 * K.RECHECK_DETECT_S + 5 * K.RECHECK_CLEAN_S)
        s.settings["recheck_timing"] = {"detect_s": 10.0, "clean_s": 1.0}  # (measured here before)
        assert s.recheck_info(path)["estimate_s"] == 25
        s.open_atlas(path)
        assert s.recheck_info()["shots"] == 5  # (the open one)
    finally:
        s.shutdown()


def test_a_recheck_records_when_and_how_long(rechecked):
    s, path = rechecked
    s.picks = list(rc.GROUPS)
    s._run_recheck()
    saved = core.Atlas.load(path)
    assert saved.last_check["version"] == K.VERSION and saved.last_check["time"] > 0
    s._note_timing(10, 25.0, 100, 40.0)
    assert s.settings["recheck_timing"] == {"detect_s": 2.5, "clean_s": 0.4}
    s._note_timing(1, 99.0, 2, 99.0)  # (too few to measure: kept as it was)
    assert s.settings["recheck_timing"] == {"detect_s": 2.5, "clean_s": 0.4}


def test_new_detections_say_their_version_and_time(tmp_path):
    from grand_project import builder

    _cache(tmp_path, "ab" * 32, builder.detector_stamp(), "1.23", 5000.0)
    assert builder.cache_head(tmp_path, "ab" * 32) == {"fresh": True, "version": "1.23", "time": 5000.0}
    assert builder.cache_head(tmp_path, "cd" * 32) is None


def test_the_recheck_is_not_applied_once_another_atlas_is_open(rechecked, monkeypatch):
    s, path = rechecked
    before = copy.deepcopy(core.Atlas.load(path).final)

    def answer_after_a_switch(question, choices, labels=None):
        s.opened = type(s.opened)(core.Atlas(), path.with_name("other.json"), s.opened.gen + 1, "")
        return list(rc.GROUPS)

    monkeypatch.setattr(s.events, "ask_choices", answer_after_a_switch)
    s._run_recheck()
    assert same(core.Atlas.load(path).final, before)  # (nothing written into the file of the atlas asked about)
    assert "another atlas was opened" in s.events.status


# ------------------------------------------------------------------ CodeRabbit round 1
def test_as_many_maps_as_can_be_are_paired():
    old = {"nodes": [{"x": 0.0, "y": 0.0, "status": "confirmed"}, {"x": 25.0, "y": 0.0, "status": "confirmed"}]}
    new = {"nodes": [{"x": -11.0, "y": 0.0, "status": "confirmed"}, {"x": 9.0, "y": 0.0, "status": "confirmed"}]}
    assert rc.match_maps(old, new) == {0: 0, 1: 1}  # (nearest-first gave 0 -> 9 and left 25 alone)


def test_a_kept_path_line_moves_with_its_maps():
    old = grid_final()
    old["paths"][0]["line"] = [[0.0, 0.0], [100.0, 10.0], [200.0, 0.0]]  # (path 0 - 1)
    new = copy.deepcopy(old)
    new["nodes"][1]["x"] += 10  # (map 1 moved 10)
    out = rc.merge(old, new, {"maps"})  # (new maps, old paths)
    line = next(p for p in out["paths"] if (p["a"], p["b"]) == (0, 1))["line"]
    assert line[0] == [0.0, 0.0] and line[-1] == [210.0, 0.0] and line[1] == [105.0, 10.0]


def test_a_kept_biome_replaces_only_its_own_maps_earlier_one():
    old = grid_final()
    merged = copy.deepcopy(old)
    already = [{"x": 200.0, "y": 0.0, "biome": "Vaal city"}]  # (map 1's, 200 from map 0... and 15 from nothing else)
    already.append({"x": 15.0, "y": 0.0, "biome": "Faridun city"})  # (map 0's: 15 from it)
    kept = rc.kept_biomes(merged, old, {0: None, 1: "Vaal city"}, {0: "Ezomyte city", 1: "Vaal city"}, already)
    assert {"x": 200.0, "y": 0.0, "biome": "Vaal city"} in kept  # (map 1's choice stays)
    assert {"x": 0.0, "y": 0.0, "biome": "Ezomyte city"} in kept and len(kept) == 2  # (map 0's replaced)


def test_a_path_of_another_kind_between_the_same_maps_is_listed():
    old = grid_final()
    new = copy.deepcopy(old)
    new["paths"][0] = {**new["paths"][0], "kind": "abyss", "abyss": True}
    assert texts(rc.changes(old, new, {}, {}), "paths") == ["Path #0 – #1 changed"]
    assert rc.changes(old, copy.deepcopy(old), {}, {})["paths"]["count"] == 0


def test_nothing_of_the_recheck_lands_in_the_atlas_before_you_apply(rechecked, monkeypatch):
    s, path = rechecked
    before = copy.deepcopy(core.Atlas.load(path).final)
    old_icons = s.atlas.icons
    monkeypatch.setattr(type(s.atlas), "rebuild_icons", lambda self, frames: setattr(self, "icons", [{"name": "x"}]))

    def answer_after_a_save(question, choices, labels=None):
        s.atlas.save(path)  # (a bookmark or an edit saves while the box is open)
        assert same(core.Atlas.load(path).final, before) and s.atlas.icons is old_icons
        return ["maps"]  # (icons left unticked)

    monkeypatch.setattr(s.events, "ask_choices", answer_after_a_save)
    s._run_recheck()
    assert s.atlas.icons is old_icons  # (the re-check's icon list only when Icons is ticked)
