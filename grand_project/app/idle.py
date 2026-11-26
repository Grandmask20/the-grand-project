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
        """Let the screenshots' memory go when no job runs and none was read for IMAGE_IDLE_RELEASE_S: the decoded
        screenshots and what is worked out from them, the zoomed-in ground's own (sharp tiles: screenshots, weights)
        and the 3D scene (the page keeps the scene it has). All made again when next needed.

        Whether a job runs is asked under the session lock, and everything let go in that same locked step: a job
        starting in between used a cache as it was cleared. A job holding the lock is not idle time.

        Args:
            now: time.monotonic() (tests give their own).

        Returns:
            How many decoded screenshots were let go (0: not idle, or none kept).
        """
        atlas = self.atlas
        now = time.monotonic() if now is None else now
        if atlas is None or now - atlas.images_used < IMAGE_IDLE_RELEASE_S:
            return 0
        if not self._lock.acquire(blocking=False):  # (a job holds it: not idle)
            return 0
        try:
            sharp = getattr(self, "_sharp", None)
            held = (
                bool(atlas._images)
                or (sharp is not None and sharp.holding())
                or getattr(self, "_scene", None) is not None
            )
            if self.working() or atlas is not self.atlas or not held:
                return 0
            n = atlas.release_images() + (sharp.release() if sharp is not None else 0)
            core_terrain._MASKS.clear()
            fin_landmarks._OCEAN.clear()
            fin_traces._GOLD.clear()
            self._scene = self._scene3d = self._scene3d_steps = None
        finally:
            self._lock.release()
        gc.collect()
        self.events.log(f"idle: {n} decoded screenshots and the map's caches let go (made again when needed)")
        return n
