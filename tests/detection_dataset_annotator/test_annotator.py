"""The detection dataset annotator (tools/detection_dataset_annotator): editor boxes map back to saved annotations,
the labels, discovery, export, and screenshots stay untouched (the review store has ``test_store.py``)."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from grand_project import cities, core
from grand_project.detect import constants as detect_constants
from grand_project.detect.icon_types import dataset_icon_types, icon_class
from grand_project.detect.labels import annotator_labels, dataset_classes
from tools.detection_dataset_annotator import (
    DetectionOptions,
    ReviewStore,
    apply_editor_boxes,
    copies,
    decode_image,
    detection_annotations,
    discover_images,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    ensure_annotation_ids,
    file_hash,
    image_key,
    label_names,
    label_palette,
    neighbour_key,
    relative_source,
    resolve_input_paths,
)
from tools.detection_dataset_annotator import constants as K
from tools.detection_dataset_annotator import state as state_module
from tools.detection_dataset_annotator.export import export_dataset
from tools.detection_dataset_annotator.split_ledger import read_ledger
from tools.detection_dataset_annotator.state import discovery_order


def test_editor_edits_map_back_by_stable_id() -> None:
    """Unchanged boxes keep detector data; changed ones become manual; new boxes get ids; reordering is safe."""
    item = {
        "annotations": [
            {"label": "map_node", "bbox": [100, 100, 48, 48], "area": 2304, "iscrowd": 0, "source": "classical",
             "score": 0.9},
            {"label": "city", "bbox": [300, 300, 60, 70], "area": 4200, "iscrowd": 0, "source": "classical",
             "score": 0.8},
            {"label": "icon", "bbox": [500, 500, 34, 34], "area": 1156, "iscrowd": 0, "source": "classical",
             "score": 0.7},
            {"label": "tower", "bbox": [700, 600, 40, 90], "area": 3600, "iscrowd": 0, "source": "classical"},
        ]
    }  # fmt: skip
    assert ensure_annotation_ids(item)
    assert not ensure_annotation_ids(item)
    ids = [annotation["id"] for annotation in item["annotations"]]
    assert len(set(ids)) == 4

    boxes = editor_boxes(item["annotations"])
    assert apply_editor_boxes(item["annotations"], boxes, width=1000, height=800) == item["annotations"]

    boxes[0]["x"] += 10  # moved
    boxes[1]["label"] = "hall"  # relabelled
    del boxes[2]  # deleted
    boxes[2]["x"] += 0.3  # within tolerance: still the detector's box
    boxes.reverse()  # order must not matter
    boxes.append({"id": "new-1", "label": "icon", "x": 990, "y": -5, "w": 40, "h": 20})  # clipped
    boxes.append({"id": "new-2", "label": "icon", "x": 10, "y": 10, "w": 0.5, "h": 20})  # under 1 px
    boxes.append({"id": "", "label": "", "x": 10, "y": 10, "w": 20, "h": 20})  # no label

    applied = apply_editor_boxes(item["annotations"], boxes, width=1000, height=800)
    edited = {annotation.get("id", "new"): annotation for annotation in applied}
    moved, relabelled, tower = edited[ids[0]], edited[ids[1]], edited[ids[3]]
    assert moved == {
        "id": ids[0],
        "label": "map_node",
        "bbox": [110.0, 100.0, 48.0, 48.0],
        "area": 2304.0,
        "iscrowd": 0,
        "source": "manual",
    }
    assert relabelled["label"] == "hall" and relabelled["source"] == "manual" and "score" not in relabelled
    assert tower == item["annotations"][3]
    assert ids[2] not in edited
    assert edited["new-1"]["bbox"] == [990.0, 0.0, 10.0, 15.0] and edited["new-1"]["source"] == "manual"
    assert len(edited) == 4

    # After an autosave the saved list is in the editor's order; the same boxes still map back correctly.
    item["annotations"] = list(edited.values())
    assert not ensure_annotation_ids(item)  # the new box kept the editor's id
    assert len({annotation["id"] for annotation in item["annotations"]}) == 4
    again = apply_editor_boxes(item["annotations"], editor_boxes(item["annotations"]), width=1000, height=800)
    assert again == item["annotations"]


def test_undo_after_a_saved_delete_restores_the_detector_box() -> None:
    """The editor's Ctrl+Z can bring back a box whose delete was already autosaved; it must keep score and id."""
    shown = [
        {"id": "b0", "label": "map_node", "bbox": [10, 10, 48, 48], "area": 2304, "iscrowd": 0,
         "source": "classical", "score": 0.9},
        {"id": "b1", "label": "icon", "bbox": [90, 90, 34, 34], "area": 1156, "iscrowd": 0,
         "source": "classical", "score": 0.7},
    ]  # fmt: skip
    boxes = editor_boxes(shown)
    saved = apply_editor_boxes(shown, boxes[1:], width=500, height=500, known=shown)  # delete autosaved
    assert [a["id"] for a in saved] == ["b1"]
    restored = apply_editor_boxes(saved, boxes, width=500, height=500, known=shown)  # undo
    assert restored == shown
    new_box = {"id": "new-abc-1", "label": "tower", "x": 200, "y": 200, "w": 30, "h": 60}
    again = apply_editor_boxes(restored, [*boxes, new_box], width=500, height=500, known=shown)
    assert again[-1]["id"] == "new-abc-1" and again[-1]["source"] == "manual"
    assert apply_editor_boxes(again, [*boxes, new_box], width=500, height=500, known=shown) == again


