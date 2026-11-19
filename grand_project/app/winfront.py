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

from .constants import FOLDER_FRONT_WAIT

_SW_RESTORE = 9
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


def explorer_windows(name: str) -> list[int]:
    """The visible Explorer windows showing a folder named `name` ("name" or "name - File Explorer").

    Args:
        name: The folder's name.

    Returns:
        Their window handles.
    """
    u = _user32()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(h, _l):
        if u.IsWindowVisible(h) and _text(u.GetClassNameW, h) == "CabinetWClass":
            t = _text(u.GetWindowTextW, h)
            if t == name or t.startswith(name + " - "):
                found.append(h)
        return True

    u.EnumWindows(each, 0)
    return found


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
    which lets it hand the front over.

    Args:
        h: The window.

    Returns:
        True when Windows took it.
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
        return bool(u.SetForegroundWindow(h))
    finally:
        if attached:
            u.AttachThreadInput(me, front_thread, False)


def open_folder_in_front(folder: Path) -> bool:
    """Open a folder in Explorer, on the monitor of the window in front, and bring it forward.

    Args:
        folder: The folder.

    Returns:
        True when its window was found and brought forward (it opens either way).
    """
    u = _user32()
    front = u.GetForegroundWindow()
    before = set(explorer_windows(folder.name))
    os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606 (a known atlas folder, no shell)
    end = time.monotonic() + FOLDER_FRONT_WAIT
    while time.monotonic() < end:
        time.sleep(0.1)
        now = explorer_windows(folder.name)
        win = next((w for w in now if w not in before), now[0] if now else None)  # a new window, else the open one
        if win:
            onto_monitor_of(win, front)
            return to_front(win)
    return False
