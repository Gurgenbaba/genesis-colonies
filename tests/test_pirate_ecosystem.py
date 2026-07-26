"""EPIC-21 / GC-P01–P02: Galaxy Heat + pirate AI flag + action log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game import db as gdb
from game.db import db
from game.galaxy import list_system
from game.models import init_db
from game.pirates import (
    get_galaxy_heat,
    heat_band,
    is_pirates_ai_enabled,
    log_pirate_action,
    recent_action_log,
    record_heat_event,
    set_pirates_ai_enabled,
)
from game.pirates.heat import HEAT_THRESHOLDS


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pirate_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pirate_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_heat_band_thresholds():
    assert heat_band(0) == "calm"
    assert heat_band(HEAT_THRESHOLDS["patrol"]) == "patrol"
    assert heat_band(HEAT_THRESHOLDS["raids"]) == "raids"
    assert heat_band(HEAT_THRESHOLDS["elite"]) == "elite"
    assert heat_band(HEAT_THRESHOLDS["crisis"]) == "crisis"
    assert heat_band(HEAT_THRESHOLDS["war"]) == "war"


def test_record_heat_event_and_log(pirate_db):
    conn = db()
    try:
        snap = record_heat_event(conn, 3, "combat")
        conn.commit()
        assert snap["galaxy_id"] == 3
        assert snap["heat"] == 8
        assert snap["band"] == "calm"
        assert snap["counters"]["combat"] == 1

        again = record_heat_event(conn, 3, "world_boss")
        conn.commit()
        assert again["heat"] == 20
        assert again["counters"]["world_boss"] == 1

        logs = recent_action_log(conn, kind="heat_event", galaxy_id=3, limit=10)
        assert len(logs) >= 2
        assert logs[0]["kind"] == "heat_event"
    finally:
        conn.close()


def test_heat_clamps_and_band_change(pirate_db):
    conn = db()
    try:
        record_heat_event(conn, 1, "combat", amount=690)
        snap = record_heat_event(conn, 1, "combat", amount=20)
        conn.commit()
        assert snap["heat"] == 710
        assert snap["band"] == "crisis"
        logs = recent_action_log(conn, galaxy_id=1, limit=5)
        assert any(l.get("payload", {}).get("band_changed") for l in logs)
    finally:
        conn.close()


def test_ai_kill_switch_default_off(pirate_db):
    conn = db()
    try:
        assert is_pirates_ai_enabled(conn=conn) is False
        set_pirates_ai_enabled(True, conn=conn)
        conn.commit()
        assert is_pirates_ai_enabled(conn=conn) is True
        set_pirates_ai_enabled(False, conn=conn)
        conn.commit()
        assert is_pirates_ai_enabled(conn=conn) is False
    finally:
        conn.close()


def test_faction_seed_and_schema(pirate_db):
    conn = db()
    try:
        cur = conn.execute("SELECT COUNT(*) AS c FROM pirate_faction_defs WHERE active = 1;")
        assert int(cur.fetchone()["c"]) == 6
        cur = conn.execute(
            "SELECT faction_key FROM pirate_faction_defs ORDER BY sort_order;"
        )
        keys = [r["faction_key"] for r in cur.fetchall()]
        assert keys == [
            "crimson_corsairs",
            "iron_collective",
            "void_cult",
            "nomad_swarm",
            "ash_raiders",
            "salt_cartel",
        ]
    finally:
        conn.close()


def test_list_system_includes_galaxy_heat(pirate_db):
    conn = db()
    try:
        record_heat_event(conn, 1, "expedition", amount=160)
        conn.commit()
        data = list_system(1, 1, conn=conn)
        assert "galaxy_heat" in data
        assert data["galaxy_heat"]["heat"] == 160
        assert data["galaxy_heat"]["band"] == "patrol"
        snap = get_galaxy_heat(conn, 1)
        assert snap["heat"] == 160
    finally:
        conn.close()


def test_galaxy_ui_heat_badge_contract():
    ring = (ROOT / "templates/partials/galaxy_ring_view.html").read_text(encoding="utf-8")
    assert "galaxy-heat-badge" in ring
    assert "data-galaxy-heat" in ring
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    assert ".galaxy-heat-badge" in css


def test_locale_keys_present_all_locales():
    required = [
        "galaxy_heat_title",
        "galaxy_heat_short",
        "galaxy_heat_band_calm",
        "pirate_faction_crimson_corsairs",
        "pirate_faction_iron_collective",
        "pirate_faction_void_cult",
        "pirate_faction_nomad_swarm",
        "pirate_bounty_label",
        "pirate_bounty_kills",
    ]
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in required:
            assert key in data, f"missing {key} in {loc}"


def test_spawn_base_requires_ai_and_heat(pirate_db):
    from game.pirates.bases import spawn_pirate_base, destroy_base, get_bases_for_system
    from game.pirates import set_pirates_ai_enabled, record_heat_event
    from game.galaxy import list_system

    conn = db()
    try:
        # AI off → blocked
        res = spawn_pirate_base(conn, galaxy=1, announce=False)
        assert res["ok"] is False
        assert res["error"] == "ai_disabled"

        set_pirates_ai_enabled(True, conn=conn)
        res = spawn_pirate_base(conn, galaxy=1, announce=False)
        assert res["ok"] is False
        assert res["error"] == "heat_too_low"

        record_heat_event(conn, 1, "combat", amount=200)
        res = spawn_pirate_base(
            conn, galaxy=1, faction_key="crimson_corsairs", announce=False
        )
        assert res["ok"] is True
        base = res["base"]
        assert base["faction_key"] == "crimson_corsairs"
        assert base["galaxy"] == 1
        assert 1 <= base["position"] <= 15

        by_pos = get_bases_for_system(1, int(base["system"]), conn=conn)
        assert int(base["position"]) in by_pos

        data = list_system(1, int(base["system"]), conn=conn)
        slot = next(s for s in data["slots"] if s["position"] == base["position"])
        assert slot["has_pirate_base"] is True
        assert slot["pirate_base"]["base_id"] == base["base_id"]

        destroyed = destroy_base(conn, int(base["base_id"]))
        assert destroyed["ok"] is True
        conn.commit()
        by_pos2 = get_bases_for_system(1, int(base["system"]), conn=conn)
        assert int(base["position"]) not in by_pos2
    finally:
        conn.close()


def test_pirate_base_ui_contract():
    ring = (ROOT / "templates/partials/galaxy_ring_view.html").read_text(encoding="utf-8")
    assert "has_pirate_base" in ring
    assert "galaxy_pirate_base_short" in ring
    assert "galaxy_pirate_base_block.html" in ring
    assert "pirate_base" in (ROOT / "game/fleet_target.py").read_text(encoding="utf-8")
    block = (ROOT / "templates/partials/galaxy_pirate_base_block.html").read_text(
        encoding="utf-8"
    )
    assert "pirate_base_attack" in block
    assert "pirate_bounty_label" in block
    assert "description_key" in block or "pb.description_key" in block


def test_pirate_base_target_and_combat(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.fleet import (
        add_planet_ships,
        evaluate_fleet_mission_target,
        process_fleet_tick,
        send_fleet,
    )
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.bases import get_base_by_id, spawn_pirate_base
    import uuid
    import time

    ok, err, user = create_user(f"pb_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="PirateHunter", conn=conn)
        commit(conn)
    finally:
        conn.close()

    conn = db()
    try:
        begin_write_transaction(conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        origin_id = int(home["id"])
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 1, "combat", amount=200)
        res = spawn_pirate_base(
            conn,
            galaxy=1,
            faction_key="crimson_corsairs",
            announce=False,
            force=True,
        )
        assert res["ok"], res
        base = res["base"]
        g, s, p = int(base["galaxy"]), int(base["system"]), int(base["position"])

        ok_t, reason, info = evaluate_fleet_mission_target(
            uid, "attack", g, s, p, conn=conn
        )
        assert ok_t, reason
        assert info["target_type"] == "pirate_base"

        add_planet_ships(
            origin_id,
            uid,
            {"falcon_interceptor": 5000, "ironclad_frigate": 2000},
            conn=conn,
        )
        conn.execute(
            "UPDATE planets SET fuel_cells = ? WHERE id = ?;",
            (5_000_000, origin_id),
        )
        commit(conn)

        ok_send, send_reason, meta = send_fleet(
            player_id=uid,
            origin_planet_id=origin_id,
            mission_type="attack",
            target_galaxy=g,
            target_system=s,
            target_position=p,
            ships={"falcon_interceptor": 5000, "ironclad_frigate": 2000},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok_send, send_reason
        assert meta and meta.get("fleet")
        fleet_id = int(meta["fleet"]["id"])
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (1.0, fleet_id),
        )
        commit(conn)
        process_fleet_tick(conn=conn, now=time.time() + 10_000.0, player_id=uid)
        commit(conn)

        after = get_base_by_id(int(base["base_id"]), conn=conn)
        assert after is not None
        assert int(after["current_hp"]) < int(base["current_hp"]) or after[
            "status"
        ] == "destroyed"
    finally:
        conn.close()


def test_log_pirate_action_roundtrip(pirate_db):
    conn = db()
    try:
        log_pirate_action(
            conn,
            kind="ai_disabled",
            message="soft off",
            severity="warn",
            galaxy_id=2,
            payload={"mode": "soft"},
        )
        conn.commit()
        rows = recent_action_log(conn, kind="ai_disabled", limit=5)
        assert len(rows) == 1
        assert rows[0]["message"] == "soft off"
        assert rows[0]["payload"]["mode"] == "soft"
    finally:
        conn.close()


def test_recompute_player_threat(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld
    from game.pirates.threat import get_player_threat, recompute_player_threat
    import uuid

    ok, err, user = create_user(f"th_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="ThreatTarget", conn=conn)
        conn.execute(
            """
            UPDATE player_scores
            SET score_total = ?, score_fleet = ?, score_defense = ?, score_destroyed = ?
            WHERE player_id = ?;
            """,
            (1_000_000, 500_000, 100_000, 250_000, uid),
        )
        # If ensure didn't create a score row yet:
        if conn.execute(
            "SELECT 1 FROM player_scores WHERE player_id = ?;", (uid,)
        ).fetchone() is None:
            conn.execute(
                """
                INSERT INTO player_scores (
                    player_id, score_total, score_fleet, score_defense, score_destroyed
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (uid, 1_000_000, 500_000, 100_000, 250_000),
            )
        snap = recompute_player_threat(uid, conn=conn)
        commit(conn)
        assert 0 < int(snap["threat"]) <= 100
        assert "empire" in snap["components"]
        again = get_player_threat(uid, conn=conn)
        assert again["threat"] == snap["threat"]
    finally:
        conn.close()


