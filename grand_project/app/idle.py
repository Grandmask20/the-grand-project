"""app.idle: the screenshots' memory given back while the app sits idle.

The app stays open while you play. Placing and checking screenshots keeps up to core.Atlas.IMAGE_CACHE of them
decoded (~6 MB each), with what is worked out per screenshot (terrain masks, ground classes, gold paths): ~650 MB of
a big atlas, kept for nothing once the work is done (user). After IMAGE_IDLE_RELEASE_S with no job running and no
screenshot read, all of it is let go; the next add reads the screenshots it needs again (~1-2 s).
"""

from __future__ import annotations

import contextlib
import gc
import threading
import time

from grand_project.core import terrain as core_terrain
from grand_project.finalize import landmarks as fin_landmarks
from grand_project.finalize import traces as fin_traces

from .constants import IDLE_LOOK_EVERY_S, IMAGE_IDLE_RELEASE_S


class IdleMixin:
    """AtlasSession mixin: give the screenshots' memory back when idle (see the module docstring)."""

    def _init_idle(self, start: bool = True) -> None:
        """Start looking for idle time, when asked.

        Args:
            start: Start the looking thread (tests call release_idle themselves).
        """
        if start:
            threading.Thread(target=self._idle_loop, daemon=True, name="idle").start()

    def _idle_loop(self) -> None:
        """Look every IDLE_LOOK_EVERY_S whether the app went idle, forever."""
        while True:
            time.sleep(IDLE_LOOK_EVERY_S)
            with contextlib.suppress(Exception):  # (never the end of the loop: next time)
                self.release_idle()

    def release_idle(self, now: float | None = None) -> int:
        """Let the screenshots' memory go when no job runs and none was read for IMAGE_IDLE_RELEASE_S.

        Args:
            now: time.monotonic() (tests give their own).

        Returns:
            How many decoded screenshots were let go (0: not idle, or nothing kept).
        """
        atlas = self.atlas
        now = time.monotonic() if now is None else now
        if atlas is None or self.working() or not atlas._images or now - atlas.images_used < IMAGE_IDLE_RELEASE_S:
            return 0
        n = atlas.release_images()
        core_terrain._MASKS.clear()
        fin_landmarks._OCEAN.clear()
        fin_traces._GOLD.clear()
        gc.collect()
        self.events.log(f"idle: {n} decoded screenshots let go (read again when needed)")
        return n
