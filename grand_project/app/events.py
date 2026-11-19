"""app.events: what the app tells the browser as it happens (Server-Sent Events), and questions it asks it.

Background work (adding screenshots, auto-add, Fix seams, the re-check) runs on its own threads and processes;
everything it has to say goes through one Events object: log lines, progress, status, "the atlas changed", and
yes / no questions the worker waits on (a weak match while adding).
"""

from __future__ import annotations

import itertools
import json
import queue
import re
import threading
import time
from collections import deque

from grand_project import logs as atlas_log

from .constants import EVENT_HISTORY, LOG_KEEP

LOG = atlas_log.get("app")


class StaleAtlas(Exception):
    """A change made for an atlas no longer open: refused (the page drops it as stale, 409)."""


class Events:
    """Publishes events to every connected browser and keeps the last log lines for a page opened later."""

    def __init__(self):
        """Start with no listeners, no log and no open question."""
        self._lock = threading.Lock()
        self._listeners: list[queue.Queue] = []
        self._ids = itertools.count(1)
        # one log per atlas (user: one shared log mixed atlases up); "" is the app's own (no atlas open)
        self.scope = ""
        self._logs: dict[str, deque] = {"": deque(maxlen=LOG_KEEP)}
        self.history: deque = deque(maxlen=EVENT_HISTORY)  # recent events, for a page that reconnects
        self.progress: str | None = None
        # progress steps already written to the log: (atlas log, step with its numbers left out) -> its tenth; per step,
        # so two jobs reporting at once (adding and Fix seams) don't each write every line, and per atlas, so the same
        # step in another atlas's job still reaches that atlas's log (CodeRabbit)
        self._progress_logged: dict[tuple[str, str], int | None] = {}
        self.status = ""
        self._questions: dict[int, dict] = {}

    # ------------------------------------------------------------------ publishing
    def publish(self, kind: str, data=None) -> None:
        """Send an event to every listener.

        Args:
            kind: Event name ("log", "progress", "status", "model", "terrain", "question", ...).
            data: JSON-able payload.
        """
        ev = {"id": next(self._ids), "kind": kind, "data": data, "time": time.time()}
        with self._lock:
            self.history.append(ev)
            for q in list(self._listeners):
                try:
                    q.put_nowait(ev)
                except queue.Full:  # a stuck browser tab: dropped; its stream ends, the page reconnects
                    q.dropped = True  # type: ignore[attr-defined]
                    self._listeners.remove(q)

    @property
    def log_lines(self) -> deque:
        """The log of the open atlas (or the app's own with none open)."""
        return self._logs.setdefault(self.scope, deque(maxlen=LOG_KEEP))

    def set_scope(self, key: str) -> None:
        """Switch the Log tab to another atlas's log (key: its file path; "" for none open)."""
        self.scope = key

    def log(self, text: str, scope: str | None = None) -> None:
        """Write a line to the log file and an atlas's log in the browser's Log tab.

        Args:
            text: The line.
            scope: The atlas it belongs to (a background job's own, captured when it started), else the open one's:
                a job finishing after a switch logged into the other atlas's log (CodeRabbit).
        """
        LOG.info(text)
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        scope = self.scope if scope is None else scope
        self._logs.setdefault(scope, deque(maxlen=LOG_KEEP)).append(line)
        self.publish("log", {"scope": scope, "line": line})

    def set_progress(self, text: str | None, scope: str | None = None) -> None:
        """Show (or clear, with None) the progress box.

        Args:
            text: What is being done, or None when done.
            scope: The atlas log its line goes in (a background job's own, captured when it started), else the open
                one's.
        """
        self.progress = text
        self.publish("progress", text)
        self._log_progress(text, scope)

    def _log_progress(self, text: str | None, scope: str | None) -> None:
        """Write a progress line to the log when a new step starts, and every 10% of a counted one ("fixing seams
        120 / 500"): what runs is in the log, not only in the progress box (user: "it should list ongoing processes").

        Args:
            text: The progress text, or None when it ended (how it ended its caller logs: done, stopped, failed).
            scope: The atlas log to write in (see set_progress).
        """
        if text is None:
            with self._lock:
                self._progress_logged.clear()
            return
        task = re.sub(r"\S*\d\S*", "#", text)  # the step without its numbers (and file names, which have digits)
        m = re.search(r"(\d+)\s*/\s*(\d+)", text)
        tenth = min(10, 10 * int(m[1]) // max(1, int(m[2]))) if m else None
        with self._lock:  # (set from several threads: the worker, Fix seams, the map image build)
            # the atlas log looked up once, for the "already written" record and the line: looked up again by log(),
            # an atlas switch between wrote the line into the other atlas's log (CodeRabbit)
            scope = self.scope if scope is None else scope
            key = (scope, task)
            if key in self._progress_logged and self._progress_logged[key] == tenth:
                return
            if len(self._progress_logged) > 200:  # steps with names in them (one per screenshot)
                self._progress_logged.clear()
            self._progress_logged[key] = tenth
        self.log(text, scope)

    def set_status(self, text: str) -> None:
        """Set the status bar text.

        Args:
            text: The text.
        """
        self.status = text
        self.publish("status", text)

    # ------------------------------------------------------------------ listening
    def listen(self) -> queue.Queue:
        """Register a listener (one per open browser page).

        Returns:
            A queue the events arrive in; give it back to stop_listening when the page goes.
        """
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._listeners.append(q)
        return q

    def stop_listening(self, q: queue.Queue) -> None:
        """Unregister a listener.

        Args:
            q: The queue listen() gave.
        """
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    # ------------------------------------------------------------------ questions
    def ask(self, question: str, preview: dict | None = None, timeout: float | None = None) -> bool:
        """Ask the browser a yes / no question and wait for the answer (from a background thread).

        With no page open the answer is No (nothing is added that nobody saw).

        Args:
            question: The question text.
            preview: Optional {"picture" (id), "box" [x0, y0, x1, y1]} of where a screenshot would go.
            timeout: Seconds to wait at most (None: until answered).

        Returns:
            The answer.
        """
        with self._lock:
            if not self._listeners:
                LOG.info(f"no page open to ask: {question!r} -> no")
                return False
        qid = next(self._ids)
        box = {"id": qid, "question": question, "preview": preview, "event": threading.Event(), "answer": False}
        with self._lock:
            self._questions[qid] = box
        self.publish("question", {"id": qid, "question": question, "preview": preview})
        box["event"].wait(timeout)
        with self._lock:
            self._questions.pop(qid, None)
        self.publish("answered", {"id": qid})
        return bool(box["answer"])

    def answer(self, qid: int, yes: bool) -> bool:
        """Answer an open question.

        Args:
            qid: The question's id.
            yes: The answer.

        Returns:
            False when no such question is open.
        """
        with self._lock:
            box = self._questions.get(qid)
        if box is None:
            return False
        box["answer"] = bool(yes)
        box["event"].set()
        return True

    def open_questions(self) -> list[dict]:
        """Return the questions waiting for an answer (a page opened while one is waiting shows it).

        Returns:
            [{"id", "question", "preview"}].
        """
        with self._lock:
            return [
                {"id": b["id"], "question": b["question"], "preview": b["preview"]} for b in self._questions.values()
            ]


def sse(ev: dict) -> bytes:
    """Encode an event for a Server-Sent Events stream.

    Args:
        ev: {"id", "kind", "data"}.

    Returns:
        The bytes to write.
    """
    return f"id: {ev['id']}\nevent: {ev['kind']}\ndata: {json.dumps(ev['data'])}\n\n".encode()
