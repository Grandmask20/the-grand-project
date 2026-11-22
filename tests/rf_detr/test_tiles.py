"""Native-scale tiles for RF-DETR (grand_project/detect/rf_detr_tiles.py): what the model sees of a screenshot."""

import random

import cv2
import numpy as np
import pytest

from grand_project import core
from grand_project.detect import constants as K
from grand_project.detect import rf_detr_tiles as T


def test_a_1080p_screenshot_is_eight_overlapping_tiles() -> None:
    origins = T.tile_origins(1920, 1080)
    assert len(origins) == 8
    xs, ys = sorted({x for x, _y in origins}), sorted({y for _x, y in origins})
    assert xs[0] == 0 and xs[-1] == 1920 - K.RF_DETR_TILE and ys == [0, 1080 - K.RF_DETR_TILE]
    assert all(b - a <= K.RF_DETR_TILE - K.RF_DETR_TILE_OVERLAP for a, b in zip(xs, xs[1:], strict=False))
    assert T.tile_origins(500, 400) == [(0, 0)]  # a small crop: one tile (padded)


@pytest.mark.parametrize("width,height", [(39, 39), (80, 220), (150, 150), (134, 125)])
def test_every_object_lies_whole_in_some_tile(width: int, height: int) -> None:
    """The tiles overlap by the tallest box (a tower), so no object is only ever seen cut in two."""
    origins = T.tile_origins(1920, 1080)
    tile = K.RF_DETR_TILE
    for x in range(0, 1920 - width, 37):
        for y in range(0, 1080 - height, 41):
            assert any(ox <= x and oy <= y and x + width <= ox + tile and y + height <= oy + tile for ox, oy in origins)


def test_crop_keeps_boxes_half_visible_and_cut_boxes_are_found() -> None:
    keep, kept = T.crop_boxes([[90, 10, 20, 20], [95, 50, 20, 20], [0, 0, 5, 5]], 0, 0, 100, 100)
    assert keep == [0, 2] and kept == [[90.0, 10.0, 10.0, 20.0], [0.0, 0.0, 5.0, 5.0]]
    tile = K.RF_DETR_TILE
    assert T.cut_by_inner_edge([700, 10, tile, 40], (0, 0), (1920, 1080))  # runs into the next tile
    assert not T.cut_by_inner_edge([0.5, 10, 40, 40], (0, 0), (1920, 1080))  # the screenshot's own edge
    assert T.cut_by_inner_edge([0.5, 10, 40, 40], (544, 0), (1920, 1080))  # another tile's left edge


def test_hud_is_painted_over_in_whole_windows_only() -> None:
    shot = np.full((1080, 1920, 3), 255, np.uint8)
    filled = T.fill_hud(shot, rgb=False)
    hud = core.hud_mask(1920, 1080) > 0
    assert hud.any() and (filled[hud] == K.RF_DETR_HUD_FILL).all() and (filled[~hud] == 255).all()
    crop = np.full((700, 900, 3), 255, np.uint8)
    assert (T.fill_hud(crop, rgb=False) == 255).all()


def test_4k_screenshots_are_read_as_1080p() -> None:
    image, boxes = T.normalise(np.zeros((2160, 3840, 3), np.uint8), [[100, 200, 68, 68]])
    assert image.shape[:2] == (1080, 1920) and boxes == [[50.0, 100.0, 34.0, 34.0]]


def test_a_random_tile_is_native_scale_and_never_mirrored() -> None:
    """User: the atlas has a fixed camera, so training never mirrors it (flips are off): a screenshot growing
    brighter to the right gives tiles growing brighter to the right, blurred or scaled as they may be."""
    ramp = np.tile(np.linspace(0, 255, 1920, dtype=np.float32), (1080, 1)).astype(np.uint8)
    image = np.dstack([ramp] * 3)
    boxes = [[900.0, 500.0, 39.0, 39.0]]
    rng = random.Random(4)
    for _ in range(20):
        tile, keep, kept = T.random_tile(image, boxes, [0], rng)
        assert tile.shape == (K.RF_DETR_TILE, K.RF_DETR_TILE, 3)
        assert keep == [0] and kept[0][0] >= 0 and kept[0][0] + kept[0][2] <= K.RF_DETR_TILE
        assert tile[:, -10:].mean() > tile[:, :10].mean()


