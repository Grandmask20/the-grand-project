"""viewer.framelog: record frame timings while you use the window (a mixin; see viewer/app.py).

Switched on in the Debug tab (internal copy) or with the ATLAS_FRAME_LOG=1 environment variable. While on,
every redraw is written with the time each part of drawing took, the window's stalls (the window thread
did not get back to Tk for longer than FRAME_STALL_MS), your wheel / drag input and every sharp-ground
tile built in the background, to user_data/frame_log_<date>_<time>.csv. Stopping writes a summary to the Log
tab. Columns:

    t_ms      time since recording started
    kind      frame / stall / input / tile / gc (a full garbage collection)
    total_ms  frame: the whole redraw; stall: how long the window did not respond; tile: build time
    wait_ms   frame: from the redraw being asked for to it starting
    terrain .. landmarks, show: ms per part of the frame (show = putting the picture on the screen)
    z, cx, cy, w, h: zoom, view centre, canvas size
    tiles_shown, tiles_missing: sharp-ground tiles drawn / still being built
    info      input: which (wheel / drag / press / release); tile: its level and position
"""

from __future__ import annotations

import contextlib
import csv
import gc
import os
import statistics
import time

from grand_project import paths as rc_paths

from .constants import FRAME_STALL_MS, FRAME_TICK_MS
from .helpers import LOG

SECTIONS = ("terrain", "tiles", "biomes", "paths", "nodes", "icons", "landmarks", "rest", "show")
COLUMNS = ("t_ms", "kind", "total_ms", "wait_ms", *SECTIONS, "z", "cx", "cy", "w", "h", "tiles_shown",
           "tiles_missing", "info")  # fmt: skip


