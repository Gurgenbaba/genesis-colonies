from __future__ import annotations

from game.pirates import settings as pirate_settings


def test_env_hard_off_overrides_runtime_soft_on(monkeypatch):
    monkeypatch.setenv("GC_PIRATE_AI_ENABLED", "0")
    monkeypatch.setattr(pirate_settings, "get_runtime_value", lambda *a, **k: "1")
    monkeypatch.setattr(pirate_settings, "is_production", lambda: True)

    assert pirate_settings.is_pirates_ai_enabled() is False


def test_env_hard_off_overrides_fresh_production_default(monkeypatch):
    monkeypatch.setenv("GC_PIRATE_AI_ENABLED", "off")
    monkeypatch.setattr(pirate_settings, "get_runtime_value", lambda *a, **k: None)
    monkeypatch.setattr(pirate_settings, "is_production", lambda: True)

    assert pirate_settings.is_pirates_ai_enabled() is False


def test_unset_env_preserves_runtime_soft_off(monkeypatch):
    monkeypatch.delenv("GC_PIRATE_AI_ENABLED", raising=False)
    monkeypatch.setattr(pirate_settings, "get_runtime_value", lambda *a, **k: "0")
    monkeypatch.setattr(pirate_settings, "is_production", lambda: True)

    assert pirate_settings.is_pirates_ai_enabled() is False


def test_unset_env_preserves_fresh_production_default(monkeypatch):
    monkeypatch.delenv("GC_PIRATE_AI_ENABLED", raising=False)
    monkeypatch.setattr(pirate_settings, "get_runtime_value", lambda *a, **k: None)
    monkeypatch.setattr(pirate_settings, "is_production", lambda: True)

    assert pirate_settings.is_pirates_ai_enabled() is True
