"""The classical detector's pipeline (grand_project/detect/pipeline.py): its models are loaded once."""

from __future__ import annotations

import pytest

from grand_project.detect import pipeline


def test_a_missing_model_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model not in the DB yet raises and is not kept as None: once it is trained, the next call loads it."""
    loaded: dict = {}
    monkeypatch.setattr(pipeline, "_models", loaded)
    monkeypatch.setattr(pipeline, "load_model", lambda name: None)
    with pytest.raises(RuntimeError, match="no maps model"):
        pipeline.ensure_models()
    assert loaded == {}
    monkeypatch.setattr(pipeline, "load_model", lambda name: f"<{name}>")
    pipeline.ensure_models()
    assert loaded == {"maps": "<maps>", "badges": "<badges>", "towers": "<towers>"}
    monkeypatch.setattr(pipeline, "load_model", lambda name: pytest.fail("loaded twice"))
    pipeline.ensure_models()  # loaded once
