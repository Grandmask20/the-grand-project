"""The folder watcher (WatchMixin) tries a screenshot again when its detection failed (no screenshots needed)."""

from grand_project.app.constants import WATCH_RETRIES
from grand_project.app.events import Events
from grand_project.app.watch import WatchMixin


class Watcher(WatchMixin):
    """Just the watcher's bookkeeping: what it has seen, and what it logged."""

    def __init__(self):
        self.events = Events()
        self._init_watch()


def test_failed_screenshot_is_watched_again_then_left_out():
    w = Watcher()
    f = "C:/shots/a.png"
    for n in range(WATCH_RETRIES):
        w._watch_seen[f] = -1  # handed over to adding
        w._watch_failed([f])
        assert f not in w._watch_seen, f"try {n + 1}: the next polls should see it again"
    w._watch_seen[f] = -1
    w._watch_failed([f])
    assert w._watch_seen[f] == -1, "after the last try it stays handled"
    assert "left out" in w.events.log_lines[-1]
