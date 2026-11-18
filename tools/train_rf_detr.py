"""Build a Hugging Face dataset and fine-tune RF-DETR on the atlas detector truth.

The project truth is point-based.  The data module converts it to explicit COCO-style boxes for map nodes, icons,
landmarks, paths, path dashes and optional fortress walls.  The saved dataset is a ``DatasetDict`` with an embedded
``Image`` feature, stable category IDs, and provenance for hand truth versus derived or cached labels.

Build only the dataset:

    python -m tools.train_rf_detr --data-root atlas_test_data --dataset-only

Build and train on a GPU:

    python -m tools.train_rf_detr --data-root atlas_test_data --output-dir runs/rf-detr-small

Training applies conservative horizontal-flip and random-crop augmentation to the train split by default. Use
``--no-augmentation`` for an unaugmented baseline; validation images are never augmented.

Training dependencies are optional: ``pip install -e '.[training]'``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from grand_project.detect.constants import (
    RF_DETR_AUGMENT_CROP_ATTEMPTS,
    RF_DETR_AUGMENT_CROP_MIN_SCALE,
    RF_DETR_AUGMENT_CROP_MIN_VISIBILITY,
    RF_DETR_AUGMENT_CROP_PROBABILITY,
    RF_DETR_AUGMENT_FLIP_PROBABILITY,
    RF_DETR_ICON_BOX,
    RF_DETR_LANDMARK_BOX,
    RF_DETR_MAP_BOX,
    RF_DETR_MAX_TARGETS,
    RF_DETR_MODEL_NAME,
    RF_DETR_STRONGHOLD_BOX,
    RF_DETR_TOWER_HEIGHT,
    RF_DETR_TOWER_WIDTH,
)
from grand_project.detect.rf_detr import (
    build_dataset,
    load_bootstrap_manifest,
    load_records,
    processor_transform,
)


# This must run before importing ``datasets``: its optional integrations can
# import torch, at which point the dynamic linker has already chosen cuDNN.
def _prepare_cuda_library_path() -> None:
    """Make pip-installed CUDA libraries win over unrelated system CUDA libraries.

    PyTorch's Linux wheels ship cuDNN in ``site-packages/nvidia``.  An inherited
    ``LD_LIBRARY_PATH`` can put a different system cuDNN first; because the
    libraries all use the same sonames, the dynamic linker silently combines
    components from both installations and cuDNN reports a sublibrary-loading
    failure during the first convolution.
    """
    if not sys.platform.startswith("linux"):
        return
    package_dirs = {Path(entry) / "nvidia" for entry in sys.path if entry}
    cuda_dirs = [
        package_dir / "cudnn" / "lib" for package_dir in package_dirs if (package_dir / "cudnn" / "lib").is_dir()
    ]
    cuda_dirs += [
        package_dir / "cu13" / "lib" for package_dir in package_dirs if (package_dir / "cu13" / "lib").is_dir()
    ]
    if not cuda_dirs:
        return
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    entries = [str(directory) for directory in cuda_dirs]
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(entries + ([existing] if existing else []))


_prepare_cuda_library_path()

from datasets import DatasetDict  # noqa: E402


def collate_fn(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Stack transformed processor outputs while retaining DETR's per-image target dictionaries."""
    import torch

    def one(value):
        return value[0] if torch.is_tensor(value) and value.ndim > 0 and value.shape[0] == 1 else value

    result: dict[str, Any] = {
        "pixel_values": torch.stack([one(item["pixel_values"]) for item in batch]),
        "labels": [one(item["labels"]) for item in batch],
    }
    if "pixel_mask" in batch[0]:
        result["pixel_mask"] = torch.stack([one(item["pixel_mask"]) for item in batch])
    return result


