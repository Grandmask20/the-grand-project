"""Detection dataset annotator: seeds an RF-DETR dataset from the classical detector, for a reviewer to correct.

    python -m tools.detection_dataset_annotator                the Streamlit page (make annotate_dataset)
    python -m tools.detection_dataset_annotator.worker         one detector worker process (started by the page)
    python -m tools.detection_dataset_annotator.build_store    the store brought up to date (discover, copies,
                                                               detect, biome truths)
    python -m tools.detection_dataset_annotator.split_ledger   every screenshot's split, kept in the ledger

Modules: state (screenshots, detection options, labels, the queue), store (the review state in SQLite:
review_state.sqlite3), detection (detector results as boxes: grand_project.detect.proposals), icon_proposals (icons and
hidden map nodes the classical finder misses), pool (detection in worker processes), splits and blocks (train /
validation / test, drawn by spatial blocks of each atlas), split_ledger (the splits by the screenshots' bytes, kept in
git), build_store (the store's steps as one run), boxes (the editor's boxes <-> saved annotations), export
(COCO + manifest), score_nodes (the biome and city-area guesses against reviewed boxes), truth_seed (city areas and
citadels from an atlas's biome truth), app and component (the Streamlit page and its box editor). The labels
themselves are grand_project.detect.labels'.
Only app and component import Streamlit; the names below do not. The command modules (build_store, export,
split_ledger, truth_seed, score_nodes) are imported by name, not here (``python -m`` must load them first).
"""

from .blocks import Block, screenshot_blocks
from .boxes import (
    annotations_changed,
    apply_editor_boxes,
    editor_boxes,
    editor_image_url,
    editor_payload_matches,
    ensure_annotation_ids,
    label_palette,
)
from .detection import decode_image, detection_annotations, run_classical_detector
from .pool import detect_pending
from .splits import assign_splits, pinned_split, split_report
from .state import (
    DetectionOptions,
    copies,
    discover_images,
    file_hash,
    image_key,
    label_names,
    neighbour_key,
    relative_source,
    resolve_input_paths,
    resolve_path,
    write_json_atomic,
)
from .store import QueueEntry, ReviewStore, StoreLayoutError

__all__ = [
    "Block",
    "DetectionOptions",
    "QueueEntry",
    "ReviewStore",
    "StoreLayoutError",
    "annotations_changed",
    "apply_editor_boxes",
    "assign_splits",
    "copies",
    "decode_image",
    "detect_pending",
    "detection_annotations",
    "discover_images",
    "editor_boxes",
    "editor_image_url",
    "editor_payload_matches",
    "ensure_annotation_ids",
    "file_hash",
    "image_key",
    "label_names",
    "label_palette",
    "neighbour_key",
    "pinned_split",
    "relative_source",
    "resolve_input_paths",
    "resolve_path",
    "run_classical_detector",
    "screenshot_blocks",
    "split_report",
    "write_json_atomic",
]
