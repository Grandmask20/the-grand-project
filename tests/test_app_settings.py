"""The app's settings file (app.settings); every test has its own file (tests/conftest.py: app_settings)."""

from __future__ import annotations

from grand_project.app import settings


def test_settings_round_trip(app_settings):
    assert settings.load_settings() == {}  # none yet
    settings.save_settings({"atlases": [{"name": "a", "json": "/x/atlas.json"}], "layers": {"paths": True}})
    assert settings.load_settings() == {"atlases": [{"name": "a", "json": "/x/atlas.json"}], "layers": {"paths": True}}
    assert app_settings.exists()


def test_unreadable_settings_are_empty(app_settings):
    app_settings.write_text("{cut off", encoding="utf-8")
    assert settings.load_settings() == {}


def test_a_failed_save_is_only_logged(app_settings, monkeypatch, caplog):
    def broken(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(settings.atlas_io, "write_text_atomic", broken)
    settings.save_settings({"a": 1})  # no exception
    assert "settings could not be saved" in caplog.text
