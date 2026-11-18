"""app.events: what the app tells the browser as it happens (Server-Sent Events), and questions it asks it.

Background work (adding screenshots, auto-add, Fix seams, the re-check) runs on its own threads and processes;
everything it has to say goes through one Events object: log lines, progress, status, "the atlas changed", and
yes / no questions the worker waits on (a weak match while adding).
"""

from __future__ import annotations

import itertools
import json
import queue
import threading
import time
from collections import deque

from grand_project import logs as atlas_log

from .constants import EVENT_HISTORY, LOG_KEEP

LOG = atlas_log.get("app")


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

    def log(self, text: str) -> None:
        """Write a line to the log file and the open atlas's log in the browser's Log tab.

        Args:
            text: The line.
        """
        LOG.info(text)
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        scope = self.scope
        self._logs.setdefault(scope, deque(maxlen=LOG_KEEP)).append(line)
        self.publish("log", {"scope": scope, "line": line})

    def set_progress(self, text: str | None) -> None:
        """Show (or clear, with None) the progress box.

        Args:
            text: What is being done, or None when done.
        """
        self.progress = text
        self.publish("progress", text)

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