def test_rare_classes_repeat_their_screenshots() -> None:
    """LVIS repeat-factor sampling: a class on few screenshots repeats them; common ones do not."""
    categories = [[0]] * 98 + [[0, 1]] * 2  # class 1 on 2% of the screenshots
    factors = T.repeat_factors(categories, threshold=0.1)
    assert factors[0] == 1.0 and factors[-1] == pytest.approx((0.1 / 0.02) ** 0.5)
    assert T.rare_classes(categories, threshold=0.1) == {1}
    drawn = T.epoch_indices(factors, 4, random.Random(1))
    assert drawn.count(0) == 4 and drawn.count(99) in (8, 9)


def test_backbone_layers_learn_slower_from_the_bottom() -> None:
    """The reference's per-layer learning-rate decay in DINOv2 (roboflow/rf-detr ``get_dinov2_lr_decay_rate``, its
    layer count ``out_indices[-1] + 1`` = 13 for DINOv2-S): the top layer x0.8^2, the embeddings least, the final
    layer norm not at all, nothing outside the backbone."""
    name = "model.backbone.backbone.encoder.layer.{}.mlp.fc1.weight"
    assert T.layer_lr_scale(name.format(11), 13, 0.8) == pytest.approx(0.8**2)
    assert T.layer_lr_scale(name.format(0), 13, 0.8) == pytest.approx(0.8**13)
    assert T.layer_lr_scale("model.backbone.backbone.embeddings.cls_token", 13, 0.8) == pytest.approx(0.8**14)
    assert T.layer_lr_scale("model.backbone.backbone.layernorm.weight", 13, 0.8) == 1.0
    assert T.layer_lr_scale("class_embed.weight", 13, 0.8) == 1.0


def test_backbone_norms_embeddings_biases_and_layer_scales_take_no_weight_decay() -> None:
    backbone = "model.backbone.backbone."
    assert T.backbone_weight_decay(f"{backbone}encoder.layer.3.attention.q_proj.weight")
    assert T.backbone_weight_decay(f"{backbone}encoder.layer.3.mlp.fc1.weight")
    for name in ("encoder.layer.3.attention.q_proj.bias", "encoder.layer.3.norm1.weight", "layernorm.weight",
                 "encoder.layer.3.layer_scale1.lambda1", "embeddings.position_embeddings"):  # fmt: skip
        assert not T.backbone_weight_decay(backbone + name), name


def test_an_epoch_always_draws_its_length() -> None:
    """The Trainer sizes an epoch by the sampler's length: the fractions of the repeat factors never change it."""
    factors = [1.0, 1.25, 1.5, 2.6]
    for seed in range(50):
        drawn = T.epoch_indices(factors, 3, random.Random(seed))
        assert len(drawn) == T.epoch_length(factors, 3) == round(3 * sum(factors))
        assert drawn.count(0) == 3 and drawn.count(3) in (7, 8)  # 7.8: its whole 7, maybe one more


