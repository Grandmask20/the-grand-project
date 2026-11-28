"""PyTorch's own CUDA libraries first (grand_project/detect/rf_detr_cuda.py): a process that will run RF-DETR restarts
itself once with them first on LD_LIBRARY_PATH, as the dynamic linker reads it only at the start."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from grand_project.detect import constants as K
from grand_project.detect import rf_detr_cuda


@pytest.fixture(params=["cu13", "cuda_runtime"])
def packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> list[str]:
    """A site-packages with PyTorch's cuDNN and CUDA runtime folders (either wheel layout), on Linux, not restarted
    yet."""
    folders = [tmp_path / "nvidia" / name / "lib" for name in ("cudnn", request.param)]
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


def test_a_main_given_its_own_arguments_restarts_with_them(packages: list[str], monkeypatch) -> None:
    """``main(argv)`` called with arguments of its own: the restart keeps the interpreter, its options and the module,
    and runs it with those arguments, not the process's own."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/cuda/lib64")
    monkeypatch.setattr(sys, "orig_argv", ["python", "-u", "-m", "grand_project", "old.json"])
    monkeypatch.setattr(sys, "argv", ["/x/grand_project/__main__.py", "old.json"])
    calls = []
    monkeypatch.setattr(rf_detr_cuda.os, "execve", lambda exe, argv, env: calls.append(argv))
    rf_detr_cuda.prefer_pip_cuda_libraries(["new.json", "--port", "0"])
    rf_detr_cuda.prefer_pip_cuda_libraries()
    assert calls == [
        [sys.executable, "-u", "-m", "grand_project", "new.json", "--port", "0"],
        [sys.executable, "-u", "-m", "grand_project", "old.json"],
    ]


def test_the_environments_own_libraries_come_before_a_system_wheels(tmp_path: Path, monkeypatch) -> None:
    """In the interpreter's search order: a system folder sorting first ("/usr/...") never comes before the
    environment's site-packages listed before it on sys.path (CodeRabbit)."""
    env, system = tmp_path / "z-env", tmp_path / "a-system"
    for root in (env, system):
        (root / "nvidia" / "cudnn" / "lib").mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [str(env), str(system)])
    assert rf_detr_cuda._library_dirs() == [
        str(env / "nvidia" / "cudnn" / "lib"),
        str(system / "nvidia" / "cudnn" / "lib"),
    ]
