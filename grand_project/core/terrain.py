"""core.terrain (from atlas_builder_core.py)"""

from __future__ import annotations

import cv2
import numpy as np

from .frame import hud_mask
from .geometry import to3

_MASKS: dict = {}  # id(image) -> (weak ref to the image, its mask): one screenshot is compared


_MASK_CACHE = 64  # with ~30 neighbours per placement (v1.01: the mask was rebuilt every time)


def _valid_mask(frame_img: np.ndarray) -> np.ndarray:
    """Return the cached ground mask of a screenshot (see _valid_mask_calc, with dark=True).

    One screenshot is compared with ~30 neighbours per placement, so masks are cached by image identity
    (v1.01: the mask was rebuilt every time). The returned array is shared and read-only.

    Args:
        frame_img: BGR screenshot image.

    Returns:
        (h, w) uint8 read-only mask: 255 = atlas ground, 0 = interface or black unexplored fog.
    """
    import weakref

    hit = _MASKS.get(id(frame_img))
    if hit is not None and hit[0]() is frame_img:
        return hit[1]
    m = _valid_mask_calc(frame_img)
    m.flags.writeable = False  # shared: callers must not change it
    try:
        # (gone with its screenshot: kept up to _MASK_CACHE after the picture was let go, ~2 MB each for nothing)
        key = id(frame_img)
        _MASKS[key] = (weakref.ref(frame_img, lambda _r, k=key: _MASKS.pop(k, None)), m)
        while len(_MASKS) > _MASK_CACHE:
            _MASKS.pop(next(iter(_MASKS)))
    except TypeError:  # (a view that cannot be weakly referenced)
        pass
    return m


def _valid_mask_calc(frame_img: np.ndarray, dark: bool = True) -> np.ndarray:
    """Compute which pixels of a screenshot show atlas ground.

    A full game window uses the drawn HUD mask (skill bars, globes, header, side columns, stats); a cropped
    screenshot uses rough boxes where the interface usually is. The mask is eroded by 7 px at the end.

    Args:
        frame_img: BGR screenshot image.
        dark: Also mask black unexplored fog (grey < 14, no texture).

    Returns:
        (h, w) uint8 mask: 255 = atlas ground of the screenshot; 0 = interface (and, with dark=True, black
        unexplored fog).
    """
    h, w = frame_img.shape[:2]
    m = np.full((h, w), 255, np.uint8)
    hud = hud_mask(w, h)
    if hud.any():  # a full game window: the drawn HUD mask (skill bars, globes, header, side columns, stats)
        m[hud > 0] = 0
    else:  # cropped screenshot: rough boxes where the interface usually is
        m[: max(112, 0), int(w * 0.20) : int(w * 0.74)] = 0  # world header / act tabs / search
        m[:94, :92] = 0
        m[:77, max(0, w - 200) :] = 0
        m[max(0, h - 100) :, :110] = 0  # globe
        m[max(0, h - 100) :, max(0, w - 110) :] = 0
        m[max(0, h - 27) :, :] = 0
        m[:, :210][int(h * 0.62) : int(h * 0.96), :] = 0  # stats / chat text, left edge
    if dark:
        fog = (cv2.cvtColor(frame_img, cv2.COLOR_BGR2GRAY) < 14).astype(np.uint8) * 255
        fog = cv2.erode(fog, np.ones((9, 9), np.uint8))  # unexplored black fog has no texture
        m[fog > 0] = 0
    return cv2.erode(m, np.ones((7, 7), np.uint8))


def terrain_ncc(img_a: np.ndarray, img_b: np.ndarray, M_b_to_a: np.ndarray) -> tuple[float, int]:
    """Measure how well two screenshots' terrain agrees where they overlap.

    Zero-mean NCC of blurred greyscale over the overlap of A and warped B. Slow lighting differences are
    removed first so the local texture is compared. Interface and fog pixels are left out.

    Args:
        img_a: BGR screenshot A (the reference).
        img_b: BGR screenshot B, warped into A.
        M_b_to_a: 2x3 or 3x3 map from B's screen px to A's screen px.

    Returns:
        (ncc, n): the correlation (-1..1; 0.0 when the overlap is under 15000 px or flat) and the number
        of overlapping ground pixels compared.
    """
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
