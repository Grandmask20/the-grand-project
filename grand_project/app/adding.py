"""app.adding: part of AtlasSession (a mixin; see app/session.py): adding screenshots.

One background worker runs jobs one at a time: added by hand, auto-add (watched folder), placed by hand near a
spot ("drop"), waiting screenshots retried, undo, and the whole-atlas re-check. The worker changes the atlas only
while holding the session lock. Questions (a weak match, a screenshot that could not be lined up where it was put)
go to the page through Events.ask, with a picture of the screenshot where it would go.
"""

from __future__ import annotations

import contextlib
import itertools
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from grand_project import builder, core
from grand_project import cities as atlas_cities
from grand_project import finalize as atlas_finalize
from grand_project import logs as atlas_log
from grand_project import paths as rc_paths
from grand_project.core import islands
from grand_project.core.geometry import apply as apply_affine
from grand_project.core.register import mutual_pairs

from . import recheck_choices
from .atlaslock import atlas_edit, atlas_switch
from .constants import (
    DETECT_LOG_EVERY,
    PICTURE_SIDE,
    PICTURES_KEPT,
    PREVIEW_AGREE_TOL,
    PREVIEW_NEAR,
    RECENT_FADE,
    RECENT_KEEP,
    RECHECK_CLEAN_S,
    RECHECK_DETECT_S,
    RECHECK_TIMING_MIN,
    UNDO_KEEP,
    VERSION,
    WATCH_BATCH,
    WEAK_INLIERS,
    WEAK_NCC,
)
from .icons import icon_label
from .model import view_model

LOG = atlas_log.get("app")


def outline(atlas, f: dict) -> np.ndarray:
    """Return a screenshot's outline on the atlas.

    Args:
        atlas: The atlas.
        f: A frame dict from atlas.frames.

    Returns:
        Its 4 corners in atlas units, shape (4, 2).
    """
    H = core.screen_to_atlas(np.array(f["M"], float), atlas.frame_R(f))
    return core.persp(H, [[0, 0], [f["w"], 0], [f["w"], f["h"]], [0, f["h"]]])


def flat_picture(img: np.ndarray, H: np.ndarray, side: int = PICTURE_SIDE) -> tuple[bytes, list[float]]:
    """Flatten a screenshot onto the atlas plane, as a see-through PNG (for the map's ghost and previews).

    Args:
        img: The screenshot (BGR).
        H: 3x3 transform from its px to atlas units.
        side: Longest side of the picture in px.

    Returns:
        (PNG bytes with alpha, [x0, y0, x1, y1] the picture covers in atlas units).
    """
    h, w = img.shape[:2]
    corners = core.persp(H, [[0, 0], [w, 0], [w, h], [0, h]])
    x0, y0 = corners.min(axis=0)
    x1, y1 = corners.max(axis=0)
    k = side / max(x1 - x0, y1 - y0, 1e-6)
    out_w, out_h = max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k))
    A = np.array([[k, 0, -x0 * k], [0, k, -y0 * k], [0, 0, 1]]) @ H
    pic = cv2.warpPerspective(img, A, (out_w, out_h), flags=cv2.INTER_AREA, borderValue=0)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), A, (out_w, out_h), flags=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", np.dstack([pic, mask]))
    if not ok:
        raise OSError("picture could not be encoded")
    return buf.tobytes(), [float(x0), float(y0), float(x1), float(y1)]


