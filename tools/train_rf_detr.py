"""Fine-tune RF-DETR on the screenshots the dataset annotator exports, with transformers' Trainer.

The data is the annotator's ``manifest.json``: its screenshots, each with the train / validation / test split the
split ledger keeps (``tools/detection_dataset_annotator``). Reviewed screenshots are the training data; with
``--truth-seeded`` the unreviewed screenshots a hand-labelled biome truth seeded join them (a bootstrap round: their
city areas and citadels are the truth's, every other box the classical detector's). Before a dataset is built, its
manifest is checked against the split ledger: a screenshot never changes split between rounds.

Build the dataset only (``make prepare_rf_detr_data`` does this for the annotator's default export):

    python -m tools.train_rf_detr --annotator-manifest DATASET/manifest.json --dataset-only

Train on a GPU (``make train_rf_detr RF_DETR_ANNOTATOR_MANIFEST=...``):

    python -m tools.train_rf_detr --annotator-manifest DATASET/manifest.json --output-dir runs/rf-detr-small

Go on from an earlier model into a new output folder, on a new export or on the data that model was trained on:

    python -m tools.train_rf_detr --annotator-manifest NEW/manifest.json --output-dir runs/rf-detr-small-2 \\
        --init-from runs/rf-detr-small/best
    python -m tools.train_rf_detr --reuse-dataset --dataset-dir runs/rf-detr-small/dataset \\
        --output-dir runs/rf-detr-small-2 --init-from runs/rf-detr-small/best

Resume an interrupted run from its last checkpoint (the newest with its EMA): the same command with ``--resume``
(the run's saved dataset is used again; a checkpoint trained on other screenshots is refused).

What the model sees: native-scale tiles of the 1080p screenshots with the game HUD painted over
(``grand_project.detect.rf_detr_tiles``): random tiles in training (scale jitter, tiles centred on rare classes,
render-scale blur, brightness and contrast; screenshots with rare classes drawn more often, LVIS repeat factors;
never mirrored, the atlas is not), the whole tiled inference for evaluation.

The recipe is the RF-DETR paper's (Appendix A) as the official roboflow/rf-detr trains it (``RF_DETR_*`` in
``grand_project/detect/constants.py``): AdamW with the DINOv2 backbone at its own rate, decayed per layer and per
component; an exponential moving average (EMA) of the weights, which is what is evaluated and kept; no warm-up and a
constant rate (the run stops when validation stops improving); gradient clipping 0.1; batches of 4 tiles, 16 per
optimizer step; bf16 where the GPU has it. The fine-tuned class heads (the decoder's and the 13 encoder heads) start
from the pre-trained checkpoint's own rows, as the reference does. The best checkpoint is the EMA weights' best
validation mean family AP (``rf_detr_eval``: the program needs where objects are, not tight boxes); the test split
is scored once, with the best checkpoint.

``--init-from`` takes each class's rows from the earlier checkpoint by name (a class it had keeps its rows, a class
with a ``parent`` it had starts from that row, any other from the reference's tiling of the earlier rows).

Training dependencies are optional: ``pip install -e '.[training]'``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from grand_project.detect import constants as K
from grand_project.detect.labels import warm_start_rows
from grand_project.detect.rf_detr import build_dataset, load_annotator_manifest, load_dataset, tile_transform
from grand_project.detect.rf_detr_cuda import prefer_pip_cuda_libraries
from grand_project.detect.rf_detr_eval import evaluate, format_report
from grand_project.detect.rf_detr_model import class_families, model_folder, predict_tiles, trained_on
from grand_project.detect.rf_detr_tiles import (
    backbone_weight_decay,
    epoch_indices,
    epoch_length,
    layer_lr_scale,
    normalise,
    rare_classes,
    repeat_factors,
)

# Before anything imports torch (``datasets`` and ``transformers`` do): the process restarts itself once with
# PyTorch's own CUDA libraries first (``rf_detr_cuda``).
if __name__ == "__main__":  # only a training run restarts itself; importing this module (tests) never does
    prefer_pip_cuda_libraries()

import torch  # noqa: E402
from datasets import DatasetDict  # noqa: E402
from torch.optim.swa_utils import AveragedModel  # noqa: E402
from transformers import (  # noqa: E402
    AutoImageProcessor,
    AutoModelForObjectDetection,
    EarlyStoppingCallback,
    PreTrainedModel,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)
from transformers.trainer import TRAINING_ARGS_NAME  # noqa: E402

EMA_DIR = "ema"
"""The folder inside each checkpoint holding the EMA weights (a Transformers model folder)."""

EMA_STATE = "ema_state.json"
"""The EMA's update count, next to its weights (the decay's warm-up goes on from it on --resume)."""


def collate_fn(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """Stack transformed processor outputs while retaining DETR's per-image target dictionaries."""

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


# ---- the model --------------------------------------------------------------------------------------------------


def _class_heads(model) -> list[tuple[Any, str, torch.nn.Linear]]:
    """Every class head of an RF-DETR: the decoder's ``class_embed`` and the encoder's ``enc_out_class_embed`` (one
    per Group DETR group), as (owner, attribute or index, layer)."""
    heads: list[tuple[Any, str, torch.nn.Linear]] = [(model, "class_embed", model.class_embed)]
    encoder_heads = getattr(getattr(model, "model", None), "enc_out_class_embed", None)
    for index, layer in enumerate(encoder_heads or []):
        heads.append((encoder_heads, str(index), layer))
    return heads


