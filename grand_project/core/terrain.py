"""core.terrain (from atlas_builder_core.py)"""

from __future__ import annotations

import cv2
import numpy as np

from .frame import hud_mask
from .geometry import to3

_MASKS: dict = {}  # id(image) -> (weak ref to the image, its mask): one screenshot is compared


_MASK_CACHE = 64  # with ~30 neighbours per placement (v1.01: the mask was rebuilt every time)


def _valid_mask(frame_img: np.ndarray) -> np.ndarray:
    import weakref

    hit = _MASKS.get(id(frame_img))
    if hit is not None and hit[0]() is frame_img:
        return hit[1]
    m = _valid_mask_calc(frame_img)
    m.flags.writeable = False  # shared: callers must not change it
    try:
        _MASKS[id(frame_img)] = (weakref.ref(frame_img), m)
        while len(_MASKS) > _MASK_CACHE:
            _MASKS.pop(next(iter(_MASKS)))
    except TypeError:  # (a view that cannot be weakly referenced)
        pass
    return m


def _valid_mask_calc(frame_img: np.ndarray) -> np.ndarray:
    h, w = frame_img.shape[:2]
    m = np.full((h, w), 255, np.uint8)
    m[: max(112, 0), int(w * 0.20) : int(w * 0.74)] = 0  # world header / act tabs / search
    m[:94, :92] = 0
    m[:77, max(0, w - 200) :] = 0
    m[max(0, h - 100) :, :110] = 0  # globe
    m[max(0, h - 100) :, max(0, w - 110) :] = 0
    m[max(0, h - 27) :, :] = 0
    m[:, :210][int(h * 0.62) : int(h * 0.96), :] = 0  # stats / chat text, left edge
    m[hud_mask(w, h) > 0] = 0  # skill bars, globes, side icon columns
    dark = (cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY) < 14).astype(np.uint8) * 255
    dark = cv2.erode(dark, np.ones((9, 9), np.uint8))  # unexplored black fog has no texture
    m[dark > 0] = 0
    return cv2.erode(m, np.ones((7, 7), np.uint8))


def terrain_ncc(img_a: np.ndarray, img_b: np.ndarray, M_b_to_a: np.ndarray) -> tuple[float, int]:
    """Zero-mean NCC of blurred greyscale over the overlap of A and warped B (2x3 or 3x3 map)."""
    h, w = img_a.shape[:2]
    H = to3(M_b_to_a) if M_b_to_a.shape == (2, 3) else M_b_to_a
    warped = cv2.warpPerspective(img_b, H, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    mb = cv2.warpPerspective(_valid_mask(img_b), H, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
    mask = (mb > 0) & (_valid_mask(img_a) > 0)
    mask = cv2.erode(mask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    n = int(mask.sum())
    if n < 15000:
        return 0.0, n
    ga = cv2.GaussianBlur(cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY), (0, 0), 2.5).astype(np.float32)
    gb = cv2.GaussianBlur(cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY), (0, 0), 2.5).astype(np.float32)
    # remove slow lighting differences, compare the local texture
    ga -= cv2.GaussianBlur(ga, (0, 0), 14)
    gb -= cv2.GaussianBlur(gb, (0, 0), 14)
    a, b = ga[mask], gb[mask]
    a -= a.mean()
    b -= b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return (float((a * b).sum() / den) if den > 1e-6 else 0.0), n