def move_batch(batch: dict[str, Any], device) -> dict[str, Any]:
    """Move tensors in a DETR batch, including nested target dictionaries, to one device."""
    import torch

    return {
        key: (
            [
                {name: value.to(device) if torch.is_tensor(value) else value for name, value in target.items()}
                for target in value
            ]
            if key == "labels"
            else value.to(device)
            if torch.is_tensor(value)
            else value
        )
        for key, value in batch.items()
    }


def run_epoch(model, loader, optimizer, device, *, amp: bool, scaler, train: bool) -> float:
    """Run one train or validation epoch and return its mean loss."""
    import torch

    model.train(train)
    total_loss = 0.0
    count = 0
    autocast_dtype = torch.float16 if device.type == "cuda" else torch.bfloat16
    context = torch.autocast(device_type=device.type, dtype=autocast_dtype) if amp else nullcontext()
    with context:
        for batch in loader:
            batch = move_batch(batch, device)
            with torch.set_grad_enabled(train):
                outputs = model(**batch)
                loss = outputs.loss
            if loss is None or not torch.isfinite(loss):
                raise RuntimeError(f"RF-DETR returned an invalid loss: {loss}")
            if train:
                optimizer.zero_grad(set_to_none=True)
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=0.1)
                scaler.step(optimizer)
                scaler.update()
            total_loss += float(loss.detach())
            count += 1
    return total_loss / max(1, count)


def save_model(model, processor, output_dir: Path, label_map: dict[str, str]) -> None:
    """Save a Transformers-compatible model, processor and detector label map."""
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir, safe_serialization=True)
    processor.save_pretrained(output_dir)
    (output_dir / "labels.json").write_text(json.dumps(label_map, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse dataset and fine-tuning options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=None, help="dataset root; defaults to ATLAS_TEST_DATA or project test data"
    )
    parser.add_argument(
        "--bootstrap-manifest",
        type=Path,
        default=None,
        help="reviewed manifest.json exported by bootstrap-dataset-program; overrides --data-root labels",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("runs/rf-detr-small"))
    parser.add_argument(
        "--dataset-dir", type=Path, default=None, help="saved DatasetDict; defaults to OUTPUT_DIR/dataset"
    )
    parser.add_argument(
        "--reuse-dataset", action="store_true", help="load an existing dataset directory instead of rebuilding"
    )
    parser.add_argument("--overwrite-dataset", action="store_true", help="replace a non-empty dataset directory")
    parser.add_argument(
        "--dataset-only", action="store_true", help="prepare and save the dataset without downloading a model"
    )
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--split-by-source", action="store_true", help="keep each truth source entirely in one split")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or mps")
    parser.add_argument("--resolution", type=int, default=None, help="optional square processor resolution")
    parser.add_argument("--map-box", type=float, default=RF_DETR_MAP_BOX)
    parser.add_argument("--icon-box", "--badge-box", dest="icon_box", type=float, default=RF_DETR_ICON_BOX)
    parser.add_argument("--landmark-box", type=float, default=RF_DETR_LANDMARK_BOX)
    parser.add_argument("--stronghold-box", type=float, default=RF_DETR_STRONGHOLD_BOX)
    parser.add_argument("--tower-width", type=float, default=RF_DETR_TOWER_WIDTH)
    parser.add_argument("--tower-height", type=float, default=RF_DETR_TOWER_HEIGHT)
    parser.add_argument(
        "--badge-granularity",
        choices=("name", "all"),
        default="all",
        help="train one generic icon class (default) or one class per icon name",
    )
    parser.add_argument("--include-soft", action="store_true", help="include UI/off-center map and icon truth labels")
    parser.add_argument(
        "--include-cached", action="store_true", help="include cached crawl detections as pseudo-labels"
    )
    parser.add_argument(
        "--include-walls", action="store_true", help="include optional fortress_paint masks as wall labels"
    )
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="experimental: train path boxes too; normal inference derives paths with the established tracer",
    )
    parser.add_argument(
        "--include-path-dashes",
        action="store_true",
        help="experimental: train path-dash boxes (not recommended; one image can exceed RF-DETR query slots)",
    )
    parser.add_argument("--no-paths", action="store_false", dest="include_paths", help=argparse.SUPPRESS)
    parser.add_argument("--no-path-dashes", action="store_false", dest="include_path_dashes", help=argparse.SUPPRESS)
    parser.set_defaults(include_paths=False, include_path_dashes=False)
    parser.add_argument("--max-images", type=int, default=None, help="limit images for a smoke test")
    parser.add_argument("--no-amp", action="store_true", help="disable CUDA mixed precision")
    parser.add_argument(
        "--no-augmentation",
        action="store_true",
        help="disable the default horizontal-flip and random-crop training augmentation",
    )
    return parser.parse_args()


