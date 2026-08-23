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
    assert "+100% Produktion" in summaries
    assert "−25% Expeditions-Haltezeit" in summaries
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
    assert effect_summary_short([{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}], locale="en") == ["+100% Production"]

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


def test_shop_discount_bps_and_max_with_promo(events_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from game.server_events import (
        KIND_SHOP_DISCOUNT_BPS,
        active_shop_discount_bps,
        create_event,
        clear_factor_cache,
        effect_summary_short,
    )
    from game.shop import ensure_catalog_seeded, serialize_cart_for_client
    from game.shop_promos import create_campaign_code

    uid = _player()
    now = int(time.time())
    create_event(
        slug="shop-sale",
        title="Shop Sale",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[{"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 2000}],
    )
    clear_factor_cache()
    assert active_shop_discount_bps(now=float(now)) == 2000
    assert "Shop −20%" in effect_summary_short(
        [{"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 2000}]
    )

    conn = db()
    ensure_catalog_seeded(conn)
    conn.commit()
    # Pick any catalog sku with price
    row = conn.execute(
        "SELECT sku, price_cents FROM shop_products WHERE active = 1 AND price_cents > 100 LIMIT 1;"
    ).fetchone()
    assert row is not None
    sku = str(row["sku"])
    list_cents = int(row["price_cents"])

    cart_event = serialize_cart_for_client(
        uid, [{"sku": sku, "qty": 1}], conn=conn
    )
    assert cart_event["ok"] is True
    assert cart_event["list_cents"] == list_cents
    assert cart_event["discount_cents"] == list_cents * 2000 // 10000
    assert cart_event["promo"] and cart_event["promo"].get("source") == "server_event"

    ok, reason, promo = create_campaign_code(
        conn=conn, code=f"SALE{uuid.uuid4().hex[:6].upper()}", discount_bps=1000
    )
    assert ok, reason
    conn.commit()
    # Event 20% > promo 10% → event wins
    cart_max = serialize_cart_for_client(
        uid, [{"sku": sku, "qty": 1}], conn=conn, promo_code=promo["code"]
    )
    assert cart_max["discount_cents"] == list_cents * 2000 // 10000
    assert cart_max["promo"].get("source") == "server_event"

    # Stronger promo wins
    ok2, reason2, promo2 = create_campaign_code(
        conn=conn, code=f"BIG{uuid.uuid4().hex[:6].upper()}", discount_bps=3000
    )
    assert ok2, reason2
    conn.commit()
    cart_promo = serialize_cart_for_client(
        uid, [{"sku": sku, "qty": 1}], conn=conn, promo_code=promo2["code"]
    )
    assert cart_promo["discount_cents"] == list_cents * 3000 // 10000
    assert cart_promo["promo"].get("source") == "promo"
    conn.close()


def test_build_research_time_speed_in_effect_resolver(events_db):
    from game.effects.effect_resolver import clear_effect_resolver_cache, get_effect_resolver
    from game.server_events import (
        KIND_BUILD_TIME_SPEED,
        KIND_RESEARCH_TIME_SPEED,
        clear_factor_cache,
        create_event,
    )

    uid = _player()
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    clear_effect_resolver_cache()
    clear_factor_cache()
    base = get_effect_resolver(uid, conn=conn, planet=planet, force_refresh=True)
    base_build = float(base.get_modifiers()["build_time_speed"])
    base_research = float(base.get_modifiers()["research_time_speed"])

    now = int(time.time())
    create_event(
        slug="build-rush",
        title="Build Rush",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[
            {"kind": KIND_BUILD_TIME_SPEED, "mult": 1.25},
            {"kind": KIND_RESEARCH_TIME_SPEED, "mult": 1.25},
        ],
        conn=conn,
    )
    clear_factor_cache()
    clear_effect_resolver_cache()
    boosted = get_effect_resolver(uid, conn=conn, planet=planet, force_refresh=True)
    mods = boosted.get_modifiers()
    assert float(mods["build_time_speed"]) == pytest.approx(base_build * 1.25, rel=1e-6)
    assert float(mods["research_time_speed"]) == pytest.approx(base_research * 1.25, rel=1e-6)
    conn.close()


def test_server_event_presets_are_locale_key_only():
    import json
    from pathlib import Path

    from game.server_events import EVENT_PRESETS, list_presets

    assert EVENT_PRESETS
    assert all("title" not in preset for preset in EVENT_PRESETS.values())
    title_keys = {str(preset.get("title_key") or "") for preset in EVENT_PRESETS.values()}
    assert all(key.startswith("server_event_preset_") for key in title_keys)
    assert len(title_keys) == len(EVENT_PRESETS)

    root = Path(__file__).resolve().parents[1]
    expected_effect_keys = {
        "server_event_scheduled_fallback",
        "server_event_effect_shop_discount",
        "server_event_effect_production",
        "server_event_effect_expedition_hold",
        "server_event_effect_build_speed",
        "server_event_effect_research_speed",
        "server_event_effect_asteroid_spawn",
        "server_event_effect_world_boss_spawn",
        "server_event_effect_inactive_farm",
    }
    for locale in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads((root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        assert title_keys <= set(data)
        assert expected_effect_keys <= set(data)
        assert all(str(data[key]).strip() for key in title_keys | expected_effect_keys)

    catalog = list_presets()
    assert len(catalog) == len(EVENT_PRESETS)
    assert all(p.get("title") and p.get("title_key") for p in catalog)


def test_server_event_effect_summary_localizes_all_effect_kinds():
    from game.server_events import (
        KIND_ASTEROID_SPAWN_MULT,
        KIND_BUILD_TIME_SPEED,
        KIND_EXPEDITION_HOLD_MULT,
        KIND_INACTIVE_FARM_MULT,
        KIND_PRODUCTION_MULT,
        KIND_RESEARCH_TIME_SPEED,
        KIND_SHOP_DISCOUNT_BPS,
        KIND_WORLD_BOSS_SPAWN_MULT,
        effect_summary_short,
    )

    effects = [
        {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
        {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
        {"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 2000},
        {"kind": KIND_BUILD_TIME_SPEED, "mult": 1.25},
        {"kind": KIND_RESEARCH_TIME_SPEED, "mult": 1.25},
        {"kind": KIND_ASTEROID_SPAWN_MULT, "mult": 2.0},
        {"kind": KIND_WORLD_BOSS_SPAWN_MULT, "mult": 2.0},
        {"kind": KIND_INACTIVE_FARM_MULT, "mult": 3.0},
    ]
    en = effect_summary_short(effects, locale="en")
    de = effect_summary_short(effects, locale="de")
    assert "+100% Production" in en
    assert "−25% Expedition Hold" in en
    assert "+100% Produktion" in de
    assert "−25% Expeditions-Haltezeit" in de
    assert "Asteroiden-Spawns ×2" in de
    assert en != de


def test_server_event_preset_title_key_and_custom_title_compatibility(events_db):
    from game.server_events import active_events_banner, apply_preset, create_event

    now = int(time.time())
    result, err = apply_preset(
        "double_production_24h",
        starts_at=now - 10,
        ends_at=now + 3600,
        now=float(now),
    )
    assert err is None, err
    assert result and result["event"]
    preset_slug = str(result["event"]["slug"])

    custom, custom_err = create_event(
        slug=f"custom-{uuid.uuid4().hex[:8]}",
        title="Community Surprise",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 1.1}],
    )
    assert custom_err is None, custom_err
    assert custom

    banner_de = active_events_banner(now=float(now), locale="de")
    preset_row = next(row for row in banner_de if row.get("slug") == preset_slug)
    custom_row = next(row for row in banner_de if row.get("slug") == custom["slug"])
    assert preset_row["title_key"] == "server_event_preset_double_production_24h"
    assert preset_row["title"] == "Doppelte Produktion"
    assert custom_row["title_key"] == ""
    assert custom_row["title"] == "Community Surprise"


def test_apply_preset_weekend_and_list(events_db):
    from game.server_events import apply_preset, list_presets, serialize_active_events

    presets = list_presets()
    ids = {p["id"] for p in presets}
    assert "weekend_prod_expo" in ids
    assert "shop_sale_20_48h" in ids
    assert "mega_weekend" in ids

    now = time.time()
    result, err = apply_preset(
        "weekend_prod_expo",
        created_by=1,
        tz_offset_minutes=120,
        now=now,
    )
    assert err is None, err
    assert result and result["event"]
    assert result["event"]["slug"].startswith("weekend-prod-expo")
    clear_factor_cache()
    active = serialize_active_events(now=now)
    assert float(active["production_mult"]) == pytest.approx(2.0)
    assert float(active["expedition_hold_mult"]) == pytest.approx(0.75)


def test_apply_preset_world_boss_dispatch(events_db):
    from game.server_events import apply_preset
    from game.world_boss import list_active_events as list_wb, world_boss_schema_ready

    conn = db()
    assert world_boss_schema_ready(conn)
    result, err = apply_preset(
        "world_boss_leviathan",
        created_by=1,
        force_world_boss=True,
        conn=conn,
    )
    assert err is None, err
    assert result is not None
    assert result["event"] is None
    assert result["actions"]
    assert result["actions"][0]["ok"] is True
    assert result["actions"][0]["type"] == "spawn_world_boss"
    active = list_wb(conn=conn)
    assert any(str(e.get("boss_key")) == "ancient_leviathan" for e in active)
    conn.close()


def test_admin_preset_apply_api(events_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()

    ok_a, _, admin_info = create_user(f"adm_pre_{uuid.uuid4().hex[:6]}", "adminpass123", is_admin=1)
    assert ok_a
    admin_id = int(admin_info["id"])
    ensure_player_and_homeworld(admin_id)

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id

    listed = client.get("/api/admin/events/presets")
    assert listed.status_code == 200
    body = listed.get_json()
    assert body["ok"] is True
    assert any(p["id"] == "double_production_24h" for p in body["presets"])

    applied = client.post(
        "/api/admin/events/presets/double_production_24h/apply",
        json={"tz_offset_minutes": 0},
        content_type="application/json",
    )
    assert applied.status_code == 200
    ab = applied.get_json()
    assert ab["ok"] is True
    assert ab["event"]["slug"].startswith("double-production")
    assert float(ab.get("event", {}).get("effects", [{}])[0].get("mult") or 0) == pytest.approx(2.0)

    events = client.get("/api/admin/events")
    eb = events.get_json()
    assert eb["ok"] is True
    assert "presets" in eb
    assert float(eb["active"]["production_mult"]) == pytest.approx(2.0)


def test_admin_panel_has_preset_gallery(events_db, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    ok_a, _, admin_info = create_user(f"adm_gal_{uuid.uuid4().hex[:6]}", "adminpass123", is_admin=1)
    assert ok_a
    with client.session_transaction() as sess:
        sess["user_id"] = int(admin_info["id"])
    res = client.get("/admin")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="admin-events-preset-gallery"' in html
    assert 'id="admin-events-live-cards"' in html
    assert 'id="admin-events-compose-wrap"' in html
    assert "admin-events-preset-grid" in html
    assert "admin-events-block" in html
    assert "admin-event-shop-bps" in html
    admin_js = (Path(__file__).resolve().parents[1] / "static" / "admin.js").read_text(
        encoding="utf-8"
    )
    assert "events-preset-apply" in admin_js
    assert "applyAdminEventPreset" in admin_js
    assert "admin-events-live-cards" in admin_js
    assert "next_window" in admin_js
    assert "openEventsCompose" in admin_js
    assert "admin-events-preset-tile" in admin_js
    assert "col-st" in admin_js
    assert "<table>" in admin_js or "<table>`" in admin_js or "tbody>" in admin_js


def test_schedule_schema_and_seed(events_db):
    from game.server_events import list_schedules, schedule_schema_ready

    conn = db()
    assert schedule_schema_ready(conn)
    schedules = list_schedules(conn=conn)
    assert len(schedules) >= 5
    ids = {s["preset_id"] for s in schedules}
    assert "weekend_prod_expo" in ids
    assert "asteroid_storm_48h" in ids
    # Live-safe: seeds must not auto-fire until an admin enables them.
    assert all(s["enabled"] is False for s in schedules if s["id"] <= 5)
    conn.close()


def test_materialize_does_not_touch_active_events(events_db):
    from game.server_events import (
        KIND_PRODUCTION_MULT,
        clear_factor_cache,
        create_event,
        list_events,
        list_schedules,
        materialize_schedule,
        tick_schedules,
    )

    now = int(time.time())
    existing, err = create_event(
        slug="keep-alive-prod",
        title="Keep Alive",
        starts_at=now - 60,
        ends_at=now + 7200,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
    )
    assert err is None and existing
    keep_id = int(existing["id"])

    schedules = list_schedules()
    shop = next(s for s in schedules if s["preset_id"] == "shop_sale_20_48h")
    # Force a window around now by materializing with force after tweaking via
    # direct materialize (compute uses Sunday noon — may be outside window).
    # Use asteroid storm daily-style by calling materialize_schedule with force
    # after temporarily ensuring window: create via tick with a custom once rule.
    result, err = materialize_schedule(int(shop["id"]), force=True, now=float(now))
    # May return no_window if not near Sunday — that's ok; still assert keep-alive
    before = {e["id"]: e for e in list_events()}
    assert keep_id in before
    assert before[keep_id]["enabled"] is True
    assert before[keep_id]["slug"] == "keep-alive-prod"

    # Double tick must not disable keep-alive
    tick_schedules(conn=db(), now=float(now))
    clear_factor_cache()
    after = {e["id"]: e for e in list_events()}
    assert keep_id in after
    assert after[keep_id]["enabled"] is True
    assert after[keep_id]["starts_at"] == before[keep_id]["starts_at"]
    assert after[keep_id]["ends_at"] == before[keep_id]["ends_at"]
    if err is None and result and not result.get("skipped") and result.get("event"):
        assert int(result["event"]["id"]) != keep_id


def test_materialize_idempotent(events_db):
    from game.server_events import materialize_schedule
    from game.db import db as gdb

    # Build a once-rule window by inserting a temporary schedule row for "now"
    conn = gdb()
    now = int(time.time())
    hh = f"{time.gmtime(now).tm_hour:02d}:00"
    cur = conn.execute(
        """
        INSERT INTO server_event_schedules (
            name, preset_id, effects_json, rrule_kind, weekdays_json,
            local_start_hhmm, duration_sec, tz_offset_minutes, priority, enabled,
            last_materialized_key, created_at, updated_at
        ) VALUES (?, ?, ?, 'daily', '[]', ?, 3600, 0, 50, 1, '', ?, ?);
        """,
        (
            "Test Daily Asteroid",
            "asteroid_storm_48h",
            "[]",
            hh,
            now,
            now,
        ),
    )
    sid = int(cur.lastrowid)
    conn.commit()

    r1, err1 = materialize_schedule(sid, conn=conn, now=float(now), force=True)
    assert err1 is None, err1
    assert r1 and not r1.get("skipped")
    assert r1.get("event")
    key = r1["materialize_key"]
    event_id = int(r1["event"]["id"])

    r2, err2 = materialize_schedule(sid, conn=conn, now=float(now), force=False)
    assert err2 is None, err2
    assert r2 and r2.get("skipped") is True
    assert r2.get("materialize_key") == key

    # Existing event row still present exactly once for that materialization
    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM server_events WHERE id = ?;", (event_id,)
    ).fetchone()
    assert int(rows["c"]) == 1
    conn.close()


def test_world_modifiers_affect_domain_schedules(events_db):
    from game.asteroids import INTER_WAVE_COOLDOWN_SEC, build_schedule_info as ast_info
    from game.server_events import (
        KIND_ASTEROID_SPAWN_MULT,
        KIND_INACTIVE_FARM_MULT,
        KIND_WORLD_BOSS_SPAWN_MULT,
        clear_factor_cache,
        create_event,
    )
    from game.world_boss import INTER_EVENT_COOLDOWN_SEC, build_schedule_info as wb_info

    now = int(time.time())
    create_event(
        slug="chaos-mods",
        title="Chaos Mods",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[
            {"kind": KIND_ASTEROID_SPAWN_MULT, "mult": 2.0},
            {"kind": KIND_WORLD_BOSS_SPAWN_MULT, "mult": 2.0},
            {"kind": KIND_INACTIVE_FARM_MULT, "mult": 3.0},
        ],
    )
    clear_factor_cache()
    conn = db()
    a = ast_info(conn=conn, now=float(now))
    assert float(a["spawn_mult"]) == pytest.approx(2.0)
    assert int(a["inter_wave_cooldown_sec"]) == int(INTER_WAVE_COOLDOWN_SEC / 2)
    assert int(a["max_concurrent"]) >= 15

    w = wb_info(conn=conn, now=float(now))
    assert float(w["spawn_mult"]) == pytest.approx(2.0)
    assert int(w["inter_event_cooldown_sec"]) == int(INTER_EVENT_COOLDOWN_SEC / 2)
    assert int(w["max_concurrent"]) == 3

    from game.inactive_autoplay import INACTIVE_RESOURCE_FLOOR, _ensure_resource_floor

    uid = _player()
    planet = get_context_planet(uid, conn=conn)
    conn.execute(
        "UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0 WHERE id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    floor = _ensure_resource_floor(conn, int(planet["id"]))
    assert floor["metal"] == int(INACTIVE_RESOURCE_FLOOR["metal"] * 3)
    assert floor["crystal"] == int(INACTIVE_RESOURCE_FLOOR["crystal"] * 3)
    assert float(floor["farm_mult"]) == pytest.approx(3.0)
    conn.close()


def test_admin_schedule_api(events_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    ok_a, _, admin_info = create_user(f"adm_sch_{uuid.uuid4().hex[:6]}", "adminpass123", is_admin=1)
    assert ok_a
    admin_id = int(admin_info["id"])
    ensure_player_and_homeworld(admin_id)
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id

    listed = client.get("/api/admin/events")
    body = listed.get_json()
    assert body["ok"] is True
    assert "schedules" in body
    assert len(body["schedules"]) >= 1
    assert "next_window" in body["schedules"][0]
    sid = int(body["schedules"][0]["id"])

    toggled = client.patch(
        f"/api/admin/events/schedules/{sid}",
        json={"enabled": False},
        content_type="application/json",
    )
    assert toggled.status_code == 200
    assert toggled.get_json()["schedule"]["enabled"] is False

    client.patch(
        f"/api/admin/events/schedules/{sid}",
        json={"enabled": True},
        content_type="application/json",
    )

    html = client.get("/admin").get_data(as_text=True)
    assert 'id="admin-events-schedule-list"' in html
    assert 'id="admin-events-live"' in html
    assert "admin-events-block" in html
    assert "admin-events-schedule-table" in html
    assert "admin-events-preset-grid" in html
    assert "gc-overflow-visible" not in html.split('id="admin-tab-events"')[1].split("</section>")[0]
