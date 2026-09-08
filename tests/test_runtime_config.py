"""Production runtime tuning (gunicorn workers, client poll intervals)."""

from __future__ import annotations

import pytest


def test_postgres_network_path_classification():
    from game.config import classify_postgres_network_path

    assert (
        classify_postgres_network_path(
            "postgresql://user:secret@postgres.railway.internal:5432/railway"
        )
        == "railway_private"
    )
    assert (
        classify_postgres_network_path(
            "postgresql://user:secret@viaduct.proxy.rlwy.net:12345/railway"
        )
        == "railway_public_proxy"
    )
    assert classify_postgres_network_path("postgresql://u:p@127.0.0.1:5432/db") == "local"
    assert classify_postgres_network_path("postgresql://u:p@db.example.com:5432/db") == "external"
    assert classify_postgres_network_path("") == "unset"


def test_health_marks_public_postgres_proxy_without_exposing_dsn(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:super-secret@viaduct.proxy.rlwy.net:12345/railway",
    )

    import game.health as health

    class _Conn:
        def execute(self, _sql):
            return None

        def close(self):
            return None

    monkeypatch.setattr(health, "db", lambda: _Conn())
    result = health.check_database()

    assert result["ok"] is True
    assert result["backend"] == "postgres"
    assert result["network_path"] == "railway_public_proxy"
    assert result["performance_warning"] == "postgres_public_proxy"
    serialized = str(result)
    assert "super-secret" not in serialized
    assert "viaduct.proxy.rlwy.net" not in serialized


def test_gunicorn_workers_default_one_for_sqlite(monkeypatch):
    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")

    from game.config import get_gunicorn_workers

    assert get_gunicorn_workers() == 1


def test_gunicorn_workers_default_two_for_postgres(monkeypatch):
    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")

    from game.config import get_gunicorn_workers

    assert get_gunicorn_workers() == 2


def test_gunicorn_workers_production_postgres_floors_legacy_one(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("GUNICORN_WORKERS", "1")

    from game.config import get_gunicorn_workers

    assert get_gunicorn_workers() == 2


def test_gunicorn_workers_development_postgres_can_explicitly_use_one(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("GUNICORN_WORKERS", "1")

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
    assert cfg["poll_idle_ms"] == 12000
    assert cfg["poll_hidden_ms"] == 30000
    assert "shipyard_poll_ms" not in cfg


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


def test_docker_entrypoint_defaults_gthread_availability():
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "scripts" / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "from game.config import init_config, get_gunicorn_workers" in text
    worker_resolver = text.split('WORKERS="$(python -c ', 1)[1].split(')"', 1)[0]
    assert "init_config()" in worker_resolver
    assert worker_resolver.index("init_config()") < worker_resolver.index("get_gunicorn_workers()")
    assert "print(get_gunicorn_workers())" in text
    assert 'WORKERS="${GUNICORN_WORKERS:-1}"' not in text
    assert 'WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gthread}"' in text
    assert 'THREADS="${GUNICORN_THREADS:-4}"' in text
    assert '--threads ${THREADS}' in text or '--threads "${THREADS}"' in text
    assert 'gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}"' in text


def test_ws_long_lived_safe_false_under_gthread(monkeypatch):
    monkeypatch.setenv("GUNICORN_WORKER_CLASS", "gthread")
    import app as app_mod

    app_mod.app.config.pop("GC_WS_LONG_LIVED_SAFE", None)
    assert app_mod.ws_long_lived_safe() is False


def test_ws_long_lived_safe_true_under_gevent(monkeypatch):
    monkeypatch.setenv("GUNICORN_WORKER_CLASS", "gevent")
    import app as app_mod

    app_mod.app.config.pop("GC_WS_LONG_LIVED_SAFE", None)
    assert app_mod.ws_long_lived_safe() is True


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
    assert "GC.shipyardPollMs" not in js
    assert "_shipyardPollIntervalId" not in js
    assert "_defensePollIntervalId" not in js
