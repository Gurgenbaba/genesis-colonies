"""GC-591C — Sidebar group accordion polish."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet, set_active_planet
from game.planet_evolution.sidebar_nav import (
    module_display_section,
    module_in_section,
    nav_link_visible,
    resolve_sidebar_nav,
    sidebar_section_visible,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc591c_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc591c.db"
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


def _create_player() -> tuple[int, str]:
    uname = f"gc591c_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _visible_module_lines(sidebar_html: str, module: str) -> list[str]:
    needle = f'data-nav-module="{module}"'
    out = []
    pos = 0
    while True:
        idx = sidebar_html.find(needle, pos)
        if idx < 0:
            break
        start = sidebar_html.rfind("<", 0, idx)
        end = sidebar_html.find(">", idx)
        if start < 0 or end < 0:
            pos = idx + 1
            continue
        tag = sidebar_html[start : end + 1]
        head = tag.lstrip().lower()
        if head.startswith(("<a", "<button")) and "hidden" not in tag:
            out.append(tag)
        pos = idx + 1
    return out


def test_homeworld_has_all_sections_without_more_toggle():
    nav = resolve_sidebar_nav(empire_role_key="homeworld", is_homeworld=True)
    assert nav["full_nav"] is True
    assert nav["show_more_section"] is False
    for section in ("command", "infrastructure", "military", "economy", "administration"):
        assert sidebar_section_visible(nav, section)


def test_mining_secondary_modules_stay_in_canonical_sections():
    nav = resolve_sidebar_nav(empire_role_key="mining", is_homeworld=False)
    assert module_display_section(nav, "buildings") == "infrastructure"
    assert module_display_section(nav, "research") == "infrastructure"
    assert module_in_section(nav, "research", "infrastructure")
    assert not module_in_section(nav, "research", "administration")
    assert module_in_section(nav, "ranking", "administration")
    assert module_in_section(nav, "hall_of_fame", "administration")
    assert module_in_section(nav, "records", "administration")


def test_sidebar_template_group_accordion_markers():
    sidebar = _read("templates/partials/sidebar.html")
    sidebar_right = _read("templates/partials/sidebar_right.html")
    assert 'data-nav-section="command"' in sidebar
    assert 'data-nav-section="infrastructure"' in sidebar
    assert 'data-nav-section="military"' in sidebar
    assert 'data-nav-section="economy"' in sidebar_right
    assert 'data-nav-section="community"' in sidebar_right
    assert 'data-nav-section="system"' in sidebar_right
    assert "gc-nav-section-toggle" in sidebar
    assert "module_in_section(_sn," in sidebar
    assert 'id="gc-nav-more-toggle"' not in sidebar
    assert 'data-nav-module="messages"' in sidebar_right
    assert 'data-nav-module="support"' not in sidebar_right


def test_main_js_section_accordion_contract():
    src = _read("static/main.js")
    assert "initSidebarSectionAccordion" in src
    assert "syncNavSectionAccordionState" in src
    assert "NAV_SECTION_STORAGE_KEY" in src
    assert "gc_sidebar_state" in src
    assert "moduleDisplaySection" in src
    assert "shouldShowSidebarNavLink" in src


def test_sidebar_economy_section_not_role_group_wrapper():
    sidebar_right = _read("templates/partials/sidebar_right.html")
    eco = sidebar_right.split('data-nav-section="economy"', 1)[1].split('data-nav-section="community"', 1)[0]
    eco_open = eco.split(">", 1)[0]
    assert 'data-nav-group="trading"' not in eco_open
    assert 'data-nav-group-modules="trading"' not in eco_open
    assert 'data-nav-module="trading"' in eco


def test_research_colony_economy_section_visible(gc591c_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name="Lab World")
    assert ok, reason
    colony_id = int(data["planet_id"])
    save_planet_buildings(colony_id, {"research_lab": 12, "academy": 5})
    set_active_planet(player_id, colony_id)

    client = _app_client(monkeypatch)
    assert client.post("/login", data={"username": uname, "password": "test-pass-123"}).status_code in (200, 302)
    html = client.get("/overview").get_data(as_text=True)
    sidebar = html.split('id="gc-sidebar-nav-right"', 1)[1].split("</nav>", 1)[0]
    assert 'data-nav-section="economy"' in sidebar
    eco = sidebar.split('data-nav-section="economy"', 1)[1].split('data-nav-section="community"', 1)[0]
    assert "Wirtschaft" in eco
    assert len(_visible_module_lines(sidebar, "trading")) == 1
    assert len(_visible_module_lines(sidebar, "empire")) == 1


def test_homeworld_overview_renders_grouped_sidebar(gc591c_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    assert client.post("/login", data={"username": uname, "password": "test-pass-123"}).status_code in (200, 302)

    html = client.get("/overview").get_data(as_text=True)
    assert 'data-nav-section="command"' in html
    assert 'data-nav-full="1"' in html
    assert 'id="gc-nav-more-toggle"' not in html
    assert "nav_section_command" in html or "Kommando" in html


def test_mining_colony_renders_community_overflow(gc591c_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name="Ore Hub")
    assert ok, reason
    colony_id = int(data["planet_id"])
    save_planet_buildings(colony_id, {"metal_mine": 10, "crystal_mine": 8})
    set_active_planet(player_id, colony_id)

    client = _app_client(monkeypatch)
    assert client.post("/login", data={"username": uname, "password": "test-pass-123"}).status_code in (200, 302)
    html = client.get("/overview").get_data(as_text=True)

    sidebar_left = html.split('id="gc-sidebar-nav"', 1)[1].split("</nav>", 1)[0]
    sidebar_right = html.split('id="gc-sidebar-nav-right"', 1)[1].split("</nav>", 1)[0]
    assert 'data-nav-full="0"' in html
    assert 'data-nav-section="community"' in sidebar_right
    assert 'data-nav-section="system"' in sidebar_right
    assert len(_visible_module_lines(sidebar_left, "research")) == 1

    switch = client.post("/api/planets/active", json={"planet_id": colony_id}).get_json()
    assert switch["state"]["active_planet"]["sidebar_nav"]["empire_role_key"] == "mining"
