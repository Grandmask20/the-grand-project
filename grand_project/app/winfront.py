"""app.winfront: open a folder in Windows Explorer, in front, on the monitor you are using (Windows only).

The app runs in the background, and Windows lets only the program in use bring a window to the front: a folder
opened from it, or one Explorer already had open, stayed behind the browser, and could be on another monitor (user).
So after opening it, its Explorer window is found by its title, moved onto the monitor of the window that was in
front (the browser the page is in), and brought forward with the input of the front window's thread attached, which
Windows allows.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as wt
from pathlib import Path

from . import constants as K

_SW_RESTORE = 9
_SW_MINIMIZE = 6
_MONITOR_NEAREST = 2
_SWP_NOZORDER_NOACTIVATE = 0x0004 | 0x0010


class _Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", wt.DWORD)]


def _user32():
    u = ctypes.windll.user32  # type: ignore[attr-defined]
    u.GetForegroundWindow.restype = wt.HWND
    u.MonitorFromWindow.restype = wt.HMONITOR
    return u


def _text(get, h) -> str:
    buf = ctypes.create_unicode_buffer(512)
    get(h, buf, 512)
    return buf.value


def explorer_titles() -> dict[int, str]:
    """The visible Explorer windows and their titles (the folder shown: "name" or "name - File Explorer").

    Returns:
        {window handle: title}.
    """
    u = _user32()
    found: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _l):
        if u.IsWindowVisible(h) and _text(u.GetClassNameW, h) == "CabinetWClass":
            found[h] = _text(u.GetWindowTextW, h)
        return True

    u.EnumWindows(each, 0)
    return found


def shows(title: str, name: str) -> bool:
    """Whether an Explorer window's title is that of a folder named `name`."""
    return title == name or title.startswith(name + " - ")


def onto_monitor_of(h: int, other: int) -> bool:
    """Move a window onto another window's monitor, centred in its work area, its size kept (or cut to fit).

    Args:
        h: The window to move.
        other: The window whose monitor it goes to.

    Returns:
        True when it was moved (False: already there).
    """
    u = _user32()
    if not other or u.MonitorFromWindow(h, _MONITOR_NEAREST) == u.MonitorFromWindow(other, _MONITOR_NEAREST):
        return False
    if u.IsIconic(h) or u.IsZoomed(h):
        u.ShowWindow(h, _SW_RESTORE)  # (a maximised window doesn't move)
    r = _Rect()
    u.GetWindowRect(h, ctypes.byref(r))
    mi = _MonitorInfo()
    mi.cbSize = ctypes.sizeof(_MonitorInfo)
    u.GetMonitorInfoW(u.MonitorFromWindow(other, _MONITOR_NEAREST), ctypes.byref(mi))
    a = mi.rcWork
    w, ht = min(r.right - r.left, a.right - a.left), min(r.bottom - r.top, a.bottom - a.top)
    x, y = a.left + (a.right - a.left - w) // 2, a.top + (a.bottom - a.top - ht) // 2
    return bool(u.SetWindowPos(h, 0, x, y, w, ht, _SWP_NOZORDER_NOACTIVATE))


def to_front(h: int) -> bool:
    """Bring a window to the front: the calling thread's input is attached to the front window's thread meanwhile,
    which lets it hand the front over. When Windows still refuses (it blinks the window on the taskbar instead: an
    Explorer window already open, behind another, user), the window is minimized and restored: Windows brings a
    restored window forward (user: a minimized one did come up).

    Args:
        h: The window.

    Returns:
        True when it is in front.
    """
    u = _user32()
    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    front_thread = u.GetWindowThreadProcessId(u.GetForegroundWindow(), None)
    me = k.GetCurrentThreadId()
    attached = bool(front_thread) and front_thread != me and bool(u.AttachThreadInput(me, front_thread, True))
    try:
        if u.IsIconic(h):
            u.ShowWindow(h, _SW_RESTORE)
        u.BringWindowToTop(h)
        u.SetForegroundWindow(h)
    finally:
        if attached:
            u.AttachThreadInput(me, front_thread, False)
    if u.GetForegroundWindow() != h:
        u.ShowWindow(h, _SW_MINIMIZE)
        u.ShowWindow(h, _SW_RESTORE)
        u.SetForegroundWindow(h)
    return u.GetForegroundWindow() == h


def open_folder_in_front(folder: Path) -> bool:
    """Bring a folder's Explorer window forward, on the monitor of the window in front: the one already showing it,
    else the one it opens in.

    A window already showing it is brought as it is, without opening it again: Explorer then made no new window (it
    reused its own, or opened a tab in another), so waiting for one took the whole wait, and a window of another
    folder blinked (user). Opened, its window is the one whose title turns to the folder's: a new window, or one that
    showed something else (a tab opened in it).

    Args:
        folder: The folder.

    Returns:
        True when its window was found and brought forward (it opens either way).
    """
    u = _user32()
    front = u.GetForegroundWindow()
    before = explorer_titles()
    win = next((h for h, t in before.items() if shows(t, folder.name)), None)
    if win is None:
        os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606 (a known atlas folder, no shell)
        end = time.monotonic() + K.FOLDER_FRONT_WAIT
        while win is None and time.monotonic() < end:
            time.sleep(K.FOLDER_FRONT_POLL)
            win = next((h for h, t in explorer_titles().items() if shows(t, folder.name) and before.get(h) != t), None)
    if win is None:
        return False
    onto_monitor_of(win, front)
    return to_front(win)
