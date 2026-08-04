"""GC-BST — Buildings colony stage layout (display-only + per-planet overrides)."""

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
from game.buildings import (
    BUILDING_ORDER,
    BUILDING_STAGE_LAYOUT,
    BUILDING_TAB,
    _make_panel_row,
    resolve_stage_layout,
    save_stage_layout,
)
from game.models import create_user, get_homeworld, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def stage_db(tmp_path, monkeypatch):
    db_file = tmp_path / "building_stage.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
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


def _client(stage_db, monkeypatch):
    dbmod.DB_PATH = stage_db
    models.DB_PATH = stage_db
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _create_and_login(client):
    uname = f"stage_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    hw = get_homeworld(player_id=int(user["id"]))
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    return int(user["id"]), int(hw["id"])


def test_stage_eager_props_and_landscape_preload():
    """Hard-reload FOUC: landscape preload + eager active-tab props (not lazy)."""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "gc-planet-landscape-preload" in base
    assert "data-gc-landscape-preload" in base
    bld = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    assert "_prop_visible" in bld
    assert "gc-perf-idle" in bld  # early drop when mini-queue active
    assert 'loading="eager"' in (ROOT / "templates" / "partials" / "page_mini_queue_strip.html").read_text(
        encoding="utf-8"
    )


def test_building_stage_layout_covers_all_buildings():
    missing = [k for k in BUILDING_ORDER if k not in BUILDING_STAGE_LAYOUT]
    assert missing == [], f"missing stage slots: {missing}"


def test_building_stage_layout_pct_in_range():
    for key, slot in BUILDING_STAGE_LAYOUT.items():
        assert 0.0 <= float(slot["left_pct"]) <= 100.0, key
        assert 0.0 <= float(slot["top_pct"]) <= 100.0, key
        assert float(slot["scale"]) > 0, key


def test_building_stage_layout_min_spacing():
    """Within each buildings tab, defaults stay far enough apart (props + actions)."""
    from collections import defaultdict

    by_tab = defaultdict(list)
    for key, slot in BUILDING_STAGE_LAYOUT.items():
        by_tab[BUILDING_TAB[key]].append((key, slot))
    for tab, items in by_tab.items():
        for i, (a, sa) in enumerate(items):
            for b, sb in items[i + 1 :]:
                dx = float(sa["left_pct"]) - float(sb["left_pct"])
                dy = float(sa["top_pct"]) - float(sb["top_pct"])
                dist = (dx * dx + dy * dy) ** 0.5
                assert dist >= 18.0, f"{tab}: {a} vs {b}: dist={dist:.2f}"


def test_panel_row_includes_stage_fields():
    planet = {"id": 1, "player_id": 1, "metal": 1e12, "crystal": 1e12}
    buildings = {k: 1 for k in BUILDING_ORDER}
    research = {}
    row = _make_panel_row(planet, buildings, research, "metal_mine")
    assert row["key"] == "metal_mine"
    assert "stage_left_pct" in row
    assert "stage_top_pct" in row
    assert row["stage_left_pct"] == BUILDING_STAGE_LAYOUT["metal_mine"]["left_pct"]


def test_save_and_resolve_stage_layout_overrides(stage_db):
    ok, err, user = create_user(f"own_{uuid.uuid4().hex[:6]}", "test-pass-123")
    assert ok and user, err
    pid = int(user["id"])
    hw = get_homeworld(player_id=pid)
    planet_id = int(hw["id"])

    ok, reason, extra = save_stage_layout(
        planet_id,
        pid,
        [{"building_key": "metal_mine", "left_pct": 12.5, "top_pct": 88.0}],
    )
    assert ok and reason == "ok"
    layout = resolve_stage_layout(planet_id)
    assert layout["metal_mine"]["left_pct"] == 12.5
    assert layout["metal_mine"]["top_pct"] == 88.0
    # untouched keys keep defaults
    assert layout["crystal_mine"]["left_pct"] == BUILDING_STAGE_LAYOUT["crystal_mine"]["left_pct"]

    row = _make_panel_row(
        {"id": planet_id, "player_id": pid, "metal": 1e12, "crystal": 1e12},
        {k: 1 for k in BUILDING_ORDER},
        {},
        "metal_mine",
        stage_layout=layout,
    )
    assert row["stage_left_pct"] == 12.5


def test_save_stage_layout_clamps_and_rejects_foreign(stage_db):
    ok, err, user = create_user(f"a_{uuid.uuid4().hex[:6]}", "test-pass-123")
    assert ok and user, err
    ok2, err2, other = create_user(f"b_{uuid.uuid4().hex[:6]}", "test-pass-123")
    assert ok2 and other, err2
    pid = int(user["id"])
    other_id = int(other["id"])
    planet_id = int(get_homeworld(player_id=pid)["id"])

    ok, reason, _ = save_stage_layout(
        planet_id,
        other_id,
        [{"building_key": "metal_mine", "left_pct": 10, "top_pct": 10}],
    )
    assert not ok and reason == "forbidden"

    ok, reason, extra = save_stage_layout(
        planet_id,
        pid,
        [{"building_key": "metal_mine", "left_pct": -20, "top_pct": 140}],
    )
    assert ok
    layout = (extra or {}).get("layout") or resolve_stage_layout(planet_id)
    assert layout["metal_mine"]["left_pct"] == 0.0
    assert layout["metal_mine"]["top_pct"] == 100.0


