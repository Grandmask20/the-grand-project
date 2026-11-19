"""The detection dataset annotator (tools/detection_dataset_annotator): editor boxes map back to saved annotations,
optional classes, the review state, export, and screenshots stay untouched."""

import base64
import hashlib
import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from grand_project.detect import constants as detect_constants
from grand_project.detect.icon_types import dataset_icon_types, icon_class
from tools.detection_dataset_annotator import (
    DetectionOptions,
    apply_editor_boxes,
    detection_annotations,
    discover_images,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    ensure_annotation_ids,
    export_dataset,
    image_key,
    label_names,
    label_palette,
    merge_discovered_images,
    neighbour_key,
    read_state,
    resolve_input_paths,
    save_state,
)
from tools.detection_dataset_annotator import constants as K


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


def test_label_palette_has_colours_and_number_keys() -> None:
    palette = label_palette([*K.ANNOTATOR_ALL_LABELS, "icon_map_boss", "custom"])
    assert [entry["hotkey"] for entry in palette[:10]] == list("1234567890")
    assert palette[10]["hotkey"] == ""
    colours = [entry["color"] for entry in palette]
    assert all(colour.startswith("#") and len(colour) == 7 for colour in colours)
    assert len(set(colours[:8])) == 8
    assert label_palette(["icon_map_boss"])[0]["color"] == palette[10]["color"]  # stable


def test_label_names_follow_options_and_used_labels() -> None:
    """Core labels first (and the derived ones for the editor), then labels in use; named icons drop ``icon``."""
    state = {"images": {"a": {"annotations": [{"label": "icon_map_boss"}, {"label": "map_node"}, {"label": ""}]}}}
    assert label_names(state, named_icons=False, derived=False) == [*K.ANNOTATOR_CORE_LABELS, "icon_map_boss"]
    named = label_names(state, named_icons=True, derived=True)
    assert "icon" not in named
    assert named[-1] == "icon_map_boss"


def test_named_icons_list_every_icon_type() -> None:
    """User: every map content icon can be labelled, whether or not the classical detector named one yet; the icon
    types come in ICON_INFO order after the core labels, so an export numbers them the same every time."""
    state = {"images": {"a": {"annotations": [{"label": "icon_unidentified"}, {"label": "icon_breachhive"}]}}}
    icons = [icon_class(name) for name in dataset_icon_types()]
    assert {"icon_breachhive", "icon_wisdomsteachings", "icon_arcanehordes", "icon_hideoutred"} <= set(icons)
    core = [label for label in K.ANNOTATOR_CORE_LABELS if label != "icon"]
    assert label_names(state, named_icons=True, derived=False) == [*core, *icons, "icon_unidentified"]
    assert label_names({"images": {}}, named_icons=True, derived=False) == [*core, *icons]  # nothing labelled yet


def test_label_palette_shows_icon_pictures_and_names() -> None:
    """Each icon label carries its icon's picture and poe2db name (the editor shows them next to the label)."""
    palette = {e["name"]: e for e in label_palette(["map_node", "city", "icon_breachhive", "icon_unidentified", "x"])}
    breach = palette["icon_breachhive"]
    assert breach["picture"].startswith("data:image/webp;base64,")
    picture = Image.open(io.BytesIO(base64.b64decode(breach["picture"].split(",", 1)[1])))  # OpenCV drops alpha
    assert picture.mode == "RGBA" and picture.size == (K.ANNOTATOR_LABEL_PICTURE_PX,) * 2
    assert picture.getchannel("A").getextrema() == (0, 255)  # a disc on a transparent square
    assert breach["title"] == "Breach Hive"
    assert "breach hive" in breach["search"] and "icon_breachhive" in breach["search"]
    assert palette["map_node"]["picture"]  # ANNOTATOR_LABEL_ART
    assert palette["city"]["picture"] == palette["x"]["picture"] == palette["x"]["title"] == ""
    assert palette["icon_unidentified"]["picture"] == ""  # no art and no stored picture: only its colour


