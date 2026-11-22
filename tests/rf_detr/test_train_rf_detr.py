"""The RF-DETR trainer (tools/train_rf_detr.py): transformers' Trainer with the reference recipe.

A whole run uses a stand-in model that "detects" white squares exactly, so a run on screenshots whose boxes are white
squares must score a validation and test mean AP near 1: that checks the wiring end to end (the annotator's
manifest, the ledger check, the saved dataset, random training tiles, the repeat-factor sampler, the Trainer with the
EMA callback, the tiled evaluation, the best checkpoint's EMA weights, the test split) without a GPU or the real
model. The recipe's pieces (class heads, parameter groups, the eval-mode loss) run on a tiny real RF-DETR. Skipped
where the training extra is not installed.
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
pytest.importorskip("accelerate")
transformers = pytest.importorskip("transformers")

from grand_project.detect import constants as K  # noqa: E402
from tools import train_rf_detr as T  # noqa: E402
from tools.detection_dataset_annotator import constants as AK  # noqa: E402
from tools.detection_dataset_annotator.split_ledger import Entry, write_ledger  # noqa: E402
from tools.detection_dataset_annotator.state import file_hash  # noqa: E402

LABELS = {"0": "map_node_grass", "1": "icon"}


class FakeProcessor:
    """A stand-in image processor: tiles as float tensors (0-255), annotations as DETR targets."""

    def __init__(self) -> None:
        self.size = {}

    @classmethod
    def from_pretrained(cls, name, **kwargs):
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
        Path(path).mkdir(parents=True, exist_ok=True)
        Path(path, "preprocessor_config.json").write_text("{}")


class Output(dict):
    """A model output as transformers gives it: a dict whose keys are also attributes."""

    __getattr__ = dict.__getitem__


class FakeDetr(torch.nn.Module):
    """A stand-in RF-DETR: finds every white square of a tile as class 0 (score 0.9); its loss is a toy one."""

    QUERIES = 6

    def __init__(self, num_labels: int = 2) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(()))
        self.class_embed = torch.nn.Linear(4, num_labels)
        self.config = SimpleNamespace(
            num_labels=num_labels,
            id2label={i: f"class{i}" for i in range(num_labels)},
            backbone_config=SimpleNamespace(out_indices=[3, 6, 9, 12]),
            group_detr=13,
        )

    @classmethod
    def from_pretrained(cls, name, **kwargs):
        labels = Path(name, "labels.json")
        return cls(len(json.loads(labels.read_text())) if labels.is_file() else 91)

    def save_pretrained(self, path, **kwargs) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        Path(path, "config.json").write_text(json.dumps({"num_labels": self.config.num_labels}))

    def forward(self, pixel_values, labels=None, pixel_mask=None):
        batch, tile = len(pixel_values), pixel_values.shape[-1]
        loss = (pixel_values.mean() / 255 - self.weight) ** 2 + self.class_embed.bias.pow(2).sum()
        logits = torch.full((batch, self.QUERIES, self.config.num_labels), -20.0)
        boxes = torch.zeros((batch, self.QUERIES, 4))
        for b, image in enumerate(pixel_values.detach().cpu().numpy()):
            white = (image == 255).all(axis=0).astype(np.uint8)
            _count, _labels, stats, _centres = cv2.connectedComponentsWithStats(white, 8)
            for q, (x, y, w, h, _area) in enumerate(stats[1 : self.QUERIES + 1]):
                logits[b, q, 0] = float(np.log(0.9 / 0.1))
                boxes[b, q] = torch.tensor([(x + w / 2) / tile, (y + h / 2) / tile, w / tile, h / tile])
        return Output(loss=loss, logits=logits, pred_boxes=boxes)


SQUARES = [(400, 300), (700, 520), (1100, 400), (1500, 700)]
SPLITS = ["train", "train", "train", "validation", "validation", "test"]


def _export(tmp_path: Path, splits: list[str] = SPLITS) -> Path:
    """An annotator export of 6 screenshots (3 train, 2 validation, 1 test) whose node boxes are white squares."""
    images = []
    for index, split in enumerate(splits):
        shot = np.full((1080, 1920, 3), 40, np.uint8)
        boxes = []
        for x, y in SQUARES[: 2 + index % 3]:
            shot[y : y + 39, x + index : x + index + 39] = 255
            boxes.append({"label": "map_node_grass", "bbox": [x + index, y, 39, 39], "source": "manual"})
        path = tmp_path / f"shot{index}.png"
        cv2.imwrite(str(path), shot)
        images.append({"image_id": index, "path": str(path), "source": path.name, "width": 1920, "height": 1080,
                       "split": split, "reviewed": True, "annotations": boxes})  # fmt: skip
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"format": "the-grand-project-rf-detr-manifest",
                                    "labels": LABELS, "images": images}))  # fmt: skip
    return manifest


@pytest.fixture
def ledger(annotator_output_dir: Path) -> Path:
    """This test's own split ledger (``tests/conftest.py`` gives every test one; the real one is in git)."""
    return Path(AK.ANNOTATOR_SPLIT_LEDGER)