def test_duplicate_ids_are_reassigned_and_new_ids_never_reused() -> None:
    item = {"annotations": [{"id": "b0", "bbox": [0, 0, 5, 5]}, {"id": "b0", "bbox": [9, 9, 5, 5]}, {}]}
    assert ensure_annotation_ids(item)
    assert [a["id"] for a in item["annotations"]] == ["b0", "b1", "b2"]
    item["annotations"].pop()
    item["annotations"].append({"bbox": [1, 1, 5, 5]})
    ensure_annotation_ids(item)
    assert item["annotations"][-1]["id"] == "b3"


def test_stale_editor_messages_and_queue_neighbours() -> None:
    payload = {"image_key": "a", "revision": 2, "boxes": []}
    assert editor_payload_matches(payload, "a", 2)
    assert not editor_payload_matches(payload, "b", 2)  # from the previous screenshot
    assert not editor_payload_matches(payload, "a", 3)  # from before a detector rerun
    assert not editor_payload_matches({"image_key": "a", "revision": 2}, "a", 2)
    assert not editor_payload_matches(None, "a", 2)

    keys = ["a", "b", "c"]
    assert neighbour_key(keys, "b", 1) == "c"
    assert neighbour_key(keys, "b", -1) == "a"
    assert neighbour_key(keys, "c", 1) is None
    assert neighbour_key(keys, "a", -1) is None
    assert neighbour_key(keys, "gone", 1) == "a"
    assert neighbour_key([], "a", 1) is None


def test_label_palette_has_colours_rules_and_registry_keys() -> None:
    """Keys come from the registry: 1-8 the node classes, 9 hall, 0 tower, Shift+digits the rest; icon types and
    custom labels get a hashed colour and no key; every registry label carries its box rule."""
    labels = list(detect_constants.RF_DETR_LABEL_INFO)  # every registry label, the icon class too
    palette = {entry["name"]: entry for entry in label_palette([*labels, "icon_map_boss", "custom"])}
    keys = {name: (entry["hotkey"], entry["code"], entry["shift"]) for name, entry in palette.items()}
    assert keys["map_node"] == ("1", "Digit1", False)
    assert keys["map_node_faridun"] == ("8", "Digit8", False)
    assert keys["hall"] == ("9", "Digit9", False) and keys["tower"] == ("0", "Digit0", False)
    assert keys["citadel_iron"] == ("⇧1", "Digit1", True)
    assert keys["custom"] == ("", "", False) and keys["icon_map_boss"][0] == ""
    pressed = [(code, shift) for _key, code, shift in keys.values() if code]
    assert len(pressed) == len(set(pressed))  # one label per key
    colours = [palette[name]["color"] for name in labels]
    assert all(colour.startswith("#") and len(colour) == 7 for colour in colours)
    assert len(set(colours)) == len(colours)
    assert all(palette[name]["rule"] for name in labels)
    assert label_palette(["custom"])[0]["color"] == palette["custom"]["color"]  # stable


