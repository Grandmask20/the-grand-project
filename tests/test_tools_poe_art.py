"""tools.poe_art: the page's pictures made from the game's interface art (the stash tab lined up and recoloured)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from tools.poe_art import line_up, stash_tab, trimmed


def piece(width: int, strip: tuple[int, int]) -> np.ndarray:
    """A made-up grey tab piece: 50 rows, light fill above row 42, a bottom strip only over `strip` (as the game's)."""
    p = np.zeros((50, width, 4), np.float32)
    p[:42, :, :] = (200, 200, 200, 255)
    p[42:, strip[0] : strip[1], :] = (230, 230, 230, 255)
    return p


def test_trimmed_cuts_a_picture_to_its_art():
    im = Image.new("RGBA", (48, 60))
    im.paste((255, 255, 255, 255), (0, 0, 39, 50))
    assert trimmed(im).size == (39, 50)


def test_the_pieces_line_up_by_their_bottom_strips():
    # (as the game's: left's strip ends at column 31, the middle's runs 9..35, right's starts at 8)
    grey = line_up(piece(39, (2, 32)), piece(43, (9, 36)), piece(39, (8, 39)), middles=3)
    assert (grey[45, 2:-1, 3] > 200).all()  # no gap along the bottom
    assert grey.shape[1] == 23 + 27 * 2 + 35 - 8 + 39


def test_lit_and_unlit_take_the_stash_tab_colours():
    grey = line_up(piece(39, (2, 32)), piece(43, (9, 36)), piece(39, (8, 39)), middles=1)[:44]
    light = np.ones(grey.shape[:2], np.float32)
    lit = np.asarray(stash_tab(grey, light, True)).astype(int)
    unlit = np.asarray(stash_tab(grey, light, False)).astype(int)
    assert lit[20, 40, 3] == 255 and unlit[20, 40, 3] == 255
    assert np.abs(unlit[20, 40, :3] - (0x4E, 0x42, 0x2C)).max() <= 2  # unlit: one flat brown
    assert lit[20, 40, :3].sum() > unlit[20, 40, :3].sum()  # lit: brighter (its fade)
