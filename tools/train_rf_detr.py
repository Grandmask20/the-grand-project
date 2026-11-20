"""Fine-tune RF-DETR on the reviewed screenshots the dataset annotator exports.

The data is the annotator's ``manifest.json``: reviewed screenshots, each with the train / validation / test split
the annotator gave it (``tools/detection_dataset_annotator``). Build the dataset only
(``make prepare_rf_detr_data`` does this for the annotator's default output folder):

    python -m tools.train_rf_detr --annotator-manifest DATASET/manifest.json --dataset-only

Train on a GPU (``make train_rf_detr RF_DETR_ANNOTATOR_MANIFEST=...``), or go on from an earlier model:

    python -m tools.train_rf_detr --annotator-manifest ... --output-dir runs/rf-detr-small
    python -m tools.train_rf_detr --annotator-manifest ... --init-from runs/rf-detr-small/best

What the model sees: native-scale tiles of the 1080p screenshots with the game HUD painted over
(``grand_project.detect.rf_detr_tiles``): random tiles in training (scale jitter, tiles centred on rare classes,
render-scale blur; screenshots with rare classes drawn more often, LVIS repeat factors; never mirrored, the atlas is
not), the inference tiles for evaluation.

The recipe (RF-DETR paper, Appendix A): learning rate 1e-4 with the DINOv2 backbone's layers decayed 0.8 per layer
from the top, an exponential moving average (EMA) of the weights, no warm-up and a constant learning rate (the run
stops when validation stops improving), gradient clipping 0.1, a larger effective batch through gradient
accumulation. The best checkpoint is the EMA weights' best validation mean family AP (``rf_detr_eval``: the program
needs where objects are, not tight boxes); the test split is scored once, with the best checkpoint.

``--init-from`` copies each class's detector row from the earlier checkpoint by name: a class it had keeps its row, a
class with a ``parent`` it had (a node biome class from ``map_node``) starts from that row, other classes start fresh.

Training dependencies are optional: ``pip install -e '.[training]'``.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import shutil
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from grand_project.detect import constants as K
from grand_project.detect.labels import warm_start_rows
from grand_project.detect.rf_detr import build_dataset, load_annotator_manifest, tile_transform
from grand_project.detect.rf_detr_eval import evaluate, format_report
from grand_project.detect.rf_detr_model import class_families, predict_tiles
from grand_project.detect.rf_detr_tiles import epoch_indices, layer_lr_scale, normalise, rare_classes, repeat_factors


# This must run before importing ``datasets``: its optional integrations can
# import torch, at which point the dynamic linker has already chosen cuDNN.
def _prepare_cuda_library_path() -> None:
    """Make pip-installed CUDA libraries win over unrelated system CUDA libraries.

    PyTorch's Linux wheels ship cuDNN in ``site-packages/nvidia``.  An inherited
    ``LD_LIBRARY_PATH`` can put a different system cuDNN first; because the
    libraries all use the same sonames, the dynamic linker silently combines
    components from both installations and cuDNN reports a sublibrary-loading
    failure during the first convolution.

    The dynamic linker reads ``LD_LIBRARY_PATH`` once, when the process starts, so
    setting it here would not reach this process: when it is not right yet, the run
    restarts itself (once, guarded by RF_DETR_CUDA_REEXEC_ENV) with the path set.
    """
    if not sys.platform.startswith("linux") or os.environ.get(K.RF_DETR_CUDA_REEXEC_ENV):
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
    current = existing.split(os.pathsep) if existing else []
    entries = [str(directory) for directory in cuda_dirs]
    if current[: len(entries)] == entries:
        return
    env = {**os.environ, "LD_LIBRARY_PATH": os.pathsep.join(entries + current), K.RF_DETR_CUDA_REEXEC_ENV: "1"}
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(sys.executable, [sys.executable, *sys.orig_argv[1:]], env)


if __name__ == "__main__":  # only a training run restarts itself; importing this module (tests) never does
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


def _loss(model, batch, device, amp: bool):
    """One batch's loss, the forward pass under mixed precision when ``amp`` (a new autocast context per batch:
    autocast caches half-precision weight copies until it exits)."""
    import torch

    autocast_dtype = torch.float16 if device.type == "cuda" else torch.bfloat16
    autocast = torch.autocast(device_type=device.type, dtype=autocast_dtype) if amp else nullcontext()
    with autocast:
        loss = model(**move_batch(batch, device)).loss
    if loss is None or not torch.isfinite(loss):
        raise RuntimeError(f"RF-DETR returned an invalid loss: {loss}")
    return loss


def train_epoch(model, loader, optimizer, device, *, amp: bool, scaler, accumulate: int, ema) -> float:
    """One training epoch: gradients accumulated over ``accumulate`` batches, clipped (``RF_DETR_GRAD_CLIP``), the
    EMA updated after every optimizer step. Returns the mean loss."""
    import torch

    model.train()
    total, count = 0.0, 0
    optimizer.zero_grad(set_to_none=True)
    batches = len(loader)
    for step, batch in enumerate(loader, start=1):
        loss = _loss(model, batch, device, amp)
        scaler.scale(loss / accumulate).backward()
        if step % accumulate == 0 or step == batches:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=K.RF_DETR_GRAD_CLIP)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)
            ema.update_parameters(model)
        total += float(loss.detach())
        count += 1
    return total / max(1, count)


def validation_loss(model, loader, device, *, amp: bool) -> float:
    """The mean loss over the validation tiles (each screenshot's densest tile), a diagnostic only."""
    import torch

    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for batch in loader:
            total += float(_loss(model, batch, device, amp))
            count += 1
    return total / max(1, count)


def evaluate_split(model, processor, split, label_map: dict[str, str], device) -> dict[str, Any]:
    """The task metrics (``rf_detr_eval``) of a model on one split: the whole tiled inference on every screenshot."""
    import cv2
    import numpy as np

    model.eval()
    families = class_families({int(i): name for i, name in label_map.items()})
    names = [label_map[str(i)] for i in range(len(label_map))]
    predictions, truths = [], []
    for example in split:
        rgb = np.asarray(example["image"].convert("RGB"))
        image, boxes = normalise(rgb, example["objects"]["bbox"])
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        predictions.append(predict_tiles(model, processor, bgr, families, device, threshold=0.05))
        truths.append(
            [
                {"label": names[int(c)], "box": [x, y, x + w, y + h]}
                for c, (x, y, w, h) in zip(example["objects"]["category"], boxes, strict=True)
            ]
        )
    return evaluate(predictions, truths)


def parameter_groups(model, *, learning_rate: float, weight_decay: float, layer_decay: float) -> list[dict[str, Any]]:
    """AdamW parameter groups: the backbone's layers at ``layer_lr_scale`` of the rate, biases and norms without
    weight decay."""
    layers = int(getattr(getattr(model.config, "backbone_config", None), "num_hidden_layers", 12))
    groups: dict[tuple[float, float], list] = {}
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        scale = layer_lr_scale(name, layers, layer_decay)
        decay = 0.0 if param.ndim <= 1 or name.endswith(".bias") else weight_decay
        groups.setdefault((scale, decay), []).append(param)
    return [
        {"params": params, "lr": learning_rate * scale, "weight_decay": decay}
        for (scale, decay), params in sorted(groups.items())
    ]


def remap_class_heads(model, init_dir: Path, label_map: dict[str, str]) -> int:
    """Copy each class's rows of the earlier checkpoint's class heads into ``model`` by name (``warm_start_rows``).

    Returns:
        How many classes took a row from the earlier checkpoint.
    """
    import torch
    from safetensors.torch import load_file

    old_labels = json.loads((init_dir / "labels.json").read_text(encoding="utf-8"))
    old_names = [old_labels[str(i)] for i in range(len(old_labels))]
    new_names = [label_map[str(i)] for i in range(len(label_map))]
    rows = warm_start_rows(old_names, new_names)
    state = {}
    for file in sorted(init_dir.glob("*.safetensors")):
        state.update(load_file(str(file)))
    params = dict(model.named_parameters())
    with torch.no_grad():
        for name, old in state.items():
            if "class_embed" not in name or name not in params or old.shape[0] != len(old_names):
                continue
            new = params[name]
            for index, row in enumerate(rows):
                if row is not None:
                    new[index].copy_(old[row].to(new.dtype))
    return sum(row is not None for row in rows)


def ema_update(decay: float, tau: float):
    """The EMA step for ``AveragedModel``: decay warmed up as ``decay * (1 - exp(-steps / tau))``."""
    import torch

    def update(averaged, current, averaged_steps) -> None:
        warm = decay * (1 - math.exp(-(float(averaged_steps) + 1) / tau))
        torch._foreach_lerp_(averaged, current, 1 - warm)

    return update


class RepeatFactorSampler:
    """Each epoch's training draws: every screenshot ``RF_DETR_TILES_PER_IMAGE`` x its repeat factor times
    (``rf_detr_tiles.epoch_indices``; each draw is a fresh random tile)."""

    def __init__(self, factors: list[float], per_image: int, seed: int) -> None:
        self.factors = factors
        self.per_image = per_image
        self.seed = seed
        self.epoch = 0

    def __iter__(self):
        indices = epoch_indices(self.factors, self.per_image, random.Random(self.seed + self.epoch))
        self.epoch += 1
        return iter(indices)

    def __len__(self) -> int:
        return round(sum(self.per_image * f for f in self.factors))


def save_model(model, processor, output_dir: Path, label_map: dict[str, str]) -> None:
    """Save a Transformers-compatible model, processor and label map."""
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir, safe_serialization=True)
    processor.save_pretrained(output_dir)
    (output_dir / "labels.json").write_text(json.dumps(label_map, indent=2) + "\n", encoding="utf-8")


