"""Make the desktop app's icons (CI: desktop.yml) into desktop/build/: icon.ico for Windows, icon.png for macOS.

    python desktop/icons.py

electron-builder wants 256 px for Windows and 512 px for macOS: from desktop/icon.png when there is one (512 px or
more: a proper one, to be added), else the program's tablet icon (references/the_grand_project.ico, 96 px) scaled up.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
TABLET = HERE.parent / "references" / "the_grand_project.ico"
WIN_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
MAC_SIZE = 512


def source(here: Path = HERE, tablet: Path = TABLET) -> Image.Image:
    """The biggest picture of the icon there is (desktop/icon.png, else the tablet icon's largest size), as RGBA."""
    own = here / "icon.png"
    if own.is_file():
        return Image.open(own).convert("RGBA")
    ico = Image.open(tablet)
    ico.size = max(ico.info["sizes"])  # (an .ico holds several: the largest)
    return ico.convert("RGBA")


def make(out: Path, picture: Image.Image) -> tuple[Path, Path]:
    """Write icon.ico (up to 256 px) and icon.png (512 px) into out.

    Args:
        out: The folder (made when missing).
        picture: The icon, any size (scaled up or down).

    Returns:
        The two files.
    """
    out.mkdir(parents=True, exist_ok=True)
    big = picture.resize((MAC_SIZE, MAC_SIZE), Image.Resampling.LANCZOS)
    ico, png = out / "icon.ico", out / "icon.png"
    big.save(ico, sizes=WIN_SIZES)
    big.save(png)
    return ico, png


if __name__ == "__main__":
    for f in make(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "build", source()):
        print(f)
