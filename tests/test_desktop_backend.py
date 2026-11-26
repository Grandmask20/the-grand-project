"""desktop/backend.py: the desktop app's frozen program runs the app's server, or a module asked for with -m (frozen,
sys.executable is that program: app/mapimage.py starts python -m grand_project.core.seams)."""

import importlib.util
import sys

from grand_project import paths


def _backend():
    spec = importlib.util.spec_from_file_location("desktop_backend", paths.ROOT / "desktop" / "backend.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_module_asked_for_with_m_runs_as_main_with_its_arguments(tmp_path, monkeypatch):
    (tmp_path / "gp_probe.py").write_text(
        "import sys\nif __name__ == '__main__':\n    open(sys.argv[1], 'w').write(' '.join(sys.argv[1:]))\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    out = tmp_path / "said.txt"
    assert _backend().main(["-I", "-m", "gp_probe", str(out), "x"]) == 0  # (-I: a Python flag, nothing to do frozen)
    assert out.read_text() == f"{out} x"


def test_anything_else_is_the_app_s_server(monkeypatch):
    got = []
    monkeypatch.setattr("grand_project.app.server.main", lambda argv: got.append(argv) or 7)
    assert _backend().main(["--no-browser"]) == 7
    assert got == [["--no-browser"]]


def test_the_self_check_loads_every_stored_detector_model(capsys):
    assert _backend().main(["--self-check"]) == 0
    said = capsys.readouterr().out.splitlines()
    assert said and all(": " in line and not line.endswith(": NoneType") for line in said)