def resize_class_heads(model, rows: list[int]) -> None:
    """Give every class head of ``model`` one row per new class: new class ``i`` copies the old row ``rows[i]``.

    The reference implementation (roboflow/rf-detr ``reinitialize_detection_head``) starts a fine-tuned head from
    the pre-trained head's rows, truncated or tiled (``rows = [i % old]``), not from random rows: the encoder heads
    choose the decoder's queries, and pre-trained rows know what an object looks like.
    """
    for owner, attribute, layer in _class_heads(model):
        new = torch.nn.Linear(layer.in_features, len(rows), bias=layer.bias is not None)
        new.to(device=layer.weight.device, dtype=layer.weight.dtype)
        with torch.no_grad():
            new.weight.copy_(layer.weight[rows])
            if layer.bias is not None:
                new.bias.copy_(layer.bias[rows])
        if isinstance(owner, torch.nn.ModuleList):
            owner[int(attribute)] = new
        else:
            setattr(owner, attribute, new)


def set_labels(model, label_map: dict[str, str]) -> None:
    """Name the model's classes (the loss reads ``num_labels``, inference the names)."""
    id2label = {int(index): name for index, name in label_map.items()}
    model.config.id2label = id2label
    model.config.label2id = {name: index for index, name in id2label.items()}
    model.config.num_labels = len(id2label)


def load_model(base: str | Path, label_map: dict[str, str]):
    """The model to fine-tune, with one class head row per class of ``label_map``.

    The pre-trained checkpoint (``RF_DETR_MODEL_NAME`` at ``RF_DETR_MODEL_REVISION``) keeps its first rows (the
    reference's truncation); an earlier checkpoint of ours (``--init-from``) gives each class its own row by name,
    a new class with a ``parent`` its parent's row, any other the reference's tiling of the earlier rows.
    """
    pretrained = str(base) == K.RF_DETR_MODEL_NAME
    model = AutoModelForObjectDetection.from_pretrained(
        base, revision=K.RF_DETR_MODEL_REVISION if pretrained else None, use_safetensors=True
    )
    new_names = [label_map[str(index)] for index in range(len(label_map))]
    old = model.class_embed.out_features
    if pretrained:
        rows = [index % old for index in range(len(new_names))]
    else:
        old_names = [model.config.id2label[index] for index in range(old)]
        rows = [
            row if row is not None else index % old for index, row in enumerate(warm_start_rows(old_names, new_names))
        ]
    resize_class_heads(model, rows)
    set_labels(model, label_map)
    return model


def load_processor(source: str | Path):
    """The checkpoint's image processor, sized to one tile (tiles are seen at their own size)."""
    pretrained = str(source) == K.RF_DETR_MODEL_NAME
    return AutoImageProcessor.from_pretrained(
        source,
        revision=K.RF_DETR_MODEL_REVISION if pretrained else None,
        size={"height": K.RF_DETR_TILE, "width": K.RF_DETR_TILE},
    )


def parameter_groups(
    model,
    *,
    learning_rate: float,
    lr_encoder: float,
    layer_decay: float,
    component_decay: float,
    weight_decay: float,
) -> list[dict[str, Any]]:
    """AdamW parameter groups, as the reference implementation builds them (roboflow/rf-detr
    ``training/param_groups.py``, ``models/backbone/backbone.py``):

    - the DINOv2 backbone at ``lr_encoder`` x ``layer_lr_scale`` x ``component_decay`` squared, without weight decay
      on its layer scales, embeddings, biases and norms;
    - the decoder at ``learning_rate`` x ``component_decay``;
    - everything else (the projector, the heads, the queries) at ``learning_rate``;
    - outside the backbone, biases and norms (one-dimensional parameters) without weight decay.
    """
    layers = int(model.config.backbone_config.out_indices[-1]) + 1
    groups: dict[tuple[float, float], list] = {}
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if "backbone.backbone." in name:
            rate = lr_encoder * layer_lr_scale(name, layers, layer_decay) * component_decay**2
            decay = weight_decay if backbone_weight_decay(name) else 0.0
        else:
            rate = learning_rate * (component_decay if name.startswith("model.decoder.") else 1.0)
            decay = 0.0 if param.ndim <= 1 or name.endswith(".bias") else weight_decay
        groups.setdefault((rate, decay), []).append(param)
    return [{"params": params, "lr": rate, "weight_decay": decay} for (rate, decay), params in sorted(groups.items())]


def save_native(model, folder: Path, state_dict: dict | None = None) -> None:
    """Save a model in transformers' own key layout, not RF-DETR's default original (Roboflow) one: the Trainer
    reloads a checkpoint's weights file as it is (the best model at the end, --resume), without the key conversion
    ``from_pretrained`` does, so an original-layout checkpoint would load nothing. ``from_pretrained`` reads both."""
    model.save_pretrained(folder, state_dict=state_dict, save_original_format=False)


# ---- training pieces ---------------------------------------------------------------------------------------------


def ema_update(decay: float, tau: float):
    """The EMA step for ``AveragedModel``: decay warmed up as ``decay * (1 - exp(-updates / tau))`` (the reference's
    ``RFDETREMACallback``, 1-indexed updates)."""

    def update(averaged, current, averaged_steps) -> None:
        warm = decay * (1 - math.exp(-(float(averaged_steps) + 1) / tau))
        torch._foreach_lerp_(averaged, current, 1 - warm)

    return update