def replace_checkpoint(model, processor, best_dir: Path, label_map: dict[str, str]) -> None:
    """Save a new best checkpoint beside the current one and switch them only once it is complete.

    A failed or interrupted save leaves the previous best in place; during the switch it is kept as
    ``<best>.previous`` (deleted once the new one is in place), so it can always be recovered.
    """
    staging = best_dir.with_name(f"{best_dir.name}.new")
    previous = best_dir.with_name(f"{best_dir.name}.previous")
    if staging.exists():
        shutil.rmtree(staging)
    save_model(model, processor, staging, label_map)
    if previous.exists():
        shutil.rmtree(previous)
    if best_dir.exists():
        best_dir.rename(previous)
    staging.rename(best_dir)
    shutil.rmtree(previous, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse dataset and fine-tuning options."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--annotator-manifest",
        type=Path,
        default=None,
        help="manifest.json exported by tools.detection_dataset_annotator (needed unless --reuse-dataset)",
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
    parser.add_argument("--init-from", type=Path, default=None, help="an earlier checkpoint to go on from")
    parser.add_argument("--epochs", type=int, default=100, help="most epochs; --patience usually stops sooner")
    parser.add_argument("--patience", type=int, default=K.RF_DETR_PATIENCE)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=4, help="batches per optimizer step")
    parser.add_argument("--learning-rate", type=float, default=K.RF_DETR_LEARNING_RATE)
    parser.add_argument("--layer-decay", type=float, default=K.RF_DETR_LAYER_DECAY)
    parser.add_argument("--ema-decay", type=float, default=K.RF_DETR_EMA_DECAY)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--tiles-per-image", type=int, default=K.RF_DETR_TILES_PER_IMAGE)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or mps")
    parser.add_argument("--max-images", type=int, default=None, help="limit images for a smoke test")
    parser.add_argument("--no-amp", action="store_true", help="disable CUDA mixed precision")
    return parser.parse_args(argv)