def test_citadels_are_labelled_by_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """User: a city's own map is labelled by its citadel (Iron = Ezomyte, Stone = Vaal, Copper = Faridun). A city
    that already has a type keeps it; the others are typed by look, an unsure look (small margin, or a window cut
    off by the screenshot edge) is flagged ``city_guess``, and two cities closer than TRIO_GAP never share a type."""
    # A: clearly Vaal. B, next to A: looks Vaal too, less clearly, so it takes the best type left (Ezomyte, unsure).
    # E: clearly Faridun, but its window is cut off by the screenshot's corner (unsure).
    looks = iter([[0.50, 0.30, 0.60], [0.60, 0.45, 0.62], [0.70, 0.70, 0.20]])
    monkeypatch.setattr(cities, "look_distances", lambda feats: next(looks))
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    detection = {
        "landmarks": [
            {"kind": "City", "x": 600, "y": 500},
            {"kind": "City", "x": 900, "y": 500},
            {"kind": "City", "x": 1700, "y": 500, "city_type": "Faridun"},  # beyond TRIO_GAP of B: rules out nothing
            {"kind": "Hall", "x": 1200, "y": 900},
            {"kind": "City", "x": 50, "y": 50},
        ]
    }
    found = [(a["label"], a["source"]) for a in detection_annotations(detection, image, image)]
    assert found == [
        ("citadel_stone", K.ANNOTATOR_CLASSICAL_SOURCE),
        ("citadel_iron", K.ANNOTATOR_CITY_GUESS_SOURCE),
        ("citadel_copper", K.ANNOTATOR_CLASSICAL_SOURCE),
        ("hall", K.ANNOTATOR_CLASSICAL_SOURCE),
        ("citadel_copper", K.ANNOTATOR_CITY_GUESS_SOURCE),
    ]
    assert {label for label, _source in found} <= set(dataset_classes())


@pytest.mark.data
def test_sure_city_types_are_right(test_data: Path) -> None:
    """On the hand-typed cities of the truth screenshots, a city type the annotator does not flag as a guess is
    right (unsure guesses may be wrong: the reviewer checks them)."""
    truth = json.loads((test_data / "truth" / "truth.json").read_text(encoding="utf-8"))
    checked = 0
    for name, labels in truth.items():
        typed = [lm for lm in labels.get("landmarks", []) if lm.get("kind") == "City" and lm.get("city_type")]
        if not typed:
            continue
        image = core.read_screenshot(test_data / "screenshots" / "random_samples" / name)
        guesses = cities.screenshot_city_types(image, [(lm["x"], lm["y"]) for lm in typed])
        for landmark, (city_type, sure) in zip(typed, guesses, strict=True):
            assert city_type in cities.TYPES
            assert not sure or city_type == landmark["city_type"], (name, landmark, city_type)
            checked += 1
    assert checked


def test_label_names_offer_only_the_datasets_labels() -> None:
    """User: with icons not named by type the list has one ``icon`` label, and labels the dataset no longer has
    (``deadly_boss_map``, the old ``city_<type>``, ``path``) are never offered, even while old boxes still use them."""
    used = ["deadly_boss_map", "city_vaal", "path", "icon_breachhive", "icon_unidentified", "map_node", "", "custom"]
    plain = label_names(used, named_icons=False)
    assert plain == annotator_labels(named_icons=False)
    assert plain[:2] == ["map_node", "map_node_grass"]
    assert [label for label in plain if label.startswith("icon")] == ["icon"]
    assert not {"deadly_boss_map", "city_vaal", "path", "custom", "icon_unidentified"} & set(plain)
    named = label_names(used, named_icons=True)
    assert "icon" not in named and "path" not in named and "icon_breachhive" in named
    assert named[-1] == "icon_unidentified"  # still to be named
    assert not {"deadly_boss_map", "city_vaal", "custom"} & set(named)


