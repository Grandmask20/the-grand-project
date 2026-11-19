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

    def run(looks):
        looks = list(looks)

        def titles():
            return looks.pop(0) if len(looks) > 1 else looks[0]

        monkeypatch.setattr(winfront, "_user32", lambda: User32())
        monkeypatch.setattr(winfront, "explorer_titles", titles)
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
