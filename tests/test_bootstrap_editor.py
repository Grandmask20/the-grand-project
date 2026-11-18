"""The bootstrapper's box editor: editor boxes map back to saved annotations, and screenshots stay untouched."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, *args: str) -> str:
    """Run a snippet with the bootstrapper's folder importable (it is a Streamlit app, not a package)."""
    environment = os.environ.copy()
    python_paths = [str(PROJECT_ROOT / "bootstrap-dataset-program"), str(PROJECT_ROOT)]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *args],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_editor_edits_map_back_by_stable_id() -> None:
    """Unchanged boxes keep detector data; changed ones become manual; new boxes get ids; reordering is safe."""
    _run(
        """
        from dataset_bootstrap import apply_editor_boxes, editor_boxes, ensure_annotation_ids

        item = {"annotations": [
            {"label": "map_node", "bbox": [100, 100, 48, 48], "area": 2304, "iscrowd": 0, "source": "classical",
             "score": 0.9},
            {"label": "city", "bbox": [300, 300, 60, 70], "area": 4200, "iscrowd": 0, "source": "classical",
             "score": 0.8},
            {"label": "icon", "bbox": [500, 500, 34, 34], "area": 1156, "iscrowd": 0, "source": "classical",
             "score": 0.7},
            {"label": "tower", "bbox": [700, 600, 40, 90], "area": 3600, "iscrowd": 0, "source": "classical"},
        ]}
        assert ensure_annotation_ids(item)
        assert not ensure_annotation_ids(item)
        ids = [annotation["id"] for annotation in item["annotations"]]
        assert len(set(ids)) == 4

        boxes = editor_boxes(item["annotations"])
        assert apply_editor_boxes(item["annotations"], boxes, width=1000, height=800) == item["annotations"]

        boxes[0]["x"] += 10                      # moved
        boxes[1]["label"] = "hall"               # relabelled
        del boxes[2]                             # deleted
        boxes[2]["x"] += 0.3                     # within tolerance: still the detector's box
        boxes.reverse()                          # order must not matter
        boxes.append({"id": "new-1", "label": "icon", "x": 990, "y": -5, "w": 40, "h": 20})  # clipped
        boxes.append({"id": "new-2", "label": "icon", "x": 10, "y": 10, "w": 0.5, "h": 20})  # under 1 px
        boxes.append({"id": "", "label": "", "x": 10, "y": 10, "w": 20, "h": 20})  # no label

        edited = {a.get("id", "new"): a for a in apply_editor_boxes(item["annotations"], boxes, width=1000,
                                                                     height=800)}
        moved, relabelled, tower = (edited[ids[0]], edited[ids[1]], edited[ids[3]])
        assert moved == {"id": ids[0], "label": "map_node", "bbox": [110.0, 100.0, 48.0, 48.0], "area": 2304.0,
                         "iscrowd": 0, "source": "manual"}
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
        """
    )


def test_undo_after_a_saved_delete_restores_the_detector_box() -> None:
    """The editor's Ctrl+Z can bring back a box whose delete was already autosaved; it must keep score and id."""
    _run(
        """
        from dataset_bootstrap import apply_editor_boxes, editor_boxes

        shown = [
            {"id": "b0", "label": "map_node", "bbox": [10, 10, 48, 48], "area": 2304, "iscrowd": 0,
             "source": "classical", "score": 0.9},
            {"id": "b1", "label": "icon", "bbox": [90, 90, 34, 34], "area": 1156, "iscrowd": 0,
             "source": "classical", "score": 0.7},
        ]
        boxes = editor_boxes(shown)
        saved = apply_editor_boxes(shown, boxes[1:], width=500, height=500, known=shown)  # delete autosaved
        assert [a["id"] for a in saved] == ["b1"]
        restored = apply_editor_boxes(saved, boxes, width=500, height=500, known=shown)  # undo
        assert restored == shown
        new_box = {"id": "new-abc-1", "label": "tower", "x": 200, "y": 200, "w": 30, "h": 60}
        again = apply_editor_boxes(restored, [*boxes, new_box], width=500, height=500, known=shown)
        assert again[-1]["id"] == "new-abc-1" and again[-1]["source"] == "manual"
        assert apply_editor_boxes(again, [*boxes, new_box], width=500, height=500, known=shown) == again
        """
    )


