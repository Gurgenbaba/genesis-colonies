"""Production runtime tuning (gunicorn workers, client poll intervals)."""

from __future__ import annotations

import pytest


def test_gunicorn_workers_default_one_for_sqlite(monkeypatch):
    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")

    from game.config import get_gunicorn_workers

    assert get_gunicorn_workers() == 1


def test_gunicorn_workers_env_override(monkeypatch):
    monkeypatch.setenv("GUNICORN_WORKERS", "3")
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")

    from game.config import get_gunicorn_workers

    assert get_gunicorn_workers() == 3


def test_client_runtime_config_production_slower_poll(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("GC_POLL_ACTIVE_MS", raising=False)

    from game.config import get_client_runtime_config

    cfg = get_client_runtime_config()
    assert cfg["poll_active_ms"] == 5000
    assert cfg["poll_idle_ms"] == 8000
    assert cfg["poll_hidden_ms"] == 20000
    assert cfg["shipyard_poll_ms"] == 8000


def test_client_runtime_config_development_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("GC_POLL_ACTIVE_MS", raising=False)

    from game.config import get_client_runtime_config

    cfg = get_client_runtime_config()
    assert cfg["poll_active_ms"] == 3000
    assert cfg["poll_idle_ms"] == 5000


def test_client_runtime_config_env_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GC_POLL_IDLE_MS", "12000")

    from game.config import get_client_runtime_config

    assert get_client_runtime_config()["poll_idle_ms"] == 12000


def test_docker_entrypoint_defaults_to_one_worker():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "scripts" / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert 'WORKERS="${GUNICORN_WORKERS:-1}"' in text
    assert 'gunicorn -w "${WORKERS}"' in text


def test_base_template_injects_client_config():
    from pathlib import Path

    tpl = (Path(__file__).resolve().parent.parent / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    assert "gc-client-config" in tpl
    assert "GC_CLIENT_CONFIG" in tpl


def test_main_js_applies_client_runtime_config():
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "static" / "main.js").read_text(encoding="utf-8")
    assert "applyClientRuntimeConfig" in js
    assert "GC.shipyardPollMs" in js
