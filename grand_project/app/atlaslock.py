"""app.atlaslock: the session lock, which refuses an edit the page made for an atlas no longer open.

The server checks a change's atlas (its generation) as the request comes in, but the change runs a moment later: an
atlas opened in between got edits meant for the one before (a landmark, a biome, a bookmark moved: GPT audit). So
while a page's change is handled, the lock knows which atlas it is for (`expect`), and every acquisition by that
request checks it: the check and the edit happen under the same lock, in one step. Atlas edits all go through the
lock (`atlas_edit` puts a method under it), so no route has to remember its own check. Background work (no
expectation set) is not affected: it checks `owns()` itself, with the record it took when it started.
"""

from __future__ import annotations

import contextlib
import functools
import threading
from collections.abc import Callable, Iterator

from .events import StaleAtlas


class AtlasLock:
    """A re-entrant lock that refuses (StaleAtlas) a page change meant for another atlas than the open one."""

    def __init__(self, generation: Callable[[], int]):
        """Args:
        generation: The open atlas's generation, read at each acquisition.
        """
        self._lock = threading.RLock()
        self._generation = generation
        self._request = threading.local()

    @contextlib.contextmanager
    def expect(self, gen: int) -> Iterator[None]:
        """While a page's change is handled (on its thread): it is for the atlas of generation `gen`."""
        before = getattr(self._request, "gen", None)
        self._request.gen = gen
        try:
            yield
        finally:
            self._request.gen = before

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """Take the lock; on a page change's thread, refuse it when its atlas is no longer the open one.

        Raises:
            StaleAtlas: The change was made for another atlas (the lock is not kept).
        """
        if not self._lock.acquire(blocking, timeout):
            return False
        gen = getattr(self._request, "gen", None)
        if gen is not None and gen != self._generation():
            self._lock.release()
            raise StaleAtlas()
        return True

    def release(self) -> None:
        """Let go of one level of the lock."""
        self._lock.release()

    @contextlib.contextmanager
    def let_go(self) -> Iterator[None]:
        """Let go of the lock entirely (every level this thread holds) for a while, then take the same levels back.

        One level only was let go before: a job holding it twice (an edit inside a job) kept it while waiting for an
        answer, and the page's requests waited with it (GPT audit).
        """
        n = 0
        while self._lock._is_owned():  # type: ignore[attr-defined]
            self._lock.release()
            n += 1
        try:
            yield
        finally:
            for _ in range(n):
                self._lock.acquire()

    def _is_owned(self) -> bool:
        """Whether this thread holds it (as RLock's own check: the tests ask it)."""
        return self._lock._is_owned()  # type: ignore[attr-defined]

    def __enter__(self) -> AtlasLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def atlas_edit(fn: Callable) -> Callable:
    """Mark a session method as an atlas edit: it runs under the session lock, so a page change meant for another
    atlas is refused before it touches anything (AtlasLock), and it can't run while a job saves the same atlas."""

    @functools.wraps(fn)
    def run(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return run