def _freeze(manifest: Path, ledger: Path) -> None:
    images = json.loads(manifest.read_text())["images"]
    write_ledger([Entry(file_hash(Path(i["path"])), i["split"], "", Path(i["path"]).name) for i in images], ledger)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transformers.AutoImageProcessor, "from_pretrained", FakeProcessor.from_pretrained)
    monkeypatch.setattr(transformers.AutoModelForObjectDetection, "from_pretrained", FakeDetr.from_pretrained)


def test_a_whole_run_trains_picks_the_best_checkpoint_and_scores_the_test_split(tmp_path: Path, fakes, ledger) -> None:
    out = tmp_path / "run"
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    args = ["--annotator-manifest", str(manifest), "--output-dir", str(out), "--epochs", "3",
            "--tiles-per-image", "1", "--batch-size", "2", "--grad-accum", "2", "--device", "cpu",
            "--patience", "1", "--workers", "0"]  # fmt: skip
    assert T.main(args) == 0
    summary = json.loads((out / "training_summary.json").read_text())
    assert summary["screenshots"] == {"train": 3, "validation": 2, "test": 1}
    assert summary["tile"] == K.RF_DETR_TILE and summary["recipe"]["precision"] == "fp32"
    assert summary["best_validation_mean_ap"] > 0.9  # a perfect detector, scored through tiles and merging
    assert summary["test"]["mean_ap"] > 0.9 and summary["test"]["families"]["node"]["recall"] == 1.0
    evaluations = [entry for entry in summary["history"] if "eval_mean_ap" in entry]
    assert len(evaluations) == 2  # no better score in epoch 2: patience 1 stops the run
    assert summary["dataset"]["ledger_sha256"] == file_hash(ledger)
    best = out / "best"
    assert json.loads((best / "labels.json").read_text()) == LABELS
    assert json.loads((best / "config.json").read_text())["num_labels"] == len(LABELS)  # the EMA model's
    assert (best / K.RF_DETR_TRAINED_ON).read_text().split() == ["shot0.png", "shot1.png", "shot2.png"]
    checkpoint = out / "checkpoints" / summary["best_checkpoint"]
    assert json.loads((checkpoint / T.EMA_DIR / T.EMA_STATE).read_text())["updates"] >= 1


def test_the_ledger_stops_a_manifest_that_moved_a_screenshot(tmp_path: Path, fakes, ledger) -> None:
    """A screenshot a model trained on must stay in train: a manifest disagreeing with the ledger builds nothing."""
    manifest = _export(tmp_path)
    moved = tmp_path / "moved"
    moved.mkdir()
    _freeze(_export(moved, ["validation", *SPLITS[1:]]), ledger)  # the same screenshots, shot0 in validation
    with pytest.raises(SystemExit, match="shot0.png: manifest train, ledger validation"):
        T.main(["--annotator-manifest", str(manifest), "--output-dir", str(tmp_path / "run"), "--dataset-only"])
    assert not (tmp_path / "run" / "dataset").exists()


