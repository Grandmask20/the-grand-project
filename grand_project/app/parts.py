"""app.parts: what the map is made of (map image, model) and how far each part is, for the page's loading cover.

The page shows the map once every part is ready, or as soon as one fails, from these states, not from a timer
guessing how long loading takes (a big atlas outgrew it, and a failed part only showed in the log: banner, user).
A part beats while it works (map image: per screenshot stitched; model: per step), so the page can tell "still
working" from "stopped making progress" however big the atlas is, and only then offers to show the map anyway.

It never takes the session's lock: the page asks for it (GET /api/parts) while the work it watches holds that lock.
"""

from __future__ import annotations

import threading
import time

PARTS = ("map_image", "model")


class Parts:
    """The states of the map's parts for the open atlas generation, safe to read from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # its own: never the session's
        self._gen = -1
        self._p: dict[str, dict] = {}

    def reset(self, gen: int) -> None:
        """Start a new atlas generation: every part waits.

        Args:
            gen: The new generation.
        """
        now = time.monotonic()
        with self._lock:
            self._gen = gen
            self._p = {n: {"state": "waiting", "error": None, "beat": now} for n in PARTS}

    def _set(self, name: str, gen: int | None, **kw) -> None:
        with self._lock:
            if gen is not None and gen != self._gen:
                return  # work for an atlas no longer open
            p = self._p.setdefault(name, {"state": "waiting", "error": None, "beat": time.monotonic()})
            p.update(kw, beat=time.monotonic())

    def start(self, name: str, gen: int | None = None) -> None:
        """A part's work began."""
        self._set(name, gen, state="building", error=None)

    def beat(self, name: str, gen: int | None = None) -> None:
        """A part's work moved on (still running)."""
        self._set(name, gen)

    def done(self, name: str, gen: int | None = None) -> None:
        """A part is ready."""
        self._set(name, gen, state="ready", error=None)

    def fail(self, name: str, error: str, gen: int | None = None) -> None:
        """A part failed (the page shows the map with what is there and says why)."""
        self._set(name, gen, state="failed", error=error)

    def payload(self) -> dict:
        """Return {"generation", "parts": {name: {"state", "error", "quiet" (s since its last beat)}}}."""
        now = time.monotonic()
        with self._lock:
            return {
                "generation": self._gen,
                "parts": {
                    n: {"state": p["state"], "error": p["error"], "quiet": round(now - p["beat"], 1)}
                    for n, p in self._p.items()
                },
            }