def _validate_target_count(largest: int) -> None:
    """Reject screenshots denser than RF-DETR Small's query budget (tiles hold far fewer objects)."""
    if largest > K.RF_DETR_MAX_TARGETS:
        raise ValueError(f"one training image has {largest} objects, above RF-DETR's {K.RF_DETR_MAX_TARGETS} queries")


def _device(name: str):
    """Choose a supported torch device without probing unavailable accelerators."""
    import torch

    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    return torch.device(name)


def _processor(model_name: str | Path):
    """The checkpoint's processor, sized to one tile (tiles are seen at their own size)."""
    from transformers import AutoImageProcessor

    processor = AutoImageProcessor.from_pretrained(model_name)
    processor.size = {"height": K.RF_DETR_TILE, "width": K.RF_DETR_TILE}
    return processor


def _load_or_build_dataset(args: argparse.Namespace):
    """Build the Arrow dataset from the manifest or load a previously saved one, with its labels."""
    dataset_dir = args.dataset_dir or args.output_dir / "dataset"
    if args.reuse_dataset:
        from datasets import load_from_disk

        dataset = load_from_disk(str(dataset_dir))
        assert isinstance(dataset, DatasetDict)
        label_file = dataset_dir / "labels.json"
        if not label_file.is_file():
            raise FileNotFoundError(f"reused dataset has no labels.json: {label_file}")
        return dataset, json.loads(label_file.read_text(encoding="utf-8")), dataset_dir
    if args.annotator_manifest is None:
        raise SystemExit("--annotator-manifest is needed (export the dataset from the annotator first)")
    records, label_map = load_annotator_manifest(args.annotator_manifest, max_images=args.max_images)
    _validate_target_count(max(len(record.annotations) for record in records))
    if args.overwrite_dataset and dataset_dir.exists():
        if dataset_dir.is_file():
            raise ValueError(f"dataset path is a file, not a directory: {dataset_dir}")
        shutil.rmtree(dataset_dir)
    dataset = build_dataset(records, label_map=label_map, output_dir=dataset_dir)
    return dataset, label_map, dataset_dir


