# PyInstaller: the program frozen for the desktop app (one folder: desktop/build/backend). From the repo's top:
#     pyinstaller desktop/grand-project.spec --noconfirm --distpath desktop/build --workpath desktop/build/pyinstaller
# The program's own files go where it looks for them (grand_project/paths.py: ROOT is the folder above the package,
# here PyInstaller's _internal): references/, frontend/dist/ (the page, built), channel.txt and manifest.json (the
# player release's: which release this is).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (PyInstaller's)

datas = [(str(ROOT / "references"), "references"), (str(ROOT / "frontend" / "dist"), "frontend/dist")]
datas += [(str(ROOT / f), ".") for f in ("channel.txt", "manifest.json", "LICENSE") if (ROOT / f).is_file()]

# every module of the program (some are started by name: python -m grand_project.core.seams), skops's own (it imports
# its parts by name: skops.io._sklearn, ...), and what the stored detector models are made of (skops builds them by
# name: grand_project/detect/models.py). desktop/backend.py --self-check loads them all (CI: desktop.yml)
hidden = collect_submodules("grand_project") + collect_submodules("skops")
hidden += collect_submodules("sklearn.ensemble._hist_gradient_boosting")
hidden += ["sklearn._loss._loss", "sklearn._loss.link", "sklearn._loss.loss", "sklearn.preprocessing._label", "skops.io"]

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "backend.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hidden,
    # no Tk (grand_project/builder.py stands in for it when missing), no test tools
    excludes=["tkinter", "pytest", "matplotlib", "IPython"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="grand-project",
    # a console program: the desktop app reads the page's address from what it prints, and starts it without a window
    console=True,
    icon=str(ROOT / "references" / "the_grand_project.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="backend")  # noqa: F821