def test_the_dataset_is_built_once_and_reused(tmp_path: Path, fakes, ledger) -> None:
    out = tmp_path / "run"
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    assert T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"]) == 0
    meta = out / "dataset" / "metadata.json"
    recorded = json.loads(meta.read_text())
    assert recorded["validation_images"] == 2 and recorded["kinds"]["train"] == {"annotator_reviewed": 3}
    assert recorded["manifest_sha256"] == file_hash(manifest) and "schema_version" not in recorded
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


def test_a_build_that_fails_keeps_the_dataset_there_was(tmp_path: Path, fakes, ledger) -> None:
    out = tmp_path / "run"
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    assert T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"]) == 0
    only_train = tmp_path / "only_train"
    only_train.mkdir()
    no_validation = _export(only_train, ["train"] * 6)
    _freeze(no_validation, ledger)
    with pytest.raises(ValueError, match="validation"):
        T.main(["--annotator-manifest", str(no_validation), "--output-dir", str(out), "--dataset-only",
                "--overwrite-dataset"])  # fmt: skip
    assert json.loads((out / "dataset" / "metadata.json").read_text())["validation_images"] == 2
    assert not (out / "dataset.new").exists() and not (out / "dataset.previous").exists()


def test_a_train_subset_keeps_only_its_screenshots(tmp_path: Path, fakes, ledger) -> None:
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    out = tmp_path / "run"
    assert T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"]) == 0
    subset = tmp_path / "subset.txt"
    subset.write_text("shot0.png\nshot2.png\n")
    from datasets import load_from_disk

    dataset = T.train_subset(load_from_disk(str(out / "dataset")), subset)
    assert dataset["train"]["source"] == ["shot0.png", "shot2.png"] and len(dataset["validation"]) == 2
    subset.write_text("shot3.png\n")  # a validation screenshot
    with pytest.raises(SystemExit, match="not training screenshots"):
        T.train_subset(load_from_disk(str(out / "dataset")), subset)