def test_duplicate_ids_are_reassigned_and_new_ids_never_reused() -> None:
    _run(
        """
        from dataset_bootstrap import ensure_annotation_ids

        item = {"annotations": [{"id": "b0", "bbox": [0, 0, 5, 5]}, {"id": "b0", "bbox": [9, 9, 5, 5]}, {}]}
        assert ensure_annotation_ids(item)
        assert [a["id"] for a in item["annotations"]] == ["b0", "b1", "b2"]
        item["annotations"].pop()
        item["annotations"].append({"bbox": [1, 1, 5, 5]})
        ensure_annotation_ids(item)
        assert item["annotations"][-1]["id"] == "b3"
        """
    )


def test_stale_editor_messages_and_queue_neighbours() -> None:
    _run(
        """
        from dataset_bootstrap import editor_payload_matches, neighbour_key

        payload = {"image_key": "a", "revision": 2, "boxes": []}
        assert editor_payload_matches(payload, "a", 2)
        assert not editor_payload_matches(payload, "b", 2)       # from the previous screenshot
        assert not editor_payload_matches(payload, "a", 3)       # from before a detector rerun
        assert not editor_payload_matches({"image_key": "a", "revision": 2}, "a", 2)
        assert not editor_payload_matches(None, "a", 2)

        keys = ["a", "b", "c"]
        assert neighbour_key(keys, "b", 1) == "c"
        assert neighbour_key(keys, "b", -1) == "a"
        assert neighbour_key(keys, "c", 1) is None
        assert neighbour_key(keys, "a", -1) is None
        assert neighbour_key(keys, "gone", 1) == "a"
        assert neighbour_key([], "a", 1) is None
        """
    )


def test_label_palette_has_colours_and_number_keys() -> None:
    _run(
        """
        from constants import BOOTSTRAP_ALL_LABELS
        from dataset_bootstrap import label_palette

        palette = label_palette([*BOOTSTRAP_ALL_LABELS, "icon_map_boss", "custom"])
        assert [entry["hotkey"] for entry in palette[:10]] == list("1234567890")
        assert palette[10]["hotkey"] == ""
        colours = [entry["color"] for entry in palette]
        assert all(colour.startswith("#") and len(colour) == 7 for colour in colours)
        assert len(set(colours[:8])) == 8
        assert label_palette(["icon_map_boss"])[0]["color"] == palette[10]["color"]  # stable
        """
    )


def test_editor_never_changes_the_screenshot(tmp_path: Path) -> None:
    """Issue: boxes looked baked into the screenshot. The editor's copy and the file itself stay clean."""
    _run(
        """
        import base64
        import hashlib
        import sys
        from pathlib import Path

        import cv2
        import numpy as np
        from dataset_bootstrap import (
            apply_editor_boxes, detection_annotations, editor_boxes, editor_image_url, ensure_annotation_ids,
            export_dataset, image_key, merge_discovered_images,
        )

        folder = Path(sys.argv[1])
        shot = folder / "shot.png"
        rows, columns = np.mgrid[0:360, 0:640]
        image = np.dstack([columns * 255 // 640, rows * 255 // 360, (rows + columns) * 255 // 1000]).astype(np.uint8)
        cv2.circle(image, (100, 100), 20, (40, 200, 240), -1)  # a few smooth "map nodes"
        cv2.circle(image, (300, 200), 15, (240, 90, 60), -1)
        cv2.imwrite(str(shot), image)
        before = hashlib.sha256(shot.read_bytes()).hexdigest()

        url = editor_image_url(shot)
        assert url.startswith("data:image/jpeg;base64,")
        shown = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        assert shown.shape == image.shape
        difference = np.abs(shown.astype(int) - image.astype(int))
        assert difference.mean() < 2 and np.percentile(difference, 99.9) < 40, (difference.mean(),)

        state = {"images": {}}
        merge_discovered_images(state, [shot])
        item = state["images"][image_key(shot)]
        detection = {"nodes": [{"x": 100, "y": 100, "score": 0.9}], "icons": [{"x": 300, "y": 200}]}
        item.update(detected=True, width=640, height=360, reviewed=True,
                    annotations=detection_annotations(detection, image, image))
        ensure_annotation_ids(item)
        boxes = editor_boxes(item["annotations"])
        boxes[0]["x"] += 5
        item["annotations"] = apply_editor_boxes(item["annotations"], boxes, width=640, height=360)
        result = export_dataset(state, folder / "export")
        assert result["images"] == 1 and result["annotations"] == 2
        assert hashlib.sha256(shot.read_bytes()).hexdigest() == before
        assert sorted(path.name for path in (folder / "export").iterdir()) == [
            "annotations.json", "labels.json", "manifest.json"
        ]
        """,
        str(tmp_path),
    )
