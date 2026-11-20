"""The RF-DETR trainer (tools/train_rf_detr.py): its recipe's pieces, and a whole run on CPU with a stand-in model.

The stand-in "detects" white squares exactly, so a run on screenshots whose boxes are white squares must score a
validation and test mean AP near 1: that checks the wiring end to end (the annotator's manifest, the saved dataset,
random training tiles, the repeat-factor sampler, the EMA, the tiled evaluation, picking and saving the best
checkpoint, the test split) without a GPU or the real model. Skipped where the training extra is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("datasets")
transformers = pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from grand_project.detect import constants as K  # noqa: E402
from tools import train_rf_detr as T  # noqa: E402

LABELS = {"0": "map_node_grass", "1": "icon"}


class FakeProcessor:
    """A stand-in image processor: tiles as float tensors (0-255), annotations as DETR targets."""

    def __init__(self) -> None:
        self.size = {}

    @classmethod
    def from_pretrained(cls, name):
        return cls()

    def __call__(self, *, images, annotations=None, return_tensors="pt"):
        pixels = torch.from_numpy(np.stack(images)).permute(0, 3, 1, 2).float()
        out = {"pixel_values": pixels}
        if annotations is not None:
            out["labels"] = [
                {
                    "class_labels": torch.tensor([a["category_id"] for a in item["annotations"]], dtype=torch.long),
                    "boxes": torch.tensor([a["bbox"] for a in item["annotations"]], dtype=torch.float).reshape(-1, 4),
                }
                for item in annotations
            ]
        return out

    def save_pretrained(self, path) -> None:
        Path(path, "preprocessor_config.json").write_text("{}")


class FakeDetr(torch.nn.Module):
    """A stand-in RF-DETR: finds every white square of a tile as class 0 (score 0.9); its loss is a toy one."""

    QUERIES = 6

    def __init__(self, num_labels: int = 2) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(()))
        self.class_embed = torch.nn.Linear(4, num_labels)
        self.config = SimpleNamespace(num_labels=num_labels)

    @classmethod
    def from_pretrained(cls, name, **kwargs):
        if "num_labels" in kwargs:
            return cls(kwargs["num_labels"])
        return cls(len(json.loads(Path(name, "labels.json").read_text())))

    def save_pretrained(self, path, safe_serialization=True) -> None:
        Path(path, "config.json").write_text(json.dumps({"num_labels": self.config.num_labels}))

    def forward(self, pixel_values, labels=None, pixel_mask=None):
        batch, tile = len(pixel_values), pixel_values.shape[-1]
        loss = (pixel_values.mean() / 255 - self.weight) ** 2 + self.class_embed.bias.pow(2).sum()
        logits = torch.full((batch, self.QUERIES, self.config.num_labels), -20.0)
        boxes = torch.zeros((batch, self.QUERIES, 4))
        for b, image in enumerate(pixel_values.detach().numpy()):
            white = (image == 255).all(axis=0).astype(np.uint8)
            _count, _labels, stats, _centres = cv2.connectedComponentsWithStats(white, 8)
            for q, (x, y, w, h, _area) in enumerate(stats[1 : self.QUERIES + 1]):
                logits[b, q, 0] = float(np.log(0.9 / 0.1))
                boxes[b, q] = torch.tensor([(x + w / 2) / tile, (y + h / 2) / tile, w / tile, h / tile])
        return SimpleNamespace(loss=loss, logits=logits, pred_boxes=boxes)


SQUARES = [(400, 300), (700, 520), (1100, 400), (1500, 700)]


def _export(tmp_path: Path) -> Path:
    """An annotator export of 6 screenshots (3 train, 2 validation, 1 test) whose node boxes are white squares."""
    images = []
    for index, split in enumerate(["train", "train", "train", "validation", "validation", "test"]):
        shot = np.full((1080, 1920, 3), 40, np.uint8)
        boxes = []
        for x, y in SQUARES[: 2 + index % 3]:
            shot[y : y + 39, x + index : x + index + 39] = 255
            boxes.append({"label": "map_node_grass", "bbox": [x + index, y, 39, 39], "source": "manual"})
        path = tmp_path / f"shot{index}.png"
        cv2.imwrite(str(path), shot)
        images.append({"image_id": index, "path": str(path), "width": 1920, "height": 1080, "split": split,
                       "annotations": boxes})  # fmt: skip
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"format": "the-grand-project-rf-detr-manifest",
                                    "labels": LABELS, "images": images}))  # fmt: skip
    return manifest


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transformers.AutoImageProcessor, "from_pretrained", FakeProcessor.from_pretrained)
    monkeypatch.setattr(transformers.AutoModelForObjectDetection, "from_pretrained", FakeDetr.from_pretrained)


def test_a_whole_run_trains_picks_the_best_checkpoint_and_scores_the_test_split(tmp_path: Path, fakes) -> None:
    out = tmp_path / "run"
    args = ["--annotator-manifest", str(_export(tmp_path)), "--output-dir", str(out), "--epochs", "3",
            "--tiles-per-image", "1", "--batch-size", "2", "--grad-accum", "2", "--device", "cpu",
            "--patience", "1"]  # fmt: skip
    assert T.main(args) == 0
    summary = json.loads((out / "training_summary.json").read_text())
    assert summary["screenshots"] == {"train": 3, "validation": 2, "test": 1}
    assert summary["tile"] == K.RF_DETR_TILE
    assert summary["best_validation_mean_ap"] > 0.9  # a perfect detector, scored through tiles and merging
    assert summary["test"]["mean_ap"] > 0.9 and summary["test"]["families"]["node"]["recall"] == 1.0
    assert len(summary["history"]) == 2  # no better score in epoch 2: patience 1 stops the run
    assert json.loads((out / "best" / "labels.json").read_text()) == LABELS
    assert json.loads((out / "best" / "config.json").read_text())["num_labels"] == len(LABELS)


def test_the_dataset_is_built_once_and_reused(tmp_path: Path, fakes) -> None:
    out = tmp_path / "run"
    manifest = _export(tmp_path)
    assert T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"]) == 0
    meta = out / "dataset" / "metadata.json"
    assert json.loads(meta.read_text())["validation_images"] == 2
    assert T.main(["--output-dir", str(out), "--reuse-dataset", "--dataset-only"]) == 0
    with pytest.raises(SystemExit):
        T.main(["--output-dir", str(tmp_path / "other"), "--dataset-only"])  # no manifest
    with pytest.raises(FileExistsError):
        T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"])
    assert (
        T.main(
            ["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only", "--overwrite-dataset"]
        )
        == 0
    )


def test_the_recipe_is_the_papers() -> None:
    args = T.parse_args([])
    assert (args.learning_rate, args.layer_decay, args.ema_decay) == (
        K.RF_DETR_LEARNING_RATE,
        K.RF_DETR_LAYER_DECAY,
        K.RF_DETR_EMA_DECAY,
    )
    assert args.patience == K.RF_DETR_PATIENCE and args.tiles_per_image == K.RF_DETR_TILES_PER_IMAGE
    T._validate_target_count(K.RF_DETR_MAX_TARGETS)
    with pytest.raises(ValueError, match="queries"):
        T._validate_target_count(K.RF_DETR_MAX_TARGETS + 1)


def test_backbone_layers_learn_slower_and_norms_are_not_decayed() -> None:
    class Model(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.config = SimpleNamespace(backbone_config=SimpleNamespace(num_hidden_layers=2))
            self.model = torch.nn.Module()
            self.model.backbone = torch.nn.Module()
            self.model.backbone.backbone = torch.nn.Module()
            self.model.backbone.backbone.encoder = torch.nn.Module()
            self.model.backbone.backbone.encoder.layer = torch.nn.ModuleList([torch.nn.Linear(2, 2) for _ in range(2)])
            self.class_embed = torch.nn.Linear(2, 3)

    groups = T.parameter_groups(Model(), learning_rate=1.0, weight_decay=0.1, layer_decay=0.5)
    by_rate = {(round(g["lr"], 4), g["weight_decay"]): len(g["params"]) for g in groups}
    assert by_rate == {(0.25, 0.0): 1, (0.25, 0.1): 1, (0.5, 0.0): 1, (0.5, 0.1): 1, (1.0, 0.0): 1, (1.0, 0.1): 1}


def test_the_ema_warms_up_then_averages_slowly() -> None:
    update = T.ema_update(0.999, 100.0)
    average, current = [torch.zeros(1)], [torch.ones(1)]
    update(average, current, torch.tensor(0))
    assert average[0].item() > 0.99  # the first step: almost a copy (an average of nothing yet)
    for step in range(1, 5000):
        update(average, [torch.zeros(1)], torch.tensor(step))
    late = average[0].clone()
    update(average, [torch.ones(1)], torch.tensor(5000))
    assert (average[0] - late).item() == pytest.approx(0.001, rel=0.01)  # 1 - decay once warm


def test_gradients_accumulate_over_batches_before_each_step() -> None:
    from torch.optim.swa_utils import AveragedModel

    model = FakeDetr()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    steps: list[int] = []
    step = optimizer.step

    def counted(*args, **kwargs):
        steps.append(1)
        return step(*args, **kwargs)

    optimizer.step = counted
    ema = AveragedModel(model, multi_avg_fn=T.ema_update(0.9, 1.0), use_buffers=True)
    batches = [{"pixel_values": torch.full((1, 3, 8, 8), 255.0), "labels": [{}]} for _ in range(5)]
    scaler = torch.amp.GradScaler("cpu", enabled=False)
    loss = T.train_epoch(
        model, batches, optimizer, torch.device("cpu"), amp=False, scaler=scaler, accumulate=2, ema=ema
    )
    assert len(steps) == 3  # after batches 2, 4 and the last one
    assert loss > 0 and int(ema.n_averaged) == 3
    assert T.validation_loss(model, batches, torch.device("cpu"), amp=False) < loss  # it learned the toy target


def test_each_epoch_draws_tiles_by_repeat_factor() -> None:
    sampler = T.RepeatFactorSampler([1.0, 2.0], per_image=2, seed=3)
    first, second = list(sampler), list(sampler)
    assert sorted(first) == [0, 0, 1, 1, 1, 1] and len(sampler) == 6
    assert sorted(second) == sorted(first) and sampler.epoch == 2


def test_init_from_copies_class_rows_by_name(tmp_path: Path) -> None:
    """An earlier checkpoint's rows: map_node's starts the new node classes, citadel_stone and icon keep their own,
    and the Iron citadel (new, no parent) keeps its fresh row."""
    from safetensors.torch import save_file

    old = tmp_path / "old"
    old.mkdir()
    (old / "labels.json").write_text(json.dumps({"0": "map_node", "1": "citadel_stone", "2": "icon"}))
    rows = torch.arange(12, dtype=torch.float).reshape(3, 4)
    save_file({"class_embed.weight": rows, "class_embed.bias": torch.tensor([10.0, 11.0, 12.0])},
              str(old / "model.safetensors"))  # fmt: skip
    new_labels = {"0": "map_node", "1": "map_node_grass", "2": "citadel_stone", "3": "icon", "4": "citadel_iron"}
    model = FakeDetr()
    model.class_embed = torch.nn.Linear(4, 5)
    fresh = model.class_embed.weight[4].detach().clone()
    assert T.remap_class_heads(model, old, new_labels) == 4
    weight, bias = model.class_embed.weight.detach(), model.class_embed.bias.detach()
    assert torch.equal(weight[0], rows[0]) and torch.equal(weight[1], rows[0])
    assert torch.equal(weight[2], rows[1]) and torch.equal(weight[3], rows[2])
    assert torch.equal(weight[4], fresh) and bias[:4].tolist() == [10.0, 10.0, 11.0, 12.0]
