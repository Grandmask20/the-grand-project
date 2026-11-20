"""app.update_apply: puts a downloaded release in place, then starts the app again (the in-app update's last step).

The app can't replace its own files while it runs, so after the download it writes a plan, starts this script as a
process of its own (copied next to the plan and run with -I, so nothing of the program folder is imported while its
files change) and quits. This then:

1. waits for the app to have closed (its process id);
2. backs up every file it replaces or removes, then copies the new release's files in and removes the ones the
   release dropped; on any failure everything backed up is put back;
3. installs the Python packages again when requirements.txt changed (a failure there puts the old files back too);
4. writes what happened (result.json, which the app logs when it starts) and starts the app.

Standard library only (it runs from a copy, beside no package).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXIT_WAIT = 90.0  # s: the app saves its atlas as it closes; after this the update goes ahead regardless
PIP_WAIT = 900.0  # s: at most this long for pip to install the packages
_SYNCHRONIZE = 0x00100000


def wait_for_exit(pid: int, timeout: float = EXIT_WAIT) -> bool:
    """Wait for a process to end.

    Args:
        pid: Its id.
        timeout: Seconds to wait at most.

    Returns:
        True when it ended (or wasn't running).
    """
    if os.name == "nt":
        import ctypes

        k = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k.OpenProcess(_SYNCHRONIZE, False, pid)
        if not h:
            return True  # (gone already)
        try:
            return k.WaitForSingleObject(h, int(timeout * 1000)) == 0
        finally:
            k.CloseHandle(h)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # (running, under another user)
        time.sleep(0.2)
    return False


def apply(plan: dict) -> dict:
    """Put the new release's files in place (see the module docstring, steps 2-3).

    Args:
        plan: {"root", "new", "backup", "copy": [rel], "delete": [rel], "pip": bool, "python", "from", "to"}.

    Returns:
        {"ok", "from", "to", "copied", "deleted", "error"?}.
    """
    root, new, backup = Path(plan["root"]), Path(plan["new"]), Path(plan["backup"])
    done: list[tuple[str, bool]] = []  # (rel, it existed before: backed up)
    out = {"ok": False, "from": plan.get("from"), "to": plan.get("to"), "copied": 0, "deleted": 0}
    try:
        for rel in plan["copy"] + plan["delete"]:
            p = root / rel
            try:
                existed = p.is_file()
                if existed:
                    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, backup / rel)
                done.append((rel, existed))
                if rel in plan["copy"]:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(new / rel, p)
                    out["copied"] += 1
                elif existed:
                    p.unlink()
                    out["deleted"] += 1
            except OSError as e:
                raise RuntimeError(f"{rel}: {e}") from e  # (which file, in the log)
        if plan.get("pip"):
            r = subprocess.run(
                [plan["python"], "-m", "pip", "install", "-r", str(root / "requirements.txt")],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=PIP_WAIT,
            )
            (backup.parent / "pip.log").write_text(r.stdout + r.stderr, encoding="utf-8", errors="replace")
            if r.returncode:
                raise RuntimeError("installing the Python packages failed (see pip.log in user_data/update)")
        out["ok"] = True
    except Exception as e:  # noqa: BLE001 (anything: the old files go back)
        out["error"] = str(e)
        for rel, existed in reversed(done):
            p = root / rel
            try:
                if existed:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup / rel, p)
                elif p.exists():
                    p.unlink()
            except OSError as e2:
                out["error"] += f"; {rel} couldn't be put back: {e2}"
    return out


def restart(plan: dict) -> None:
    """Start the app again, on its own (this process ends right after)."""
    kw: dict = {
        "cwd": plan["root"],
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(plan["restart"], **kw)  # noqa: S603 (the app's own interpreter and module)


def main(argv: list[str]) -> int:
    """Run an update plan: python -I update_apply.py plan.json."""
    plan_file = Path(argv[1])
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if not wait_for_exit(int(plan["pid"])):
        result = {"ok": False, "from": plan.get("from"), "to": plan.get("to"), "error": "the app didn't close"}
    else:
        result = apply(plan)
    Path(plan["result"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
    restart(plan)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
