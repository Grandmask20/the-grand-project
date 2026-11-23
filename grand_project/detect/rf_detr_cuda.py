"""The CUDA libraries an RF-DETR process loads (Linux): PyTorch's own, never a system copy first.

PyTorch's Linux wheels ship cuDNN and the CUDA runtime in ``site-packages/nvidia``. An inherited
``LD_LIBRARY_PATH`` can put a different system cuDNN (``/usr/local/cuda/lib64``) first; the libraries share their
sonames, so the dynamic linker silently combines parts of both, and cuDNN fails at the first convolution
(``CUDNN_STATUS_SUBLIBRARY_LOADING_FAILED``; preloading the right libraries is not enough, cuDNN then reports a
version mismatch). The dynamic linker reads ``LD_LIBRARY_PATH`` only when a process starts, so a process that will
run RF-DETR on CUDA restarts itself once, at its start, with PyTorch's libraries first: the training, the detect
commands, the app (its detection workers inherit the environment), the annotator's model pre-labels.

Standard library only: the player release ships it, and it does nothing where PyTorch's CUDA libraries are absent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import constants as K


def _library_dirs() -> list[str]:
    """PyTorch's CUDA library folders (cuDNN, the CUDA 13 runtime) found on ``sys.path``."""
    package_dirs = {Path(entry) / "nvidia" for entry in sys.path if entry}
    found = [package_dir / name / "lib" for name in ("cudnn", "cu13") for package_dir in sorted(package_dirs)]
    return [str(folder) for folder in found if folder.is_dir()]


def _restart_command(argv: list[str] | None) -> list[str]:
    """The command line the process restarts with: its own, or with ``argv`` in place of its arguments (the
    interpreter, its options and the script or ``-m`` module stay)."""
    own = list(sys.orig_argv[1:])
    if argv is None:
        return [sys.executable, *own]
    head = own[: len(own) - (len(sys.argv) - 1)]  # sys.argv[1:] is the tail of sys.orig_argv
    return [sys.executable, *head, *argv]


def prefer_pip_cuda_libraries(argv: list[str] | None = None) -> None:
    """Restart this process (once) with PyTorch's CUDA libraries first on ``LD_LIBRARY_PATH``, when they are not.

    Call it first thing in a process that will run RF-DETR, before anything imports torch. Nothing happens off Linux,
    without PyTorch's CUDA libraries, when they come first already, or after the restart
    (``RF_DETR_CUDA_REEXEC_ENV``).

    Args:
        argv: The arguments the restarted process runs with, for a ``main(argv)`` given its own: in place of this
            process's arguments, after the same interpreter, options and script or module. None: its own.
    """
    if not sys.platform.startswith("linux") or os.environ.get(K.RF_DETR_CUDA_REEXEC_ENV):
        return
    entries = _library_dirs()
    if not entries:
        return
    sep = K.RF_DETR_CUDA_PATH_SEPARATOR
    first = sep.join(entries)
    existing = os.environ.get("LD_LIBRARY_PATH", "")
    # compared as text, never split: a folder name may hold the separator (a drive letter, where tests fake Linux)
    if existing == first or existing.startswith(first + sep):
        return
    env = {**os.environ, "LD_LIBRARY_PATH": f"{first}{sep}{existing}" if existing else first}
    env[K.RF_DETR_CUDA_REEXEC_ENV] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(sys.executable, _restart_command(argv), env)


__all__ = ["prefer_pip_cuda_libraries"]
