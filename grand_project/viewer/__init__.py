"""PoE2 Atlas viewer: browse, search and bookmark a merged atlas, and add screenshots to it.

    py atlas_viewer.py                      (reopens the last atlas)
    py atlas_viewer.py my_atlas.json

Mouse:  wheel = zoom at cursor, drag = pan, click = select, double-click = zoom in,
        right-click = bookmark here / show source screenshots.
Keys:   + / - zoom, 0 fit, arrows pan, Ctrl+F search, Ctrl+B bookmark selection,
        Ctrl+O open, Ctrl+S save (Cmd instead of Ctrl on macOS), Delete remove selected bookmark.

Shows the atlas-wide result (atlas["final"]): nodes and paths checked against every screenshot.
The atlas file is the same JSON the command-line builder writes; bookmarks are stored in it.
"""

from .app import Viewer, main  # noqa: F401
from .constants import VERSION  # noqa: F401
