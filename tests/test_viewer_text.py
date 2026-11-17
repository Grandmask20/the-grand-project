"""Text drawn on the map: the black outline sits exactly around the coloured text (no doubled black copy)."""

import numpy as np

from grand_project.viewer.helpers import BoxGrid, put_text


def test_outline_follows_the_text():
    """The outline is at most a pixel or two wider than the coloured text on each side.

    With OpenCV 5's font a thicker stroke also spaces letters wider; an outline drawn as one thick stroke drifted
    right of the text and showed as doubled black text in the progress boxes (user).
    """
    for text in ("detecting 3 screenshots..   3s", "re-checking the whole atlas.   12s"):
        img = np.full((60, 600, 3), 200, np.uint8)
        put_text(img, text, (10, 40), (0, 220, 255), 0.55)
        yellow = (img[..., 2] > 200) & (img[..., 0] < 80)
        black = img.max(axis=2) < 60
        xs_y, xs_b = np.nonzero(yellow.any(axis=0))[0], np.nonzero(black.any(axis=0))[0]
        assert xs_b.min() >= xs_y.min() - 3 and xs_b.max() <= xs_y.max() + 3, (text, xs_y.max(), xs_b.max())


def test_box_grid_finds_overlaps_nearby_only():
    """Icon names are checked against the boxes around them (review: no full list per name)."""
    g = BoxGrid()
    g.add((100, 100, 140, 120))
    assert g.hits((130, 110, 200, 125))  # overlaps
    assert not g.hits((141, 100, 200, 120))  # touches the edge only
    assert not g.hits((1000, 1000, 1100, 1020))  # far away
    g.add((-50, -10, -20, 5))  # off the left / top edge
    assert g.hits((-30, 0, 0, 10))
