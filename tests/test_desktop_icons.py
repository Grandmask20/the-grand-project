"""desktop/icons.py: the desktop app's icons, from the tablet icon (or desktop/icon.png), in the sizes
electron-builder asks for."""

import importlib.util

from PIL import Image

from grand_project import paths


def _icons():
    spec = importlib.util.spec_from_file_location("desktop_icons", paths.ROOT / "desktop" / "icons.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_tablet_icon_makes_a_256_px_ico_and_a_512_px_png(tmp_path):
    icons = _icons()
    ico, png = icons.make(tmp_path / "build", icons.source(here=tmp_path))
    assert (256, 256) in Image.open(ico).info["sizes"]
    assert Image.open(png).size == (512, 512)


def test_an_own_icon_png_wins_over_the_tablet(tmp_path):
    Image.new("RGBA", (600, 600), (255, 0, 0, 255)).save(tmp_path / "icon.png")
    picture = _icons().source(here=tmp_path)
    assert picture.size == (600, 600) and picture.getpixel((0, 0)) == (255, 0, 0, 255)