def test_api_stage_layout_save_and_reset(stage_db, monkeypatch):
    client = _client(stage_db, monkeypatch)
    _uid, planet_id = _create_and_login(client)

    res = client.post(
        "/api/buildings/stage-layout",
        json={
            "positions": [{"building_key": "solar_plant", "left_pct": 33, "top_pct": 44}],
            "request_id": f"rid-{uuid.uuid4().hex[:8]}",
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    layout = resolve_stage_layout(planet_id)
    assert layout["solar_plant"]["left_pct"] == 33.0
    assert layout["solar_plant"]["top_pct"] == 44.0

    res2 = client.post(
        "/api/buildings/stage-layout",
        json={"reset": True, "request_id": f"rid-{uuid.uuid4().hex[:8]}"},
    )
    assert res2.status_code == 200
    assert res2.get_json()["ok"] is True
    layout2 = resolve_stage_layout(planet_id)
    assert layout2["solar_plant"]["left_pct"] == BUILDING_STAGE_LAYOUT["solar_plant"]["left_pct"]


def test_buildings_page_has_stage_markers(stage_db, monkeypatch):
    client = _client(stage_db, monkeypatch)
    _create_and_login(client)
    res = client.get("/buildings?tab=resources")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "data-bld-planet-stage" in html
    assert 'data-active-stage-tab="resources"' in html
    assert 'data-stage-tab="resources"' in html
    assert "data-bld-stage-deck" not in html
    assert "data-bld-stage-composition" not in html
    assert "bld-stage-prop--round" in html
    assert "data-bld-stage-actions" in html
    assert "btn-upgrade" in html
    assert "data-bld-stage-prop=" in html
    assert "data-bld-stage-arrange" in html
    # Default mode is Colony Stage — exclusive visible UI (no Retro cards panel).
    assert 'data-buildings-ui-mode="stage"' in html
    assert "data-bld-cards-panel" not in html
    assert "data-bld-card-popup" in html
    # Hidden card sources for detail popup + live patches (not Retro chrome).
    assert "data-bld-stage-card-source" in html
    assert 'data-building-row="metal_mine"' in html
    assert "buildings-prog-list" in html
    # SSR is tab-scoped — only active-tab props are rendered (no cross-tab hidden class needed).
    assert "data-bld-stage-prop=\"research_lab\"" not in html


def test_stage_tab_filter_in_js():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function syncBuildingStageActiveTab" in js
    assert "is-stage-tab-hidden" in js
    activate = js.split("function activateBuildingTabByName")[1].split("function bindBuildingTabsOnce")[0]
    assert "syncBuildingStageActiveTab(" in activate


def test_planet_switch_includes_building_stage_layout(stage_db, monkeypatch):
    client = _client(stage_db, monkeypatch)
    uid, planet_id = _create_and_login(client)
    ok, reason, _ = save_stage_layout(
        planet_id,
        uid,
        [{"building_key": "metal_mine", "left_pct": 21.0, "top_pct": 77.0}],
    )
    assert ok and reason == "ok"

    res = client.post("/api/planets/active", json={"planet_id": planet_id})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    layout = (body.get("state") or {}).get("building_stage_layout")
    assert isinstance(layout, dict)
    assert layout["metal_mine"]["left_pct"] == 21.0
    assert layout["metal_mine"]["top_pct"] == 77.0


def test_stage_surface_uses_planet_landscape_token():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    surface_idx = css.find(".bld-planet-stage-surface{")
    assert surface_idx >= 0
    chunk = css[surface_idx : surface_idx + 900]
    assert "--planet-landscape" in chunk
    assert "buildings/stage/yard.webp" not in chunk
    assert "blur(" not in chunk
    assert "filter: none" in chunk
    assert ".bld-planet-stage-deck{" not in css
    assert "conic-gradient" in css
    assert "bld-stage-prop-actions" in css
    assert "border-radius: 50%" in css
    assert "--gc-id-rgb" in css
    assert "bld-stage-prop-actions a.gc-bld-head-action-btn--go" in css
    popup_idx = css.find(".bld-card-popup::backdrop{")
    assert popup_idx >= 0
    popup_chunk = css[popup_idx : popup_idx + 220]
    assert "backdrop-filter: none" in popup_chunk


def test_stage_build_fx_driven_from_mini_queue():
    """Stage construction FX must not depend only on hidden card queues."""
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function setBuildingStagePropBuildFx" in js
    assert "function updateBuildingStageBuildFxFromMiniQueue" in js
    assert "updateBuildingStageBuildFxFromMiniQueue(" in js
    assert "dataset.ownerKey = ownerKey" in js
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "@keyframes bld-stage-build-pulse" in css
    assert "@keyframes bld-stage-art-pulse" in css
    assert "@keyframes bld-stage-scan" in css
    assert ".bld-stage-prop--queue .bld-stage-prop-build{" in css
    tpl = (ROOT / "templates" / "partials" / "page_mini_queue_strip.html").read_text(encoding="utf-8")
    assert "data-owner-key" in tpl


def test_stage_popup_strips_upgrade_actions_in_js():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    fn = js.split("function openBuildingCardPopup")[1].split("function setBuildingCardsExpanded")[0]
    assert 'data-building-row="${key}"' in fn or "data-building-row=\"${key}\"" in fn
    assert "gc-bld-card-hero-action-slot" in fn
    assert "btn-upgrade-max" in fn
    assert ".forEach((el) => el.remove())" in fn


def test_technical_modal_closes_stage_card_popup():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    fn = js.split("function openBuildingTechnicalModal")[1].split("function closeBuildingTechnicalModal")[0]
    assert "closeBuildingCardPopup()" in fn


def test_stage_icon_prefers_stage_asset():
    from game.buildings import get_building_stage_icon

    icon = get_building_stage_icon("metal_mine")
    assert icon.startswith("img/buildings/stage/")
    assert "metal_mine" in icon