def test_a_checkpoint_switch_never_loses_the_last_good_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The new folder replaces the old one only once complete; a switch interrupted before (best.previous, no best)
    keeps that one until the new one is in place; a switch that fails puts the old one back."""

    def folder(name: str, text: str) -> Path:
        path = tmp_path / name
        path.mkdir()
        (path / "weights").write_text(text)
        return path

    best, previous = tmp_path / "best", tmp_path / "best.previous"
    folder("best.previous", "old")  # interrupted between the two renames: only the backup is left
    T.swap_in(folder("best.new", "new"), best)
    assert (best / "weights").read_text() == "new" and not previous.exists()

    rename = Path.rename

    def failing(self: Path, target):
        if self.name == "best.new":
            raise OSError("disk full")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", failing)
    with pytest.raises(OSError, match="disk full"):
        T.swap_in(folder("best.new", "newer"), best)
    assert (best / "weights").read_text() == "new" and not previous.exists()  # put back


def test_the_recipe_is_the_references() -> None:
    """A run's defaults are the official recipe's numbers (roboflow/rf-detr ``TrainConfig``, ``RFDETREMACallback``,
    ``param_groups.py``): changing one is a recipe change, to check against that repo first (AGENTS.md)."""
    args = T.parse_args([])
    assert (args.learning_rate, args.lr_encoder, args.layer_decay, args.component_decay) == (1e-4, 1.5e-4, 0.8, 0.7)
    assert (args.weight_decay, args.ema_decay, K.RF_DETR_EMA_TAU, K.RF_DETR_GRAD_CLIP) == (1e-4, 0.993, 100.0, 0.1)
    assert args.batch_size * args.grad_accum == 16 and K.RF_DETR_EARLY_STOP_DELTA == 0.001
    with pytest.raises(SystemExit):
        T.parse_args(["--tiles-per-image", "0"])  # no tiles: an epoch would train on nothing
    training = T.training_arguments(T.parse_args(["--device", "cpu", "--workers", "0"]), Path("checkpoints"))
    assert training.lr_scheduler_type == "constant" and training.warmup_steps == 0
    assert training.max_grad_norm == K.RF_DETR_GRAD_CLIP and training.metric_for_best_model == "mean_ap"
    assert not training.remove_unused_columns and training.load_best_model_at_end
    # the detection labels are lists of dicts the Trainer cannot count: the batch mean is divided over accumulation
    assert T.RfDetrTrainer.loss_is_scaled_for_ga is False


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


def test_resume_needs_a_checkpoint(tmp_path: Path, fakes, ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    """--resume on a run that saved nothing (no checkpoint folder, or an empty one) stops before any model is
    loaded, rather than starting over."""
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    (tmp_path / "run" / "checkpoints").mkdir(parents=True)
    loaded = []
    monkeypatch.setattr(transformers.AutoModelForObjectDetection, "from_pretrained", lambda *a, **k: loaded.append(a))
    args = ["--annotator-manifest", str(manifest), "--output-dir", str(tmp_path / "run"), "--resume",
            "--device", "cpu", "--workers", "0"]  # fmt: skip
    with pytest.raises(SystemExit, match="no checkpoint"):
        T.main(args)
    assert loaded == []


def test_each_epoch_draws_tiles_by_repeat_factor() -> None:
    sampler = T.RepeatFactorSampler([1.0, 2.0], per_image=2, seed=3)
    first, second = list(sampler), list(sampler)
    assert sorted(first) == [0, 0, 1, 1, 1, 1] and len(sampler) == 6
    assert sorted(second) == sorted(first) and sampler.epoch == 2
    fractional = T.RepeatFactorSampler([1.0, 1.3, 1.6], per_image=1, seed=0)
    draws = [list(fractional) for _ in range(400)]
    assert {len(epoch) for epoch in draws} == {len(fractional)} == {4}  # always the length the Trainer was told
    counts = np.bincount(np.concatenate(draws), minlength=3) / 400
    # one draw beyond the whole parts goes by the fractions (0.3, 0.6): each image's share of it
    assert counts.tolist() == pytest.approx([1.0, 1 + 0.3 / 0.9, 1 + 0.6 / 0.9], abs=0.06)
    fractional.set_epoch(7)
    assert list(fractional) == list(T.RepeatFactorSampler([1.0, 1.3, 1.6], per_image=1, seed=7))


# ---- a tiny real RF-DETR --------------------------------------------------------------------------------------


def _tiny(labels: dict[str, str]):
    """A tiny RF-DETR (a 4-layer DINOv2 backbone of width 32, 8 queries in 2 groups): fast on a CPU."""
    backbone = transformers.RfDetrDinov2Config(
        hidden_size=32, num_hidden_layers=4, num_attention_heads=2, mlp_ratio=2, image_size=64, patch_size=16,
        num_windows=2, out_indices=[1, 2, 3, 4], out_features=["stage1", "stage2", "stage3", "stage4"],
        window_block_indexes=[0, 2],
    )  # fmt: skip
    config = transformers.RfDetrConfig(
        backbone_config=backbone, d_model=32, decoder_layers=1, num_queries=8, group_detr=2, decoder_ffn_dim=64,
        decoder_self_attention_heads=2, decoder_cross_attention_heads=2, intermediate_size=32,
        num_labels=len(labels), id2label={int(i): n for i, n in labels.items()},
    )  # fmt: skip
    return transformers.RfDetrForObjectDetection(config)


def _number_rows(model) -> None:
    """Give every class head row the value of its class id (weights and bias), to follow rows around."""
    with torch.no_grad():
        for _owner, _attribute, layer in T._class_heads(model):
            for row in range(layer.out_features):
                layer.weight[row].fill_(row)
                layer.bias[row] = row


def _rows(model) -> list[list[int]]:
    """Every class head's rows, each as the value it was numbered with."""
    return [[int(round(v)) for v in layer.bias.tolist()] for _o, _a, layer in T._class_heads(model)]


def test_a_resumed_run_goes_on_with_its_ema(tmp_path: Path) -> None:
    """--resume restores a checkpoint's EMA weights and update count (where the decay's warm-up stands), not a fresh
    copy of the live weights the Trainer reloads."""
    args = SimpleNamespace(output_dir=str(tmp_path))
    model = _tiny(LABELS)
    first = T.EmaCallback(0.9, 10.0)
    first.on_train_begin(args, None, None, model=model)
    for _step in range(3):
        with torch.no_grad():
            for param in model.parameters():
                param.add_(0.5)  # an optimizer step
        first.on_step_end(args, None, None, model=model)
    first.on_save(args, SimpleNamespace(global_step=3), None)

    live = _tiny(LABELS)
    resumed = T.EmaCallback(0.9, 10.0, resume_from=tmp_path / "checkpoint-3")
    resumed.on_train_begin(args, None, None, model=live)
    assert int(resumed.ema.n_averaged) == 3
    saved, restored = first.ema.module.state_dict(), resumed.ema.module.state_dict()
    assert all(torch.equal(saved[name], restored[name]) for name in saved)
    assert not torch.equal(restored["class_embed.weight"], live.state_dict()["class_embed.weight"])


