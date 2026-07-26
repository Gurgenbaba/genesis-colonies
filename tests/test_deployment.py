"""
Deployment / installer tests.

Run: python -m pytest tests/test_deployment.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def deploy_env(tmp_path, monkeypatch):
    db_file = tmp_path / "deploy_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


def test_config_rejects_insecure_secret_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "change-me-dev-secret")
    monkeypatch.setenv("FLASK_DEBUG", "0")

    from game.config import init_config, validate_config

    init_config()
    errors = validate_config(strict=True)
    assert any("SECRET_KEY" in e for e in errors)


def test_config_postgres_requires_database_url(monkeypatch):
    """GC-PERF-DB-002: postgres is implemented but needs DATABASE_URL (+ psycopg)."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from game.config import init_config, validate_config

    init_config()
    errors = validate_config(strict=True)
    assert any("DATABASE_URL" in e for e in errors)


def test_config_postgres_accepts_url_when_psycopg_present(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/gc")
    monkeypatch.setenv("GC_ALLOW_POSTGRES_PROD", "1")

    from game.config import init_config, validate_config

    init_config()
    errors = validate_config(strict=True)
    assert not any("not implemented" in e.lower() for e in errors)
    # DATABASE_URL is set; remaining errors must not be the missing-URL gate
    assert not any(e == "GC_DB_BACKEND=postgres requires DATABASE_URL=postgresql://…" for e in errors)
    assert not any("blocked in production until cutover" in e for e in errors)


def test_config_postgres_blocked_in_production_without_allow(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/gc")
    monkeypatch.delenv("GC_ALLOW_POSTGRES_PROD", raising=False)

    from game.config import init_config, validate_config

    init_config()
    errors = validate_config(strict=True)
    assert any("blocked in production until cutover" in e for e in errors)


def test_ensure_db_parent_dir_creates_volume_path(monkeypatch, tmp_path):
    db_file = tmp_path / "data" / "game.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")

    from game.db import ensure_db_parent_dir, resolve_db_path

    assert not db_file.parent.exists()
    ensure_db_parent_dir()
    assert db_file.parent.exists()
    assert resolve_db_path() == db_file


def test_db_postgres_requires_url_at_connect(monkeypatch):
    """Without DATABASE_URL, connect still fails clearly (no silent SQLite fallback)."""
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from game.db import db

    with pytest.raises(NotImplementedError) as exc:
        db()
    assert "PostgreSQL" in str(exc.value) or "postgres" in str(exc.value).lower() or "DATABASE_URL" in str(exc.value)

def test_config_rejects_debug_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("FLASK_DEBUG", "1")

    from game.config import init_config, validate_config

    init_config()
    errors = validate_config(strict=True)
    assert any("DEBUG" in e for e in errors)


def test_fresh_install_script(deploy_env, tmp_path, monkeypatch):
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(deploy_env)
    env["SECRET_KEY"] = "install-test-secret-key-with-enough-length"
    env["APP_ENV"] = "development"
    env["GC_SKIP_MIGRATION_CHECK"] = "1"

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "install.py"), "--non-interactive"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert deploy_env.exists()


def test_health_endpoint(deploy_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    data = resp.get_json()
    assert "version" in data
    assert "checks" in data
    assert data["checks"]["database"]["ok"] is True


def test_migration_pending_detected(deploy_env):
    from game.bootstrap import bootstrap_application
    from game.migrations_util import get_pending_migration_names

    bootstrap_application(skip_migration_check=True)
    pending, err = get_pending_migration_names()
    assert err is None
    assert isinstance(pending, list)


def test_docker_entrypoint_migrations_apply_player_messages(deploy_env):
    """Simulates Railway start: migrate.py before app (see scripts/docker-entrypoint.sh)."""
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(deploy_env)
    env["GC_SKIP_MIGRATION_CHECK"] = "1"

    from game.models import init_db

    init_db()

    result = subprocess.run(
        [sys.executable, str(ROOT / "migrate.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    from game.db import db, table_exists

    conn = db()
    try:
        assert table_exists(conn, "player_messages")
        row = conn.execute(
            "SELECT name FROM migration_history WHERE name = ?;",
            ("020_player_messages.sql",),
        ).fetchone()
        assert row is not None
    finally:
        conn.close()

    from game.migrations_util import migrations_are_current

    current, pending, err = migrations_are_current()
    assert err is None
    assert current is True
    assert "020_player_messages.sql" not in pending


def test_env_example_exists():
    assert (ROOT / ".env.example").exists()
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SECRET_KEY" in text
    assert "GC_DB_PATH" in text
    assert "GC_DB_BACKEND" in text


def test_railway_infra_files_exist():
    """Operator deploy uses railway.toml + Dockerfile + operator runbook."""
    railway = ROOT / "railway.toml"
    dockerfile = ROOT / "Dockerfile"
    entrypoint = ROOT / "scripts" / "docker-entrypoint.sh"
    dockerignore = ROOT / ".dockerignore"
    operator_doc = ROOT / "docs" / "RAILWAY_OPERATOR.md"
    assert railway.exists()
    assert dockerfile.exists()
    assert entrypoint.exists()
    assert dockerignore.exists()
    assert operator_doc.exists()
    railway_text = railway.read_text(encoding="utf-8")
    assert "dockerfile" in railway_text.lower()
    assert "/health" in railway_text
    assert "watchPatterns" in railway_text
    assert "/CHANGELOG.md" in railway_text
    dockerignore_text = dockerignore.read_text(encoding="utf-8")
    assert "tests/" in dockerignore_text
    assert "docs/" in dockerignore_text
    assert "!CHANGELOG.md" in dockerignore_text
    operator_text = operator_doc.read_text(encoding="utf-8")
    assert "Wait for CI" in operator_text
    assert "PUBLIC_BASE_URL" in operator_text
    assert "/api/internal/cron/ranking" in operator_text
    assert "GC_ALLOW_POSTGRES_PROD" in operator_text