def test_brightness_and_contrast_change_and_the_hue_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reference's small-dataset brightness and contrast: a grass-green tile stays green (the hue tells the
    biome), only lighter or darker."""
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_PHOTO_PROBABILITY", 1.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_RENDER_PROBABILITY", 0.0)
    image = np.zeros((K.RF_DETR_TILE, K.RF_DETR_TILE, 3), np.uint8)
    image[:] = (60, 140, 50)
    boxes = [[100.0, 100.0, 39.0, 39.0]]
    changed = 0
    for seed in range(20):
        tile, _keep, _kept = T.random_tile(image, boxes, [0], random.Random(seed))
        hue = cv2.cvtColor(tile[:1, :1], cv2.COLOR_RGB2HSV)[0, 0, 0]
        assert abs(int(hue) - int(cv2.cvtColor(image[:1, :1], cv2.COLOR_RGB2HSV)[0, 0, 0])) <= 2
        changed += not np.array_equal(tile[0, 0], image[0, 0])
    assert changed >= 15


def test_nms_of_many_boxes_is_the_pairwise_rule() -> None:
    """The vectorised NMS keeps what the pairwise rule keeps (a weak model's thousands of boxes take milliseconds)."""
    rng = random.Random(4)
    detections = []
    for _ in range(400):
        x, y = rng.uniform(0, 300), rng.uniform(0, 300)
        detections.append(
            {"family": rng.choice(["node", "icon"]), "box": [x, y, x + 39, y + 39], "score": rng.random()}
        )
    kept = T.nms(detections, 0.5)
    expected = []
    for det in sorted(detections, key=lambda d: -d["score"]):
        if all(o["family"] != det["family"] or T.box_iou(det["box"], o["box"]) < 0.5 for o in expected):
            expected.append(det)
    assert kept == expected


def test_nms_keeps_one_detection_per_object_and_family() -> None:
    detections = [
        {"family": "node", "box": [0, 0, 40, 40], "score": 0.6},
        {"family": "node", "box": [2, 2, 42, 42], "score": 0.9},  # the same node, another tile or class
        {"family": "icon", "box": [2, 2, 36, 36], "score": 0.5},  # another family: kept
    ]
    kept = T.nms(detections, 0.5)
    assert [(d["family"], d["score"]) for d in kept] == [("node", 0.9), ("icon", 0.5)]


def test_a_small_crop_is_padded_to_one_tile() -> None:
    crop = np.full((500, 600, 3), 200, np.uint8)
    padded = T.pad_to_tile(crop, rgb=False)
    assert padded.shape == (K.RF_DETR_TILE, K.RF_DETR_TILE, 3)
    assert (padded[:500, :600] == 200).all() and tuple(padded[-1, -1]) == K.RF_DETR_HUD_FILL
    assert T.pad_to_tile(np.zeros((1080, 1920, 3), np.uint8), rgb=False).shape == (1080, 1920, 3)
    prepared, boxes = T.prepare(np.zeros((2160, 3840, 3), np.uint8), [[100, 100, 78, 78]], rgb=True)
    assert prepared.shape == (1080, 1920, 3) and boxes == [[50.0, 50.0, 39.0, 39.0]]


def test_tiles_are_centred_on_rare_classes_often(seed: int, runs) -> None:
    """With repeat factors, a rare object (a locked stronghold) is in the tile far more often than chance: measured
    about 95% of the tiles against 39%, so a margin of 0.3 holds at 200 draws by about 7 standard deviations."""
    image = np.zeros((1080, 1920, 3), np.uint8)
    boxes = [[1700.0, 100.0, 150.0, 150.0], [100.0, 900.0, 39.0, 39.0]]  # the rare one far in a corner
    draws = runs(200)

    def share(rare: set[int]) -> float:
        rng = random.Random(seed)  # the same draws for both, so only the centring differs
        return sum(0 in T.random_tile(image, boxes, [7, 0], rng, rare=rare)[1] for _ in range(draws)) / draws

    assert share({7}) > share(set()) + 0.3


def test_flips_mirror_pixels_and_boxes_together_when_turned_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off by default (the atlas is never mirrored); turned on for an experiment, a box still frames its object."""
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_FLIP_PROBABILITY", 1.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_RENDER_PROBABILITY", 0.0)
    monkeypatch.setattr(K, "RF_DETR_AUGMENT_SCALE_JITTER", 0.0)
    image = np.zeros((1080, 1920, 3), np.uint8)
    image[500:539, 900:939] = 255
    tile, _keep, kept = T.random_tile(image, [[900.0, 500.0, 39.0, 39.0]], [0], random.Random(1))
    x, y, w, h = (round(v) for v in kept[0])
    assert (tile[y : y + h, x : x + w] == 255).all()


def test_the_validation_tile_of_an_empty_screenshot() -> None:
    tile, keep, kept = T.densest_tile(np.zeros((1080, 1920, 3), np.uint8), [])
    assert tile.shape == (K.RF_DETR_TILE, K.RF_DETR_TILE, 3) and keep == [] and kept == []
    assert T.repeat_factors([]) == [] and T.rare_classes([]) == set()


def test_brightness_and_contrast_clip_at_black_and_white() -> None:
    """A tile darkened (or lightened) past the range is clipped: never folded back as a grey."""

    class Extreme:
        def __init__(self, pick) -> None:
            self.pick = pick

        def uniform(self, low: float, high: float) -> float:
            return self.pick(low, high)

    dark = T._brightness_contrast(np.full((4, 4, 3), 5, np.uint8), Extreme(min))
    light = T._brightness_contrast(np.full((4, 4, 3), 250, np.uint8), Extreme(max))
    assert dark.dtype == np.uint8 and (dark == 0).all() and (light == 255).all()
