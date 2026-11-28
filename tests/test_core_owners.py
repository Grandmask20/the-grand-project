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


def test_the_same_view_twice_the_newer_keeps_every_spot():
    # (no times known: the later in the atlas is the newer; the older shows nothing better - user, 2026-11-25)
    at, frames = atlas_with(0, 0)
    shares = core.owned_shares(at, frames)
    assert shares["s1"] > 0.6 and shares["s0"] < core.OWNER_DUMP_SHARE  # (all but its edges)


def test_an_older_near_repeat_of_a_view_goes_to_dump():
    # the camera barely moved (a near-copy was placed 0.3 units off): "most central wins" split the area between the
    # two, and nothing ever went to dump; moved further, the older one shows ground clearly the newer doesn't
    at, frames = atlas_with(0, 10)
    shares = core.owned_shares(at, frames)
    assert shares["s0"] < core.OWNER_DUMP_SHARE and shares["s1"] > 0.6  # (its own edge strip doesn't keep it)


def test_the_time_a_screenshot_was_taken_decides_which_is_newer():
    at, frames = atlas_with(0, 10)
    frames[0]["taken"], frames[1]["taken"] = 2000.0, 1000.0  # (the first in the atlas is the newer one)
    shares = core.owned_shares(at, frames)
    assert shares["s0"] > 0.6 and shares["s1"] < core.OWNER_DUMP_SHARE


def test_an_older_view_panned_clearly_away_keeps_its_own_part():
    at, frames = atlas_with(0, 600)
    shares = core.owned_shares(at, frames)
    assert shares["s0"] > 0.2  # (where it shows the ground clearly more centrally, or alone)


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