def _checkpoint_step(path: Path) -> int | None:
    """The step of a ``checkpoint-N`` folder, or None for anything else."""
    prefix = "checkpoint-"
    if path.is_dir() and path.name.startswith(prefix) and path.name[len(prefix) :].isdigit():
        return int(path.name[len(prefix) :])
    return None


def ema_complete(checkpoint: Path) -> bool:
    """Whether a checkpoint holds its whole EMA: the weights and the update count (``EmaCallback.on_save`` writes them
    after the Trainer's own files, so a run stopped in between leaves a checkpoint without them)."""
    folder = Path(checkpoint) / EMA_DIR
    weights = (folder / "model.safetensors").is_file() or (folder / "model.safetensors.index.json").is_file()
    return weights and (folder / EMA_STATE).is_file()


def last_complete_checkpoint(checkpoints: Path) -> Path | None:
    """The newest ``checkpoint-N`` with its whole EMA (``ema_complete``), for ``--resume``; newer ones without it
    are passed over (said so), or None when there is none."""
    if not checkpoints.is_dir():
        return None
    found = sorted(
        (path for path in checkpoints.iterdir() if _checkpoint_step(path) is not None),
        key=_checkpoint_step,
        reverse=True,
    )
    for path in found:
        if ema_complete(path):
            return path
        print(f"--resume: {path.name} has no complete EMA ({EMA_DIR}/), passed over", flush=True)
    return None


class EmaCallback(TrainerCallback):
    """An exponential moving average of the weights, updated after every optimizer step and saved into every
    checkpoint (``<checkpoint>/ema``): it is the model the run evaluates and keeps.

    Args:
        decay: the EMA's decay per optimizer step.
        tau: optimizer steps over which the decay warms up.
        resume_from: a checkpoint whose EMA to go on from (``--resume``).
    """

    def __init__(self, decay: float, tau: float, resume_from: Path | None = None) -> None:
        self.decay = decay
        self.tau = tau
        self.resume_from = resume_from
        self.ema: AveragedModel | None = None
        self.step_skipped = lambda: False
        """Whether the optimizer step just taken was skipped (an fp16 overflow): ``RfDetrTrainer`` sets it."""

    def on_train_begin(self, args, state, control, model=None, **kwargs):
        if self.ema is not None or model is None:
            return
        self.ema = AveragedModel(model, multi_avg_fn=ema_update(self.decay, self.tau), use_buffers=True)
        self.ema.module.eval()
        if self.resume_from is None:
            return
        saved = self.resume_from / EMA_DIR
        if not ema_complete(self.resume_from):
            # a fresh EMA with no updates would replace the averaged weights the run evaluates and keeps
            raise RuntimeError(f"{self.resume_from} has no complete EMA ({EMA_DIR}/ weights and {EMA_STATE})")
        weights = AutoModelForObjectDetection.from_pretrained(saved, use_safetensors=True).state_dict()
        self.ema.module.load_state_dict(weights)
        count = json.loads((saved / EMA_STATE).read_text(encoding="utf-8"))["updates"]
        self.ema.n_averaged.fill_(int(count))

    def on_step_end(self, args, state, control, model=None, **kwargs):
        # one update per optimizer step that ran: a skipped one left the weights as they were
        if self.ema is not None and model is not None and not self.step_skipped():
            self.ema.update_parameters(model)

    def on_save(self, args, state, control, **kwargs):
        if self.ema is None:
            return
        folder = Path(args.output_dir) / f"checkpoint-{state.global_step}" / EMA_DIR
        if isinstance(self.ema.module, PreTrainedModel):
            save_native(self.ema.module, folder)
        else:  # a stand-in model (tests)
            self.ema.module.save_pretrained(folder)
        # the counter marks the EMA whole (ema_complete): written beside it, renamed into place once complete
        partial = folder / f"{EMA_STATE}.tmp"
        partial.write_text(json.dumps({"updates": int(self.ema.n_averaged.item())}), encoding="utf-8")
        os.replace(partial, folder / EMA_STATE)

    def model(self, fallback):
        """The EMA model (eval mode), or ``fallback`` before training began."""
        return fallback if self.ema is None else self.ema.module


class MembershipCallback(TrainerCallback):
    """Writes the run's training screenshots and its dataset's identity into every checkpoint
    (``RF_DETR_TRAINED_ON``, ``RF_DETR_DATASET_ID``), so --resume can refuse a checkpoint trained on other data
    (``check_resume_sources``).

    Listed before the EMA's callback: a checkpoint with its whole EMA (``ema_complete``, written last) has both.
    """

    def __init__(self, sources: list[str], dataset_id: str, inherited: set[str] = frozenset()) -> None:
        self.sources = sorted(sources)
        self.trained = sorted(set(sources) | set(inherited))  # what the weights learned: the model gone on from's too
        self.dataset_id = dataset_id

    def on_save(self, args, state, control, **kwargs):
        folder = Path(args.output_dir) / f"checkpoint-{state.global_step}"
        folder.mkdir(parents=True, exist_ok=True)
        _write_list(folder / K.RF_DETR_TRAINED_ON, self.trained)
        _write_list(folder / K.RF_DETR_RUN_SOURCES, self.sources)
        (folder / K.RF_DETR_DATASET_ID).write_text(self.dataset_id, encoding="utf-8")


def _write_list(path: Path, names: list[str]) -> None:
    """A list of screenshots, one a line."""
    path.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")


