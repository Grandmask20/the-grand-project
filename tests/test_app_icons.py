"""The icon types' names, search aliases, colours, row positions and pictures (app.icons)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from grand_project.app import icons
from grand_project.app.constants import ICON_DRAW_REV, ICON_INFO, ICON_ROW_DY, ICON_ROW_STEP

UNKNOWN = "NoSuchIconTypeForTests"


def test_hex_and_bgr_colours_convert_both_ways():
    assert icons.hex_bgr("#ffcc00", None) == (0, 204, 255)
    assert icons.hex_bgr("ffcc00", None) == (0, 204, 255)  # the # is optional
    for bad in ("", None, "#fff", "#zzzzzz", "#12345678"):
        assert icons.hex_bgr(bad, "default") == "default"
    assert icons.bgr_hex((0, 204, 255)) == "#ffcc00"
    assert icons.bgr_hex(icons.hex_bgr("#3a7bd5", None)) == "#3a7bd5"


def test_icons_of_a_map_stand_in_a_row_above_it():
    nodes = [{"x": 100.0, "y": 200.0}, {"x": 500.0, "y": 500.0}]
    icons_ = [{"x": 130.0, "y": 170.0}, {"x": 90.0, "y": 180.0}, {"x": 101.0, "y": 175.0}, {"x": 7.0, "y": 8.0}]
    pts = icons.icon_rows(nodes, icons_, {0: 0, 1: 0, 2: 0})
    y = 200 - ICON_ROW_DY
    # left to right by where they were seen, centred on the map, ICON_ROW_STEP apart
    assert np.allclose(pts[1], (100 - ICON_ROW_STEP, y))
    assert np.allclose(pts[2], (100, y))
    assert np.allclose(pts[0], (100 + ICON_ROW_STEP, y))
    assert np.allclose(pts[3], (7, 8))  # no map: where it was seen


def test_icon_rows_of_no_icons_is_empty():
    assert icons.icon_rows([], [], {}).shape == (0, 2)


def test_names_aliases_labels_and_colours():
    raw = "MapBoss"
    name, colour, aliases = ICON_INFO[raw]
    assert icons.icon_name(raw) == name
    assert icons.icon_aliases(raw) == f"{name} {aliases} {raw}".lower()
    assert icons.icon_col(raw) == colour
    assert icons.icon_name("MapBossThing") == "Map boss thing"  # unknown: the raw name in words
    assert icons.icon_aliases("MapBossThing") == "mapbossthing"
    assert icons.icon_col(UNKNOWN) == (230, 140, 255)  # unknown: violet
    assert icons.icon_label({"name": raw, "label": "Big one"}) == "Big one"
    assert icons.icon_label({"name": raw}) == name


def test_flat_and_outline_pictures_are_drawn_in_the_type_colour():
    b, g, r = icons.icon_col("MapBoss")
    for style in ("flat colour", "outline"):
        img = icons.icon_picture("MapBoss", 32, style)
        assert img.size == (32, 32) and img.mode == "RGBA"
        px = np.array(img)
        solid = px[px[..., 3] > 250][:, :3].astype(int)
        assert len(solid) and np.abs(solid - (r, g, b)).sum(axis=1).min() < 30
    flat = np.array(icons.icon_picture("MapBoss", 32, "flat colour"))
    ring = np.array(icons.icon_picture("MapBoss", 32, "outline"))
    assert flat[16, 16, 3] == 255 and ring[16, 16, 3] == 0  # the outline is hollow


def test_a_type_without_any_art_is_a_dot_in_its_colour(monkeypatch):
    monkeypatch.setattr(icons, "_zip_art", lambda raw: None)
    monkeypatch.setattr(icons, "_poe2db_art", lambda raw, size: None)
    for style in ("game art", "poe2db art", "from screenshots"):
        img = icons.icon_picture(UNKNOWN, 40, style)
        px = np.array(img)
        assert img.size == (40, 40)
        assert px[20, 20, 3] == 255 and tuple(px[20, 20, :3]) == (255, 140, 230)  # violet, RGB
        assert px[0, 0, 3] == 0  # round: the corners are clear


def test_game_art_comes_from_the_icon_zip():
    art = icons._zip_art("MapBoss")
    assert art is not None and art.mode == "RGBA"
    img = icons.icon_picture("MapBoss", 48)
    assert img.size == (48, 48)
    assert icons._zip_art(UNKNOWN) is None


def test_png_pictures_are_cached_per_type_size_and_style():
    icons._PICTURES.clear()
    a = icons.icon_png("MapBoss", 24, "flat colour")
    assert a[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(a)).size == (24, 24)
    assert icons.icon_png("MapBoss", 24, "flat colour") is a  # from the cache
    assert icons.icon_png("MapBoss", 32, "flat colour") is not a
    assert len(icons._PICTURES) == 2


def test_art_version_names_the_drawing_and_is_kept_a_while(monkeypatch):
    v = icons.icon_art_version()
    assert v.startswith(f"{ICON_DRAW_REV}-")
    calls = []
    monkeypatch.setattr(icons, "_art_version", lambda: calls.append(1) or "changed")
    assert icons.icon_art_version() == v and not calls  # within ICON_ART_RECHECK: not worked out again
    monkeypatch.setattr(icons, "_ART_VERSION", (-1e9, v))
    assert icons.icon_art_version() == "changed" and calls
