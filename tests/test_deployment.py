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


def test_env_example_exists():
    assert (ROOT / ".env.example").exists()
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SECRET_KEY" in text
    assert "GC_DB_PATH" in text
    assert "GC_DB_BACKEND" in text
