"""app.winfront: an atlas folder opened in Explorer comes to the front, on the monitor in use (the Windows calls are
faked, so this runs on every system)."""

from pathlib import Path

from grand_project.app import constants as K
from grand_project.app import winfront


def test_the_folder_s_window_is_moved_to_the_monitor_in_use_then_brought_forward(monkeypatch):
    steps = []

    class User32:
        GetForegroundWindow = staticmethod(lambda: 7)  # the browser

    windows = iter([[], [], [42]])  # the folder's Explorer window shows up after a moment
    monkeypatch.setattr(winfront, "_user32", lambda: User32())
    monkeypatch.setattr(winfront, "explorer_windows", lambda name: next(windows, [42]))
    monkeypatch.setattr(winfront.os, "startfile", lambda f: steps.append(("open", f)), raising=False)
    monkeypatch.setattr(winfront, "onto_monitor_of", lambda h, other: steps.append(("move", h, other)))
    monkeypatch.setattr(winfront, "to_front", lambda h: steps.append(("front", h)) or True)
    assert winfront.open_folder_in_front(Path("C:/atlases/default"))
    assert steps == [("open", Path("C:/atlases/default")), ("move", 42, 7), ("front", 42)]


def test_an_already_open_window_is_the_one_brought_forward(monkeypatch):
    # (Explorer reuses a window already showing the folder: it stayed where it was, behind: user)
    class User32:
        GetForegroundWindow = staticmethod(lambda: 7)

    moved = []
    monkeypatch.setattr(K, "FOLDER_FRONT_WAIT", 0.2)  # (no new window comes: waited for, then the open one)
    monkeypatch.setattr(winfront, "_user32", lambda: User32())
    monkeypatch.setattr(winfront, "explorer_windows", lambda name: [99])
    monkeypatch.setattr(winfront.os, "startfile", lambda f: None, raising=False)
    monkeypatch.setattr(winfront, "onto_monitor_of", lambda h, other: moved.append(h))
    monkeypatch.setattr(winfront, "to_front", lambda h: True)
    assert winfront.open_folder_in_front(Path("C:/atlases/default"))
    assert moved == [99]


def test_a_window_already_open_isn_t_taken_while_the_new_one_comes(monkeypatch):
    # (it was taken at once and moved, and the new window opened where Explorer put it: user)
    class User32:
        GetForegroundWindow = staticmethod(lambda: 7)

    windows = iter([[99], [99], [99], [99, 42]])
    moved = []
    monkeypatch.setattr(winfront, "_user32", lambda: User32())
    monkeypatch.setattr(winfront, "explorer_windows", lambda name: next(windows, [99, 42]))
    monkeypatch.setattr(winfront.os, "startfile", lambda f: None, raising=False)
    monkeypatch.setattr(winfront, "onto_monitor_of", lambda h, other: moved.append(h))
    monkeypatch.setattr(winfront, "to_front", lambda h: True)
    assert winfront.open_folder_in_front(Path("C:/atlases/default"))
    assert moved == [42]
