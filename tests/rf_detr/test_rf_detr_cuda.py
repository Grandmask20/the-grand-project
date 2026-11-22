"""PyTorch's own CUDA libraries first (grand_project/detect/rf_detr_cuda.py): a process that will run RF-DETR restarts
itself once with them first on LD_LIBRARY_PATH, as the dynamic linker reads it only at the start."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from grand_project.detect import constants as K
from grand_project.detect import rf_detr_cuda


@pytest.fixture
def packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A site-packages with PyTorch's cuDNN and CUDA runtime folders, on Linux, not restarted yet."""
    folders = [tmp_path / "nvidia" / name / "lib" for name in ("cudnn", "cu13")]
    for folder in folders:
        folder.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv(K.RF_DETR_CUDA_REEXEC_ENV, raising=False)
    return [str(folder) for folder in folders]


def test_a_system_cuda_first_restarts_the_process_once(packages: list[str], monkeypatch) -> None:
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/cuda/lib64")
    calls = []
    monkeypatch.setattr(rf_detr_cuda.os, "execve", lambda exe, argv, env: calls.append(env))
    rf_detr_cuda.prefer_pip_cuda_libraries()
    (env,) = calls
    assert env["LD_LIBRARY_PATH"] == ":".join([*packages, "/usr/local/cuda/lib64"])  # whole: C:\ folders on Windows
    assert env[K.RF_DETR_CUDA_REEXEC_ENV] == "1"


@pytest.mark.parametrize("case", ["first already", "restarted", "not linux", "no pytorch cuda"])
def test_nothing_happens_when_it_is_not_needed(packages: list[str], monkeypatch, tmp_path: Path, case: str) -> None:
    monkeypatch.setenv(
        "LD_LIBRARY_PATH", ":".join([*packages, "/usr/local/cuda/lib64"]) if case == "first already" else "/x"
    )
    if case == "restarted":
        monkeypatch.setenv(K.RF_DETR_CUDA_REEXEC_ENV, "1")
    if case == "not linux":
        monkeypatch.setattr(sys, "platform", "win32")
    if case == "no pytorch cuda":
        monkeypatch.setattr(sys, "path", [str(tmp_path / "elsewhere")])
    monkeypatch.setattr(rf_detr_cuda.os, "execve", lambda *args: pytest.fail("restarted"))
    rf_detr_cuda.prefer_pip_cuda_libraries()