def test_init_from_carries_every_class_head_row_by_name(tmp_path: Path) -> None:
    """An earlier checkpoint saved by transformers (its own key layout): map_node's row starts the new node class,
    citadel_stone and icon keep theirs, the new Iron citadel takes the reference's tiling, in the decoder's head and
    in each of the encoder's (the 2 Group DETR groups' heads)."""
    old = tmp_path / "old"
    model = _tiny({"0": "map_node", "1": "citadel_stone", "2": "icon"})
    _number_rows(model)
    model.save_pretrained(old)
    new = {"0": "map_node", "1": "map_node_grass", "2": "citadel_stone", "3": "icon", "4": "citadel_iron"}
    loaded = T.load_model(old, new)
    assert len(T._class_heads(loaded)) == 3  # class_embed and both encoder heads
    assert _rows(loaded) == [[0, 0, 1, 2, 1]] * 3  # 4 % 3 = 1 for the Iron citadel
    assert loaded.config.num_labels == 5 and loaded.config.id2label[4] == "citadel_iron"


def test_a_fine_tune_keeps_the_pretrained_rows_of_its_head(tmp_path: Path) -> None:
    """As the reference: a pre-trained head's first rows start the new classes (no row is random)."""
    pretrained = tmp_path / "pretrained"
    model = _tiny({str(i): f"coco{i}" for i in range(5)})
    _number_rows(model)
    model.save_pretrained(pretrained)
    loaded = T.load_model(pretrained, LABELS)
    assert _rows(loaded) == [[0, 1]] * 3 and loaded.class_embed.out_features == 2


def test_parameter_groups_follow_the_reference() -> None:
    model = _tiny(LABELS)
    groups = T.parameter_groups(
        model, learning_rate=1.0, lr_encoder=2.0, layer_decay=0.5, component_decay=0.5, weight_decay=0.1
    )
    rate = {id(p): (g["lr"], g["weight_decay"]) for g in groups for p in g["params"]}
    named = dict(model.named_parameters())
    backbone = "model.backbone.backbone."
    layers = 4 + 1  # out_indices[-1] + 1, as the reference counts
    top = named[f"{backbone}encoder.layer.3.attention.q_proj.weight"]
    assert rate[id(top)] == (2.0 * 0.5 ** (layers - 3) * 0.25, 0.1)
    assert rate[id(named[f"{backbone}encoder.layer.0.norm1.weight"])] == (2.0 * 0.5**layers * 0.25, 0.0)
    assert rate[id(named[f"{backbone}embeddings.position_embeddings"])] == (2.0 * 0.5 ** (layers + 1) * 0.25, 0.0)
    assert rate[id(named[f"{backbone}layernorm.weight"])] == (2.0 * 0.25, 0.0)  # the final norm is not decayed
    decoder = next(p for n, p in named.items() if n.startswith("model.decoder.") and p.ndim == 2)
    assert rate[id(decoder)] == (0.5, 0.1)
    assert rate[id(named["class_embed.weight"])] == (1.0, 0.1) and rate[id(named["class_embed.bias"])] == (1.0, 0.0)
    assert sum(len(g["params"]) for g in groups) == sum(p.requires_grad for p in model.parameters())


