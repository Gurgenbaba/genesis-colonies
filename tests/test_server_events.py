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


def test_login_calendar_marks_event_days(events_db):
    """Streak-day UTC buckets overlapping server events get event:true; claim status unchanged."""
    from game.login_rewards import day_bucket, serialize_for_client as lr_serialize

    uid = _player()
    now = float(int(time.time()))
    today = day_bucket(now)
    day_start = today * 86400
    create_event(
        slug="cal-weekend",
        title="Calendar Weekend",
        starts_at=day_start,
        ends_at=day_start + 2 * 86400,
        effects=[
            {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
            {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
        ],
    )
    clear_factor_cache()
    conn = db()
    payload = lr_serialize(uid, conn=conn, now=now, include_calendar=True)
    assert payload.get("ready") is True
    assert payload.get("available") is True
    assert payload.get("next_day") == 1
    days = {int(d["day"]): d for d in payload.get("days") or []}
    assert days[1]["status"] == "claimable"
    assert days[1]["event"] is True
    assert days[1]["day_bucket"] == today
    summaries = days[1]["events"][0]["effects_summary"]
    assert any("Prod" in s for s in summaries)
    assert any("Hold" in s for s in summaries)
    # Tomorrow's locked day still in the 2-day window
    assert days[2]["status"] == "locked"
    assert days[2]["event"] is True
    # Far future locked day outside window
    assert days[10]["status"] == "locked"
    assert days[10]["event"] is False
    assert isinstance(payload.get("active_server_events"), list)
    assert any(e.get("slug") == "cal-weekend" for e in payload["active_server_events"])
    banner = payload["active_server_events"][0]
    assert "effects_summary" in banner
    assert banner.get("kind") == "server_event"


def test_active_events_banner_and_overview_live_events(events_db):
    """Overview status must surface active server events via live_events."""
    from game.overview_page import build_overview_live_events
    from game.server_events import active_events_banner, effect_summary_short

    now = float(int(time.time()))
    create_event(
        slug="ov-boost",
        title="Overview Boost",
        starts_at=int(now) - 60,
        ends_at=int(now) + 3600,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
    )
    clear_factor_cache()
    conn = db()
    banner = active_events_banner(now=now, conn=conn)
    assert len(banner) >= 1
    assert banner[0]["slug"] == "ov-boost"
    assert banner[0]["href"] == "login_rewards_view"
    assert effect_summary_short([{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}]) == ["+100% Prod"]

    live = build_overview_live_events(conn=conn, now=now)
    assert any(e.get("slug") == "ov-boost" and e.get("kind") == "server_event" for e in live)
    conn.close()


def test_overview_live_events_template_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    overview = (root / "templates" / "overview.html").read_text(encoding="utf-8")
    rail = (root / "templates" / "partials" / "header_icon_rail.html").read_text(
        encoding="utf-8"
    )
    main = (root / "static" / "main.js").read_text(encoding="utf-8")
    assert "data-overview-live-events" not in overview
    assert "data-header-live-events" in rail
    assert 'data-nav-badge="live_events"' in rail
    assert "bindHeaderLiveEventsOnce" in main
    assert "patchHeaderLiveEvents" in main
    assert "resolveLiveEventsFromGameState" in main
    assert 'inventory_view' in main
    assert "overview_live_events_goto_inventory" in main
    assert "overview_live_events_group_resources" in main
    assert "gc-header-live-events-group" in main
    assert "_normalize_live_event_groups" in (
        root / "game" / "overview_page.py"
    ).read_text(encoding="utf-8")
    hud = main.split("function applyHudOnlyGameState(data, reason, opts)")[1].split(
        "function applyGameStateData"
    )[0]
    assert "syncLiveOpsFromGameState(data, reason)" in hud
    sync = main.split("function syncLiveOpsFromGameState(data, reason)")[1].split(
        "function _formatLiveEventEta"
    )[0]
    assert "resolveLiveEventsFromGameState(data)" in sync
    assert "events !== null" in sync
    boot = main.split("function bootstrapHudFromDom()")[1].split(
        "GC.bootstrapHudFromDom = bootstrapHudFromDom"
    )[0]
    assert "syncLiveOpsFromGameState(boot, \"ssr_hud_boot\")" in boot or (
        "syncLiveOpsFromGameState(boot, 'ssr_hud_boot')" in boot
    )


def test_build_overview_live_events_opens_own_conn(events_db):
    """Owner must work without an injected conn (SSR / boot paths)."""
    from game.overview_page import build_overview_live_events

    now = float(int(time.time()))
    create_event(
        slug="own-conn-boost",
        title="Own Conn Boost",
        starts_at=int(now) - 60,
        ends_at=int(now) + 3600,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
    )
    clear_factor_cache()
    live = build_overview_live_events(now=now)
    assert any(e.get("slug") == "own-conn-boost" for e in live)


def test_overview_live_events_include_player_boosters(events_db):
    """Timed inventory boosters appear in the Live Events rail with remaining time."""
    from game.db import commit
    from game.inventory import grant_inventory_item
    from game.inventory_boosters import activate_inventory_booster, boosters_schema_ready
    from game.models import create_user
    from game.overview_page import build_overview_live_events

    ok, _reason, user = create_user(f"le_boost_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    uid = int(user["id"])
    now = float(int(time.time()))
    conn = db()
    try:
        assert boosters_schema_ready(conn)
        grant_inventory_item(uid, "booster_production_25", 1, conn=conn)
        effect = activate_inventory_booster(uid, "booster_production_25", conn=conn, now=now)
        assert effect is not None
        commit(conn)
        live = build_overview_live_events(conn=conn, now=now, user_id=uid, locale="de")
        boosters = [e for e in live if e.get("kind") == "booster"]
        assert boosters, live
        row = boosters[0]
        assert row.get("href") == "inventory_view"
        assert int(row.get("remaining_sec") or 0) > 0
        assert int(row.get("ends_at") or 0) > int(now)
        assert row.get("effects_summary")
        assert row.get("title") or row.get("title_key")
        assert row.get("group") == "resources"
        assert row.get("affected_domain") == "production"
        assert row.get("title_key") == "overview_live_events_resources_prod"
        # One summarized production card — not N flat tier rows.
        assert len([b for b in boosters if b.get("affected_domain") == "production"]) == 1
    finally:
        conn.close()


def test_overview_live_events_group_order_resources_first(events_db):
    """Resource boosts sort under Ressourcen before world/other appends."""
    from game.db import commit
    from game.inventory import grant_inventory_item
    from game.inventory_boosters import activate_inventory_booster
    from game.models import create_user
    from game.overview_page import build_overview_live_events

    ok, _reason, user = create_user(f"le_grp_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    uid = int(user["id"])
    now = float(int(time.time()))
    conn = db()
    try:
        create_event(
            slug=f"expo_{uuid.uuid4().hex[:6]}",
            title="Expo Hold",
            starts_at=int(now) - 60,
            ends_at=int(now) + 3600,
            effects=[{"kind": "expedition_hold_mult", "mult": 0.75}],
            enabled=True,
            conn=conn,
        )
        grant_inventory_item(uid, "booster_production_25", 1, conn=conn)
        assert activate_inventory_booster(uid, "booster_production_25", conn=conn, now=now)
        commit(conn)
        live = build_overview_live_events(conn=conn, now=now, user_id=uid, locale="de")
        assert live
        groups = [str(e.get("group") or "") for e in live]
        assert "resources" in groups
        assert "events" in groups
        first_res = next(i for i, g in enumerate(groups) if g == "resources")
        first_events = next(i for i, g in enumerate(groups) if g == "events")
        assert first_res < first_events, groups
        prod = [e for e in live if e.get("kind") == "booster" and e.get("affected_domain") == "production"]
        assert len(prod) == 1
        assert prod[0].get("group") == "resources"
    finally:
        conn.close()