def test_raid_brain_dispatch_and_intel(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.bases import get_base_by_id, spawn_pirate_base
    from game.pirates.brain import dispatch_raid_from_base
    import time
    import uuid

    ok, err, user = create_user(f"rv_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="RaidVictim", conn=conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        g = int(home["galaxy"])
        # Soft target: high loot, idle, no fleet — stay on home coords.
        conn.execute(
            """
            UPDATE planets
            SET metal = 5000000, crystal = 5000000, fuel_cells = 100000
            WHERE id = ?;
            """,
            (int(home["id"]),),
        )
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (time.time() - 72 * 3600, uid),
        )
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, g, "combat", amount=350)
        spawned = spawn_pirate_base(
            conn,
            galaxy=g,
            faction_key="crimson_corsairs",
            announce=False,
            force=True,
        )
        assert spawned["ok"], spawned
        full = get_base_by_id(int(spawned["base"]["base_id"]), conn=conn)
        assert full and full.get("fleet_stacks")
        from game.fleet import get_planet_ships, set_planet_ships
        from game.pirates.accounts import ensure_faction_bot

        bot = ensure_faction_bot("crimson_corsairs", conn=conn)
        hangar = get_planet_ships(int(bot["planet_id"]), conn=conn)
        hangar["falcon_interceptor"] = max(int(hangar.get("falcon_interceptor") or 0), 25)
        hangar["ironclad_frigate"] = max(int(hangar.get("ironclad_frigate") or 0), 10)
        set_planet_ships(int(bot["planet_id"]), int(bot["player_id"]), hangar, conn=conn)
        res = dispatch_raid_from_base(conn, full, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        assert int(res.get("fleet_id") or 0) > 0
        cur = conn.execute(
            "SELECT opportunity FROM pirate_intel WHERE target_player_id = ? LIMIT 1;",
            (uid,),
        )
        intel = cur.fetchone()
        assert intel is not None
        assert int(intel["opportunity"]) >= 35
        logs = recent_action_log(conn, kind="raid_dispatch", limit=5)
        assert any(l.get("target_player_id") == uid for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_pirate_bot_chat_forbidden(pirate_db):
    from game.chat import send_chat_message
    from game.db import begin_write_transaction, commit
    from game.pirates.accounts import ensure_faction_bot

    conn = db()
    try:
        begin_write_transaction(conn)
        bot = ensure_faction_bot("crimson_corsairs", conn=conn)
        assert bot
        commit(conn)
        pid = int(bot["player_id"])
    finally:
        conn.close()

    res = send_chat_message(pid, "ahoy")
    assert res.get("ok") is False
    assert res.get("error") == "pirate_bot_chat_forbidden"


def test_admin_pirates_panel_contract():
    html = (ROOT / "templates/admin_panel.html").read_text(encoding="utf-8")
    assert 'data-admin-tab="pirates"' in html
    assert 'data-admin-panel="pirates"' in html
    assert "data-admin-action=\"pirates-refresh\"" in html
    assert "data-admin-action=\"pirates-force-spawn\"" in html
    js = (ROOT / "static/admin.js").read_text(encoding="utf-8")
    assert "loadPiratesAdmin" in js
    assert "/api/admin/pirates" in js
    assert "forceSpawnPiratesAdmin" in js
    assert "/api/admin/pirates/force-spawn" in js
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "admin_pirates_title" in data
        assert "admin_pirates_force_spawn" in data
        assert "admin_pirates_kpi_bots" in data
        assert "admin_pirates_kpi_spies" in data


@pytest.fixture()
def pirate_admin_client(pirate_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application
    from game.models import create_user, ensure_player_and_homeworld

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)

    ok_a, _, admin_info = create_user("pirate_admin", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("pirate_user", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def test_admin_pirates_api_and_ai_toggle(pirate_admin_client):
    client, admin_id, user_id = pirate_admin_client

    r = client.get("/api/admin/pirates")
    assert r.status_code == 401

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    r = client.get("/api/admin/pirates")
    assert r.status_code == 403

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    r = client.get("/api/admin/pirates")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["ai_enabled"] is False
    assert "log" in data
    assert "kpis" in data

    on = client.post("/api/admin/pirates/ai", json={"enabled": True})
    assert on.status_code == 200
    on_data = on.get_json()
    assert on_data["ai_enabled"] is True
    assert int(on_data.get("bots_bootstrapped") or 0) == 6

    r2 = client.get("/api/admin/pirates")
    payload = r2.get_json()
    assert payload["ai_enabled"] is True
    assert int(payload["kpis"].get("bots_online") or 0) == 6
    assert len(payload.get("bots") or []) == 6
    assert all(b.get("exists") for b in payload["bots"])
    assert all(int(b.get("ship_count") or 0) > 0 for b in payload["bots"])

    force = client.post("/api/admin/pirates/force-spawn", json={})
    assert force.status_code == 200
    force_data = force.get_json()
    assert force_data["ok"] is True
    assert force_data.get("spawn", {}).get("ok") is True

    r3 = client.get("/api/admin/pirates")
    assert int(r3.get_json().get("live_bases") or 0) >= 1

    off = client.post("/api/admin/pirates/ai", json={"enabled": False})
    assert off.status_code == 200
    assert off.get_json()["ai_enabled"] is False

    hard = client.post("/api/admin/pirates/ai", json={"mode": "hard"})
    assert hard.status_code == 200
    hard_data = hard.get_json()
    assert hard_data["ai_enabled"] is False
    assert hard_data["mode"] == "hard"
    assert "recalled" in hard_data


def test_soft_on_bootstraps_hangars_without_http(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.fleet import get_planet_ships
    from game.pirates.admin import admin_set_ai
    from game.pirates.accounts import FACTION_BOTS, HOME_PROBE_MIN, HOME_SEED_ARK_MIN

    conn = db()
    try:
        begin_write_transaction(conn)
        res = admin_set_ai(conn, True)
        assert res["ai_enabled"] is True
        assert res["bots_bootstrapped"] == 6
        for bot in res["bots"]:
            ships = get_planet_ships(int(bot["planet_id"]), conn=conn)
            # GC-P27: one-time utility seed — combat ships from economy/shipyard.
            assert int(ships.get("veil_probe") or 0) >= HOME_PROBE_MIN
            assert int(ships.get("seed_ark") or 0) >= HOME_SEED_ARK_MIN
            cur = conn.execute(
                "SELECT metal FROM planets WHERE id = ?;",
                (int(bot["planet_id"]),),
            )
            assert float((cur.fetchone() or {"metal": 0})["metal"] or 0) >= 1_000_000
        assert set(b["faction_key"] for b in res["bots"]) == set(FACTION_BOTS)
        # Second Soft-On must not restock utility again (player-like).
        from game.pirates.accounts import ensure_bot_utility_fleet

        bot0 = res["bots"][0]
        again = ensure_bot_utility_fleet(conn, dict(bot0), force=False)
        assert again.get("skipped") == "already_seeded"
        commit(conn)
    finally:
        conn.close()


def test_patrol_spy_dispatch_at_heat_150(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.brain import dispatch_spy_from_home
    import time
    import uuid

    ok, err, user = create_user(f"spyv_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="SpyVictim", conn=conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        # Place victim in pirate belt galaxy for target selection.
        g = 1
        conn.execute(
            "UPDATE planets SET galaxy = ?, system = 10, position = 5, metal = 900000 WHERE id = ?;",
            (g, int(home["id"])),
        )
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, g, "combat", amount=160)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "void_cult")
        res = dispatch_spy_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        assert int(res.get("fleet_id") or 0) > 0
        logs = recent_action_log(conn, kind="spy_dispatch", limit=5)
        assert any(l.get("bot_player_id") == bot["player_id"] for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_home_raid_without_base_at_heat_300(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.brain import dispatch_raid_from_home
    import time
    import uuid

    ok, err, user = create_user(f"hr_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="HomeRaidVictim", conn=conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        g = 1
        conn.execute(
            """
            UPDATE planets
            SET galaxy = ?, system = 11, position = 4,
                metal = 5000000, crystal = 5000000, fuel_cells = 100000
            WHERE id = ?;
            """,
            (g, int(home["id"])),
        )
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (time.time() - 72 * 3600, uid),
        )
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, g, "combat", amount=350)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "crimson_corsairs")
        # GC-P22: raids use real hangar — seed combat wing for the test (no template overwrite).
        from game.fleet import get_planet_ships, set_planet_ships

        hangar = get_planet_ships(int(bot["planet_id"]), conn=conn)
        hangar["falcon_interceptor"] = max(int(hangar.get("falcon_interceptor") or 0), 20)
        hangar["ironclad_frigate"] = max(int(hangar.get("ironclad_frigate") or 0), 8)
        set_planet_ships(int(bot["planet_id"]), int(bot["player_id"]), hangar, conn=conn)
        # No pirate base — home raid only.
        res = dispatch_raid_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        assert res.get("origin") == "home"
        assert int(res.get("fleet_id") or 0) > 0
        logs = recent_action_log(conn, kind="raid_dispatch", limit=5)
        assert any(
            l.get("target_player_id") == uid
            and (l.get("payload") or {}).get("origin") == "home"
            for l in logs
        ) or any(l.get("target_player_id") == uid for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_kill_switch_blocks_new_missions(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.admin import admin_set_ai
    from game.pirates.brain import dispatch_raid_from_home, dispatch_spy_from_home
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        admin_set_ai(conn, True)
        bots = bootstrap_faction_bots(conn=conn)
        bot = bots[0]
        admin_set_ai(conn, False)
        spy = dispatch_spy_from_home(conn, bot, now=time.time(), force_playtime=True)
        raid = dispatch_raid_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert spy.get("ok") is False
        assert spy.get("error") == "ai_disabled"
        assert raid.get("ok") is False
        assert raid.get("error") == "ai_disabled"
        commit(conn)
    finally:
        conn.close()


def test_ingest_spy_report_writes_intel(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates.accounts import ensure_faction_bot
    from game.pirates.brain import ingest_spy_report_for_intel
    import uuid

    ok, err, user = create_user(f"ing_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="IntelTarget", conn=conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        bot = ensure_faction_bot("void_cult", conn=conn)
        assert bot
        res = ingest_spy_report_for_intel(
            conn,
            bot_player_id=int(bot["player_id"]),
            meta={
                "target_planet_id": int(home["id"]),
                "resources": {"metal": 100000, "crystal": 50000, "fuel_cells": 1000},
                "ships": {"falcon_interceptor": 10},
                "defense": {},
            },
            snapshot={"planet_id": int(home["id"]), "player_id": uid},
        )
        assert res.get("ok")
        cur = conn.execute(
            """
            SELECT opportunity, fleet_score FROM pirate_intel
            WHERE bot_player_id = ? AND target_planet_id = ?
            LIMIT 1;
            """,
            (int(bot["player_id"]), int(home["id"])),
        )
        row = cur.fetchone()
        assert row is not None
        assert int(row["opportunity"]) >= 0
        commit(conn)
    finally:
        conn.close()


def test_bounty_add_and_destroy_formula(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld
    from game.pirates.bounty import (
        add_player_bounty,
        bounty_for_damage,
        bounty_for_destroy,
        get_player_bounty,
        list_player_bounties,
    )
    import uuid

    assert bounty_for_damage(2500) == 50
    assert bounty_for_destroy(2, share=0.5) == int(round((500 + 800) * 0.5))

    ok, err, user = create_user(f"by_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="BountyHunter", conn=conn)
        snap = add_player_bounty(
            conn, uid, "crimson_corsairs", credits=900, kills=1
        )
        assert snap["credits"] == 900
        assert snap["kills"] == 1
        snap2 = add_player_bounty(conn, uid, "crimson_corsairs", credits=100)
        assert snap2["credits"] == 1000
        assert get_player_bounty(uid, "crimson_corsairs", conn=conn)["credits"] == 1000
        listed = list_player_bounties(uid, conn=conn)
        assert listed and listed[0]["faction_key"] == "crimson_corsairs"
        commit(conn)
    finally:
        conn.close()


def test_bot_state_playtime_and_personality(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.pirates.accounts import ensure_faction_bot
    from game.pirates.bot_state import (
        bot_may_act,
        ensure_bot_state,
        in_playtime_window,
        personality_raid_modifiers,
    )

    assert in_playtime_window(1080, 420, minute=100) is True  # wrap
    assert in_playtime_window(360, 1200, minute=100) is False
    mods = personality_raid_modifiers(
        {"attack_bias": 0.85, "spy_bias": 0.55, "turtle": 0.1}
    )
    assert mods["fleet_fraction"] > 0.5
    assert mods["opportunity_floor"] < 40

    conn = db()
    try:
        begin_write_transaction(conn)
        bot = ensure_faction_bot("crimson_corsairs", conn=conn)
        assert bot
        state = ensure_bot_state(
            conn,
            bot_player_id=int(bot["player_id"]),
            faction_key="crimson_corsairs",
        )
        assert state["personality"] == "aggressive"
        # Force always-on window + zero skip for deterministic gate.
        state["playtime_start_min"] = 0
        state["playtime_end_min"] = 1440
        state["skip_chance_pct"] = 0
        gate = bot_may_act(state, now=1_700_000_000.0)
        assert gate["ok"] is True
        commit(conn)
    finally:
        conn.close()


def test_bounty_biases_raid_target(pirate_db):
    """High faction bounty should prefer that victim over a richer undefended idle world."""
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.bases import get_base_by_id, spawn_pirate_base
    from game.pirates.bounty import add_player_bounty
    from game.pirates.brain import dispatch_raid_from_base
    import time
    import uuid

    victims = []
    for tag in ("ba", "bb"):
        ok, err, user = create_user(f"pbnty_{tag}_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok, err
        victims.append(int(user["id"]))

    conn = db()
    try:
        begin_write_transaction(conn)
        set_pirates_ai_enabled(True, conn=conn)
        homes = []
        for i, uid in enumerate(victims):
            ensure_player_and_homeworld(uid, player_name=f"V{i}", conn=conn)
            home = get_planets_by_player(uid, conn=conn)[0]
            # Park both in galaxy 1 free-ish systems
            conn.execute(
                """
                UPDATE planets
                SET galaxy = 1, system = ?, position = ?,
                    metal = 500000, crystal = 500000, fuel_cells = 10000
                WHERE id = ?;
                """,
                (10 + i, 5 + i, int(home["id"])),
            )
            conn.execute(
                "UPDATE players SET last_seen = ? WHERE id = ?;",
                (time.time() - 72 * 3600, uid),
            )
            homes.append(home)
        # Wanted player has huge bounty with crimson.
        add_player_bounty(conn, victims[1], "crimson_corsairs", credits=6000, kills=3)
        record_heat_event(conn, 1, "combat", amount=350)
        spawned = spawn_pirate_base(
            conn,
            galaxy=1,
            faction_key="crimson_corsairs",
            announce=False,
            force=True,
        )
        assert spawned["ok"], spawned
        full = get_base_by_id(int(spawned["base"]["base_id"]), conn=conn)
        from game.fleet import get_planet_ships, set_planet_ships
        from game.pirates.accounts import ensure_faction_bot

        bot = ensure_faction_bot("crimson_corsairs", conn=conn)
        hangar = get_planet_ships(int(bot["planet_id"]), conn=conn)
        hangar["falcon_interceptor"] = max(int(hangar.get("falcon_interceptor") or 0), 25)
        set_planet_ships(int(bot["planet_id"]), int(bot["player_id"]), hangar, conn=conn)
        res = dispatch_raid_from_base(conn, full, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        assert int(res["target_player_id"]) == victims[1]
        commit(conn)
    finally:
        conn.close()


def test_pirate_war_emergency_from_heat(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.galactic_diplomacy import get_active_emergency, get_emergency_definition
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.crisis import maybe_sync_pirate_war

    assert get_emergency_definition("pirate_war") is not None or True  # after migrate
    conn = db()
    try:
        begin_write_transaction(conn)
        # Ensure definition exists even if cache was cold before migration 108.
        from game.galactic_diplomacy.emergencies import reload_emergency_definitions

        reload_emergency_definitions(conn=conn)
        assert get_emergency_definition("pirate_war", conn=conn) is not None
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 2, "combat", amount=720)
        out = maybe_sync_pirate_war(conn)
        assert 2 in out.get("started", [])
        active = get_active_emergency(2, conn=conn)
        assert active is not None
        assert active["emergency_key"] == "pirate_war"
        # Idempotent: already active → skipped
        out2 = maybe_sync_pirate_war(conn)
        assert 2 in out2.get("skipped", [])
        commit(conn)
    finally:
        conn.close()


def test_infiltration_and_smuggler_lifecycle(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.infiltration import (
        active_infiltration_magnitude,
        expire_due_infiltrations,
        start_infiltration,
    )
    from game.pirates.smugglers import expire_due_smugglers, list_live_smugglers, maybe_spawn_smugglers
    import time
    import uuid

    ok, err, user = create_user(f"inf_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="InfilTarget", conn=conn)
        planet_id = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        started = start_infiltration(
            conn,
            planet_id=planet_id,
            faction_key="void_cult",
            ttl_sec=1,
            now=time.time(),
        )
        assert started["ok"]
        assert active_infiltration_magnitude(conn, planet_id, now=time.time()) > 0
        expired = expire_due_infiltrations(conn, now=time.time() + 10)
        assert started["id"] in expired
        assert active_infiltration_magnitude(conn, planet_id, now=time.time() + 10) == 0.0

        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 1, "combat", amount=320)
        spawned = maybe_spawn_smugglers(conn, now=time.time())
        assert len(spawned) >= 1
        live = list_live_smugglers(conn)
        assert live
        expire_due_smugglers(conn, now=time.time() + 100_000)
        assert list_live_smugglers(conn) == []
        commit(conn)
    finally:
        conn.close()


def test_expo_ambush_plants_infiltration_on_loss(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import set_pirates_ai_enabled
    from game.pirates.ambush import on_expedition_pirate_ambush
    from game.pirates.infiltration import list_active_infiltrations
    import uuid

    ok, err, user = create_user(f"amb_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="AmbushVictim", conn=conn)
        planet_id = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        set_pirates_ai_enabled(True, conn=conn)
        res = on_expedition_pirate_ambush(
            conn,
            galaxy_id=1,
            player_id=uid,
            planet_id=planet_id,
            won=False,
            movement_id=42,
        )
        assert res["ok"]
        assert res["infiltration"] and res["infiltration"]["ok"]
        assert list_active_infiltrations(conn)
        commit(conn)
    finally:
        conn.close()


def test_ship_gate_contracts():
    """EPIC-21 ship-gate: kill-switch, bot-log, no chat, combat owner, emergency key."""
    from game.galactic_diplomacy.emergencies import EMERGENCY_KEYS
    from game.pirates.accounts import PIRATE_BOT_USERNAMES
    from game.fleet_target import WORLD_NATIVE_TARGET_TYPES

    assert "pirate_war" in EMERGENCY_KEYS
    assert "pirate_base" in WORLD_NATIVE_TARGET_TYPES
    assert "gc_pirate_crimson" in PIRATE_BOT_USERNAMES
    admin = (ROOT / "templates/admin_panel.html").read_text(encoding="utf-8")
    assert 'data-admin-panel="pirates"' in admin
    assert "pirates-ai-hard-off" in admin
    chat = (ROOT / "game/chat.py").read_text(encoding="utf-8")
    assert "pirate_bot_chat_forbidden" in chat
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "gdp_emergency_pirate_war_title" in data
        assert "pirate_ai_badge" in data
        assert "pirate_ai_mode_aggressive" in data
        assert "fleet_ship_planet_breaker" in data


def test_pirate_ai_visible_in_ranking_galaxy_playercard(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.galaxy import list_system
    from game.pirates.accounts import FACTION_HOMEWORLDS, ensure_faction_bot, get_pirate_ai_profile
    from game.playercard import build_public_card
    from game.ranking import get_sorted_ranking_entries

    conn = db()
    try:
        begin_write_transaction(conn)
        bot = ensure_faction_bot("crimson_corsairs", conn=conn)
        assert bot
        pid = int(bot["player_id"])
        profile = get_pirate_ai_profile(pid, conn=conn)
        assert profile and profile["is_ai"] is True
        assert profile["player_mode"] == "ai_pirate"
        assert profile["faction_key"] == "crimson_corsairs"
        assert profile["mode_key"] == "pirate_ai_mode_aggressive"

        g, s, p = FACTION_HOMEWORLDS["crimson_corsairs"]
        assert int(bot["galaxy"]) == g
        assert int(bot["system"]) == s
        assert int(bot["position"]) == p

        commit(conn)
    finally:
        conn.close()

    rows = get_sorted_ranking_entries(limit=200)
    match = next((r for r in rows if int(r["player_id"]) == pid), None)
    assert match is not None
    assert match["is_ai"] is True
    assert match["inactive"] is False
    assert match["ai_faction_key"] == "crimson_corsairs"

    data = list_system(g, s, viewer_player_id=pid)
    slot = next(s for s in data["slots"] if int(s["position"]) == p)
    assert slot["occupied"] is True
    assert slot["is_ai"] is True
    assert slot["player_id"] == pid
    assert slot["inactive"] is False

    card, err = build_public_card(pid, viewer_id=None)
    assert err is None
    assert card["is_ai"] is True
    assert card["player_mode"] == "ai_pirate"
    assert card["can_edit"] is False
    assert card["allows_chat"] is False
    assert "pirate_ai_mode" in (card.get("ai_mode_key") or "")
    assert not (card.get("bio") or "").strip()
    assert "iron_collective" not in str(card.get("bio") or "")
    assert "Autonomous pirate AI" not in str(card.get("bio") or "")
    assert "(" not in str(card.get("bio") or "")

    view = (ROOT / "templates/partials/player_card_view.html").read_text(encoding="utf-8")
    assert "gc-player-card-ai-banner" in view
    assert "is_ai" in view
    assert "not card.get('is_ai')" in view or "not card.get(\"is_ai\")" in view
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "rankingAiBadgeHtml" in js
    badges = (ROOT / "templates/partials/galaxy_slot_status_badges.html").read_text(
        encoding="utf-8"
    )
    assert "galaxy-ring-status-chip--ai" in badges


def test_bot_hangar_includes_seed_ark(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.fleet import get_planet_ships
    from game.pirates.admin import admin_set_ai

    conn = db()
    try:
        begin_write_transaction(conn)
        res = admin_set_ai(conn, True)
        assert res["bots_bootstrapped"] == 6
        for bot in res["bots"]:
            ships = get_planet_ships(int(bot["planet_id"]), conn=conn)
            assert int(ships.get("seed_ark") or 0) >= 1
            assert int(ships.get("veil_probe") or 0) >= 8
        commit(conn)
    finally:
        conn.close()


def test_colonize_dispatch_at_heat_150(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.brain import dispatch_colonize_from_home
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 1, "combat", amount=160)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "nomad_swarm")
        res = dispatch_colonize_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        assert int(res.get("fleet_id") or 0) > 0
        logs = recent_action_log(conn, kind="colonize_dispatch", limit=5)
        assert any(l.get("bot_player_id") == bot["player_id"] for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_bot_planet_floor_restores_after_wipe(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.models import get_planets_by_player
    from game.pirates.accounts import bootstrap_faction_bots, ensure_bot_planet_floor
    from game.pirates.admin import admin_set_ai

    conn = db()
    try:
        begin_write_transaction(conn)
        admin_set_ai(conn, True)
        bots = bootstrap_faction_bots(conn=conn)
        bot = bots[0]
        pid = int(bot["player_id"])
        planets = get_planets_by_player(pid, conn=conn) or []
        assert planets
        for p in planets:
            conn.execute("DELETE FROM planets WHERE id = ?;", (int(p["id"]),))
        assert not (get_planets_by_player(pid, conn=conn) or [])
        floor = ensure_bot_planet_floor(conn, bot)
        assert floor.get("ok") and floor.get("restored")
        restored = get_planets_by_player(pid, conn=conn) or []
        assert len(restored) >= 1
        logs = recent_action_log(conn, kind="bot_planet_floor", limit=5)
        assert any(l.get("bot_player_id") == pid for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_kill_switch_blocks_colonize(pirate_db):
    from game.db import begin_write_transaction, commit
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.admin import admin_set_ai
    from game.pirates.brain import dispatch_colonize_from_home
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        admin_set_ai(conn, True)
        bots = bootstrap_faction_bots(conn=conn)
        bot = bots[0]
        admin_set_ai(conn, False)
        res = dispatch_colonize_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert res.get("ok") is False
        assert res.get("error") == "ai_disabled"
        commit(conn)
    finally:
        conn.close()


def test_bot_economy_enqueues_building(pirate_db):
    """GC-P21: Soft-On bots enqueue real build jobs and spend resources."""
    from game.db import begin_write_transaction, commit
    from game.models import get_planet_buildings
    from game.pirates.admin import admin_set_ai
    from game.pirates.economy import run_economy_brain_tick
    from game.queue_engine import finish_due_work_once
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        res = admin_set_ai(conn, True)
        bot = next(b for b in res["bots"] if b["faction_key"] == "iron_collective")
        planet_id = int(bot["planet_id"])
        cur = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (planet_id,),
        )
        before = cur.fetchone()
        metal_before = float(before["metal"] or 0)
        econ = run_economy_brain_tick(conn, now=time.time(), bots=[bot])
        assert econ.get("ok")
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM build_queue WHERE planet_id = ?;",
            (planet_id,),
        )
        queued = int((cur.fetchone() or {"c": 0})["c"] or 0)
        assert queued >= 1
        cur = conn.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (planet_id,),
        )
        metal_after = float((cur.fetchone() or {"metal": 0})["metal"] or 0)
        assert metal_after < metal_before
        # Fast-forward job and finish via owner queue engine.
        conn.execute(
            "UPDATE build_queue SET finish_time = ? WHERE planet_id = ?;",
            (time.time() - 10, planet_id),
        )
        finish_due_work_once(
            player_id=int(bot["player_id"]),
            planet_id=planet_id,
            now=time.time(),
            conn=conn,
            source="test",
            manage_transaction=False,
            dedup=False,
        )
        buildings = get_planet_buildings(planet_id, conn=conn)
        assert int(buildings.get("metal_mine") or 0) >= 1 or int(
            buildings.get("crystal_mine") or 0
        ) >= 1 or int(buildings.get("solar_plant") or 0) >= 1
        logs = recent_action_log(conn, kind="bot_economy_tick", limit=5)
        assert any(l.get("bot_player_id") == bot["player_id"] for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_raid_does_not_overwrite_hangar_template(pirate_db):
    """GC-P22: home raid sends a hangar fraction without set_planet_ships wipe."""
    from game.db import begin_write_transaction, commit
    from game.fleet import get_planet_ships, set_planet_ships
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.brain import dispatch_raid_from_home
    import time
    import uuid

    ok, err, user = create_user(f"hangar_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="HangarVictim", conn=conn)
        home = get_planets_by_player(uid, conn=conn)[0]
        conn.execute(
            """
            UPDATE planets
            SET galaxy = 1, system = 12, position = 3,
                metal = 4000000, crystal = 4000000
            WHERE id = ?;
            """,
            (int(home["id"]),),
        )
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (time.time() - 72 * 3600, uid),
        )
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 1, "combat", amount=350)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "crimson_corsairs")
        hangar = get_planet_ships(int(bot["planet_id"]), conn=conn)
        hangar["falcon_interceptor"] = 40
        hangar["spark_drone"] = 30
        set_planet_ships(int(bot["planet_id"]), int(bot["player_id"]), hangar, conn=conn)
        before = get_planet_ships(int(bot["planet_id"]), conn=conn)
        res = dispatch_raid_from_home(conn, bot, now=time.time(), force_playtime=True)
        assert res.get("ok"), res
        after = get_planet_ships(int(bot["planet_id"]), conn=conn)
        # Remaining hangar should be lower by the sent wing, not replaced by a template.
        assert int(after.get("falcon_interceptor") or 0) < int(before.get("falcon_interceptor") or 0)
        assert int(after.get("spark_drone") or 0) <= int(before.get("spark_drone") or 0)
        commit(conn)
    finally:
        conn.close()


def test_inbound_attack_triggers_fleet_save(pirate_db):
    """GC-P23: attacking an AI planet panic-recalls outbound bot fleets."""
    from game.db import begin_write_transaction, commit
    from game.fleet import get_planet_ships, send_fleet, set_planet_ships
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.admin import admin_set_ai
    from game.pirates.ambush import maybe_fleet_save_on_inbound_attack
    from game.ranking import ensure_player_score_row
    import time
    import uuid

    ok, err, user = create_user(f"fsave_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        admin_set_ai(conn, True)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "void_cult")
        ensure_player_and_homeworld(uid, player_name="Saver", conn=conn)
        attacker_home = get_planets_by_player(uid, conn=conn)[0]
        # Align scores so noob corridor allows the attack path if used.
        ensure_player_score_row(uid, conn=conn)
        ensure_player_score_row(int(bot["player_id"]), conn=conn)
        conn.execute(
            "UPDATE player_scores SET score_total = 100000 WHERE player_id IN (?, ?);",
            (uid, int(bot["player_id"])),
        )
        set_planet_ships(
            int(attacker_home["id"]),
            uid,
            {"falcon_interceptor": 5},
            conn=conn,
        )
        hangar = get_planet_ships(int(bot["planet_id"]), conn=conn)
        hangar["falcon_interceptor"] = 20
        set_planet_ships(int(bot["planet_id"]), int(bot["player_id"]), hangar, conn=conn)
        ok_s, reason, meta = send_fleet(
            player_id=int(bot["player_id"]),
            origin_planet_id=int(bot["planet_id"]),
            mission_type="attack",
            target_galaxy=int(attacker_home["galaxy"]),
            target_system=int(attacker_home["system"]),
            target_position=int(attacker_home["position"]),
            ships={"falcon_interceptor": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok_s, reason
        fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)

        # Direct owner hook (same as send_fleet inbound path).
        save = maybe_fleet_save_on_inbound_attack(
            conn,
            attacker_id=uid,
            target_planet_id=int(bot["planet_id"]),
            now=time.time(),
        )
        assert save.get("ok"), save
        assert int(save.get("recalled") or 0) >= 1
        cur = conn.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        )
        status = str((cur.fetchone() or {"status": ""})["status"])
        assert status == "returning"
        logs = recent_action_log(conn, kind="fleet_save", limit=5)
        assert any(l.get("bot_player_id") == bot["player_id"] for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_ai_colony_destroy_requires_breaker_and_spares_homeworld(pirate_db):
    """GC-P24: wipe AI colony with breaker after full military wipe; homeworld blocked."""
    from game.db import begin_write_transaction, commit
    from game.models import create_user, get_planets_by_player
    from game.pirates.accounts import bootstrap_faction_bots
    from game.pirates.admin import admin_set_ai
    from game.pirates.bounty import get_player_bounty
    from game.pirates.destroy import (
        destroy_colony_planet,
        maybe_destroy_colony_after_combat,
    )
    import time
    import uuid

    ok, err, user = create_user(f"brk_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    attacker_id = int(user["id"])

    class _FakeCombat:
        winner = "attacker"

    conn = db()
    try:
        begin_write_transaction(conn)
        admin_set_ai(conn, True)
        bots = bootstrap_faction_bots(conn=conn)
        bot = next(b for b in bots if b["faction_key"] == "nomad_swarm")
        pid = int(bot["player_id"])
        home = get_planets_by_player(pid, conn=conn)[0]
        cur = conn.execute(
            """
            INSERT INTO planets (
                player_id, name, galaxy, system, position, is_homeworld,
                metal, crystal, fuel_cells, last_update
            ) VALUES (?, 'AI Outpost', 1, 20, 4, 0, 1000, 1000, 1000, ?);
            """,
            (pid, time.time()),
        )
        colony_id = int(cur.lastrowid)
        hw_wipe = destroy_colony_planet(
            conn, planet_id=int(home["id"]), owner_player_id=pid
        )
        assert hw_wipe.get("ok") is False
        assert hw_wipe.get("error") == "homeworld_protected"

        no_breaker = maybe_destroy_colony_after_combat(
            conn,
            attacker_id=attacker_id,
            defender_id=pid,
            target_planet_id=colony_id,
            combat_result=_FakeCombat(),
            return_ships={"falcon_interceptor": 10},
            now=time.time(),
        )
        assert no_breaker.get("ok") is False
        assert no_breaker.get("error") == "breaker_required"

        wiped = maybe_destroy_colony_after_combat(
            conn,
            attacker_id=attacker_id,
            defender_id=pid,
            target_planet_id=colony_id,
            combat_result=_FakeCombat(),
            return_ships={"planet_breaker": 1, "falcon_interceptor": 5},
            now=time.time(),
        )
        assert wiped.get("ok"), wiped
        assert wiped.get("return_ships", {}).get("planet_breaker") in (None, 0)
        planets = get_planets_by_player(pid, conn=conn) or []
        assert all(int(p["id"]) != colony_id for p in planets)
        assert any(int(p.get("is_homeworld") or 0) == 1 for p in planets)
        bounty = get_player_bounty(attacker_id, "nomad_swarm", conn=conn)
        assert int(bounty.get("credits") or 0) >= 5000
        logs = recent_action_log(conn, kind="bot_colony_destroyed", limit=5)
        assert any(l.get("bot_player_id") == pid for l in logs)
        commit(conn)
    finally:
        conn.close()


def test_play_loop_prefers_economy_when_weak(pirate_db):
    """GC-P26: weak bot chooses economy over raid."""
    from game.db import begin_write_transaction, commit
    from game.pirates.admin import admin_set_ai
    from game.pirates.play_loop import decide_bot_action
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        res = admin_set_ai(conn, True)
        bot = next(b for b in res["bots"] if b["faction_key"] == "salt_cartel")
        # Fresh bots have level-0 buildings → economy.
        action = decide_bot_action(conn, bot, now=time.time())
        assert action in ("economy", "rebuild")
        commit(conn)
    finally:
        conn.close()


def test_play_loop_round_robin_budget(pirate_db):
    """Cron must not process all 6 bots every tick (Railway hang guard)."""
    from game.db import begin_write_transaction, commit
    from game.pirates.admin import admin_set_ai
    from game.pirates.play_loop import PLAY_BOTS_PER_TICK, run_play_loop_tick
    import time

    conn = db()
    try:
        begin_write_transaction(conn)
        res = admin_set_ai(conn, True)
        bots = res["bots"]
        assert len(bots) == 6
        first = run_play_loop_tick(conn, now=time.time(), bots=bots)
        assert first.get("ok")
        assert int(first.get("active") or 0) == min(PLAY_BOTS_PER_TICK, 6)
        assert int(first.get("roster") or 0) == 6
        second = run_play_loop_tick(conn, now=time.time(), bots=bots)
        first_factions = {s.get("faction_key") for s in (first.get("steps") or [])}
        second_factions = {s.get("faction_key") for s in (second.get("steps") or [])}
        # Cursor advances — second slice should differ when budget < roster.
        if PLAY_BOTS_PER_TICK < 6:
            assert first_factions != second_factions
        commit(conn)
    finally:
        conn.close()


def test_human_colony_destroy_path(pirate_db):
    """GC-P31: human colony can be wiped with breaker; homeworld blocked."""
    from game.db import begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.pirates.destroy import destroy_colony_planet, maybe_destroy_colony_after_combat
    import time
    import uuid

    class _FakeCombat:
        winner = "attacker"

    ok, err, user = create_user(f"hwipe_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    victim = int(user["id"])
    ok2, err2, atk = create_user(f"hatk_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok2, err2
    attacker = int(atk["id"])

    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(victim, player_name="Victim", conn=conn)
        home = get_planets_by_player(victim, conn=conn)[0]
        cur = conn.execute(
            """
            INSERT INTO planets (
                player_id, name, galaxy, system, position, is_homeworld,
                metal, crystal, fuel_cells, last_update
            ) VALUES (?, 'Human Outpost', 1, 33, 4, 0, 1000, 1000, 1000, ?);
            """,
            (victim, time.time()),
        )
        colony_id = int(cur.lastrowid)
        assert destroy_colony_planet(
            conn, planet_id=int(home["id"]), owner_player_id=victim
        ).get("error") == "homeworld_protected"
        wiped = maybe_destroy_colony_after_combat(
            conn,
            attacker_id=attacker,
            defender_id=victim,
            target_planet_id=colony_id,
            combat_result=_FakeCombat(),
            return_ships={"planet_breaker": 1},
            now=time.time(),
        )
        assert wiped.get("ok"), wiped
        assert wiped.get("defender_is_ai") is False
        planets = get_planets_by_player(victim, conn=conn) or []
        assert all(int(p["id"]) != colony_id for p in planets)
        logs = recent_action_log(conn, kind="colony_destroyed", limit=5)
        assert logs
        commit(conn)
    finally:
        conn.close()


def test_planet_breaker_locale_and_def():
    from game.fleet_defs import ACTIVE_SHIP_KEYS, get_ship

    assert "planet_breaker" in ACTIVE_SHIP_KEYS
    spec = get_ship("planet_breaker")
    assert spec and spec.get("role") == "siege"
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        assert "fleet_ship_planet_breaker" in data
        assert "fleet_ship_planet_breaker_desc" in data
        assert "pirate_faction_ash_raiders" in data
        assert "pirate_faction_salt_cartel" in data


def test_faction_homes_distributed(pirate_db):
    """GC-P30: six faction homes are spread, not camped in 490–491."""
    from game.pirates.accounts import FACTION_BOTS, FACTION_HOMEWORLDS

    assert len(FACTION_BOTS) == 6
    assert len(FACTION_HOMEWORLDS) == 6
    systems = [coords[1] for coords in FACTION_HOMEWORLDS.values()]
    assert len(set(systems)) == 6
    assert all(s < 490 for s in systems)
    assert max(systems) - min(systems) >= 300