def test_named_icons_list_every_icon_type() -> None:
    """User: every map content icon can be labelled, whether or not the classical detector named one yet; the icon
    types come in ICON_INFO order after the core labels, so an export numbers them the same every time."""
    used = ["icon_unidentified", "icon_breachhive"]
    icons = [icon_class(name) for name in dataset_icon_types()]
    assert {"icon_breachhive", "icon_wisdomsteachings", "icon_arcanehordes", "icon_hideoutred"} <= set(icons)
    structural = [label for label in annotator_labels(named_icons=True) if label not in icons]
    assert label_names(used, named_icons=True) == [*structural, *icons, "icon_unidentified"]
    assert label_names([], named_icons=True) == [*structural, *icons]  # nothing labelled yet


def test_label_palette_shows_icon_pictures_and_names() -> None:
    """Each icon label carries its icon's picture and poe2db name (the editor shows them next to the label)."""
    names = ["map_node", "citadel_stone", "icon_breachhive", "icon_unidentified", "x"]
    palette = {e["name"]: e for e in label_palette(names)}
    breach = palette["icon_breachhive"]
    assert breach["picture"].startswith("data:image/webp;base64,")
    picture = Image.open(io.BytesIO(base64.b64decode(breach["picture"].split(",", 1)[1])))  # OpenCV drops alpha
    assert picture.mode == "RGBA" and picture.size == (K.ANNOTATOR_LABEL_PICTURE_PX,) * 2
    assert picture.getchannel("A").getextrema() == (0, 255)  # a disc on a transparent square
    assert breach["title"] == "Breach Hive"
    assert "breach hive" in breach["search"] and "icon_breachhive" in breach["search"]
    assert palette["map_node"]["picture"]  # the registry's picture
    assert palette["citadel_stone"]["title"] == "Stone Citadel: a Vaal city's own map"
    assert palette["citadel_stone"]["picture"] == palette["x"]["picture"] == palette["x"]["title"] == ""
    assert palette["icon_unidentified"]["picture"] == ""  # no art and no stored picture: only its colour


def test_icons_are_named_only_with_named_icons_and_paths_are_no_boxes() -> None:
    """Named icon labels with the option, else ``icon``; a traced path gives no box (paths are the classical
    tracer's, not a dataset label)."""
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    detection = {"edges": [{"line": [[10, 20], [90, 30]]}], "icons": [{"x": 50, "y": 50, "name": "Map Boss"}]}

    def labels(options: DetectionOptions) -> list[str]:
        return [annotation["label"] for annotation in detection_annotations(detection, image, image, options)]

    assert labels(DetectionOptions(named_icons=True)) == ["icon_map_boss"]
    assert labels(DetectionOptions()) == ["icon"]


def test_detection_options_round_trip() -> None:
    options = DetectionOptions(named_icons=True)
    assert DetectionOptions.from_settings(options.as_settings()) == options
    assert DetectionOptions.from_settings({}) == DetectionOptions()
    # a store's settings from before the path and wall options keep only what is an option now
    assert DetectionOptions.from_settings({"include_paths": True, "named_icons": True}) == options


def test_discovery_finds_images_once(tmp_path: Path) -> None:
    """Discovery finds images recursively, without duplicates, under folders and single-file roots."""
    (tmp_path / "shots" / "deep").mkdir(parents=True)
    for name in ("shots/a.png", "shots/deep/b.JPG", "shots/notes.txt"):
        (tmp_path / name).write_bytes(name.encode())
    roots = resolve_input_paths([str(tmp_path / "shots"), "  ", str(tmp_path / "shots" / "a.png")])
    found = discover_images(roots)
    assert [path.name for path in found] == ["a.png", "b.JPG"]