def test_named_icons_and_derived_classes_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named icon labels work while paths and fortress walls remain independently optional."""
    monkeypatch.setattr(detect_constants, "RF_DETR_WALL_MIN_AREA", 100)
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    wall_mask = np.zeros((100, 100), dtype=np.uint8)
    wall_mask[10:30, 10:30] = 1
    detection = {"edges": [{"line": [[10, 20], [90, 30]]}], "icons": [{"x": 50, "y": 50, "name": "Map Boss"}]}

    def labels(options: DetectionOptions) -> list[str]:
        annotations = detection_annotations(detection, image, image, options, wall_mask=wall_mask)
        return [annotation["label"] for annotation in annotations]

    assert labels(DetectionOptions(include_paths=True, named_icons=True)) == ["icon_map_boss", "path"]
    assert labels(DetectionOptions(include_fortress_walls=True, named_icons=True)) == ["icon_map_boss", "fortress_wall"]
    assert labels(DetectionOptions()) == ["icon"]


def test_detection_options_round_trip() -> None:
    options = DetectionOptions(include_paths=True, named_icons=True)
    assert DetectionOptions.from_settings(options.as_settings()) == options
    assert DetectionOptions.from_settings({}) == DetectionOptions()
    assert options.derived and not DetectionOptions(named_icons=True).derived


def test_review_state_round_trip(tmp_path: Path) -> None:
    """Discovery finds images recursively without duplicates; a saved state reads back; other versions are refused."""
    (tmp_path / "shots" / "deep").mkdir(parents=True)
    for name in ("shots/a.png", "shots/deep/b.JPG", "shots/notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    roots = resolve_input_paths([str(tmp_path / "shots"), "  ", str(tmp_path / "shots" / "a.png")])
    found = discover_images(roots)
    assert [path.name for path in found] == ["a.png", "b.JPG"]

    state_path = tmp_path / "out" / K.ANNOTATOR_STATE_FILE
    state = read_state(state_path, roots)
    assert merge_discovered_images(state, found) == (2, 0)
    assert merge_discovered_images(state, found) == (0, 2)
    save_state(state_path, state)
    assert read_state(state_path, []) == state

    state_path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        read_state(state_path, [])


def test_editor_never_changes_the_screenshot(tmp_path: Path) -> None:
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

    state = {"images": {}}
    merge_discovered_images(state, [shot])
    item = state["images"][image_key(shot)]
    detection = {"nodes": [{"x": 100, "y": 100, "score": 0.9}], "icons": [{"x": 300, "y": 200}]}
    item.update(
        detected=True, width=640, height=360, reviewed=True, annotations=detection_annotations(detection, image, image)
    )
    ensure_annotation_ids(item)
    boxes = editor_boxes(item["annotations"])
    boxes[0]["x"] += 5
    item["annotations"] = apply_editor_boxes(item["annotations"], boxes, width=640, height=360)
    result = export_dataset(state, tmp_path / "export")
    assert result.images == 1 and result.annotations == 2
    assert hashlib.sha256(shot.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in (tmp_path / "export").iterdir()) == [
        "annotations.json",
        "labels.json",
        "manifest.json",
    ]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == K.ANNOTATOR_MANIFEST_FORMAT
    assert manifest["images"][0]["source_type"] == "annotator_reviewed"

    # with named icons the export lists every icon type, used or not, in a fixed order (user)
    state["settings"] = DetectionOptions(named_icons=True).as_settings()
    item["annotations"][1]["label"] = "icon_breachhive"
    named = export_dataset(state, tmp_path / "named")
    labels = json.loads(named.manifest_path.read_text(encoding="utf-8"))["labels"]
    core = [label for label in K.ANNOTATOR_CORE_LABELS if label != "icon"]
    assert list(labels.values()) == [*core, *(icon_class(name) for name in dataset_icon_types())]
