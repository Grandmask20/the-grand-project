"""The classical landmark rules shared with the RF-DETR detector (grand_project/detect/landmarks.py)."""

from __future__ import annotations

from grand_project.detect import constants as K
from grand_project.detect.landmarks import stronghold_kind

NODE = [{"x": 1000.0, "y": 540.0}]  # a map node inside the stronghold at (1000, 540)


def test_a_stronghold_with_maps_inside_and_no_hand_is_open() -> None:
    assert stronghold_kind(1000.0, 540.0, [], NODE) == ("Breach stronghold", "purple structure")


def test_a_hand_reveal_button_beside_it_locks_it() -> None:
    near = (1000.0 + K.STRONGHOLD_LOCK_REACH - 1, 540.0)
    far = (1000.0 + K.STRONGHOLD_LOCK_REACH + 1, 540.0)
    assert stronghold_kind(1000.0, 540.0, [near], NODE) == ("Locked stronghold", "hand badge")
    assert stronghold_kind(1000.0, 540.0, [far], NODE)[0] == "Breach stronghold"


def test_a_stronghold_with_no_map_inside_is_locked() -> None:
    """Only ground shows inside a locked stronghold (STRONGHOLD_EMPTY)."""
    away = [{"x": 1000.0 + K.STRONGHOLD_EMPTY, "y": 540.0}]
    assert stronghold_kind(1000.0, 540.0, [], away) == ("Locked stronghold", "no maps inside")