def _data_root(args: argparse.Namespace) -> Path:
    """Resolve the configured data root through the project's normal test-data lookup."""
    if args.data_root is not None:
        return args.data_root
    from grand_project import paths

    return paths.TEST_DATA


def _validate_target_count(largest: int) -> None:
    """Reject dense annotations that cannot fit RF-DETR Small's fixed query budget."""
    if largest > RF_DETR_MAX_TARGETS:
        raise ValueError(
            f"one training image has {largest} objects, above RF-DETR's {RF_DETR_MAX_TARGETS} query slots; "
            "omit --include-path-dashes and let the adapter derive paths"
        )


def _device(name: str):
    """Choose a supported torch device without probing unavailable accelerators."""
    import torch

    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    return torch.device(name)


def _processor(model_name: str, resolution: int | None):
    """Load the checkpoint processor and optionally override its square training size."""
    from transformers import AutoImageProcessor

    processor = AutoImageProcessor.from_pretrained(model_name)
    if resolution is not None:
        if resolution < 256:
            raise ValueError("--resolution must be at least 256")
        if "height" in processor.size or "width" in processor.size:
            processor.size = {"height": resolution, "width": resolution}
        else:
            processor.size = {"shortest_edge": resolution, "longest_edge": resolution}
    return processor


def _load_or_build_dataset(args: argparse.Namespace, data_root: Path):
    """Build the Arrow dataset or load a previously saved one and its stable labels."""
    dataset_dir = args.dataset_dir or args.output_dir / "dataset"
    if args.reuse_dataset:
        from datasets import load_from_disk

        dataset = load_from_disk(str(dataset_dir))
        assert isinstance(dataset, DatasetDict)
        largest = max(
            (len(objects["category"]) for split in dataset.values() for objects in split["objects"]),
            default=0,
        )
        _validate_target_count(largest)

        label_file = dataset_dir / "labels.json"
        if not label_file.is_file():
            raise FileNotFoundError(f"reused dataset has no labels.json: {label_file}")
        return dataset, json.loads(label_file.read_text(encoding="utf-8")), dataset_dir, None

    if args.bootstrap_manifest is not None:
        records, label_map = load_bootstrap_manifest(args.bootstrap_manifest, max_images=args.max_images)
    else:
        records, label_map = load_records(
            data_root,
            map_box=args.map_box,
            icon_box=args.icon_box,
            landmark_box=args.landmark_box,
            tower_width=args.tower_width,
            tower_height=args.tower_height,
            stronghold_box=args.stronghold_box,
            include_soft=args.include_soft,
            badge_granularity=args.badge_granularity,
            include_paths=args.include_paths,
            include_path_dashes=args.include_path_dashes,
            include_cached=args.include_cached,
            include_walls=args.include_walls,
            max_images=args.max_images,
        )
    _validate_target_count(max(len(record.annotations) for record in records))
    if args.overwrite_dataset and dataset_dir.exists():
        if dataset_dir.is_file():
            raise ValueError(f"dataset path is a file, not a directory: {dataset_dir}")
        shutil.rmtree(dataset_dir)
    dataset = build_dataset(
        records,
        val_fraction=args.val_fraction,
        seed=args.seed,
        output_dir=dataset_dir,
        by_source=args.split_by_source,
        label_map=label_map,
    )
    return dataset, label_map, dataset_dir, records