def test_an_eval_mode_loss_uses_one_query_group() -> None:
    """Transformers' loss is always in training mode: in eval it would match the 8 eval queries in 2 groups."""
    model = _tiny(LABELS).eval()
    pixels = torch.randn(1, 3, 64, 64)
    labels = [
        {"class_labels": torch.tensor([0, 1]), "boxes": torch.tensor([[0.3, 0.3, 0.1, 0.1], [0.6, 0.6, 0.2, 0.2]])}
    ]
    with torch.no_grad():
        grouped = float(model(pixel_values=pixels, labels=labels).loss)
        with T.single_group(model):
            assert model.config.group_detr == 1
            single = float(model(pixel_values=pixels, labels=labels).loss)
    assert model.config.group_detr == 2 and single != pytest.approx(grouped)


def test_the_processor_sees_tiles_at_their_own_size(tmp_path: Path) -> None:
    """The trainer's processor loader on a real saved RF-DETR processor: the installed transformers knows the
    rf_detr image processor (pyproject asks for a release that does), sized to one tile."""
    saved = tmp_path / "rf-detr"
    transformers.RfDetrImageProcessor().save_pretrained(saved)
    processor = T.load_processor(saved)
    assert type(processor).__name__ == "RfDetrImageProcessor"
    assert dict(processor.size) == {"height": K.RF_DETR_TILE, "width": K.RF_DETR_TILE}


def test_checkpoints_keep_transformers_own_key_layout(tmp_path: Path) -> None:
    """The Trainer reloads a checkpoint's weights as they are (the best model, --resume): saved in RF-DETR's default
    original layout they match none of the model's backbone parameters; in transformers' own layout all of them."""
    from safetensors.torch import load_file

    model = _tiny(LABELS)
    expected = set(model.state_dict())
    T.save_native(model, tmp_path / "native")
    assert set(load_file(str(tmp_path / "native" / "model.safetensors"))) == expected
    model.save_pretrained(tmp_path / "original")  # transformers' default: the original (Roboflow) layout
    original = set(load_file(str(tmp_path / "original" / "model.safetensors")))
    assert not {name for name in original if name.startswith("model.backbone.backbone.")}
    reloaded = transformers.RfDetrForObjectDetection.from_pretrained(tmp_path / "native")
    pairs = zip(reloaded.state_dict().values(), model.state_dict().values(), strict=True)
    assert all(torch.equal(a, b) for a, b in pairs)


def test_a_resume_goes_on_with_the_saved_dataset(tmp_path: Path, fakes, ledger) -> None:
    """--resume with the run's own command (its manifest given again) uses the dataset the run saved, rather than
    refusing to build over it, and goes on to its checkpoints."""
    manifest = _export(tmp_path)
    _freeze(manifest, ledger)
    out = tmp_path / "run"
    assert T.main(["--annotator-manifest", str(manifest), "--output-dir", str(out), "--dataset-only"]) == 0
    (out / "checkpoints").mkdir()
    args = ["--annotator-manifest", str(manifest), "--output-dir", str(out), "--resume", "--device", "cpu",
            "--workers", "0"]  # fmt: skip
    with pytest.raises(SystemExit, match="no checkpoint"):  # not FileExistsError: the dataset was reused
        T.main(args)


def test_resume_passes_over_a_checkpoint_without_its_ema(tmp_path: Path) -> None:
    """A run stopped between the Trainer's files and the EMA's leaves a checkpoint without its EMA: resuming from it
    would start a fresh average, so the newest whole one is taken (numbers sorted as numbers), and the callback
    refuses an incomplete one."""
    folder = tmp_path / "checkpoints"

    def checkpoint(step: int, state: bool = True) -> Path:
        ema = folder / f"checkpoint-{step}" / T.EMA_DIR
        ema.mkdir(parents=True)
        (ema / "model.safetensors").write_bytes(b"x")
        if state:
            (ema / T.EMA_STATE).write_text('{"updates": 1}')
        return ema.parent

    checkpoint(2)
    whole = checkpoint(9)
    broken = checkpoint(10, state=False)
    (folder / "runs").mkdir()  # not a checkpoint
    assert T.last_complete_checkpoint(folder) == whole
    assert T.last_complete_checkpoint(tmp_path / "nothing") is None
    callback = T.EmaCallback(0.9, 10.0, resume_from=broken)
    with pytest.raises(RuntimeError, match="no complete EMA"):
        callback.on_train_begin(SimpleNamespace(output_dir=str(tmp_path)), None, None, model=_tiny(LABELS))
