"""Detection dataset annotator: seeds an RF-DETR dataset from the classical detector, for a reviewer to correct.

    python -m tools.detection_dataset_annotator          the Streamlit page (make annotate_dataset)
    python -m tools.detection_dataset_annotator.worker   one detector worker process (started by the page)

Modules: state (screenshots, detection options, labels, the queue), store (the review state in SQLite:
review_state.sqlite3), detection (detector results as boxes), icon_proposals (icons and hidden map nodes the classical
finder misses), pool (detection in worker processes), boxes (the editor's boxes <-> saved annotations), export (COCO +
manifest), app and component (the Streamlit page and its box editor).
Only app and component import Streamlit; the names below do not.
"""

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
from .export import ExportResult, export_dataset
from .pool import detect_pending
from .state import (
    DetectionOptions,
    discover_images,
    image_key,
    label_names,
    neighbour_key,
    relative_source,
    resolve_input_paths,
    resolve_path,
    write_json_atomic,
)
from .store import QueueEntry, ReviewStore

__all__ = [
    "DetectionOptions",
    "ExportResult",
    "QueueEntry",
    "ReviewStore",
    "annotations_changed",
    "apply_editor_boxes",
    "decode_image",
    "detect_pending",
    "detection_annotations",
    "discover_images",
    "editor_boxes",
    "editor_image_url",
    "editor_payload_matches",
    "ensure_annotation_ids",
    "export_dataset",
    "image_key",
    "label_names",
    "label_palette",
    "neighbour_key",
    "relative_source",
    "resolve_input_paths",
    "resolve_path",
    "run_classical_detector",
    "write_json_atomic",
]
