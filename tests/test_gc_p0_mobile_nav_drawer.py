"""GC-P0 MOBILE — dual sidebar mobile drawer contract tests."""
from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.planet_evolution.sidebar_nav import mobile_bottom_modules, resolve_sidebar_nav

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc_p0_mobile_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_p0_mobile.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _create_player() -> tuple[int, str]:
    uname = f"gc_p0_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def test_mobile_drawer_uses_sidebar_partials_not_copied_links():
    base = _read("templates/base.html")
    sidebar_left = _read("templates/partials/sidebar.html")
    assert "mobile-drawer-left" in base
    assert 'include "partials/sidebar.html"' in base
    assert 'include "partials/sidebar_right.html"' in base
    assert "gc-nav-drawer-tabs" in base
    assert 'NAV_SHELL=' in base
    assert 'gc-mnav-' in sidebar_left
    assert 'id="{{ _nav_id }}"' in sidebar_left
    assert "gc-nav-drawer-link" not in base


def test_mobile_drawer_has_no_duplicate_nav_ids():
    base = _read("templates/base.html")
    ids = re.findall(r'id="(gc-[^"]+)"', base)
    assert len(ids) == len(set(ids)), "duplicate element IDs in base shell"


def test_main_js_mobile_drawer_lifecycle():
    src = _read("static/main.js")
    assert "syncMobileDrawerSidebars" in src
    assert "gc_mobile_nav_tab" in src
    assert "gc-mnav-sidebar-nav" in src
    assert "gc-sidebar-mobile-drawer" in src
    assert "applyMobileDrawerNav" not in src


def test_homeworld_mobile_bottom_nav_includes_fleet():
    nav = resolve_sidebar_nav(empire_role_key="homeworld", is_homeworld=True)
    bottom = mobile_bottom_modules(nav)
    assert bottom == ["overview", "buildings", "research", "fleet"]


def test_overview_mobile_drawer_renders_gameplay_and_meta(gc_p0_mobile_db, monkeypatch):
    _, uname = _create_player()
    client = _app_client(monkeypatch)
    assert client.post("/login", data={"username": uname, "password": "test-pass-123"}).status_code in (200, 302)
    html = client.get("/overview").get_data(as_text=True)
    drawer = html.split('id="gc-nav-drawer"', 1)[1].split('id="gc-locale"', 1)[0]
    assert 'data-nav-section="command"' in drawer
    assert 'data-nav-section="economy"' in drawer
    assert 'data-nav-section="messages"' in drawer
    assert 'data-nav-section="system"' in drawer
    assert 'data-nav-section="utility"' in drawer
    assert 'data-special-open-window="support"' in drawer
    assert 'data-mobile-nav-tab="gameplay"' in drawer
    assert 'data-mobile-nav-tab="meta"' in drawer
    assert 'data-nav-module="trading"' in drawer
    assert 'data-nav-module="alliance"' in drawer
