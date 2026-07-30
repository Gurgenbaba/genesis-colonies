"""GC-575A — Planet Registry (right rail) and planet-switch contract."""
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
import time

from game.models import (
    add_build_job,
    add_research_job,
    create_user,
    db,
    get_homeworld,
    init_db,
    save_planet_buildings,
)
from game.planet_evolution.service import colonize_planet, list_player_planets_for_switcher, set_active_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def switcher_db(tmp_path, monkeypatch):
    db_file = tmp_path / "planet_registry.db"
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
    uname = f"reg_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return (int(user["id"]), uname)


def _unlock_first_expansion(uid: int) -> None:
    from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH
    from conftest import unlock_colony_slots

    conn = db()
    try:
        hw = get_homeworld(uid, conn=conn)
        assert hw
        unlock_colony_slots(conn, int(hw["id"]), slots=1)
        # Registry / PE UI paths also exercise the interstellar tech gate
        # (evaluate_expansion_gates), which unlock_colony_slots does not cover.
        conn.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(uid), INTERSTELLAR_EXPANSION_TECH, 1),
        )
        conn.commit()
    finally:
        conn.close()


def _second_planet(player_id: int) -> int:
    _unlock_first_expansion(player_id)
    ok, reason, extra = colonize_planet(
        player_id,
        name=f"Colony_{uuid.uuid4().hex[:4]}",
        allow_legacy_coordinates=True,
        source="test",
    )
    assert ok, reason
    return int(extra["planet_id"])


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _login(client, player_id: int, uname: str) -> None:
    """Prefer session_transaction — importlib.reload can invalidate cookie sessions mid-suite."""
    with client.session_transaction() as sess:
        sess["user_id"] = int(player_id)
        sess["username"] = uname


def test_list_player_planets_for_switcher_includes_coords(switcher_db):
    player_id, _ = _create_player()
    colony_id = _second_planet(player_id)
    planets = list_player_planets_for_switcher(player_id)
    assert len(planets) == 2
    by_id = {int(p["planet_id"]): p for p in planets}
    assert by_id[colony_id]["coordinates_formatted"]
    assert by_id[colony_id]["planet_class_label_key"]