def ancestry(init_from: Path | None) -> set[str]:
    """What the model a run goes on from trained on (``trained_on``); nothing for the pre-trained checkpoint (None).

    Raises:
        SystemExit: the model lists no training screenshots: the new model's list would miss them.
    """
    if init_from is None:
        return set()
    listed = trained_on(init_from)
    if listed is None:
        raise SystemExit(
            f"{init_from} lists no training screenshots ({K.RF_DETR_TRAINED_ON}): a model gone on from it would not "
            "know what it trained on; train it with tools.train_rf_detr, which writes the list"
        )
    return listed


def checkpoints_to_keep(checkpoints: Path, best: str | None) -> set[Path]:
    """The checkpoints a run must keep: the newest whole one (``ema_complete``: what --resume goes on from), the best
    so far, and the best each kept one's ``trainer_state.json`` names (a resume from it loads that one at the end)."""
    found = sorted((path for path in checkpoints.iterdir() if _checkpoint_step(path) is not None), key=_checkpoint_step)
    keep = set(found[-1:])  # the one just saved (its EMA written by now)
    whole = [path for path in found if ema_complete(path)]
    keep |= set(whole[-1:])
    if best:
        keep.add(Path(best))
    for path in list(keep):
        state_file = path / "trainer_state.json"
        if state_file.is_file():
            named = json.loads(state_file.read_text(encoding="utf-8")).get("best_model_checkpoint")
            if named:
                keep.add(Path(named))
    return {path.resolve() for path in keep}


class PruneCallback(TrainerCallback):
    """Deletes the checkpoints no longer needed (``checkpoints_to_keep``), after a checkpoint's EMA is written.

    In place of the Trainer's ``save_total_limit``, which deletes before the callbacks write the EMA: a run stopped in
    between kept no whole checkpoint to resume from, or one whose best was deleted. Listed after the EMA's callback.
    """

    def on_save(self, args, state, control, **kwargs):
        folder = Path(args.output_dir)
        keep = checkpoints_to_keep(folder, state.best_model_checkpoint)
        for path in folder.iterdir():
            if _checkpoint_step(path) is not None and path.resolve() not in keep:
                shutil.rmtree(path, ignore_errors=True)


class RepeatFactorSampler(torch.utils.data.Sampler):
    """Each epoch's training draws: every screenshot ``tiles_per_image`` x its repeat factor times
    (``rf_detr_tiles.epoch_indices``, always ``epoch_length`` draws; each draw is a fresh random tile)."""

    def __init__(self, factors: list[float], per_image: int, seed: int) -> None:
        self.factors = factors
        self.per_image = per_image
        self.seed = seed
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __iter__(self):
        import random

        indices = epoch_indices(self.factors, self.per_image, random.Random(self.seed + self.epoch))
        self.epoch += 1
        return iter(indices)

    def __len__(self) -> int:
        return epoch_length(self.factors, self.per_image)


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


def metric_items(result: dict[str, Any], prefix: str) -> dict[str, float]:
    """``rf_detr_eval.evaluate``'s result as flat metrics: ``<prefix>_mean_ap`` and each family's AP, precision,
    recall and class accuracy."""
    out = {f"{prefix}_mean_ap": float(result["mean_ap"])}
    for family, values in sorted(result["families"].items()):
        for name in ("ap", "precision", "recall", "class_accuracy"):
            out[f"{prefix}_{family}_{name}"] = float(values[name])
    return out


