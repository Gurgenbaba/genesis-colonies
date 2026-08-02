"""
Server Events — timed production / expedition hold bonuses.

Run: python -m pytest tests/test_server_events.py -v
"""

from __future__ import annotations

import importlib
import time
import uuid

import pytest

from game.db import db
from game.fleet import expedition_stay_seconds
from game.fleet_defs import EXPEDITION_STAY_HOUR_SECONDS
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet
from game.production_formula import calculate_resource_output, production_context_from_resolver
from game.server_events import (
    KIND_EXPEDITION_HOLD_MULT,
    KIND_PRODUCTION_MULT,
    active_expedition_hold_mult,
    active_production_mult,
    clear_factor_cache,
    create_event,
    schema_ready,
    validate_effects,
)


@pytest.fixture
def events_db(tmp_path, monkeypatch):
    db_path = tmp_path / "server_events.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    clear_factor_cache()
    yield
    clear_factor_cache()
    gdb._DB_PATH = None


def _player():
    ok, err, user = create_user(f"sev_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    ensure_player_and_homeworld(uid, player_name="SevOps", conn=conn)
    conn.commit()
    conn.close()
    return uid


def test_schema_ready_after_migrate(events_db):
    conn = db()
    assert schema_ready(conn)
    conn.close()


def test_validate_effects_rejects_unknown_kind(events_db):
    cleaned, err = validate_effects([{"kind": "loot_mult", "mult": 2.0}])
    assert cleaned == []
    assert err and err.startswith("unknown_effect_kind")


def test_active_factors_window_and_disabled(events_db):
    now = int(time.time())
    entry, err = create_event(
        slug="weekend-boost",
        title="Weekend",
        starts_at=now - 60,
        ends_at=now + 3600,
        effects=[
            {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
            {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
        ],
        enabled=True,
    )
    assert err is None, err
    assert entry is not None
    clear_factor_cache()
    assert active_production_mult(now=float(now)) == pytest.approx(2.0)
    assert active_expedition_hold_mult(now=float(now)) == pytest.approx(0.75)

    # Outside window
    clear_factor_cache()
    assert active_production_mult(now=float(now + 10_000)) == pytest.approx(1.0)

    # Disabled
    from game.server_events import update_event

    update_event(int(entry["id"]), enabled=False)
    clear_factor_cache()
    assert active_production_mult(now=float(now)) == pytest.approx(1.0)


def test_expedition_stay_seconds_applies_hold_mult(events_db):
    now = int(time.time())
    create_event(
        slug="expo-hold",
        title="Hold Cut",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[{"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75}],
    )
    clear_factor_cache()
    expected = max(1, int(4 * EXPEDITION_STAY_HOUR_SECONDS * 0.75))
    assert expedition_stay_seconds(4, now=float(now)) == expected


def test_production_event_modifier_doubles_output(events_db):
    from game.effects.effect_resolver import clear_effect_resolver_cache, get_effect_resolver

    uid = _player()
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    clear_effect_resolver_cache()
    resolver = get_effect_resolver(uid, conn=conn, planet=planet, force_refresh=True)
    ctx_base = production_context_from_resolver(resolver, "metal")
    # Force baseline without event (no active events yet)
    assert float(ctx_base.event_modifier) == pytest.approx(1.0)
    base_out = calculate_resource_output("metal", ctx_base)

    now = int(time.time())
    create_event(
        slug="prod-double",
        title="Prod x2",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
        conn=conn,
    )
    clear_factor_cache()
    clear_effect_resolver_cache()
    resolver2 = get_effect_resolver(uid, conn=conn, planet=planet, force_refresh=True)
    ctx_boost = production_context_from_resolver(resolver2, "metal")
    assert float(ctx_boost.event_modifier) == pytest.approx(2.0)
    boosted = calculate_resource_output("metal", ctx_boost)
    assert boosted == pytest.approx(base_out * 2.0, rel=1e-6)
    conn.close()


def test_resource_bar_hud_includes_event_production(events_db):
    from game.inventory_boosters import build_active_effects_for_hud

    uid = _player()
    now = int(time.time())
    create_event(
        slug="hud-prod",
        title="Weekend Prod",
        starts_at=now - 10,
        ends_at=now + 7200,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
    )
    clear_factor_cache()
    conn = db()
    hud = build_active_effects_for_hud(uid, conn=conn, locale="de", now=float(now))
    conn.close()
    chip = next(
        (e for e in hud if e.get("hud_chip_only") and e.get("affected_domain") == "production"),
        None,
    )
    assert chip is not None
    assert "Event +100" in str(chip.get("effect_summary") or "")
    assert int(chip.get("remaining_seconds") or 0) > 0
    listed = next((e for e in hud if e.get("key") == "server_event:production"), None)
    assert listed is not None


def test_admin_events_api_crud(events_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()

    ok_a, _, admin_info = create_user(f"adm_sev_{uuid.uuid4().hex[:6]}", "adminpass123", is_admin=1)
    assert ok_a
    admin_id = int(admin_info["id"])
    ensure_player_and_homeworld(admin_id)

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id

    now = int(time.time())
    create = client.post(
        "/api/admin/events",
        json={
            "slug": "api-weekend",
            "title": "API Weekend",
            "starts_at": now - 30,
            "ends_at": now + 7200,
            "enabled": True,
            "effects": [
                {"kind": "production_mult", "mult": 2.0},
                {"kind": "expedition_hold_mult", "mult": 0.75},
            ],
        },
        content_type="application/json",
    )
    assert create.status_code == 200
    body = create.get_json()
    assert body["ok"] is True
    event_id = int(body["event"]["id"])

    listed = client.get("/api/admin/events")
    assert listed.status_code == 200
    listed_body = listed.get_json()
    assert listed_body["ok"] is True
    assert any(int(e["id"]) == event_id for e in listed_body["events"])
    assert float(listed_body["active"]["production_mult"]) == pytest.approx(2.0)

    bad = client.post(
        "/api/admin/events",
        json={
            "slug": "bad-kind",
            "title": "Bad",
            "starts_at": now,
            "ends_at": now + 100,
            "effects": [{"kind": "not_a_real_kind", "mult": 2.0}],
        },
        content_type="application/json",
    )
    assert bad.status_code == 400
    bad_body = bad.get_json()
    assert bad_body["ok"] is False
    assert "unknown_effect_kind" in str(bad_body.get("error") or "")

    deleted = client.delete(f"/api/admin/events/{event_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["ok"] is True


def test_admin_panel_has_events_tab(events_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    ok_a, _, admin_info = create_user(f"adm_tab_{uuid.uuid4().hex[:6]}", "adminpass123", is_admin=1)
    assert ok_a
    with client.session_transaction() as sess:
        sess["user_id"] = int(admin_info["id"])
    res = client.get("/admin")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'data-admin-tab="events"' in html
    assert 'data-admin-panel="events"' in html