def test_discovery_keeps_one_of_identical_files(tmp_path: Path) -> None:
    """The 115 screenshots/crawl files were fr-atlas's own, found twice: a copy is left out wherever it lies (the
    first in discovery order stays); a file of the same size with other bytes is no copy."""
    for name, data in (
        ("fr-atlas/shot.png", b"same"),
        ("screenshots/crawl/shot.png", b"same"),
        ("screenshots/other.png", b"diff"),
        ("screenshots/big.png", b"bigger"),
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    found = discover_images([tmp_path / "screenshots", tmp_path / "fr-atlas"])
    assert [path.relative_to(tmp_path).as_posix() for path in found] == [
        "fr-atlas/shot.png",
        "screenshots/big.png",
        "screenshots/other.png",
    ]


def test_copies_name_the_first_file_with_the_same_bytes(tmp_path: Path) -> None:
    """The build script removes the copies discovery leaves out: the same file must stay (discovery order), or the
    next discovery would add the removed one back."""
    files = {name: tmp_path / name for name in ("B.png", "a.png", "c.png", "d.png")}
    for name, data in (("B.png", b"same"), ("a.png", b"same"), ("c.png", b"same"), ("d.png", b"diff")):
        files[name].write_bytes(data)
    ordered = discovery_order(files.values())
    assert [path.name for path in ordered] == ["a.png", "B.png", "c.png", "d.png"]
    # names only the case tells apart keep one order, however they were found
    twins = [tmp_path / "x" / "Shot.png", tmp_path / "x" / "shot.png"]
    assert discovery_order(twins) == discovery_order(twins[::-1]) == twins
    assert copies(ordered) == {files["B.png"]: files["a.png"], files["c.png"]: files["a.png"]}
    assert file_hash(files["a.png"]) == hashlib.sha256(b"same").hexdigest()
    # a pinned test screenshot is the one kept, wherever it comes in the order (else it would lose its test split)
    pinned = {files["c.png"]}
    assert copies(ordered, prefer=pinned.__contains__) == {
        files["a.png"]: files["c.png"],
        files["B.png"]: files["c.png"],
    }


def test_editor_never_changes_the_screenshot(tmp_path: Path, review_store: ReviewStore) -> None:
    """Issue: boxes looked baked into the screenshot. The editor's copy and the file itself stay clean."""
    shot = tmp_path / "shot.png"
    rows, columns = np.mgrid[0:360, 0:640]
    image = np.dstack([columns * 255 // 640, rows * 255 // 360, (rows + columns) * 255 // 1000]).astype(np.uint8)
    cv2.circle(image, (100, 100), 20, (40, 200, 240), -1)  # a few smooth "map nodes"
    cv2.circle(image, (300, 200), 15, (240, 90, 60), -1)
    cv2.imwrite(str(shot), image)
    before = hashlib.sha256(shot.read_bytes()).hexdigest()

    url = editor_image_url(shot)
    assert url is not None and url.startswith("data:image/jpeg;base64,")
    shown = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
    assert shown.shape == image.shape
    difference = np.abs(shown.astype(int) - image.astype(int))
    assert difference.mean() < 2 and np.percentile(difference, 99.9) < 40, (difference.mean(),)

    review_store.add_images([shot])
    key = image_key(shot)
    detection = {"nodes": [{"x": 100, "y": 100, "score": 0.9}], "icons": [{"x": 300, "y": 200}]}
    annotations = detection_annotations(detection, image, image)
    detected = {"width": 640, "height": 360, "annotations": annotations, K.ANNOTATOR_DETECTED_SHA: file_hash(shot)}
    review_store.record_detection(key, detected, force=False)
    item = review_store.item(key)
    boxes = editor_boxes(item["annotations"])
    boxes[0]["x"] += 5
    edited = apply_editor_boxes(item["annotations"], boxes, width=640, height=360)
    assert review_store.save_review(key, item["edit_version"], annotations=edited, reviewed=True)
    result = export_dataset(review_store, tmp_path / "export")
    assert result.images == 1 and result.annotations == 2
    assert hashlib.sha256(shot.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in (tmp_path / "export").iterdir()) == ["manifest.json"]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == K.ANNOTATOR_MANIFEST_FORMAT
    assert manifest["images"][0]["source_type"] == "annotator_reviewed"

    assert manifest["images"][0]["split"] in K.ANNOTATOR_SPLITS

    # named icons are exported as the detector finds them: one `icon` class, named from the stored pictures
    review_store.set_settings(DetectionOptions(named_icons=True))
    edited[1]["label"] = "icon_breachhive"
    assert review_store.save_review(key, item["edit_version"], annotations=edited)
    named = export_dataset(review_store, tmp_path / "named")
    exported = json.loads(named.manifest_path.read_text(encoding="utf-8"))
    assert list(exported["labels"].values()) == dataset_classes()
    assert [a["label"] for a in exported["images"][0]["annotations"]][1] == "icon"


def test_unreadable_images_decode_to_none(tmp_path: Path) -> None:
    empty, junk = tmp_path / "empty.png", tmp_path / "junk.png"
    empty.write_bytes(b"")
    junk.write_bytes(b"not a picture")
    assert decode_image(empty) is None
    assert decode_image(junk) is None
    assert decode_image(tmp_path / "missing.png") is None


def _export_store(tmp_path: Path, store: ReviewStore) -> dict[str, str]:
    """Four screenshots in the store, the detected ones with their size saved, under one discovery root and outside
    it; return name -> image key."""
    root, other = tmp_path / "shots", tmp_path / "elsewhere"
    for folder in (root / "atlas1", other):
        folder.mkdir(parents=True)
    paths = {
        "done": root / "atlas1" / "done.png",
        "reviewed_empty": root / "atlas1" / "empty.png",
        "never_detected": root / "atlas1" / "new.png",
        "outside": other / "outside.png",
    }
    for path in paths.values():
        path.write_bytes(b"x")
    store.set_input_roots([root])
    store.add_images(paths.values())
    keys = {name: image_key(path) for name, path in paths.items()}
    box = {"label": "icon", "bbox": [10, 20, 34, 34], "source": "classical"}
    detected = {
        "done": [box, {**box, "bbox": [float("nan"), 20, 34, 34]}, {**box, "bbox": [10, 20, 0.001, 34]}],
        "reviewed_empty": [],
        "outside": [box],
    }
    for name, annotations in detected.items():
        result = {"width": 1920, "height": 1080, "annotations": annotations}
        result[K.ANNOTATOR_DETECTED_SHA] = file_hash(paths[name])
        store.record_detection(keys[name], result, force=False)
    store.save_review(keys["reviewed_empty"], 1, reviewed=True)
    return keys


def test_export_takes_processed_screenshots_and_finite_boxes(tmp_path: Path, review_store: ReviewStore) -> None:
    """Screenshots never detected are left out (a reviewed one with no box stays); boxes that are not finite or round
    to nothing are skipped."""
    _export_store(tmp_path, review_store)
    result = export_dataset(review_store, tmp_path / "export", reviewed_only=False)

    assert (result.images, result.annotations, result.skipped_annotations) == (3, 2, 2)
    text = result.manifest_path.read_text(encoding="utf-8")
    assert "NaN" not in text
    names = {Path(image["path"]).name for image in json.loads(text)["images"]}
    assert names == {"done.png", "empty.png", "outside.png"}
    reviewed = export_dataset(review_store, tmp_path / "reviewed")
    assert (reviewed.images, reviewed.annotations) == (1, 0)  # only the reviewed screenshot


def test_an_export_gives_every_screenshot_its_block_split(tmp_path: Path, review_store: ReviewStore) -> None:
    """The splits are drawn over the whole store, reviewed or not, by blocks: the four screenshots one atlas places
    close together share a split, though only one of them is reviewed and exported."""
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    names = [f"shot{i}" for i in range(4)]
    frames = [
        {"name": name, "path": f"{name}.png", "w": 1920, "h": 1080, "M": [[1, 0, i * 200], [0, 1, 0]]}
        for i, name in enumerate(names)
    ]
    (atlas / "atlas.json").write_text(json.dumps({"frames": frames, "nodes": [], "edges": [], "landmarks": []}))
    paths = [atlas / f"{name}.png" for name in names]
    for i, path in enumerate(paths):
        path.write_bytes(bytes([i]))
    review_store.add_images(paths)
    for path in paths:
        result = {"width": 1920, "height": 1080, "annotations": [{"label": "tower", "bbox": [5, 5, 20, 20]}],
                  K.ANNOTATOR_DETECTED_SHA: file_hash(path)}  # fmt: skip
        review_store.record_detection(image_key(path), result, force=False)
    review_store.save_review(image_key(paths[0]), 1, reviewed=True)

    result = export_dataset(review_store, tmp_path / "export")
    assert result.images == 1 and sum(result.splits.values()) == 1
    splits = review_store.splits()
    assert set(splits) == {image_key(path) for path in paths}
    assert len(set(splits.values())) == 1
    assert "blocks" in result.report
    # the ledger keeps all four, by their bytes, with their block
    ledger = read_ledger()
    assert result.ledger_added == 4
    assert {entry.file for entry in ledger.values()} == {relative_source(path) for path in paths}
    assert {entry.split for entry in ledger.values()} == set(splits.values())
    assert {entry.block for entry in ledger.values()} == {f"{relative_source(atlas)}#0"}


def test_a_failed_export_keeps_the_previous_one(
    tmp_path: Path, review_store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest is written whole or not at all: when moving the new one into place fails, the previous export is
    there as it was, and no temporary file is left behind."""
    keys = _export_store(tmp_path, review_store)
    output = tmp_path / "export"
    export_dataset(review_store, output, reviewed_only=False)
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    assert review_store.save_review(keys["outside"], 1, annotations=[])  # the next export differs
    real_replace = os.replace

    def failing_replace(source, destination):
        if Path(destination) == output / K.ANNOTATOR_MANIFEST_FILE:
            raise OSError("disk full")
        return real_replace(source, destination)

    monkeypatch.setattr(state_module.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        export_dataset(review_store, output, reviewed_only=False)

    assert {path.name: path.read_bytes() for path in output.iterdir()} == before


def test_discovery_skips_atlas_map_pictures_and_missing_roots(tmp_path: Path) -> None:
    """An atlas folder keeps its stitched map in atlas_files/ (roa-atlas: 9950x4019, 741 boxes): not a screenshot."""
    (tmp_path / "atlas" / "atlas_files").mkdir(parents=True)
    (tmp_path / "atlas" / "shot.png").write_bytes(b"x")
    (tmp_path / "atlas" / "atlas_files" / "atlas_terrain.png").write_bytes(b"x")
    found = discover_images([tmp_path / "atlas", tmp_path / "missing"])
    assert [path.name for path in found] == ["shot.png"]


def test_discovery_leaves_out_paths_utf8_cannot_hold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file name with bytes that are not UTF-8 (Python keeps them as surrogate escapes) is left out instead of
    stopping discovery. No file is made, as macOS and Windows refuse such a name: every path counts as a file here."""
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    plain = tmp_path / "shot.png"
    assert discover_images([tmp_path / "shot\udcff.png", plain]) == [plain.resolve()]


def test_detection_refuses_what_is_not_a_screenshot(tmp_path: Path) -> None:
    """Larger than a 4K game window is a stitched map, not a screenshot; an unreadable file is an error too."""
    from tools.detection_dataset_annotator import run_classical_detector

    huge = tmp_path / "huge.png"
    cv2.imwrite(str(huge), np.zeros((50, 3900, 3), np.uint8))
    with pytest.raises(ValueError, match="Not a screenshot: 3900x50"):
        run_classical_detector(huge)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"")
    with pytest.raises(ValueError, match="Could not read image"):
        run_classical_detector(broken)


def test_a_screenshot_is_read_upright_as_training_decodes_it(tmp_path: Path) -> None:
    """Training's decoder (``datasets.Image``, as ``build_dataset`` stores the screenshots) applies the EXIF rotation:
    the editor and its boxes must see the same frame, the same pixels at the same place."""
    datasets = pytest.importorskip("datasets")
    path = tmp_path / "rotated.png"
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees clockwise to display"
    stored = Image.new("RGB", (64, 32), (0, 0, 0))
    stored.paste((200, 10, 10), (0, 0, 8, 8))  # a red corner, top left as stored
    stored.save(path, exif=exif)
    annotator = decode_image(path)
    trained = np.asarray(datasets.Image().decode_example({"path": str(path), "bytes": None}).convert("RGB"))
    assert annotator.shape[:2] == trained.shape[:2] == (64, 32)  # upright: the stored width is the height
    assert np.array_equal(annotator[:, :, ::-1], trained)  # BGR vs RGB: the red corner at the same place
    assert trained[0, -1].tolist() == [200, 10, 10]  # rotated clockwise: the corner is now top right


def test_a_box_the_editor_edited_is_saved_however_little_it_moved() -> None:
    """The editor marks a box it edited ``manual``: a 0.3 px typed change is saved, and a box moved back by hand to
    where the detector had it stays the reviewer's (no detector score). Undo gives the box its detector source back,
    and then the saved or known detector box returns."""
    shown = [{"id": "b0", "label": "map_node", "bbox": [10.0, 10.0, 48.0, 48.0], "area": 2304.0, "iscrowd": 0,
              "source": "classical", "score": 0.9}]  # fmt: skip
    (box,) = editor_boxes(shown)
    typed = {**box, "x": 10.3, "source": "manual"}
    saved = apply_editor_boxes(shown, [typed], width=500, height=500, known=shown)
    assert saved[0]["bbox"][0] == 10.3 and saved[0]["source"] == "manual" and "score" not in saved[0]
    back = {**box, "source": "manual"}  # moved back by hand
    again = apply_editor_boxes(saved, [back], width=500, height=500, known=shown)
    assert again[0]["source"] == "manual" and "score" not in again[0]
    undone = apply_editor_boxes(saved, [box], width=500, height=500, known=shown)  # Ctrl+Z: the detector's again
    assert undone == shown


def test_ids_are_never_handed_out_again() -> None:
    """The counter passes every kept ``b<n>``: a deleted box's id (its old annotation still known to the editor's undo
    memory) is never given to a new box, and the counter is kept whenever it moves."""
    item = {"annotations": [{"id": "b7", "label": "icon"}, {"label": "tower"}], "next_annotation_id": 0}
    assert ensure_annotation_ids(item)
    assert item["annotations"][1]["id"] == "b8" and item["next_annotation_id"] == 9
    kept = {"annotations": [{"id": "b3", "label": "icon"}], "next_annotation_id": 0}
    assert not ensure_annotation_ids(kept) and kept["next_annotation_id"] == 4  # no id added, the counter still moves


def test_discovery_and_the_store_clean_up_skip_the_same_folders(tmp_path: Path) -> None:
    """An atlas's map pictures are never screenshots, whether the root is the atlas, the atlas_files folder itself or
    a file in it: discovery takes none and the clean-up removes nothing more (a second run changes nothing)."""
    from tools.detection_dataset_annotator.build_store import left_out

    pictures = tmp_path / "atlas" / "atlas_files"
    pictures.mkdir(parents=True)
    terrain = pictures / "atlas_terrain.png"
    cv2.imwrite(str(terrain), np.zeros((8, 8, 3), np.uint8))
    shot = tmp_path / "atlas" / "shot.png"
    cv2.imwrite(str(shot), np.full((8, 8, 3), 9, np.uint8))
    for root in (tmp_path / "atlas", pictures, terrain):
        found = discover_images([root])
        assert terrain.resolve() not in found
        assert left_out({image_key(path): path for path in found}, found) == {}
    assert set(left_out({"t": terrain}, [])) == {"t"}


def test_an_editor_box_with_a_coordinate_that_is_not_finite_is_dropped() -> None:
    """NaN passes every clip (each comparison is False) and would be saved; such a box is no box (CodeRabbit)."""
    boxes = [
        {"id": "b1", "label": "map_node", "x": float("nan"), "y": 10, "w": 20, "h": 20, "source": "manual"},
        {"id": "b2", "label": "map_node", "x": 10, "y": 10, "w": float("inf"), "h": 20, "source": "manual"},
        {"id": "b3", "label": "map_node", "x": 10, "y": 10, "w": 20, "h": 20, "source": "manual"},
    ]
    saved = apply_editor_boxes([], boxes, width=100, height=100)
    assert [(a["id"], a["bbox"]) for a in saved] == [("b3", [10.0, 10.0, 20.0, 20.0])]
