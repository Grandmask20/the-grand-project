"""The folder watcher tries a screenshot again when its detection failed (no window, no screenshots needed)."""

from grand_project.viewer.autoadd import AutoAddMixin
from grand_project.viewer.constants import WATCH_RETRIES


class Watcher(AutoAddMixin):
    """Just the watcher's bookkeeping: what it has seen, and what it logged."""

    def __init__(self):
        self._watch_seen = {}
        self.logged = []

    def log(self, text):
        self.logged.append(text)


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
    assert "left out" in w.logged[-1]