def test_switcher_payload_includes_empire_identity(switcher_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    save_planet_buildings(colony_id, {"metal_mine": 10, "crystal_mine": 8})
    planets = list_player_planets_for_switcher(player_id)
    by_id = {int(p["planet_id"]): p for p in planets}
    hw = by_id[hw_id]
    colony = by_id[colony_id]
    assert hw["empire_role_key"] == "homeworld"
    assert hw["empire_role_label_key"] == "empire_role_homeworld"
    assert hw["empire_role_icon"] == "🏛"
    assert colony["empire_role_key"] == "mining"
    assert colony["empire_role_label_key"] == "empire_role_mining"
    assert colony["empire_role_icon"] == "⛏"


def test_switcher_payload_includes_herocard_relpath(switcher_db):
    player_id, _ = _create_player()
    _second_planet(player_id)
    planets = list_player_planets_for_switcher(player_id)
    assert planets
    for p in planets:
        assert p.get("herocard_relpath", "").startswith("img/herocards/")
        assert p.get("herocard_webp_relpath", "").startswith("img/herocards/")


def test_switcher_payload_status_indicators_building_queue(switcher_db):
    """GC-PLANET-UI-001: status_indicators reflects active build_queue per planet."""
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    now = time.time()
    add_build_job(hw_id, "metal_mine", now - 10, now + 600)

    planets = list_player_planets_for_switcher(player_id)
    by_id = {int(p["planet_id"]): p for p in planets}

    hw_inds = by_id[hw_id]["status_indicators"]
    assert isinstance(hw_inds, list)
    assert len(hw_inds) == 1
    assert hw_inds[0]["key"] == "building"
    assert hw_inds[0]["icon"] == "🏗"
    assert hw_inds[0]["label_key"] == "planet_status_building_active"

    assert by_id[colony_id]["status_indicators"] == []


def test_switcher_payload_status_indicators_research_shipyard_defense(switcher_db):
    """GC-PLANET-UI-001: research on active planet; shipyard/defense per colony."""
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    set_active_planet(player_id, hw_id)
    now = time.time()
    add_research_job(player_id, "energy_tech", now - 10, now + 900)

    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO shipyard_queue (
                player_id, planet_id, ship_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_fuel_cells
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                player_id,
                colony_id,
                "mule_courier",
                1,
                "queued",
                now - 5,
                now + 1800,
                now,
                0,
                0,
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO defense_queue (
                player_id, planet_id, defense_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_fuel_cells
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                player_id,
                colony_id,
                "sentinel_turret",
                1,
                "queued",
                now - 5,
                now + 1200,
                now,
                0,
                0,
                0,
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    planets = list_player_planets_for_switcher(player_id)
    by_id = {int(p["planet_id"]): p for p in planets}
    hw_keys = [i["key"] for i in by_id[hw_id]["status_indicators"]]
    colony_keys = [i["key"] for i in by_id[colony_id]["status_indicators"]]

    assert hw_keys == ["research"]
    assert by_id[hw_id]["status_indicators"][0]["icon"] == "🔬"
    assert by_id[hw_id]["status_indicators"][0]["label_key"] == "planet_status_research_active"
    assert colony_keys == ["shipyard", "defense"]
    assert {i["key"]: i["icon"] for i in by_id[colony_id]["status_indicators"]} == {
        "shipyard": "⚓",
        "defense": "🛡",
    }


def test_registry_ssr_shows_building_status_indicator(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    now = time.time()
    add_build_job(hw_id, "metal_mine", now - 10, now + 600)
    add_research_job(player_id, "energy_tech", now - 10, now + 900)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    assert "gc-planet-registry-card-meta" in body
    assert "gc-planet-registry-card-status" in body
    assert 'data-status-key="building"' in body
    assert 'data-status-key="research"' in body
    assert "gc-planet-registry-status-icon" in body


def test_registry_shows_role_and_coords(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)
    save_planet_buildings(colony_id, {"research_lab": 12, "academy": 6})
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    for needle in (
        "gc-planet-registry",
        "gc-planet-registry-card",
        "gc-planet-registry-card-thumb",
        "gc-planet-registry-card-role",
        "gc-planet-registry-card-coord",
        "data-planet-role-key",
        "data-planet-identity-key",
        "data-planet-herocard",
        "data-gc-planet-registry",
        "img/herocards/",
    ):
        assert needle in body, f"missing registry marker: {needle}"
    assert "gc-planet-registry-card-icon" not in body
    assert "gc-planet-switcher" not in body
    assert 'include "partials/header_planet_switcher.html"' not in (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "empire_role_homeworld" in body or "Genesis Ark" in body


def test_main_js_registry_role_contract():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "empireIdentityLabelKey" in src
    assert "gc-planet-registry-card-role" in src
    assert "gc-planet-registry-card-thumb" in src
    rebuild = src.split("function rebuildPlanetRegistry")[1].split("function updatePlanetRegistryFromPlanets")[0]
    assert "herocard_url" in rebuild
    assert "status_indicators" in rebuild
    assert "gc-planet-registry-card-status" in rebuild
    assert "gc-planet-registry-status-icon" in rebuild
    assert "planetRoleKey" in src
    assert "planetIdentityKey" in src
    assert "empire_identity_key" in src.split("function empireIdentityLabelKey")[1].split("function planetRegistryRoots")[0]
    assert "initHeaderPlanetSwitcher" not in src
    assert "GC.updateHeaderPlanetSwitcherFromState" not in src


def test_diet_poll_planets_keep_identity_label_keys():
    """GC-575: diet poll must not strip role subtitle keys — otherwise registry roles flash then vanish."""
    live = (ROOT / "game" / "live_state.py").read_text(encoding="utf-8")
    block = live.split("_PLANET_SWITCHER_POLL_KEYS = (")[1].split(")", 1)[0]
    for key in (
        "empire_role_key",
        "empire_role_icon",
        "empire_role_label_key",
        "empire_subtitle_key",
        "identity_title_key",
        "herocard_url",
        "herocard_webp_url",
        "status_indicators",
    ):
        assert f'"{key}"' in block, f"missing diet planet key: {key}"


def test_registry_css_role_hierarchy():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gc-planet-registry-card-role" in css
    assert ".gc-planet-registry-card-thumb" in css
    assert ".gc-planet-registry-card-coord" in css
    assert ".gc-planet-registry-card-meta" in css
    assert ".gc-planet-registry-card-status" in css
    assert ".gc-planet-registry-status-icon" in css
    assert ".gc-sidebar-right-rails" in css
    assert "display: contents" in css
    assert ".gc-planet-switcher" not in css
    assert ".gc-planet-registry-card-icon" not in css

def test_four_column_shell_order(switcher_db, monkeypatch):
    """Left | Main | Meta | Imperium — registry is sibling after meta, not stacked above it."""
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    left_idx = body.find('id="gc-sidebar-nav"')
    main_idx = body.find('id="main-content"')
    meta_idx = body.find('id="gc-sidebar-nav-right"')
    reg_idx = body.find('id="gc-planet-registry"')
    assert left_idx >= 0
    assert main_idx > left_idx
    assert meta_idx > main_idx
    assert reg_idx > meta_idx
    assert "gc-sidebar-meta-wrap" not in body
    assert "gc-sidebar-meta-toggle" not in body


def test_overview_renders_registry_with_all_planets(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    resp = client.get("/overview")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="gc-planet-registry"' in body
    assert 'data-gc-planet-registry-list' in body
    assert f'data-planet-id="{colony_id}"' in body
    assert f'data-planet-id="{hw_id}"' in body
    assert "gc-planet-switcher-menu" not in body


def test_registry_single_planet_still_lists_card(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    assert "gc-planet-registry" in body
    assert "gc-planet-registry-card" in body
    assert "gc-planet-switcher" not in body


def test_api_set_active_updates_state_and_overview(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    save_planet_buildings(hw_id, {"metal_mine": 2, "solar_plant": 1})
    save_planet_buildings(colony_id, {"metal_mine": 9, "solar_plant": 1})
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason
    r = client.post(
        "/api/planets/active",
        json={"planet_id": hw_id},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["state"]["active_planet_id"] == hw_id
    assert int(data["state"]["buildings"]["metal_mine"]) == 2
    assert isinstance(data.get("planets"), list)
    assert len(data["planets"]) == 2
    gs = client.get("/api/game-state").get_json()
    assert gs["active_planet_id"] == hw_id
    assert gs.get("active_planet", {}).get("name")
    assert int(data["state"]["player"]["metal"]) == int(data["state"]["resources"]["metal"])
    assert "buildings_panel" not in data["state"]


def test_api_planets_active_switch_returns_fresh_colony_resources(switcher_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    conn = db()
    conn.execute("UPDATE planets SET metal = 100, crystal = 50 WHERE id = ?;", (hw_id,))
    conn.execute("UPDATE planets SET metal = 9000, crystal = 8000 WHERE id = ?;", (colony_id,))
    conn.commit()
    conn.close()
    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    r = client.post(
        "/api/planets/active",
        json={"planet_id": hw_id},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    st = body["state"]
    assert st["active_planet_id"] == hw_id
    assert int(st["resources"]["metal"]) == 100
    assert int(st["player"]["metal"]) == 100


def test_planet_evolution_template_no_switch_or_colonize_ui():
    tpl = (ROOT / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert "pe-colony-bar" not in tpl
    assert "pe-planet-btn" not in tpl
    assert "pe-colonize-btn" not in tpl


def test_main_js_planet_registry_bound():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "initPlanetRegistry" in src
    assert "GC.updatePlanetRegistryFromState" in src
    assert "rebuildPlanetRegistry" in src
    assert "applyPlanetLandscapeFromState" in src
    assert "gc-has-planet-landscape" in src
    assert "reloadPageForActivePlanet" in src
    assert "getDomPlanetId" in src
    assert "trader-hub-page" in src
    assert "force: true" in src
    assert ".pe-planet-btn" not in src
    assert "initHeaderPlanetSwitcher" not in src


def test_trader_hub_template_scoped_to_active_planet():
    tpl = (ROOT / "templates" / "trader_hub.html").read_text(encoding="utf-8")
    assert 'id="trader-hub-page"' in tpl
    assert "data-planet-id" in tpl
    assert "HEADER_ACTIVE_PLANET" in tpl


def test_landscape_css_uses_gc_bg_layer():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "gc-has-planet-landscape" in css
    assert "gc-has-planet-landscape .gc-bg" in css
    assert '[style*="--planet-landscape"]::before' not in css


def test_base_template_landscape_class():
    tpl = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "gc-has-planet-landscape" in tpl
    assert "current_planet_landscape_url" in tpl
    assert "header_planet_switcher" not in tpl
    assert "gc-hslot-planet-switcher" not in tpl


def test_overview_injects_planet_landscape_css_var(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw = get_homeworld(player_id=player_id)
    hw_pos = int(hw.get("position") or 1)
    from game.planet_visuals import get_landscape_for_position

    expected_fn = get_landscape_for_position(hw_pos)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    assert "--planet-landscape:" in body
    assert f"img/landscapes/{expected_fn}" in body


def test_game_state_includes_planet_limit(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    gs = client.get("/api/game-state").get_json()
    assert gs.get("ok") is True
    pl = gs.get("planet_limit") or {}
    assert pl.get("owned_worlds") == 1
    assert pl.get("max") == 1
    assert pl.get("effective_max_worlds") == 1
    colony_id = _second_planet(player_id)
    gs2 = client.get("/api/game-state").get_json()
    pl2 = gs2.get("planet_limit") or {}
    assert pl2.get("owned_worlds") == 2
    assert pl2.get("max") == 2
    assert pl2.get("effective_max_worlds") == 2
    assert colony_id > 0


def test_registry_shows_planet_limit():
    registry = (ROOT / "templates" / "partials" / "planet_registry.html").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "hud-res-planet-limit" not in base
    assert "data-planet-limit-value" in registry
    assert "gc-planet-registry-limit" in registry


def test_main_js_patches_planet_limit_from_state():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "patchHeaderPlanetLimitFromState" in src
    assert "data-planet-limit-value" in src
    assert "planet_limit" in src
    fn = src.split("function patchHeaderPlanetLimitFromState(data, force)")[1].split(
        "GC.patchHeaderPlanetLimitFromState"
    )[0]
    assert "if (!force) return" in fn


def test_game_state_includes_planets_list(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    gs = client.get("/api/game-state").get_json()
    assert gs.get("ok") is True
    planets = gs.get("planets") or []
    assert len(planets) == 2
    ids = {int(p["planet_id"]) for p in planets}
    assert colony_id in ids


def test_game_state_includes_landscape_url(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)
    from game.planet_visuals import get_landscape_for_position

    conn = db()
    row = conn.execute("SELECT position FROM planets WHERE id = ?;", (colony_id,)).fetchone()
    conn.close()
    position = int(row["position"])
    expected_fn = get_landscape_for_position(position)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    set_active_planet(player_id, colony_id)
    gs = client.get("/api/game-state").get_json()
    ap = gs.get("active_planet") or {}
    assert ap.get("position") == position
    assert ap.get("landscape_url")
    assert expected_fn in ap["landscape_url"]


def test_gc641_economy_nav_visible_on_colony(switcher_db, monkeypatch):
    """GC-641 — Wirtschaft / Trader Hub / Empire visible on every colony."""
    from game.planet_evolution.sidebar_nav import nav_module_tier, resolve_sidebar_nav, sidebar_section_visible

    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)
    save_planet_buildings(colony_id, {"research_lab": 12, "academy": 5})
    set_active_planet(player_id, colony_id)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    gs = client.get("/api/game-state").get_json()
    ap = gs["active_planet"]
    # Diet polls keep empire_role_key; sidebar_nav is shell/SSR (not diet payload).
    nav = resolve_sidebar_nav(
        empire_role_key=str(ap.get("empire_role_key") or "general"),
        is_homeworld=bool(ap.get("is_homeworld")),
    )
    assert nav["full_nav"] is False
    assert sidebar_section_visible(nav, "economy") is True
    assert nav_module_tier(nav, "trading") == "prominent"
    assert nav_module_tier(nav, "empire") == "prominent"
    html = client.get("/overview").get_data(as_text=True)
    sidebar = html.split('id="gc-sidebar-nav-right"', 1)[1].split("</nav>", 1)[0]
    eco_idx = sidebar.find('data-nav-section="economy"')
    assert eco_idx >= 0
    eco_open = sidebar[eco_idx - 80 : sidebar.find(">", eco_idx) + 1]
    assert " hidden" not in eco_open
    assert 'data-nav-group="trading"' not in eco_open
    assert "Wirtschaft" in sidebar.split('data-nav-section="economy"', 1)[1].split("data-nav-section=", 1)[0]
    assert 'data-nav-module="trading"' in sidebar
    assert 'data-nav-module="empire"' in sidebar
    assert "gc-nav-module--secondary" not in sidebar.split('data-nav-module="trading"', 1)[1][:120]
    assert "gc-nav-module--secondary" not in sidebar.split('data-nav-module="empire"', 1)[1][:120]


def test_meta_nav_before_registry(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    body = client.get("/overview").get_data(as_text=True)
    meta_idx = body.find('id="gc-sidebar-nav-right"')
    reg_idx = body.find('id="gc-planet-registry"')
    assert meta_idx >= 0
    assert reg_idx > meta_idx
    assert 'data-nav-section="economy"' in body[meta_idx:reg_idx]


def test_trader_hub_and_shipyard_render_active_planet_id(switcher_db, monkeypatch):
    """Full SSR (not X-PJAX): PJAX skips HEADER_ACTIVE_PLANET by shell contract."""
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)
    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason
    trader = client.get("/trader-hub").get_data(as_text=True)
    assert f'data-planet-id="{colony_id}"' in trader
    ok, reason = set_active_planet(player_id, hw_id)
    assert ok, reason
    shipyard = client.get("/shipyard").get_data(as_text=True)
    assert f'data-planet-id="{hw_id}"' in shipyard


def test_planet_switch_hotfix_client_contract():
    """GC-803 / GC-575A: planet switch is POST + soft panel / skip SSR; polls stay HUD-only."""
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    refresh = src.split("async function refreshGameState(reason)")[1].split("function refreshHudFromGameState")[0]
    assert "isPlanetSwitchReason" not in refresh
    assert "include_panel=1" not in refresh
    registry = src.split("function initPlanetRegistry()")[1].split("function bindPlanetEvolutionOnce()")[0]
    assert "skipPolling: true" in registry
    assert "releaseBusy" in registry
    assert "unlockShellEarly" in registry
    assert "planet_switch_pre_reload" in registry
    assert "GC._planetSwitchInFlight" in registry
    assert "GC._planetSwitchCooldownUntil" in registry
    assert "PLANET_SWITCH_COOLDOWN_MS" in registry
    assert 'refreshGameState("planet_switch")' not in registry
    # GC-FLEET-PLANET-SWITCH-001: soft fleet refresh with explicit planet + force
    assert 'pageName === "fleet"' in registry
    assert 'reason: "planet_switch"' in registry
    assert "force: true" in registry
    assert "planetId," in registry or "planetId: planetId" in registry
    # GC-PERF-PLANET-SWITCH-004: buildings etc soft-patch, no HTML tear-down
    assert '"buildings"' in registry
    assert "PLANET_SWITCH_SOFT_PANEL" in registry
    assert 'forceCanonicalGameStateRefresh("planet_switch_panel"' in registry
    apply = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "GC.refreshInFlight = null" in apply
    assert "hudOnly: isPlanetSwitch" in apply
    assert "staleMutationPlanet" in apply
    upd = src.split(
        "GC.updatePlanetRegistryFromState = function updatePlanetRegistryFromState(data)"
    )[1].split("function rebuildLanguageSelectMenu")[0]
    assert "GC.lastState.planets" in upd


def test_header_planet_switcher_template_removed():
    assert not (ROOT / "templates" / "partials" / "header_planet_switcher.html").exists()
    assert (ROOT / "templates" / "partials" / "planet_registry.html").exists()
