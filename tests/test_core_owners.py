"""How much of the map picture each screenshot owns (core.owners), for the dump folder."""

import numpy as np

from grand_project import core


def atlas_with(*xs: float) -> tuple[core.Atlas, list[dict]]:
    """An atlas with 1920 x 1080 screenshots placed 1:1 at these x offsets (atlas units = px)."""
    at = core.Atlas()
    frames = [
        {"name": f"s{k}", "path": f"s{k}.png", "w": 1920, "h": 1080, "M": [[1, 0, x], [0, 1, 0]], "stats": {}}
        for k, x in enumerate(xs)
    ]
    at.frames = frames
    return at, frames


def test_overlapping_screenshots_each_own_the_part_they_show_most_centrally():
    at, frames = atlas_with(0, 900)
    shares = core.owned_shares(at, frames)
    assert 0.3 < shares["s0"] < 0.9 and 0.3 < shares["s1"] < 0.9


def test_a_screenshot_shown_better_everywhere_owns_nothing():
    # the same view twice: the first keeps every spot (a tie isn't taken over), the second shows nothing better
    at, frames = atlas_with(0, 0)
    shares = core.owned_shares(at, frames)
    assert shares["s0"] > 0.9 and shares["s1"] < core.OWNER_DUMP_SHARE


def test_an_edge_view_between_two_central_ones_owns_little():
    # s1 sits half over s0 and half over s2: most of what it shows, the other two show more centrally
    at, frames = atlas_with(0, 960, 1920)
    shares = core.owned_shares(at, frames)
    assert shares["s1"] < shares["s0"] and shares["s1"] < shares["s2"]


def test_a_clean_maps_ownership_is_read_as_it_is():
    at, frames = atlas_with(0, 0)
    owner = np.full((1080, 1920), -1, np.int16)
    owner[:, :960] = 1  # (names[1] = s0)
    names = ["s1", "s0"]
    shares = core.owned_shares(at, frames, (owner, names, (0.0, 0.0, 1.0)))
    assert abs(shares["s0"] - 0.5) < 0.01 and shares["s1"] == 0.0
