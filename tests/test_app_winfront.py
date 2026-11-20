"""app.winfront: an atlas folder opened in Explorer comes to the front, on the monitor in use (the Windows calls are
faked, so this runs on every system)."""

from pathlib import Path

import pytest

from grand_project.app import constants as K
from grand_project.app import winfront


@pytest.fixture
def faked(monkeypatch):
    """Explorer's windows as a list of {handle: title} looked at one after another (the last one stays)."""
    steps = []

    class User32:
        GetForegroundWindow = staticmethod(lambda: 7)  # the browser

    def run(looks, paths=None):
        looks = list(looks)
        paths = paths if paths is not None else {99: "C:/atlases/default"}

        def titles():
            return looks.pop(0) if len(looks) > 1 else looks[0]

        monkeypatch.setattr(winfront, "_user32", lambda: User32())
        monkeypatch.setattr(winfront, "explorer_titles", titles)
        monkeypatch.setattr(winfront, "explorer_paths", lambda: paths)
        monkeypatch.setattr(winfront.os, "startfile", lambda f: steps.append(("open", f.name)), raising=False)
        monkeypatch.setattr(winfront, "onto_monitor_of", lambda h, other: steps.append(("move", h, other)))
        monkeypatch.setattr(winfront, "to_front", lambda h: steps.append(("front", h)) or True)
        monkeypatch.setattr(K, "FOLDER_FRONT_POLL", 0.0)
        return winfront.open_folder_in_front(Path("C:/atlases/default")), steps

    return run


def test_the_folder_s_window_is_moved_to_the_monitor_in_use_then_brought_forward(faked):
    ok, steps = faked([{}, {}, {42: "default - File Explorer"}])  # it shows up after a moment
    assert ok and steps == [("open", "default"), ("move", 42, 7), ("front", 42)]


def test_a_window_already_showing_it_is_brought_without_opening_it_again(faked):
    # (Explorer made no new window: the whole wait went by, and a window of another folder blinked: user)
    ok, steps = faked([{99: "default", 5: "other"}])
    assert ok and steps == [("move", 99, 7), ("front", 99)]


def test_a_tab_opened_in_another_window_is_that_window(faked):
    ok, steps = faked([{5: "other"}, {5: "other"}, {5: "default - File Explorer"}])
    assert ok and steps[-2:] == [("move", 5, 7), ("front", 5)]


def test_no_window_found_gives_up_after_the_wait(faked, monkeypatch):
    monkeypatch.setattr(K, "FOLDER_FRONT_WAIT", 0.05)
    ok, steps = faked([{5: "other"}])
    assert not ok and steps == [("open", "default")]


def test_a_title_is_a_folder_s_by_its_whole_name():
    assert winfront.shows("default - File Explorer", "default") and winfront.shows("default", "default")
    assert not winfront.shows("default2", "default")


class _Windows:
    """A fake user32 for to_front: `front` is the window in front; SetForegroundWindow works only once `allowed`."""

    def __init__(self, allowed_after_restore: bool):
        self.front = 7
        self.calls = []
        self.restored = False
        self.allowed_after_restore = allowed_after_restore

    def GetForegroundWindow(self):  # noqa: N802 (Windows' names)
        return self.front

    def GetWindowThreadProcessId(self, h, _p):  # noqa: N802
        return 100

    def AttachThreadInput(self, *_a):  # noqa: N802
        return 1

    def IsIconic(self, h):  # noqa: N802
        return False

    def BringWindowToTop(self, h):  # noqa: N802
        self.calls.append("top")

    def ShowWindow(self, h, how):  # noqa: N802
        self.calls.append(("show", how))
        if how == winfront._SW_RESTORE:
            self.restored = True

    def SetForegroundWindow(self, h):  # noqa: N802
        self.calls.append("set")
        if self.restored and self.allowed_after_restore:
            self.front = h
        return self.front == h


def test_a_window_refused_the_front_is_minimized_and_restored(monkeypatch):
    # (an Explorer window already open, behind another: the taskbar blinked and it stayed behind: user)
    w = _Windows(allowed_after_restore=True)
    monkeypatch.setattr(winfront, "_user32", lambda: w)
    monkeypatch.setattr(
        winfront.ctypes,
        "windll",
        type("W", (), {"kernel32": type("K", (), {"GetCurrentThreadId": staticmethod(lambda: 1)})})(),
        raising=False,
    )
    assert winfront.to_front(42)
    assert ("show", winfront._SW_MINIMIZE) in w.calls and w.calls[-1] == "set"


def test_a_window_of_another_folder_with_that_name_isn_t_taken_for_it(faked):
    # (D:/backup/default open, C:/atlases/default asked for: the atlas folder never opened, CodeRabbit)
    ok, steps = faked(
        [{99: "default"}, {99: "default"}, {99: "default", 42: "default"}], paths={99: "D:/backup/default"}
    )
    assert ok and steps[0] == ("open", "default") and steps[-1] == ("front", 42)


def test_paths_that_can_t_be_read_open_the_folder(faked):
    ok, steps = faked([{99: "default"}, {99: "default"}, {99: "default", 42: "default"}], paths={})
    assert steps[0] == ("open", "default")


def test_the_same_folder_whatever_the_case_and_slashes():
    assert winfront.same_folder("C:/Atlases/Default", "c:\\atlases\\default\\")
    assert not winfront.same_folder("D:/backup/default", "C:/atlases/default")