def main() -> int:
    """Prepare the dataset, then fine-tune and save the best RF-DETR checkpoint."""
    args = parse_args()
    data_root = _data_root(args)
    dataset, label_map, dataset_dir, records = _load_or_build_dataset(args, data_root)
    print(f"dataset: {len(dataset['train'])} train / {len(dataset['validation'])} validation -> {dataset_dir}")
    print(f"classes ({len(label_map)}): {', '.join(label_map.values())}")
    if args.dataset_only:
        return 0

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForObjectDetection

    processor = _processor(RF_DETR_MODEL_NAME, args.resolution)
    id2label = {int(index): name for index, name in label_map.items()}
    label2id = {name: index for index, name in id2label.items()}
    model = AutoModelForObjectDetection.from_pretrained(
        RF_DETR_MODEL_NAME,
        id2label=id2label,
        label2id=label2id,
        num_labels=len(label_map),
        ignore_mismatched_sizes=True,
    )
    model.config.id2label = id2label
    model.config.label2id = label2id
    model.config.num_labels = len(label_map)
    if model.config.id2label != id2label or model.config.label2id != label2id:
        raise RuntimeError("RF-DETR label configuration was not replaced with the atlas detector labels")

    device = _device(args.device)
    model.to(device)
    amp = not args.no_amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    train_dataset = dataset["train"].with_transform(
        processor_transform(processor, augment=not args.no_augmentation, seed=args.seed)
    )
    validation_dataset = dataset["validation"].with_transform(processor_transform(processor))
    loader_kwargs = {
        "num_workers": args.workers,
        "pin_memory": device.type == "cuda",
        "collate_fn": collate_fn,
    }
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, **loader_kwargs)
    validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size, shuffle=False, **loader_kwargs)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))
    best_val = float("inf")
    best_dir = args.output_dir / "best"
    started = time.time()

    for epoch in range(1, args.epochs + 1):
        train_loss = run_epoch(model, train_loader, optimizer, device, amp=amp, scaler=scaler, train=True)
        val_loss = run_epoch(model, validation_loader, optimizer, device, amp=amp, scaler=scaler, train=False)
        scheduler.step()
        print(
            f"epoch {epoch:03d}/{args.epochs}: train_loss={train_loss:.4f} "
            f"val_loss={val_loss:.4f} lr={scheduler.get_last_lr()[0]:.3g}"
        )
        if val_loss < best_val:
            best_val = val_loss
            if best_dir.exists():
                shutil.rmtree(best_dir)
            save_model(model, processor, best_dir, label_map)
            print(f"saved {best_dir} (best validation loss)")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "training_summary.json").write_text(
        json.dumps(
            {
                "base_model": RF_DETR_MODEL_NAME,
                "dataset_dir": str(dataset_dir),
                "train_screenshots": len(train_dataset),
                "validation_screenshots": len(validation_dataset),
                "source_types": sorted({record.source_type for record in records}) if records else [],
                "classes": label_map,
                "augmentation": {
                    "enabled": not args.no_augmentation,
                    "seed": args.seed,
                    "horizontal_flip_probability": RF_DETR_AUGMENT_FLIP_PROBABILITY,
                    "crop_probability": RF_DETR_AUGMENT_CROP_PROBABILITY,
                    "crop_min_scale": RF_DETR_AUGMENT_CROP_MIN_SCALE,
                    "crop_min_visibility": RF_DETR_AUGMENT_CROP_MIN_VISIBILITY,
                    "crop_attempts": RF_DETR_AUGMENT_CROP_ATTEMPTS,
                },
                "best_validation_loss": best_val,
                "device": str(device),
                "seconds": round(time.time() - started, 1),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"done: {best_dir}  best_val_loss={best_val:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