class FrameLogMixin:
    """Viewer mixin that records frame timings, stalls, input, tile builds and garbage collections to a CSV file.

    The recording calls (_fl_...) are cheap no-ops while not recording.

    Attributes:
        _fl_rows: Rows recorded since the last write to the file; None while not recording.
    """

    _fl_rows: list | None = None  # None: not recording

    def frame_log_autostart(self):
        """Start recording at startup when the ATLAS_FRAME_LOG environment variable is set."""
        if os.environ.get("ATLAS_FRAME_LOG"):
            self.start_frame_log()

    # ------------------------------------------------------------------ on / off
    def toggle_frame_log(self):
        """Start or stop recording (the frame log checkbox in the Debug tab)."""
        if self._fl_rows is None:
            self.start_frame_log()
        else:
            self.stop_frame_log()

    def start_frame_log(self):
        """Start recording to a new user_data/frame_log_<date>_<time>.csv (does nothing if already recording).

        Writes the header, starts the stall tick and the garbage collection hook, ticks the Debug tab's checkbox and
        says where it records in Log.
        """
        if self._fl_rows is not None:
            return
        rc_paths.USER_DATA.mkdir(parents=True, exist_ok=True)
        self._fl_file = rc_paths.USER_DATA / time.strftime("frame_log_%Y%m%d_%H%M%S.csv")
        self._fl_t0 = time.perf_counter()
        self._fl_rows = []
        self._fl_all: list = []  # everything recorded (for the summary)
        self._fl_marks: list = []
        self._fl_asked = None  # when the pending redraw was asked for
        self._fl_tick_last = time.perf_counter()
        self._fl_tiles = (0, 0)
        with open(self._fl_file, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(COLUMNS)
        self.root.after(FRAME_TICK_MS, self._fl_tick)
        gc.callbacks.append(self._fl_gc)
        if getattr(self, "frame_log_var", None) is not None:
            self.frame_log_var.set(True)
        self.log(f"frame log: recording to {self._fl_file}")

    def stop_frame_log(self):
        """Stop recording: write what is left, unhook, untick the checkbox and put a summary in Log."""
        if self._fl_rows is None:
            return
        self._fl_flush()
        with contextlib.suppress(ValueError):
            gc.callbacks.remove(self._fl_gc)
        rows, self._fl_rows = self._fl_all, None
        if getattr(self, "frame_log_var", None) is not None:
            self.frame_log_var.set(False)
        self.log(self._fl_summary(rows))
        self.log(f"frame log saved: {self._fl_file}")

    # ------------------------------------------------------------------ recording (cheap no-ops when off)
    def _fl_now(self) -> float:
        """Time since recording started.

        Returns:
            Milliseconds.
        """
        return (time.perf_counter() - self._fl_t0) * 1000

    def _fl_mark(self, section: str):
        """Mark the end of one part of the frame being drawn.

        Args:
            section: Part name, one of SECTIONS (e.g. "terrain", "paths", "show").
        """
        if self._fl_rows is not None:
            self._fl_marks.append((section, time.perf_counter()))

    def _fl_asked_redraw(self):
        """Note when the pending redraw was first asked for (for the frame's wait_ms)."""
        if self._fl_rows is not None and self._fl_asked is None:
            self._fl_asked = time.perf_counter()

    def _fl_frame_start(self):
        """Note the start of a redraw."""
        if self._fl_rows is not None:
            self._fl_marks = [("start", time.perf_counter())]

    def _fl_frame_end(self, w, h):
        """Record a finished frame: the whole time, the wait, ms per part, the view and the tiles shown / missing.

        Args:
            w: Canvas width in screen px.
            h: Canvas height in screen px.
        """
        if self._fl_rows is None or not self._fl_marks:
            return
        t_start = self._fl_marks[0][1]
        parts = dict.fromkeys(SECTIONS, 0.0)
        prev = t_start
        for name, t in self._fl_marks[1:]:
            parts[name] = parts.get(name, 0.0) + (t - prev) * 1000
            prev = t
        end = time.perf_counter()
        wait = (t_start - self._fl_asked) * 1000 if self._fl_asked is not None else ""
        self._fl_asked = None
        shown, missing = self._fl_tiles
        self._fl_tiles = (0, 0)
        self._fl_rows.append(
            [round((t_start - self._fl_t0) * 1000, 1), "frame", round((end - t_start) * 1000, 1),
             round(wait, 1) if wait != "" else "", *(round(parts[s], 2) for s in SECTIONS),
             round(self.z, 4), round(self.cx, 1), round(self.cy, 1), w, h, shown, missing, ""]
        )  # fmt: skip

    def _fl_gc(self, phase, info):
        """Record garbage collections of the oldest generation (the long ones), from whichever thread ran them.

        Hooked into gc.callbacks while recording.

        Args:
            phase: "start" or "stop".
            info: The gc callback's info dict ("generation", "collected").
        """
        if phase == "start":
            self._fl_gc_t = time.perf_counter()
        elif info.get("generation") == 2 and self._fl_rows is not None:
            ms = (time.perf_counter() - getattr(self, "_fl_gc_t", time.perf_counter())) * 1000
            self._fl_rows.append(self._fl_row("gc", round(ms, 1), f"collected {info.get('collected', 0)}"))

    def _fl_tiles_drawn(self, shown: int, missing: int):
        """Note how many sharp-ground tiles this frame drew and still misses.

        Args:
            shown: Tiles drawn.
            missing: Tiles still being built.
        """
        if self._fl_rows is not None:
            self._fl_tiles = (shown, missing)

    def _fl_input(self, what: str):
        """Record a mouse input.

        Args:
            what: "wheel", "drag", "press" or "release".
        """
        if self._fl_rows is not None:
            self._fl_rows.append(self._fl_row("input", "", what))

    def _fl_tile_built(self, key, ms: float):
        """Record a sharp-ground tile built, from the tile worker thread (a list append is safe there).

        Args:
            key: The tile's (level, column, row).
            ms: Build time in ms.
        """
        if self._fl_rows is not None:
            self._fl_rows.append(self._fl_row("tile", round(ms, 1), f"level {key[0]:g} tile {key[1]},{key[2]}"))

    def _fl_row(self, kind, total, info):
        """A CSV row for a non-frame event, with the current view.

        Args:
            kind: Row kind: "stall", "input", "tile" or "gc".
            total: The total_ms value (or "").
            info: The info column text.

        Returns:
            List of values in COLUMNS order.
        """
        return [round(self._fl_now(), 1), kind, total, "", *([""] * len(SECTIONS)), round(self.z, 4),
                round(self.cx, 1), round(self.cy, 1), "", "", "", "", info]  # fmt: skip

    def _fl_tick(self):
        """Check for stalls every FRAME_TICK_MS: a late tick means the window thread was busy (a stall).

        Records lateness over FRAME_STALL_MS and writes rows to the file once more than 400 are waiting. Runs on the
        window thread via root.after until recording stops.
        """
        if self._fl_rows is None:
            return
        now = time.perf_counter()
        late = (now - self._fl_tick_last) * 1000 - FRAME_TICK_MS
        self._fl_tick_last = now
        if late > FRAME_STALL_MS:
            self._fl_rows.append(self._fl_row("stall", round(late, 1), ""))
        if len(self._fl_rows) > 400:
            self._fl_flush()
        self.root.after(FRAME_TICK_MS, self._fl_tick)

    def _fl_flush(self):
        """Append the waiting rows to the CSV file (also kept for the summary); a failed write is only logged."""
        rows = self._fl_rows or []
        if not rows:
            return
        self._fl_all += rows
        self._fl_rows = []
        try:
            with open(self._fl_file, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(rows)
        except OSError:
            LOG.warning("frame log could not be written", exc_info=True)

    @staticmethod
    def _fl_summary(rows) -> str:
        """One-line summary of a recording for the Log tab.

        Args:
            rows: Every row recorded, in COLUMNS order.

        Returns:
            Frame count, median / 95% / worst frame ms, the four slowest parts on average, stalls, tiles built and full
            garbage collections.
        """
        frames = [r for r in rows if r[1] == "frame"]
        stalls = [r[2] for r in rows if r[1] == "stall"]
        tiles = [r[2] for r in rows if r[1] == "tile"]
        gcs = [r[2] for r in rows if r[1] == "gc"]
        if not frames:
            return "frame log: no frames recorded"
        tot = sorted(r[2] for r in frames)
        p95 = tot[min(len(tot) - 1, int(0.95 * len(tot)))]
        avg = {s: statistics.mean(float(r[4 + k]) for r in frames) for k, s in enumerate(SECTIONS)}
        top = ", ".join(f"{s} {v:.0f}" for s, v in sorted(avg.items(), key=lambda kv: -kv[1])[:4])
        out = (
            f"frame log: {len(frames)} frames, median {statistics.median(tot):.0f} ms, 95% under {p95:.0f} ms, "
            f"worst {tot[-1]:.0f} ms | most time (avg ms): {top} | {len(stalls)} stalls"
        )
        if stalls:
            out += f" (worst {max(stalls):.0f} ms)"
        if tiles:
            out += f" | {len(tiles)} tiles built, avg {statistics.mean(tiles):.0f} ms"
        if gcs:
            out += f" | {len(gcs)} full garbage collections, worst {max(gcs):.0f} ms"
        return out
