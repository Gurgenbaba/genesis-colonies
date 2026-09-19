from __future__ import annotations

from game.config import _validate_network_runtime_config


def _set_network_base(monkeypatch, *, universe: str = "dev") -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_UNIVERSE_KEY", universe)
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://www.genesis-colonies.de")
    monkeypatch.setenv(
        "GC_NETWORK_UNI1_URL",
        "https://genesis-colonies-u2-production.up.railway.app",
    )
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "n" * 48)
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")


def test_network_production_config_accepts_ready_authority(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    assert _validate_network_runtime_config() == []


def test_network_production_config_requires_explicit_universe(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.delenv("GC_UNIVERSE_KEY")
    errors = _validate_network_runtime_config()
    assert any("GC_UNIVERSE_KEY" in error for error in errors)


def test_network_production_config_rejects_short_handoff_secret(monkeypatch):
    _set_network_base(monkeypatch, universe="dev")
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "too-short")
    errors = _validate_network_runtime_config()
    assert any("GC_NETWORK_AUTH_SECRET" in error for error in errors)


def test_open_non_authority_requires_maintenance_path(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "0")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    errors = _validate_network_runtime_config()
    assert any("maintenance" in error.lower() for error in errors)


def test_open_non_authority_accepts_maintenance_sidecar(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    assert _validate_network_runtime_config() == []


def test_uni1_requires_https_public_url(monkeypatch):
    _set_network_base(monkeypatch, universe="uni1")
    monkeypatch.setenv("GC_NETWORK_UNI1_URL", "http://uni1.invalid")
    monkeypatch.setenv("GC_MAINTENANCE_WORKER", "1")
    errors = _validate_network_runtime_config()
    assert any("GC_NETWORK_UNI1_URL" in error for error in errors)
