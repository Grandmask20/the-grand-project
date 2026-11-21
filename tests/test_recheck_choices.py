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
    assert every["stats"].pop("recheck_kept") == []
    assert same(every, new)
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
    t = threading.Thread(target=lambda: got.append(ev.ask_choices("Tick", {"groups": groups})))
    t.start()
    assert _wait(lambda: ev.open_questions())  # (no page open: it waits for one, unlike a yes / no question)
    q = ev.open_questions()[0]
    assert q["choices"]["groups"][0]["id"] == "maps"
    assert not ev.answer(q["id"], False)  # (no plain No: only its button answers it)
    assert not ev.answer(q["id"], True)  # (with no ticks sent)
    assert ev.answer(q["id"], True, picked=["maps", "nonsense", 3])
    t.join(5)
    assert got == [["maps"]]


def test_a_question_with_ticks_is_none_when_the_app_closes():
    ev = Events()
    got = []
    t = threading.Thread(target=lambda: got.append(ev.ask_choices("Tick", {"groups": []})))
    t.start()
    assert _wait(lambda: ev.open_questions())
    assert ev.end_questions() == 1
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
    old = {i: lab for i, (lab, _st) in cities.biomes(core.Atlas.load(path), _view(before, path))["potential"].items()}
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


def _view(final, path):
    from grand_project.app.model import view_model

    at = core.Atlas.load(path)
    at.final = final
    return view_model(at)


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