class AddingMixin:
    """AtlasSession mixin: the background worker and its jobs (see the module docstring)."""

    def _init_adding(self, start: bool = True) -> None:
        """Make the job queue and, when asked, start the worker thread.

        Args:
            start: Start the worker (tests run jobs with run_job on their own thread).
        """
        self._jobs: queue.Queue = queue.Queue()
        # held while a job is queued, and while an atlas switch checks that none is (taken inside the session lock,
        # never around it): a job admitted between that check and the switch ran on no atlas / the next one, the
        # worker then dropped it (CodeRabbit). Apart from the session lock, which a running job holds for long.
        self._admit = threading.RLock()
        self._busy = False
        self._pictures: dict[int, bytes] = {}
        self._picture_ids = itertools.count(1)
        self._forget_adding()
        if start:
            threading.Thread(target=self._worker, daemon=True, name="adding").start()

    def _forget_adding(self) -> None:
        """Clear undo, recently added and waiting: they belong to the atlas they were made in."""
        self._undo: list[dict] = []
        self.recent: list[str] = []
        self._pending_watch: list = []
        self._taken: set[str] = set()
        self._wait_tries: dict[str, int] = {}
        self.recent_pick: str | None = None

    # ------------------------------------------------------------------ queue
    def working(self) -> bool:
        """Tell whether a job is queued or running.

        Returns:
            True while there is work.
        """
        return self._busy or self._jobs.unfinished_tasks > 0

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until no job is queued or running.

        Args:
            timeout: Seconds at most (None: no limit).

        Returns:
            True when idle.
        """
        end = None if timeout is None else time.monotonic() + timeout
        while self.working():
            if end is not None and time.monotonic() > end:
                return False
            time.sleep(0.05)
        return True

    def _queue_job(self, paths, mode, gen: int | None = None) -> None:
        """Hand a job to the worker, tagged with the atlas it is for (not started while closing).

        Args:
            paths: Screenshot files (may be empty: "undo", "recheck_all", retry).
            mode: "manual", "watch", "recheck_all", "undo", ("drop", x, y) or ("retry", indices or None).
            gen: The atlas generation it is for (None: the open one); the worker skips it once another is open.
        """
        with self._admit:
            queued = self._admit_job(paths, mode, gen)
        if queued:
            self.events.publish("busy", True)

    def _admit_job(self, paths, mode, gen: int | None) -> bool:
        """Put a job in the queue (with _admit held: see _init_adding); False when closing."""
        if self._closing:
            self.events.log(f"closing: {len(paths) or 'a'} job(s) not started")
            return False
        if gen is None:  # the page request's atlas when it is one, else the open one: a request made just before a
            # switch is skipped by the worker, never run on the atlas opened after it (CodeRabbit)
            gen = self._lock.expected()
        self._jobs.put((list(paths), mode, self.generation if gen is None else gen))
        return True

    def _drop_queued_jobs(self) -> None:
        """Forget jobs that have not started."""
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                return
            self._jobs.task_done()

    @staticmethod
    def _drop_stale_snapshots(atlas_path: Path) -> None:
        """Remove undo snapshots left by an earlier session (undo only reaches this session's adds).

        Args:
            atlas_path: The atlas file whose <stem>_undo folder is cleaned.
        """
        d = core.atlas_files(atlas_path) / (atlas_path.stem + "_undo")
        for f in d.glob("before_*.json") if d.is_dir() else ():
            with contextlib.suppress(OSError):
                f.unlink()

    def detector_ready(self) -> None:
        """Check that the detector database is there.

        Raises:
            ValueError: When it is missing (nothing can be detected).
        """
        if not rc_paths.DATABASE.exists():
            raise ValueError(
                f"The detector database is missing: {rc_paths.DATABASE}. "
                "Reinstall, or set DATABASE in local_paths.json."
            )

    def add_screenshots(self, paths: list, mode: str = "manual", sync: bool = False, gen: int | None = None) -> None:
        """Add screenshots to the atlas through the worker.

        Args:
            paths: Screenshot files.
            mode: "manual" (by hand) or "watch" (auto-add).
            sync: Run the job now on this thread (tests).
            gen: The atlas generation they are for (auto-add: the one it was started for; None: the open one).

        Raises:
            ValueError: With no atlas open, or the detector database missing.
        """
        self._lock.refuse_stale()  # (made for another atlas: refused at once, see _queue_job)
        if not self.atlas or not self.path:
            raise ValueError("open or create an atlas first")
        self.detector_ready()
        paths = [Path(p) for p in paths]
        if sync:
            self.run_job(paths, mode)
        else:
            self._queue_job(paths, mode, gen)

    def place_by_hand(self, path, x: float, y: float) -> None:
        """Line up a screenshot put roughly in place by hand near (x, y) (a "drop" job).

        Args:
            path: The screenshot file.
            x: Atlas x where it was put.
            y: Atlas y where it was put.

        Raises:
            ValueError: With no atlas open, or the detector database missing.
        """
        self._lock.refuse_stale()  # (made for another atlas: refused at once, see _queue_job)
        if not self.atlas or not self.path:
            raise ValueError("open or create an atlas first")
        self.detector_ready()
        self._queue_job([Path(path)], ("drop", float(x), float(y)))

    def recheck_all(self) -> None:
        """Start a full re-check of the atlas in the background (minutes on a large atlas).

        Raises:
            ValueError: With no screenshots.
        """
        self._lock.refuse_stale()  # (made for another atlas: refused at once, see _queue_job)
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots to re-check")
        self._queue_job([], "recheck_all")

    @atlas_switch
    def recheck_atlas(self, p) -> None:
        """Re-check an atlas from its card in the Atlases tab: opened first when another one is open, and its Re-check
        queued in the same step (the switch lock held throughout: another tab's switch can't come between, and the job
        is tagged with the atlas opened here, not the one the page saw).

        Args:
            p: Its atlas .json file.

        Raises:
            ValueError: When it can't be opened (work running, unreadable) or has no screenshots.
        """
        p = Path(p)
        if self.path is None or p.resolve() != self.path.resolve():
            self.open_atlas(p)
        if not self.atlas or not self.atlas.frames:
            raise ValueError("no screenshots to re-check")
        self._queue_job([], "recheck_all", gen=self.generation)

    @atlas_edit
    def undo_last(self) -> list[str]:
        """Remove the screenshots added last (an "undo" job).

        Returns:
            Their names.

        Raises:
            ValueError: With nothing to undo, or work running.
        """
        if not self._undo:
            raise ValueError("nothing to undo")
        if self.working():
            raise ValueError("wait until the screenshots being added are done")
        names = self._undo[-1]["names"]
        self._queue_job([], "undo")
        return names

    @atlas_edit
    def retry_waiting(self, indices: list[int] | None = None) -> int:
        """Search again for waiting screenshots (all, or those at these places in the waiting list).

        Args:
            indices: Places in waiting_list(), or None for all.

        Returns:
            How many are retried.

        Raises:
            ValueError: With nothing waiting.
        """
        if not self._pending_watch:
            raise ValueError("nothing is waiting")
        # the screenshots themselves, picked now: a list position could point at another one by the time the job
        # runs (one placed or taken meanwhile: CodeRabbit)
        picked = (
            None
            if indices is None
            else [str(self._pending_watch[k].path) for k in indices if 0 <= k < len(self._pending_watch)]
        )
        self._queue_job([], ("retry", picked))
        n = len(picked) if picked is not None else len(self._pending_watch)
        self.events.set_status(f"retrying {n} waiting screenshot(s)")
        return n

    def take_waiting(self, index: int) -> str:
        """Take a waiting screenshot out of the queue (to place it by hand).

        Args:
            index: Its place in waiting_list().

        Returns:
            Its file path.

        Raises:
            ValueError: When there is no such waiting screenshot.
        """
        with self._lock:
            if not 0 <= index < len(self._pending_watch):
                raise ValueError("no such waiting screenshot")
            fr = self._pending_watch.pop(index)
            self._taken.add(fr.sha)  # (a job running meanwhile doesn't put it back: CodeRabbit)
        self.events.publish("lists", None)
        return str(fr.path)

    def waiting_list(self) -> list[dict]:
        """Return the waiting screenshots, with how often each was tried.

        Returns:
            [{"name", "path", "tries"}].
        """
        return [
            {"name": Path(fr.path).name, "path": str(fr.path), "tries": self._wait_tries.get(Path(fr.path).name, 0)}
            for fr in self._pending_watch
        ]

    def recent_outlines(self) -> list[dict]:
        """Return the outlines of the newest additions (they fade with age) and of the one picked in the list.

        Returns:
            [{"name", "corners" (4 atlas points), "age" (0 newest), "picked"}].
        """
        if not self.atlas or not self.recent:
            return []
        by_name = {f["name"]: f for f in self.atlas.frames}
        names = list(reversed(self.recent))[:RECENT_FADE]
        out = []
        for age, n in enumerate(names):
            if n in by_name:
                out.append(
                    {"name": n, "corners": outline(self.atlas, by_name[n]).tolist(), "age": age, "picked": False}
                )
        pick = self.recent_pick
        if pick and pick in by_name and pick not in names:
            out.append({"name": pick, "corners": outline(self.atlas, by_name[pick]).tolist(), "age": 0, "picked": True})
        return out

    def frame_centre(self, name: str) -> list[float] | None:
        """Return the centre of a screenshot on the atlas (and outline it as picked when it was added recently).

        Args:
            name: Screenshot name.

        Returns:
            [x, y], or None when the atlas has no such screenshot.
        """
        f = next((f for f in (self.atlas.frames if self.atlas else []) if f["name"] == name), None)
        if f is None:
            return None
        if name in self.recent:
            self.recent_pick = name
            self.events.publish("lists", None)
        return outline(self.atlas, f).mean(axis=0).tolist()

    # ------------------------------------------------------------------ pictures (ghost / preview)
    def _keep_picture(self, data: bytes) -> int:
        """Keep a picture for the page to fetch (the last PICTURES_KEPT).

        Args:
            data: PNG bytes.

        Returns:
            Its id.
        """
        pid = next(self._picture_ids)
        self._pictures[pid] = data
        for old in sorted(self._pictures)[:-PICTURES_KEPT]:
            self._pictures.pop(old, None)
        return pid

    def picture(self, pid: int) -> bytes | None:
        """Return a kept picture.

        Args:
            pid: Its id.

        Returns:
            PNG bytes, or None.
        """
        return self._pictures.get(pid)

    def ghost(self, path) -> dict:
        """Make the see-through picture of a screenshot to place by hand: flattened like the atlas, centred on 0.

        Args:
            path: The screenshot file.

        Returns:
            {"picture" (id), "box" [x0, y0, x1, y1] around its centre in atlas units, "name", "path"}.

        Raises:
            ValueError: With no atlas open, or when the file is not an image.
        """
        if not self.atlas or not self.path:
            raise ValueError("open or create an atlas first")
        p = Path(path)
        img = core.read_screenshot(str(p))
        if img is None:
            raise ValueError(f"not an image: {p.name}")
        h, w = img.shape[:2]
        R = core.rectifier(w, h, core.constants.HORIZON / h if core.constants.HORIZON else None)
        data, box = flat_picture(img, R)
        return {"picture": self._keep_picture(data), "box": box, "name": p.name, "path": str(p)}

    def _preview_of(self, frame, reg) -> dict | None:
        """Make the picture of a screenshot where it would be added (shown while a question about it is open).

        Args:
            frame: The screenshot (core.Frame).
            reg: Its proposed placement.

        Returns:
            {"picture", "box", "agree", "near"}, or None when it can't be read. "agree": the atlas map nodes its own
            map nodes land on ([x, y] each: the maps the question says agree); "near": the box round what it joins:
            those maps and the screenshot its terrain was compared with (else the PREVIEW_NEAR placed screenshots
            nearest to it), or None in an empty atlas. Shown alone, a weak match couldn't be judged: what it
            connected to was off screen or under the dialog (user).
        """
        img = core.read_screenshot(str(frame.path))
        if img is None:
            return None
        M = np.array(reg.M, float)
        data, box = flat_picture(img, core.screen_to_atlas(M, frame.R))
        agree: list[list[float]] = []
        near = None
        if self.atlas.frames:
            atlas_pts = self.atlas.points()
            src = np.asarray(frame.pts, float)[np.asarray(frame.usable, bool)] if len(frame.pts) else np.zeros((0, 2))
            if len(src) and len(atlas_pts):  # paired as the placement pairs them (core.register)
                pairs = mutual_pairs(apply_affine(M, src), atlas_pts, PREVIEW_AGREE_TOL)
                agree = [[round(float(v), 1) for v in atlas_pts[j]] for _i, j, _d in pairs]
            ref = [f for f in self.atlas.frames if f["name"] == reg.ref_frame]
            if ref:
                corners = [np.asarray(core.footprint(self.atlas, ref[0])[0], float)]
            else:
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                corners = [np.asarray(core.footprint(self.atlas, f)[0], float) for f in self.atlas.frames]
                corners.sort(key=lambda c: float(np.hypot(*(c.mean(axis=0) - (cx, cy)))))
                corners = corners[:PREVIEW_NEAR]
            pts = np.vstack([*corners, np.asarray(agree, float).reshape(-1, 2)])
            near = [float(v) for v in (*pts.min(axis=0), *pts.max(axis=0))]
        return {"picture": self._keep_picture(data), "box": box, "agree": agree, "near": near}

    def _ask(self, question: str, preview: dict | None = None) -> bool:
        """Ask the page a yes / no question and wait for the answer (worker thread).

        Args:
            question: The question.
            preview: {"picture", "box"} of where a screenshot would go, or None.

        Returns:
            The answer (No when no page is open).
        """
        # the session lock is let go while the question is open (the job holds it): the page's requests that need it
        # (new tiles, the ground just pasted) waited until the answer, minutes maybe. The job's atlas stays this
        # atlas: another can't be opened while it runs (working()).
        # (all of its levels: AtlasLock.let_go; nothing to let go when it isn't held)
        with self._lock.let_go():
            return self.events.ask(question, preview=preview)

    # ------------------------------------------------------------------ the worker
    def _tally(self) -> dict[str, int]:
        """Count what the atlas shows (for the log's before / after of a job).

        Returns:
            {"maps", "paths", "icons", "landmarks"} (removed ones left out).
        """
        V = self.V
        return {
            "maps": sum(1 for n in V["nodes"] if n.get("status") != "removed"),
            "paths": len(V["paths"]),
            "icons": len(V["icons"]),
            "landmarks": sum(1 for lm in V["landmarks"] if not str(lm.get("status", "")).startswith("removed")),
        }

    def _log_job(self, mode, paths: list, before: dict[str, int], took: float) -> None:
        """Log what a job did: how long it took and how the atlas changed (user: the log said little).

        Args:
            mode: The job kind.
            paths: Its screenshots.
            before: _tally() before it ran.
            took: Seconds.
        """
        after = self._tally()
        changes = [
            f"{k} {after[k]}" + (f" ({after[k] - before[k]:+d})" if after[k] != before[k] else "") for k in after
        ]
        name = mode[0] if isinstance(mode, tuple) else mode
        what = {"manual": "adding", "watch": "auto-add", "undo": "undo", "recheck_all": "Re-check",
                "keep_all": "keeping copies", "drop": "placing by hand",
                "retry": "retry"}.get(name, str(name))  # fmt: skip
        self.events.log(f"{what} took {took:.1f} s: " + ", ".join(changes))

    def _worker(self) -> None:
        """Run queued jobs one at a time, forever (auto-add jobs that arrived meanwhile run as one batch)."""
        while True:
            paths, mode, gen = self._jobs.get()
            jobs = 1
            if mode == "watch":
                paths = list(paths)
                with self._jobs.mutex:
                    q = self._jobs.queue
                    while q and q[0][1] == "watch" and q[0][2] == gen and len(paths) < WATCH_BATCH:
                        paths += q.popleft()[0]
                        jobs += 1
            with self._lock:  # decided together with the open atlas: a switch can't slip in between
                current = self.owns(gen) and not self._closing
                self._busy = True
                self.pin_ground()  # the ground as it was before these jobs (the page's backdrop)
            try:
                if not current:
                    self.events.log(f"skipped a job queued for another atlas ({mode})")
                else:
                    if paths:
                        name = mode[0] if isinstance(mode, tuple) else mode
                        what = {"manual": "adding", "watch": "auto-add", "drop": "placing by hand"}.get(name, name)
                        names = ", ".join(Path(p).name for p in paths[:3])
                        more = f" and {len(paths) - 3} more" if len(paths) > 3 else ""
                        self.events.log(f"{what}: {len(paths)} screenshot(s) ({names}{more})")
                    before, t0 = self._tally(), time.monotonic()
                    self.run_job(paths, mode)
                    self._log_job(mode, paths, before, time.monotonic() - t0)
            except Exception as e:
                LOG.exception(f"adding failed ({mode}): {paths}")
                self.events.log(f"adding failed: {e}")
                self._note_seams_trouble(f"adding failed: {e}")  # (a queued Fix seams asks first)
                if mode == "watch" and self.owns(gen):
                    self._watch_failed([str(p) for p in paths])
            finally:
                for _ in range(jobs):
                    self._jobs.task_done()
                self._busy = self._jobs.unfinished_tasks > 0
                self.events.set_progress(None)
                if not self._busy:
                    self._tile_before = None  # (the page's backdrop follows the current ground now)
                    self.scan_locks()
                    self.events.publish("busy", False)
                    try:  # (one queued while this ran: fix_seams). Never the worker's end: a failure here
                        # left the queued screenshots with no one to add them (CodeRabbit)
                        self._start_waiting_seams()
                    except Exception as e:
                        LOG.exception("starting the queued Fix seams failed")
                        self.events.log(f"Fix seams could not start: {e}")

    def _cache_dir(self) -> Path:
        """Return the detection cache folder of the open atlas (<stem>_frames next to it).

        Returns:
            The folder.
        """
        return self.path.with_name(self.path.stem + "_frames")

    def _counter(self, what: str):
        """Make a progress function for detecting many screenshots ("<what> 652 / 1261").

        Args:
            what: The first words.

        Returns:
            Function (done, total).
        """

        def progress(done: int, total: int) -> None:
            """Show how many screenshots are done."""
            self.events.set_progress(f"{what} {done} / {total}")
            if done % DETECT_LOG_EVERY == 0 or done == total:
                LOG.info(f"{what}: {done} / {total} screenshots")

        return progress

    def _detect(self, paths: list[Path], what: str) -> tuple[list, list[str]]:
        """Detect screenshots (in worker processes when several, then read from the cache).

        Args:
            paths: Screenshot files.
            what: Progress words ("detecting", "detecting again").

        Returns:
            (detected frames, paths that failed).
        """
        frames, failed = [], []
        if len(paths) > 1:
            self.events.set_progress(f"{what} {len(paths)} screenshots")
            for p, err in builder.detect_uncached(
                paths, self._cache_dir(), log=self.events.log, progress=self._counter(what)
            ).items():
                LOG.warning(f"{Path(p).name}: detection failed in a worker: {err}")
        for i, p in enumerate(paths, 1):
            self.events.set_progress(f"{what} {p.name} ({i}/{len(paths)})")
            try:
                fr = builder.extract_frame(p, self._cache_dir())
                frames.append(fr)
                self.events.log(f"{p.name}: {int(fr.usable.sum())} maps, {len(getattr(fr, 'icons', []))} icons")
            except Exception as e:
                LOG.exception(f"{p.name}: detection failed")
                self.events.log(f"{p.name}: detection failed: {e}")
                self._note_seams_trouble(f"{p.name} could not be read: {e}")
                failed.append(str(p))
        return frames, failed

    def run_job(self, paths: list[Path], mode) -> None:
        """Run one job: detect the screenshots, place them, update the map image, save, and tell the page.

        Args:
            paths: Screenshot files.
            mode: The kind of job (see _queue_job).
        """
        if mode == "undo":
            self._run_undo()
            return
        if mode == "recheck_all":
            self._run_recheck()
            return
        if mode == "keep_all":
            self._run_keep()
            return
        retry = isinstance(mode, tuple) and mode[0] == "retry"
        frames, failed = self._detect(paths, "detecting") if paths else ([], [])
        if failed and mode == "watch":
            self._watch_failed(failed)
        # their copies kept right away: one deleted while it is placed still has its picture (user: aggressive
        # checking on files deleted mid-way); made after the job, it had none
        self._copy_detected(frames)
        self.events.set_progress("placing")
        self._shown_early = set()  # (screenshots pasted while a question was open: _show_placed)
        self._rebuilt_early = False
        with self._lock:
            before = len(self.atlas.frames)
            snapshot = self._snapshot()
            if retry:
                picked = None if mode[1] is None else set(mode[1])
                aside = [f for f in self._pending_watch if picked is not None and str(f.path) not in picked]
                self._pending_watch = [f for f in self._pending_watch if picked is None or str(f.path) in picked]
                try:
                    added, _ = self._place_watched([])
                finally:  # (a failing retry lost them: CodeRabbit)
                    self._pending_watch += aside
                refused = [Path(f.path).name for f in self._pending_watch]
            elif isinstance(mode, tuple):
                added, refused = self._place_dropped(frames, mode[1], mode[2])
            elif mode == "manual":
                lines: list[str] = []
                added, refused = builder.place_frames(self.atlas, frames, log=lines.append)
                for ln in lines:
                    if ln.strip().startswith(("MERGED", "first", "NOT ADDED", "final")) or "==" in ln:
                        self.events.log(ln)
            else:
                added, refused = self._place_watched(frames)
            rec = self.opened  # (the job's atlas, for the copies kept after it: _keep_screenshots)
            if added:
                new = self.atlas.frames[-added:]
                self._remember_add([f["name"] for f in new], snapshot)
                shown = self.__dict__.pop("_shown_early", set())  # pasted while a question was open
                rest = [f for f in new if f.get("sha") not in shown]
                # built again when an early build ran (it lacks what came after, and would replace the map image
                # when done: the newer build supersedes it), else the rest pasted
                if before == 0 or self._rebuilt_early or (rest and not self.paste_terrain(rest)):
                    self.load_terrain(cities=False)  # first screenshots, or outside the map image: build it
                if mode != "manual":
                    self.events.set_progress("updating maps and paths around the new screenshot")
                    builder.recheck(self.atlas, [f["name"] for f in new], log=self.events.log)
                self.events.set_progress("saving")
                self.atlas.save(self.path)
            else:
                with contextlib.suppress(OSError):
                    snapshot.unlink()
        self._after_placed(mode, added, refused)
        if added:  # copies kept, the originals in the atlas's folder moved to used/ (safe to delete: user)
            self._keep_screenshots(rec, [f["name"] for f in new])
            self._sort_dump(rec)  # (a newer, more central screenshot can send an older one to dump/)

    def _run_recheck(self) -> None:
        """Detect again screenshots detected by an older detector, re-check the whole atlas, then ask which of the
        changes to take: the groups you leave unticked stay as they were (app.recheck_choices).

        The open atlas's record is taken once: the box's wait lets the session lock go, and the result is applied
        only while that atlas is still the open one (owns; another can't be opened while the job runs, but the job
        doesn't lean on that alone: AGENTS.md)."""
        rec = self.opened
        atlas, path = rec.atlas, rec.path
        stale = [
            Path(f["path"])
            for f in atlas.frames
            if Path(f["path"]).exists()
            and not builder.is_cached(Path(f["path"]), path.with_name(path.stem + "_frames"))
        ]
        t0 = time.monotonic()
        if stale:
            self.events.log(
                f"Re-check: {len(stale)} screenshot(s) were detected by an older detector: detecting them again"
            )
            self._detect(stale, "detecting again")
        t1 = time.monotonic()
        self.events.set_progress("re-checking the whole atlas")
        with self._lock:
            if not self.owns(rec):
                self._done("Re-check stopped: another atlas was opened")
                return
            # the candidate is made aside: the atlas keeps its result and its icon list until you apply (a save
            # meanwhile - a bookmark, an edit - or a failure listing the changes wrote it unapproved: CodeRabbit).
            # (The clean-up makes a new result and icon list and never changes the old ones: no copies needed.)
            old, old_icons = atlas.final, atlas.icons
            try:
                atlas.rebuild_icons(builder.cached_frames(path, atlas.frames))
                atlas_finalize.finalize(atlas, log=self.events.log)
                new, new_icons = atlas.final, atlas.icons
            finally:
                atlas.final, atlas.icons = old, old_icons
            self._note_timing(len(stale), t1 - t0, len(atlas.frames), time.monotonic() - t1)
            listed = None
            if old is not None:
                self.events.set_progress("listing what the re-check changed")
                listed = recheck_choices.changes(
                    old,
                    new,
                    self._biomes_of(atlas, old, kept=True),
                    self._biomes_of(atlas, new, kept=False),
                    icon_label,
                )
            if listed is None or not any(g["count"] for g in listed.values()):
                # (nothing to choose from: only its numbers can differ)
                atlas.final, atlas.icons = new, new_icons
                atlas.last_check = self._check_record()
                atlas.save(path)
                done = "whole atlas re-checked" + (": nothing changed" if listed is not None else "")
        if listed is None or not any(g["count"] for g in listed.values()):
            self.rebuild_model()
            self._slim_down(rec)  # (ticked in the Re-check prompt: the copies of dump screenshots removed)
            self._done(done)
            return
        picked = self._ask_recheck(listed)
        if picked is None:  # (the app is closing: nothing is changed)
            self._done("Re-check not applied: the app closed before you chose what to update")
            return
        self.events.set_progress("updating what you ticked")
        with self._lock:
            if not self.owns(rec):  # (the result is for the atlas the box was about)
                self._done("Re-check not applied: another atlas was opened")
                return
            cur = atlas.final  # (as it is now: the one you saw while choosing)
            merged = recheck_choices.merge(cur, new, set(picked))
            if "biomes" in picked:
                atlas.biome_kept = []  # (the biomes as the re-check works them out)
            else:
                atlas.biome_kept = recheck_choices.kept_biomes(
                    merged,
                    cur,
                    self._biomes_of(atlas, merged, kept=True),
                    self._biomes_of(atlas, cur, kept=True),
                    atlas.biome_kept,
                )
            atlas.final = merged
            if "icons" in picked:
                atlas.icons = new_icons  # (the icons as the re-check merged them: kept as before when unticked)
            atlas.last_check = self._check_record()
            atlas.save(path)
        self.rebuild_model()
        took = [recheck_choices.GROUP_NAMES[g].lower() for g in recheck_choices.GROUPS if g in picked]
        left = [
            recheck_choices.GROUP_NAMES[g].lower()
            for g in recheck_choices.GROUPS
            if g not in picked and listed[g]["count"]
        ]
        msg = "whole atlas re-checked: " + (f"updated {', '.join(took)}" if took else "nothing updated")
        if left:
            msg += f"; kept as before: {', '.join(left)}"
        self._slim_down(rec)  # (ticked in the Re-check prompt: the copies of dump screenshots removed)
        self._done(msg)

    @staticmethod
    def _check_record() -> dict:
        """When and on which version the whole atlas was re-checked (atlas.last_check: the Re-check prompt says)."""
        return {"time": round(time.time(), 1), "version": VERSION}

    def _note_timing(self, detected: int, detect_s: float, shots: int, clean_s: float) -> None:
        """Keep how long a Re-check's steps took per screenshot on this computer (the next prompt's estimate)."""
        t = dict(self.settings.get("recheck_timing") or {})
        if detected >= RECHECK_TIMING_MIN:
            t["detect_s"] = round(detect_s / detected, 2)
        if shots >= RECHECK_TIMING_MIN:
            t["clean_s"] = round(clean_s / shots, 3)
        if t:
            self.set_setting("recheck_timing", t)

    def recheck_info(self, p=None) -> dict:
        """What the Re-check prompt says about an atlas: when it was last re-checked, when and on which version its
        screenshots were detected (in groups), how many will be detected again and about how long it takes.

        Args:
            p: Its atlas .json file (None: the open one). Another atlas is read from its file, not opened.

        Returns:
            {"last_check": {"time", "version"} or None, "shots", "detect", "missing", "estimate_s", "groups":
            [{"version" (None: before 1.23), "fresh", "count", "newest", "oldest"}] (newest first)}.

        Raises:
            ValueError: When the file can't be read.
        """
        rec = self.opened  # (one record: never the session lock, a job holds it for minutes - self review)
        if p is None or (rec.path is not None and Path(p).resolve() == rec.path.resolve()):
            atlas, path = rec.atlas, rec.path
            if atlas is None:
                raise ValueError("no atlas open")
            frames = list(atlas.frames)  # (a copy of the list: placing screenshots appends to it meanwhile)
            last = atlas.last_check
        else:
            path = Path(p)
            try:
                atlas = core.Atlas.load(path)
            except Exception as e:
                raise ValueError(f"could not read {path}: {e}") from e
            frames, last = atlas.frames, atlas.last_check
        cache_dir = path.with_name(path.stem + "_frames")
        groups: dict[tuple, dict] = {}
        detect = missing = 0
        for f in frames:
            here = Path(f["path"]).exists()
            head = builder.cache_head(cache_dir, f["sha"]) if f.get("sha") else None
            if head is None or not head["fresh"]:
                if here:
                    detect += 1  # (a detection gone or from an older detector: detected again)
                else:
                    missing += 1  # (its screenshot is gone: its old detection is used as it is)
            if head is None:
                continue
            g = groups.setdefault(
                (head["version"], head["fresh"]),
                {"version": head["version"], "fresh": head["fresh"], "count": 0, "newest": 0.0, "oldest": 1e18},
            )
            g["count"] += 1
            g["newest"] = max(g["newest"], head["time"])
            g["oldest"] = min(g["oldest"], head["time"])
        t = self.settings.get("recheck_timing") or {}
        estimate = detect * float(t.get("detect_s", RECHECK_DETECT_S)) + len(frames) * float(
            t.get("clean_s", RECHECK_CLEAN_S)
        )
        return {
            "last_check": last,
            "shots": len(frames),
            "detect": detect,
            "missing": missing,
            "estimate_s": round(estimate),
            "groups": sorted(groups.values(), key=lambda g: -g["newest"]),
            # the slim down's tick (packaged with Re-check: user): the copies of screenshots in dump
            "slim": self.slim_info(atlas, rec if atlas is rec.atlas else None),
        }

    def _biomes_of(self, atlas, final: dict, kept: bool) -> dict:
        """Each map's biome in an atlas-wide result (held under the session lock).

        Args:
            atlas: The atlas (the record the job took).
            final: An atlas-wide result (atlas.final is set to it while they are worked out, then put back).
            kept: Apply the biomes a Re-check left as they were (cities.biomes).

        Returns:
            {map node index: biome}.
        """
        saved = atlas.final
        atlas.final = final
        try:
            found = atlas_cities.biomes(atlas, view_model(atlas), ground=self.ground(), kept=kept)
        finally:
            atlas.final = saved
        return recheck_choices.biome_labels(found["potential"])

    def _ask_recheck(self, listed: dict) -> list[str] | None:
        """Ask the page which of the re-check's changes to take, and remember your ticks (for every atlas).

        Args:
            listed: recheck_choices.changes.

        Returns:
            The groups ticked, or None when the app closes first.
        """
        ticks = self.ui_settings()["recheck_update"]
        groups = [
            {
                "id": g,
                "name": recheck_choices.GROUP_NAMES[g],
                "count": listed[g]["count"],
                "added": listed[g]["added"],
                "removed": listed[g]["removed"],
                "changed": listed[g]["changed"],
                "items": listed[g]["items"],
                "ticked": bool(ticks.get(g, True)) and listed[g]["count"] > 0,
            }
            for g in recheck_choices.GROUPS
        ]
        for g in groups:
            if g["count"]:
                self.events.log(f"Re-check: {g['name'].lower()}: {g['count']} change(s)")
        self.events.set_progress("Re-check: choose what to update")
        with self._lock.let_go():  # (as _ask: the page's requests go on while the box is open)
            picked = self.events.ask_choices(
                "Here are the map changes. Choose which to keep: a group left unticked stays as it was before, on "
                "the maps it was on.",
                {"groups": groups},
                labels={"title": "Re-check atlas has finished", "yes": "Apply"},
            )
        if picked is not None:
            changed = {g["id"]: g["id"] in picked for g in groups if g["count"]}
            self.set_setting("recheck_update", {**ticks, **changed})
        return picked

    def _done(self, msg: str) -> None:
        """Tell the page a job finished.

        Args:
            msg: Status / log text.
        """
        self.events.set_progress(None)
        self.events.set_status(msg)
        self.events.log(msg)
        self.events.publish("atlas", self.atlas_summary())
        self.events.publish("lists", None)

    def _after_placed(self, mode, added: int, refused: list[str]) -> None:
        """Update the model and tell the page after a job (the map image was updated by pasting).

        Args:
            mode: The job kind.
            added: Screenshots added.
            refused: Names not added.
        """
        if added:
            self.rebuild_model()
        if isinstance(mode, tuple):
            mode = "retry" if mode[0] == "retry" else "drop"
        if mode == "manual":
            msg = f"added {added} screenshot(s)"
            if refused:
                msg += f"; not placed (no overlap found): {', '.join(refused)}"
            if added:
                threading.Thread(target=self._export_quiet, args=(self.generation,), daemon=True).start()
        elif mode == "drop":
            msg = "screenshot added" if added else "screenshot not added"
        elif mode == "retry":
            msg = f"retry: {added} waiting screenshot(s) placed" + (
                f"; {len(refused)} still waiting" if refused else ""
            )
        else:
            msg = f"auto-add: {added} new screenshot(s) added" + (
                f"; {len(refused)} NOT added yet (see Auto-add: place by hand)" if refused else ""
            )
        self._done(msg)
        if mode in ("watch", "retry") and refused and not added:
            self.events.publish("show_tab", "auto")

    def _export_quiet(self, gen: int) -> None:
        """Write the map PNGs in the background (not when another atlas was opened meanwhile); failures are logged.

        Args:
            gen: The atlas generation they are for.
        """
        try:
            with self._lock:
                if not self.owns(gen):
                    return
                builder.export(self.atlas, self.path)
        except Exception as e:
            LOG.exception("PNG export failed")
            self.events.log(f"PNG export failed: {e}")

    # ------------------------------------------------------------------ undo / recently added
    def _undo_dir(self) -> Path:
        """Return the undo snapshot folder of the open atlas, made if missing.

        Returns:
            The folder.
        """
        d = core.atlas_files(self.path) / (self.path.stem + "_undo")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _snapshot(self) -> Path:
        """Save the atlas as it is before an add (under the lock).

        Returns:
            The snapshot file.
        """
        f = self._undo_dir() / f"before_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.atlas.frames)}.json"
        self.atlas.save(f)
        return f

    def _remember_add(self, names: list[str], snapshot: Path) -> None:
        """Record an add for undo (the last UNDO_KEEP) and in the recently added list (the last RECENT_KEEP).

        Args:
            names: Names of the screenshots added.
            snapshot: The atlas before the add.
        """
        self._undo.append({"file": snapshot, "names": names})
        while len(self._undo) > UNDO_KEEP:
            old = self._undo.pop(0)
            with contextlib.suppress(OSError):
                Path(old["file"]).unlink()
        self.recent = (self.recent + list(names))[-RECENT_KEEP:]
        self.recent_pick = None

    def _run_undo(self) -> None:
        """Put the atlas back to its snapshot from before the last add, all of it but your hand edits (bookmarks,
        city types, landmark and biome edits: Atlas.HAND_EDITS), which stay as they are now."""
        entry = self._undo[-1]
        self.events.set_progress("undoing the last add")
        with self._lock:
            rec = self.opened
            old = core.Atlas.load(entry["file"])  # (raises: the entry stays, Undo can be tried again: CodeRabbit)
            self._undo.pop()
            kept = {f["name"] for f in old.frames}
            self._unkeep([f for f in self.atlas.frames if f["name"] not in kept])  # (out of used/: not in the atlas)
            # each screenshot where it is now: the snapshot names its place from before the add, and the add's sort
            # (or a keep since) moved some into used/ or dump/; the old place kept them there for good (self review)
            now = {f["name"]: f["path"] for f in self.atlas.frames}
            for f in old.frames:
                if f["name"] in now and Path(now[f["name"]]).exists():
                    f["path"] = now[f["name"]]
            self._lock_rev = getattr(self, "_lock_rev", 0) + 1  # (a stronghold search running now is out of date)
            for attr in core.Atlas.SAVED:
                if attr not in core.Atlas.HAND_EDITS:
                    setattr(self.atlas, attr, getattr(old, attr))
            self.atlas.save(self.path)
        with contextlib.suppress(OSError):
            Path(entry["file"]).unlink()
        gone = set(entry["names"])
        self.recent = [n for n in self.recent if n not in gone]
        self.rebuild_model()
        self.load_terrain(cities=True)
        self._sort_dump(rec)  # (a screenshot the undone ones outshone shows its spots again: back to used/)
        self._done(f"undone: {', '.join(entry['names'])}")

    # ------------------------------------------------------------------ placing
    def _place_dropped(self, frames, x: float, y: float) -> tuple[int, list[str]]:
        """Line up screenshots put roughly in place by hand near (x, y); one that can't be lined up is added
        exactly there if the user says so.

        Args:
            frames: The detected screenshots.
            x: Atlas x.
            y: Atlas y.

        Returns:
            (number added, names not added).
        """
        added, refused = 0, []
        for fr in frames:
            name = Path(fr.path).name
            reg = self.atlas.place_near(fr, x, y)
            if reg.ok:
                d = np.hypot(*(reg.M[:, 2] - [x, y]))
                self.atlas.commit_frame(fr, reg)
                added += 1
                self.events.log(f"{name}: lined up {d:.0f} units from where you put it ({reg.reason})")
            elif "already" in reg.reason:
                self.events.log(f"{name}: already in the atlas")
            elif self._ask(
                f"{name} could not be lined up with the atlas near where you put it ({reg.reason}).\n\n"
                "Add it exactly where you put it?"
            ):
                reg.ok, reg.reason = True, "placed by hand"
                self.atlas.commit_frame(fr, reg)
                added += 1
                self.events.log(f"{name}: placed by hand where you put it")
            else:
                refused.append(name)
        return added, refused

    @staticmethod
    def _concerns(frame, reg) -> list[str]:
        """List reasons to ask before adding a watched screenshot: a weak match.

        Args:
            frame: The detected screenshot.
            reg: Its placement result.

        Returns:
            The reasons as text.
        """
        out = []
        few = reg.reason.startswith("terrain") or reg.inliers <= WEAK_INLIERS
        if few and reg.ncc < WEAK_NCC:
            maps = "no maps to compare" if reg.reason.startswith("terrain") else f"only {reg.inliers} maps agree"
            out.append(f"the match is weak ({maps}, terrain agreement {reg.ncc:.2f})")
        return out

    def _place_one(self, fr):
        """Place a screenshot anywhere in the atlas by its maps (not committed); newest screenshots first.

        Args:
            fr: The detected screenshot.

        Returns:
            The placement result.
        """
        hints = [f["name"] for f in self.atlas.frames[-6:]][::-1]
        return self.atlas.add_frame(fr, hints=hints, commit=False)

    def _show_placed(self, shas: list[str]) -> None:
        """Paste screenshots placed in the running job into the map image now (not at the job's end).

        Args:
            shas: The screenshots (their sha) committed in this job; those pasted already are skipped.
        """
        shown = self.__dict__.setdefault("_shown_early", set())
        new = [f for f in self.atlas.frames if f.get("sha") in set(shas) and f.get("sha") not in shown]
        if not new:
            return
        if not self.paste_terrain(new):
            # outside the map image (new ground past its edge): built again in the background, with them in it (the
            # paste alone left them black, which is where a bridge's ground usually is)
            self.load_terrain(cities=False)
            self._rebuilt_early = True  # (the job's end builds it again: this build doesn't know what comes after)
        shown.update(f["sha"] for f in new)

    def _place_watched(self, frames) -> tuple[int, list[str]]:
        """Place screenshots one at a time; earlier ones that did not fit are retried, and waiting ones joined to
        each other may fit as a group (islands). A weak match is asked about first.

        Args:
            frames: Newly detected screenshots (the waiting ones are tried too).

        Returns:
            (number added, names still waiting).
        """
        # the waiting list stays the list while the job runs (the page shows it, also while a question is open: it
        # read empty when the job took it out at its start, and a failure lost it); placed ones leave it one by one
        placed_now: list[str] = []  # (shas) committed in this job, not on the map yet
        self._taken: set[str] = set()  # taken out by hand meanwhile (take_waiting, while a question is open)
        added, todo = 0, self._pending_watch + frames
        progress = True
        try:
            while progress and todo:
                progress, left = False, []
                for fr in todo:
                    reg = self._place_one(fr)
                    name = Path(fr.path).name
                    if not reg.ok:
                        if "already in the atlas" not in reg.reason:
                            left.append(fr)
                            self._wait_tries[name] = self._wait_tries.get(name, 0) + 1
                            self.events.log(f"{name}: no place found yet ({reg.reason}); will retry")
                        continue
                    worry = self._concerns(fr, reg) if self.atlas.frames else []
                    if worry:
                        # the screenshots placed so far in this job onto the map first: the question shows what this
                        # one would join (user: it sat in black fog, the ground it joins wasn't drawn yet)
                        self._show_placed(placed_now)
                        q = (
                            f"{name} would be added, but " + "; and ".join(worry) + ".\n\n"
                            "Add it anyway? (No = leave it out; you can add it later with Add screenshots.)"
                        )
                        if not self._ask(q, preview=self._preview_of(fr, reg)):
                            self.events.log(f"{name}: left out by you")
                            continue
                    self.atlas.commit_frame(fr, reg)
                    placed_now.append(fr.sha)
                    self._pending_watch = [f for f in self._pending_watch if f.sha != fr.sha]
                    added += 1
                    progress = True
                    self.events.log(f"{name}: added ({reg.inliers} maps agree, terrain {reg.ncc:.2f})")
                todo = left
                if not progress and len(todo) >= islands.ISLAND_MIN:
                    joined = islands.merge_waiting(self.atlas, todo, log=self.events.log)
                    if joined:
                        added += len(joined)
                        progress = True
                        shas = {f.sha for f in joined}
                        todo = [f for f in todo if f.sha not in shas]
                        self._pending_watch = [f for f in self._pending_watch if f.sha not in shas]
        except BaseException:
            # a failure mid-job (a preview, a question, the island search) leaves the waiting ones waiting (taken out
            # at the start, a failure once lost a 9-screenshot island); the new ones go back to auto-add
            # (_watch_failed)
            placed = {f.get("sha") for f in self.atlas.frames}
            self._pending_watch = [f for f in self._pending_watch if f.sha not in placed]
            raise
        todo = [f for f in todo if f.sha not in self._taken]
        self._pending_watch = todo
        return added, [Path(f.path).name for f in todo]