class RfDetrTrainer(Trainer):
    """transformers' Trainer with the RF-DETR recipe: its parameter groups, the repeat-factor sampler, and an
    evaluation of the EMA weights by the production tiled inference.

    Args:
        ema: the run's ``EmaCallback`` (also passed in ``callbacks``).
        sampler: the training sampler.
        recipe: ``parameter_groups``'s keyword arguments.
        label_map: class id -> name.
    """

    # The detection labels are lists of dicts, which the Trainer cannot count: the loss it gets is the mean over a
    # batch, to be divided over the accumulated batches (None would decide from RF-DETR's **kwargs forward).
    loss_is_scaled_for_ga = False

    def __init__(
        self,
        *args,
        ema: EmaCallback,
        sampler: RepeatFactorSampler,
        recipe: dict[str, float],
        label_map: dict[str, str],
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ema = ema
        ema.step_skipped = lambda: bool(self.accelerator.optimizer_step_was_skipped)
        self.sampler = sampler
        self.recipe = recipe
        self.label_map = label_map

    def _save(self, output_dir: str | None = None, state_dict: dict | None = None) -> None:
        """A checkpoint as the Trainer saves one, its weights in transformers' own key layout (``save_native``)."""
        if not self.args.should_save:  # the Trainer's own writer check: only the designated process writes
            return
        model = self.accelerator.unwrap_model(self.model, keep_torch_compile=False)
        if not isinstance(model, PreTrainedModel):
            super()._save(output_dir, state_dict)
            return
        folder = Path(output_dir or self.args.output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        save_native(model, folder, state_dict)
        if self.processing_class is not None:
            self.processing_class.save_pretrained(folder)
        torch.save(self.args, folder / TRAINING_ARGS_NAME)

    def create_optimizer(self, model=None):
        if self.optimizer is None:
            self.optimizer = torch.optim.AdamW(parameter_groups(model or self.model, **self.recipe))
        return self.optimizer

    def _get_train_sampler(self, train_dataset=None):
        return self.sampler

    def evaluate(self, eval_dataset=None, ignore_keys=None, metric_key_prefix: str = "eval") -> dict[str, float]:
        """Score the EMA weights on whole screenshots (``evaluate_split``) and tell the callbacks (early stopping,
        the best checkpoint) as the Trainer's own evaluation does."""
        started = time.time()
        split = self.eval_dataset if eval_dataset is None else eval_dataset
        model = self.ema.model(self.model)
        result = evaluate_split(model, self.processing_class, split, self.label_map, self.args.device)
        metrics = metric_items(result, metric_key_prefix)
        metrics[f"{metric_key_prefix}_runtime"] = round(time.time() - started, 2)
        self.log(metrics)
        self.control = self.callback_handler.on_evaluate(self.args, self.state, self.control, metrics)
        print(f"epoch {self.state.epoch or 0:.0f} {metric_key_prefix} (EMA):\n{format_report(result)}", flush=True)
        return metrics


# ---- folders -----------------------------------------------------------------------------------------------------


def swap_in(staging: Path, target: Path) -> None:
    """Put the complete folder ``staging`` at ``target``; the old ``target`` is kept as ``<target>.previous`` until the
    new one is in place, so it can always be recovered.

    A ``<target>.previous`` without a ``target`` (a switch interrupted before) is the last good folder: it is kept
    until the new one is in place. If the switch fails, the old folder is put back.
    """
    previous = target.with_name(f"{target.name}.previous")
    if target.exists():
        if previous.exists():
            shutil.rmtree(previous)
        target.rename(previous)
    try:
        staging.rename(target)
    except BaseException:
        if previous.exists() and not target.exists():
            previous.rename(target)
        raise
    shutil.rmtree(previous, ignore_errors=True)


def export_best(checkpoint: Path, processor, best_dir: Path, label_map: dict[str, str], sources: list[str]) -> None:
    """Put a checkpoint's EMA weights, the processor, the label map and the screenshots trained on
    (``RF_DETR_TRAINED_ON``: this run's and those of the model it went on from) at ``best_dir`` (the folder the program
    loads), switched in only once complete (``swap_in``)."""
    staging = best_dir.with_name(f"{best_dir.name}.new")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(checkpoint / EMA_DIR, staging, ignore=shutil.ignore_patterns(EMA_STATE))
    processor.save_pretrained(staging)
    (staging / "labels.json").write_text(json.dumps(label_map, indent=2) + "\n", encoding="utf-8")
    _write_list(staging / K.RF_DETR_TRAINED_ON, sorted(sources))
    swap_in(staging, best_dir)


def _git_commit() -> str | None:
    """The project's git commit, or None outside a git checkout."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


# ---- the dataset -------------------------------------------------------------------------------------------------


def _check_ledger(manifest: dict[str, Any], base: Path) -> tuple[str, list]:
    """Stop when the manifest's splits disagree with the split ledger (a screenshot a model trained on must stay in
    train); returns the ledger's SHA-256 for the run's record and its rows, from one read of the file: the check, the
    recorded SHA-256 and the dataset's byte check (``_ledger_bytes``) are of one version of the ledger.

    Args:
        manifest: the parsed manifest (the same read the dataset is built from).
        base: its folder (its relative paths lie there, as the dataset reads them).
    """
    from tools.detection_dataset_annotator.split_ledger import check_manifest, ledger_snapshot

    rows, sha = ledger_snapshot()
    problems = check_manifest(manifest, base=base, rows=rows)
    if problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise SystemExit(f"the manifest's splits disagree with the split ledger:\n  {shown}{more}")
    return sha, rows


def _ledger_bytes(rows: list):
    """``build_dataset``'s ``check_bytes``: the bytes a screenshot is built from (read once and embedded) must be the
    ones its manifest row was exported with (``Record.sha256``) and ones the split ledger (``rows``,
    the snapshot the manifest was checked against) keeps with the screenshot's split. The ledger check vouched for the
    files as they were then; a file replaced since is stopped here, not trained on under a split it never had."""
    book: dict[str, Any] = {}
    for entry in rows:
        book.setdefault(entry.sha256, entry)

    def check(record, digest: str) -> None:
        if digest != record.sha256:
            raise SystemExit(
                f"{record.path} changed since it was exported: its bytes are not the ones the manifest names; "
                "export again"
            )
        entry = book.get(digest)
        if entry is None or entry.split != record.split:
            where = "is not in the split ledger" if entry is None else f"is {entry.split} in the split ledger"
            raise SystemExit(
                f"{record.path} changed since the ledger check: its bytes {where} (the manifest says {record.split}); "
                "export again"
            )

    return check


def _published(dataset_dir: Path) -> bool:
    """Whether a dataset folder is a whole one: ``build_dataset`` writes its labels and metadata last (a cut-off build
    has none)."""
    return (dataset_dir / "labels.json").is_file() and (dataset_dir / "metadata.json").is_file()


def _load_or_build_dataset(args: argparse.Namespace):
    """Build the Arrow dataset from the manifest (after the ledger check) or load a saved one, with its labels."""
    dataset_dir = args.dataset_dir or args.output_dir / "dataset"
    # a resumed run goes on with the data it began with (its folder holds it: rebuilt, the folder would be in the way)
    if args.reuse_dataset or (args.resume and _published(dataset_dir)):
        if not _published(dataset_dir):
            raise FileNotFoundError(f"no whole dataset to reuse in {dataset_dir} (labels.json and metadata.json)")
        dataset = load_dataset(dataset_dir)
        assert isinstance(dataset, DatasetDict)
        label_file = dataset_dir / "labels.json"
        return dataset, json.loads(label_file.read_text(encoding="utf-8")), dataset_dir
    if args.annotator_manifest is None:
        raise SystemExit("--annotator-manifest is needed (export the dataset from the annotator first)")
    if dataset_dir.is_file():
        raise ValueError(f"dataset path is a file, not a directory: {dataset_dir}")
    # an existing one is replaced only when asked, also one whose switch was cut off (only <dataset>.previous left:
    # swap_in keeps it until the new one is in place)
    previous = dataset_dir.with_name(f"{dataset_dir.name}.previous")
    there = (dataset_dir.exists() and any(dataset_dir.iterdir())) or previous.exists()
    if there and not args.overwrite_dataset:
        raise FileExistsError(f"dataset output directory is not empty: {dataset_dir} (--overwrite-dataset replaces it)")
    # read once: the ledger check, the records and the recorded SHA-256 are of the same bytes (an export written
    # meanwhile would otherwise be checked as one file and built as another)
    raw = args.annotator_manifest.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    ledger_sha, ledger_rows = _check_ledger(manifest, args.annotator_manifest.parent)
    records, label_map = load_annotator_manifest(
        args.annotator_manifest, max_images=args.max_images, truth_seeded=args.truth_seeded, data=manifest
    )
    provenance = {
        "manifest": str(args.annotator_manifest),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "ledger_sha256": ledger_sha,
        "truth_seeded": bool(args.truth_seeded),
        "max_images": args.max_images,  # None: every screenshot (a smoke build's cap is no dataset to reuse)
    }
    # built beside the old one and swapped in only when complete: a failed build (no validation screenshot, a full
    # disk) keeps the old dataset
    staging = dataset_dir.with_name(f"{dataset_dir.name}.new")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        build_dataset(
            records,
            label_map=label_map,
            output_dir=staging,
            provenance=provenance,
            check_bytes=_ledger_bytes(ledger_rows),
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    swap_in(staging, dataset_dir)
    return load_dataset(dataset_dir), label_map, dataset_dir


# ---- the run -----------------------------------------------------------------------------------------------------


def _positive_int(text: str) -> int:
    """An argparse type: a whole number of at least 1."""
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {value}")
    return value


def _at_least_two(text: str) -> int:
    """An argparse type for --max-images: room for one training and one validation screenshot."""
    value = int(text)
    if value < 2:
        raise argparse.ArgumentTypeError(
            f"must be at least 2 (one training and one validation screenshot), not {value}"
        )
    return value


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
    parser.add_argument(
        "--truth-seeded",
        action="store_true",
        help="also train on the unreviewed screenshots a hand-labelled biome truth seeded (a bootstrap round)",
    )
    parser.add_argument(
        "--init-from", default=None, help="an earlier model to go on from: its folder or Hugging Face id (owner/name)"
    )
    parser.add_argument("--resume", action="store_true", help="go on from OUTPUT_DIR's last checkpoint")
    parser.add_argument("--epochs", type=int, default=100, help="most epochs; --patience usually stops sooner")
    parser.add_argument("--patience", type=int, default=K.RF_DETR_PATIENCE)
    parser.add_argument("--batch-size", type=int, default=K.RF_DETR_BATCH)
    parser.add_argument("--grad-accum", type=int, default=K.RF_DETR_GRAD_ACCUM, help="batches per optimizer step")
    parser.add_argument("--learning-rate", type=float, default=K.RF_DETR_LEARNING_RATE)
    parser.add_argument("--lr-encoder", type=float, default=K.RF_DETR_LR_ENCODER)
    parser.add_argument("--layer-decay", type=float, default=K.RF_DETR_LAYER_DECAY)
    parser.add_argument("--component-decay", type=float, default=K.RF_DETR_COMPONENT_DECAY)
    parser.add_argument("--ema-decay", type=float, default=K.RF_DETR_EMA_DECAY)
    parser.add_argument("--weight-decay", type=float, default=K.RF_DETR_WEIGHT_DECAY)
    parser.add_argument("--tiles-per-image", type=_positive_int, default=K.RF_DETR_TILES_PER_IMAGE)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1), help="data loader processes")
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda", "mps"))
    parser.add_argument(
        "--max-images", type=_at_least_two, default=None, help="limit images for a smoke test (2 or more)"
    )
    parser.add_argument(
        "--report-to", default="none", help="Trainer report_to: none, tensorboard, trackio, ... (installed separately)"
    )
    return parser.parse_args(argv)


def check_device(device: str) -> None:
    """Stop when the device asked for is not there: an explicit ``cuda`` or ``mps`` must not train on the CPU
    unnoticed (``auto`` takes what there is)."""
    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("--device cuda: PyTorch sees no CUDA device (use --device auto or cpu)")
    if device == "mps" and not torch.backends.mps.is_available():
        raise SystemExit("--device mps: PyTorch sees no Apple GPU (use --device auto or cpu)")


def check_single_process(training: TrainingArguments) -> None:
    """Stop when the run would train on several GPUs: one process on several wraps the model in DataParallel, whose
    scatter splits each image's target dict apart from its image (``n_gpu`` is above 1 only then); several processes
    (torchrun) are not supported. One GPU trains."""
    if training.world_size > 1:
        raise SystemExit("one training process only: run it without torchrun (one GPU trains)")
    if training.n_gpu > 1:
        raise SystemExit(f"{training.n_gpu} GPUs visible to the process: expose one (CUDA_VISIBLE_DEVICES=0)")


def check_resume_labels(checkpoint: Path, label_map: dict[str, str]) -> None:
    """Stop when a checkpoint to resume from has other classes than the dataset (in order): its class rows, optimizer
    and EMA would be restored onto the wrong classes.

    Raises:
        SystemExit: the classes differ.
    """
    config = json.loads((Path(checkpoint) / "config.json").read_text(encoding="utf-8"))
    saved = [str(config.get("id2label", {}).get(str(index))) for index in range(len(config.get("id2label", {})))]
    wanted = [label_map[str(index)] for index in range(len(label_map))]
    if saved != wanted:
        raise SystemExit(
            f"--resume: {checkpoint.name} was trained on other classes than this dataset; go on from it with "
            "--init-from and a new --output-dir instead"
        )


def dataset_id(dataset_dir: Path) -> str:
    """The identity of a saved dataset: the SHA-256 of its ``metadata.json`` (the manifest's and the ledger's
    SHA-256, the kinds per split, the limit), or "" when it has none."""
    meta = dataset_dir / "metadata.json"
    return hashlib.sha256(meta.read_bytes()).hexdigest() if meta.is_file() else ""


def check_resume_sources(checkpoint: Path, sources: list[str], dataset: str) -> None:
    """Stop when a checkpoint to resume from was trained on other data than this run trains on (a dataset built from
    another export, even of the same screenshots): its weights, optimizer and EMA would go on as if they were the
    same run.

    Args:
        checkpoint: the checkpoint folder.
        sources: this run's training screenshots.
        dataset: this run's ``dataset_id``.

    Raises:
        SystemExit: the screenshots or the dataset differ, or the checkpoint lists none (``MembershipCallback``).
    """
    listed = checkpoint / K.RF_DETR_RUN_SOURCES  # this run's own (RF_DETR_TRAINED_ON adds an ancestor's)
    lines = listed.read_text(encoding="utf-8").splitlines() if listed.is_file() else []
    recorded = {line.strip() for line in lines if line.strip()}  # (a path may hold spaces: one a line)
    wanted = set(sources)
    if recorded != wanted:
        listed = f"{len(wanted - recorded)} new, {len(recorded - wanted)} left out" if recorded else "it lists none"
        raise SystemExit(
            f"--resume: {checkpoint.name} was trained on other screenshots than this run ({listed}); go on from it "
            "with --init-from and a new --output-dir instead"
        )
    saved = checkpoint / K.RF_DETR_DATASET_ID
    if not saved.is_file() or saved.read_text(encoding="utf-8").strip() != dataset:
        raise SystemExit(
            f"--resume: {checkpoint.name} was trained on another dataset than this run's (another export or build); "
            "go on from it with --init-from and a new --output-dir instead"
        )


def training_arguments(args: argparse.Namespace, checkpoints: Path) -> TrainingArguments:
    """The Trainer's settings: the recipe (``RF_DETR_*``) and the run's options."""
    cuda = args.device in ("auto", "cuda") and torch.cuda.is_available()
    bf16 = cuda and torch.cuda.is_bf16_supported(including_emulation=False)  # pre-Ampere: fp16
    workers = max(0, args.workers)
    return TrainingArguments(
        output_dir=str(checkpoints),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        max_grad_norm=K.RF_DETR_GRAD_CLIP,
        lr_scheduler_type="constant",
        warmup_steps=0,
        bf16=bf16,
        fp16=cuda and not bf16,
        tf32=True if bf16 else None,
        use_cpu=args.device == "cpu",
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=None,  # PruneCallback deletes, once a checkpoint's EMA is written
        load_best_model_at_end=True,
        # --resume: early stopping goes on with its saved patience count (a fresh run's starts at zero)
        restore_callback_states_from_checkpoint=True,
        metric_for_best_model="mean_ap",
        greater_is_better=True,
        remove_unused_columns=False,
        label_names=["labels"],
        dataloader_num_workers=workers,
        dataloader_persistent_workers=workers > 0,
        dataloader_pin_memory=cuda,
        seed=args.seed,
        data_seed=args.seed,
        logging_strategy="steps",
        logging_steps=25,
        report_to=args.report_to,
        disable_tqdm=not sys.stderr.isatty(),
    )


def main(argv: list[str] | None = None) -> int:
    """Prepare the dataset, then fine-tune and save the best RF-DETR checkpoint."""
    args = parse_args(argv)
    checkpoints = args.output_dir / "checkpoints"
    inherited: set[str] = set()
    # a Hub id is downloaded once, here: the list read and the weights loaded are of the same download
    init_from = model_folder(args.init_from) if args.init_from and not args.dataset_only else None
    if not args.dataset_only:
        check_device(args.device)  # before a dataset is built or a model loaded
        training_args = training_arguments(args, checkpoints)
        check_single_process(training_args)
        if not args.resume:
            inherited = ancestry(init_from)  # (a model without its list stops here, before any work)
        if not args.resume and checkpoints.is_dir() and any(checkpoints.glob("checkpoint-*")):
            # a fresh run among an earlier run's checkpoints: the Trainer's best-model and pruning would take them for
            # its own; refused before the dataset is built, which would replace the one those checkpoints name
            # (--reuse-dataset with another --output-dir keeps it)
            raise SystemExit(
                f"{checkpoints} holds an earlier run's checkpoints: go on from them with --resume, or train into a "
                "new --output-dir"
            )
    dataset, label_map, dataset_dir = _load_or_build_dataset(args)
    sizes = {split: len(rows) for split, rows in dataset.items()}
    print(f"dataset: {sizes} -> {dataset_dir}")
    print(f"classes ({len(label_map)}): {', '.join(label_map.values())}")
    if args.dataset_only:
        return 0

    from transformers import set_seed

    set_seed(args.seed)
    resume_from = last_complete_checkpoint(checkpoints) if args.resume else None
    if args.resume and resume_from is None:  # before a model is downloaded or loaded
        raise SystemExit(f"--resume: no checkpoint (with its EMA) in {checkpoints}")
    run_sources = sorted(set(dataset["train"]["source"]))  # this run's training screenshots
    run_dataset = dataset_id(dataset_dir)
    if resume_from is not None:
        check_resume_labels(resume_from, label_map)
        check_resume_sources(resume_from, run_sources, run_dataset)
        # a resumed run's ancestry is its checkpoint's (what the weights it goes on with learned), whatever
        # --init-from says now; a fresh run's is the model it starts from
        inherited = ancestry(resume_from)
    base = init_from or K.RF_DETR_MODEL_NAME
    # resumed: the processor and the model from the checkpoint itself (the Trainer then restores its weights), never
    # a download or an --init-from folder that may have changed since
    source = resume_from or base
    processor = load_processor(source)
    model = load_model(source, label_map)

    categories = [list(objects["category"]) for objects in dataset["train"]["objects"]]
    sampler = RepeatFactorSampler(repeat_factors(categories), args.tiles_per_image, args.seed)
    rare = frozenset(rare_classes(categories))
    ema = EmaCallback(args.ema_decay, K.RF_DETR_EMA_TAU, resume_from=resume_from)
    trainer = RfDetrTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"].with_transform(tile_transform(processor, seed=args.seed, rare=rare)),
        eval_dataset=dataset["validation"],
        data_collator=collate_fn,
        processing_class=processor,
        # the membership first: the EMA's files, written last, mark a checkpoint whole (ema_complete)
        callbacks=[
            MembershipCallback(run_sources, run_dataset, inherited),
            ema,
            PruneCallback(),  # after the EMA: a checkpoint is whole before an older one goes
            EarlyStoppingCallback(args.patience, K.RF_DETR_EARLY_STOP_DELTA),
        ],
        ema=ema,
        sampler=sampler,
        recipe={
            "learning_rate": args.learning_rate,
            "lr_encoder": args.lr_encoder,
            "layer_decay": args.layer_decay,
            "component_decay": args.component_decay,
            "weight_decay": args.weight_decay,
        },
        label_map=label_map,
    )
    started = time.time()
    trainer.train(resume_from_checkpoint=str(resume_from) if resume_from else None)
    trainer.save_state()

    best = trainer.state.best_model_checkpoint
    if best is None:
        raise SystemExit("no checkpoint was evaluated: nothing to keep")
    best_dir = args.output_dir / "best"
    # a model gone on from another (--init-from) has also learned what that one trained on
    export_best(Path(best), processor, best_dir, label_map, sorted(set(run_sources) | inherited))
    mean_ap = trainer.state.best_metric
    print(f"saved {best_dir} (the EMA weights of {Path(best).name}, validation mean AP {mean_ap:.4f})")

    test_metrics = None
    if len(dataset["test"]):
        kept = AutoModelForObjectDetection.from_pretrained(best_dir, use_safetensors=True).to(trainer.args.device)
        test_metrics = evaluate_split(kept, processor, dataset["test"], label_map, trainer.args.device)
        print(f"test split (best checkpoint):\n{format_report(test_metrics)}")
    metadata_file = dataset_dir / "metadata.json"
    summary = {
        "base_model": str(base),
        "base_revision": K.RF_DETR_MODEL_REVISION if str(base) == K.RF_DETR_MODEL_NAME else None,
        "git_commit": _git_commit(),
        "dataset_dir": str(dataset_dir),
        "dataset": json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.is_file() else None,
        "screenshots": sizes,
        "classes": label_map,
        "tile": K.RF_DETR_TILE,
        "recipe": {
            "learning_rate": args.learning_rate,
            "lr_encoder": args.lr_encoder,
            "layer_decay": args.layer_decay,
            "component_decay": args.component_decay,
            "weight_decay": args.weight_decay,
            "ema_decay": args.ema_decay,
            "ema_tau": K.RF_DETR_EMA_TAU,
            "grad_clip": K.RF_DETR_GRAD_CLIP,
            "batch_size": args.batch_size,
            "grad_accum": args.grad_accum,
            "tiles_per_image": args.tiles_per_image,
            "patience": args.patience,
            "precision": "bf16" if trainer.args.bf16 else "fp16" if trainer.args.fp16 else "fp32",
            "render_probability": K.RF_DETR_AUGMENT_RENDER_PROBABILITY,
            "photo_probability": K.RF_DETR_AUGMENT_PHOTO_PROBABILITY,
            "scale_jitter": K.RF_DETR_AUGMENT_SCALE_JITTER,
            "seed": args.seed,
        },
        "init_from": str(args.init_from) if args.init_from else None,
        "best_checkpoint": Path(best).name,
        "best_validation_mean_ap": trainer.state.best_metric,
        "test": test_metrics,
        "history": trainer.state.log_history,
        "device": str(trainer.args.device),
        "seconds": round(time.time() - started, 1),
    }
    (args.output_dir / "training_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"done: {best_dir}  best validation mean AP {trainer.state.best_metric:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