def main(argv: list[str] | None = None) -> int:
    """Prepare the dataset, then fine-tune and save the best RF-DETR checkpoint."""
    args = parse_args(argv)
    dataset, label_map, dataset_dir = _load_or_build_dataset(args)
    sizes = {split: len(rows) for split, rows in dataset.items()}
    print(f"dataset: {sizes} -> {dataset_dir}")
    print(f"classes ({len(label_map)}): {', '.join(label_map.values())}")
    if args.dataset_only:
        return 0

    import torch
    from torch.optim.swa_utils import AveragedModel
    from torch.utils.data import DataLoader
    from transformers import AutoModelForObjectDetection

    torch.manual_seed(args.seed)
    base = args.init_from or K.RF_DETR_MODEL_NAME
    processor = _processor(base)
    id2label = {int(index): name for index, name in label_map.items()}
    label2id = {name: index for index, name in id2label.items()}
    model = AutoModelForObjectDetection.from_pretrained(
        base, id2label=id2label, label2id=label2id, num_labels=len(label_map), ignore_mismatched_sizes=True
    )
    model.config.id2label, model.config.label2id, model.config.num_labels = id2label, label2id, len(label_map)
    if args.init_from is not None:
        kept = remap_class_heads(model, args.init_from, label_map)
        print(f"--init-from {args.init_from}: {kept} of {len(label_map)} classes start from its rows")

    device = _device(args.device)
    model.to(device)
    amp = not args.no_amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    categories = [list(objects["category"]) for objects in dataset["train"]["objects"]]
    rare = frozenset(rare_classes(categories))
    sampler = RepeatFactorSampler(repeat_factors(categories), args.tiles_per_image, args.seed)
    loader_kwargs = {"num_workers": args.workers, "pin_memory": device.type == "cuda", "collate_fn": collate_fn}
    train_loader = DataLoader(
        dataset["train"].with_transform(tile_transform(processor, train=True, seed=args.seed, rare=rare)),
        batch_size=args.batch_size,
        sampler=sampler,
        **loader_kwargs,
    )
    validation_loader = DataLoader(
        dataset["validation"].with_transform(tile_transform(processor, train=False)),
        batch_size=args.batch_size,
        **loader_kwargs,
    )
    optimizer = torch.optim.AdamW(
        parameter_groups(
            model, learning_rate=args.learning_rate, weight_decay=args.weight_decay, layer_decay=args.layer_decay
        )
    )
    ema = AveragedModel(model, multi_avg_fn=ema_update(args.ema_decay, K.RF_DETR_EMA_TAU), use_buffers=True)
    best_dir = args.output_dir / "best"
    best_score, best_epoch, best_report, history = -1.0, 0, "", []
    started = time.time()
    for epoch in range(1, args.epochs + 1):
        train_loss = train_epoch(
            model, train_loader, optimizer, device, amp=amp, scaler=scaler, accumulate=args.grad_accum, ema=ema
        )
        val_loss = validation_loss(ema.module, validation_loader, device, amp=amp)
        metrics = evaluate_split(ema.module, processor, dataset["validation"], label_map, device)
        history.append({"epoch": epoch, "train_loss": train_loss, "val_loss": val_loss, "val_map": metrics["mean_ap"]})
        print(
            f"epoch {epoch:03d}: train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
            f"val_mean_ap={metrics['mean_ap']:.4f}"
        )
        if metrics["mean_ap"] > best_score:
            best_score, best_epoch, best_report = metrics["mean_ap"], epoch, format_report(metrics)
            replace_checkpoint(copy.deepcopy(ema.module).cpu(), processor, best_dir, label_map)
            print(f"saved {best_dir} (best validation mean AP)\n{best_report}")
        elif epoch - best_epoch >= args.patience:
            print(f"no better validation score for {args.patience} epochs: stopping")
            break

    test_metrics = None
    if len(dataset["test"]) and best_dir.is_dir():
        best = AutoModelForObjectDetection.from_pretrained(best_dir).to(device)
        test_metrics = evaluate_split(best, processor, dataset["test"], label_map, device)
        print(f"test split (best checkpoint):\n{format_report(test_metrics)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "training_summary.json").write_text(
        json.dumps(
            {
                "base_model": str(base),
                "dataset_dir": str(dataset_dir),
                "screenshots": sizes,
                "classes": label_map,
                "tile": K.RF_DETR_TILE,
                "recipe": {
                    "learning_rate": args.learning_rate,
                    "layer_decay": args.layer_decay,
                    "ema_decay": args.ema_decay,
                    "batch_size": args.batch_size,
                    "grad_accum": args.grad_accum,
                    "tiles_per_image": args.tiles_per_image,
                    "flip_probability": K.RF_DETR_AUGMENT_FLIP_PROBABILITY,
                    "render_probability": K.RF_DETR_AUGMENT_RENDER_PROBABILITY,
                    "scale_jitter": K.RF_DETR_AUGMENT_SCALE_JITTER,
                    "seed": args.seed,
                },
                "best_epoch": best_epoch,
                "best_validation_mean_ap": best_score,
                "test": test_metrics,
                "history": history,
                "device": str(device),
                "seconds": round(time.time() - started, 1),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"done: {best_dir}  best validation mean AP {best_score:.4f} (epoch {best_epoch})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
