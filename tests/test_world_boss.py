"""EPIC-20 World Boss system tests."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.fleet import add_planet_ships, resolve_fleet_target, send_fleet
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.world_boss import (
    WAVE_COOLDOWN_SEC,
    build_world_boss_payload,
    claim_world_boss_rewards,
    get_active_event,
    get_active_event_at,
    get_bosses_for_system,
    list_alliance_contributions,
    list_contributions,
    resolve_attack_arrival,
    spawn_world_boss,
    tick_world_boss_schedule,
    world_boss_schema_ready,
)


@pytest.fixture
def wb_db(tmp_path, monkeypatch):
    db_path = tmp_path / "world_boss_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(name="Admiral"):
    ok, err, user = create_user(f"wb_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        commit(conn)
    finally:
        conn.close()
    return uid


def _home(uid):
    conn = db()
    try:
        return int(get_planets_by_player(uid, conn=conn)[0]["id"])
    finally:
        conn.close()


def _fund(planet_id: int):
    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
            (int(planet_id),),
        )
        commit(conn)
    finally:
        conn.close()


def _seed_combat_fleet(planet_id: int, player_id: int):
    conn = db()
    try:
        begin_write_transaction(conn)
        add_planet_ships(
            int(planet_id),
            int(player_id),
            {"falcon_interceptor": 500, "ironclad_frigate": 100},
            conn=conn,
        )
        commit(conn)
    finally:
        conn.close()


def test_schema_and_catalog(wb_db):
    conn = db()
    try:
        assert world_boss_schema_ready(conn)
        from game.world_boss import list_definitions

        defs = list_definitions(conn=conn)
        keys = {d["boss_key"] for d in defs}
        assert "ancient_leviathan" in keys
        assert "void_titan" in keys
        assert "planet_eater" in keys
        assert "rogue_ai_nexus" in keys
    finally:
        conn.close()


def test_spawn_and_galaxy_attach(wb_db):
    conn = db()
    try:
        begin_write_transaction(conn)
        result = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=1,
            position=8,
            announce=False,
        )
        assert result["ok"], result
        event = result["event"]
        assert event["status"] == "active"
        assert event["current_hp"] == event["max_hp"]
        bosses = get_bosses_for_system(1, 1, conn=conn)
        assert 8 in bosses
        assert bosses[8]["event_id"] == event["id"]
        link = bosses[8]["fleet_deep_link"]
        assert "target_galaxy=1" in link
        assert "target_system=1" in link
        assert "target_position=8" in link
        assert "mission=attack" in link
        assert "&galaxy=" not in link.replace("target_galaxy=", "")
        at = get_active_event_at(1, 1, 8, conn=conn)
        assert at and at["id"] == event["id"]
        target = resolve_fleet_target(1, 1, 1, 8, conn=conn)
        assert target["target_type"] == "world_boss"
        assert "attack" in target["allowed_missions"]

        from game.galaxy import list_system

        system = list_system(1, 1, conn=conn)
        slot = next(s for s in system["slots"] if int(s["position"]) == 8)
        assert slot["has_world_boss"] is True
        assert slot["world_boss"]["event_id"] == event["id"]
        assert "target_galaxy" in slot["world_boss"]["fleet_deep_link"]
        commit(conn)
    finally:
        conn.close()


def test_world_boss_galaxy_ui_contracts():
    ring = Path("templates/partials/galaxy_ring_view.html").read_text(encoding="utf-8")
    assert "has-world-boss" in ring
    assert "galaxy_ring_world_boss_marker.html" in ring
    assert "galaxy_world_boss_block.html" in ring

    marker = Path("templates/partials/galaxy_ring_world_boss_marker.html").read_text(encoding="utf-8")
    assert "galaxy-ring-wb-marker" in marker
    assert "fleet_deep_link" in marker

    actions = Path("templates/partials/galaxy_fleet_actions.html").read_text(encoding="utf-8")
    assert "has_world_boss" in actions
    assert "galaxy-fleet-action--world-boss" in actions

    page = Path("templates/world_boss.html").read_text(encoding="utf-8")
    assert "target_galaxy=" in page
    assert "target_system=" in page
    assert "target_position=" in page
    assert "img/bosses/" in page
    assert "gc-world-boss-hero" in page
    assert "gc-world-boss-hero--active" in page
    assert "gc-world-boss-stage" in page
    assert "gc-wb-glow" in page
    assert "gc-world-boss-hp-fill" in page
    assert 'id="wb-attack-btn"' in page
    assert "data-wb-locked-until" in page
    assert "data-wb-attack-cooldown" in page

    css = Path("static/style.css").read_text(encoding="utf-8")
    assert "object-fit: contain" in css
    assert "gc-wb-glow-pulse" in css
    assert "gc-nav-wb-live-pulse" in css
    assert "gc-nav-sub-link--wb-live" in css

    sidebar = Path("templates/partials/sidebar_right.html").read_text(encoding="utf-8")
    assert 'data-nav-badge="world_boss"' in sidebar
    assert "gc-nav-sub-link--wb-live" in sidebar
    assert "WORLD_BOSS_ACTIVE" in sidebar

    art_dir = Path("static/img/bosses")
    for name in (
        "_placeholder.png",
        "ancient_leviathan.png",
        "void_titan.png",
        "planet_eater.png",
        "rogue_ai_nexus.png",
    ):
        assert (art_dir / name).is_file(), name


def test_nav_badges_world_boss_live(wb_db):
    from game.live_state import nav_badges_for_game_state

    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        badges0 = nav_badges_for_game_state(uid, conn=conn)
        assert badges0["world_boss"]["active"] is False

        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=11,
            position=4,
            announce=False,
        )
        assert spawn["ok"], spawn
        badges1 = nav_badges_for_game_state(uid, conn=conn)
        assert badges1["world_boss"]["active"] is True
        assert badges1["world_boss"]["label"] == "LIVE"
        commit(conn)
    finally:
        conn.close()


def test_attack_contribution_and_defeat(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "rogue_ai_nexus",
            conn=conn,
            galaxy=1,
            system=2,
            position=9,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        conn.execute(
            "UPDATE world_boss_events SET max_hp = 50, current_hp = 50, "
            "fleet_stacks_json = ? WHERE id = ?;",
            ('{"falcon_interceptor":5}', event_id),
        )
        result = resolve_attack_arrival(
            movement={
                "id": 900001,
                "player_id": uid,
                "origin_planet_id": 0,
                "target_galaxy": 1,
                "target_system": 2,
                "target_position": 9,
                "resources": {},
            },
            ships={"falcon_interceptor": 200, "ironclad_frigate": 50},
            player_id=uid,
            conn=conn,
        )
        assert result["ok"], result
        assert int(result["damage"]) > 0
        from game.world_boss import get_event_by_id

        event = get_event_by_id(event_id, conn=conn)
        assert event is not None
        contribs = list_contributions(event_id, conn=conn)
        assert len(contribs) == 1
        assert contribs[0]["player_id"] == uid
        assert contribs[0]["damage"] > 0
        assert int(event["current_hp"]) < 50 or event["status"] == "defeated"
        commit(conn)
    finally:
        conn.close()


def test_full_wipe_deals_wave_hp_fraction(wb_db):
    """Even fight full wipe ≈ WAVE_HP_FRACTION; mega fleet scales via overkill."""
    from game.world_boss import (
        MAX_WAVE_HP_FRACTION,
        WAVE_HP_FRACTION,
        compute_world_boss_hp_damage,
    )

    stacks = {"falcon_interceptor": 800, "ironclad_frigate": 200, "eclipse_runner": 40}
    max_hp = 5_000_000
    # Equal-ish attacker: force_ratio ~1 → overkill_mult = 1 → base fraction only.
    damage = compute_world_boss_hp_damage(
        defender_ships_before=stacks,
        defender_losses=stacks,
        max_hp=max_hp,
        attacker_ships_before=stacks,
    )
    expected = int(max_hp * WAVE_HP_FRACTION)
    cap = int(max_hp * MAX_WAVE_HP_FRACTION)
    assert damage == min(expected, cap)
    assert damage == 150_000
    assert damage > 50_000

    half = compute_world_boss_hp_damage(
        defender_ships_before=stacks,
        defender_losses={"falcon_interceptor": 400, "ironclad_frigate": 100, "eclipse_runner": 20},
        max_hp=max_hp,
        attacker_ships_before=stacks,
    )
    assert 60_000 <= half <= 90_000

    mega = {
        "falcon_interceptor": 1_000_000,
        "ironclad_frigate": 700_000_000,
        "eclipse_runner": 1_000_000,
    }
    mega_damage = compute_world_boss_hp_damage(
        defender_ships_before=stacks,
        defender_losses=stacks,
        max_hp=max_hp,
        attacker_ships_before=mega,
    )
    assert mega_damage >= int(max_hp * 0.40)
    assert mega_damage <= cap
    assert mega_damage > damage


def test_claim_rewards_after_defeat(wb_db):
    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=1,
            system=3,
            position=7,
            announce=False,
        )
        event_id = int(spawn["event"]["id"])
        now = time.time()
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 1000, 1, ?, ?, ?);
            """,
            (event_id, uid, now, now, now),
        )
        conn.execute(
            "UPDATE world_boss_events SET status = 'defeated', current_hp = 0, defeated_at = ? WHERE id = ?;",
            (now, event_id),
        )
        claim = claim_world_boss_rewards(uid, event_id, conn=conn, now=now)
        assert claim["ok"], claim
        assert "participate" in claim["tiers"]
        assert claim["rewards"]
        again = claim_world_boss_rewards(uid, event_id, conn=conn, now=now)
        assert not again["ok"]
        assert again["error"] == "already_claimed"
        commit(conn)
    finally:
        conn.close()


def test_schedule_expire_and_spawn(wb_db):
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=4,
            position=6,
            announce=False,
        )
        event_id = int(spawn["event"]["id"])
        past = time.time() - 10
        conn.execute(
            "UPDATE world_boss_events SET ends_at = ? WHERE id = ?;",
            (past, event_id),
        )
        from game.runtime_state import set_runtime_value
        from game.world_boss import INTER_EVENT_COOLDOWN_SEC, SCHEDULE_RUNTIME_KEY

        # Expire first (sets last_ended = now → cooldown blocks immediate respawn).
        tick1 = tick_world_boss_schedule(conn=conn, now=time.time())
        assert tick1["ok"]
        assert event_id in tick1["expired_ids"]
        assert tick1.get("spawned_event_id") is None

        # After inter-event cooldown, next tick spawns rotation boss.
        set_runtime_value(
            SCHEDULE_RUNTIME_KEY,
            str(time.time() - INTER_EVENT_COOLDOWN_SEC - 1),
            conn=conn,
        )
        tick2 = tick_world_boss_schedule(conn=conn, now=time.time())
        assert tick2["ok"]
        assert tick2.get("spawned_event_id")
        active = get_active_event(conn=conn)
        assert active is not None
        assert int(active["id"]) != event_id
        commit(conn)
    finally:
        conn.close()


def test_alliance_board(wb_db):
    uid = _player(name="Leader")
    conn = db()
    try:
        begin_write_transaction(conn)
        now = time.time()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alliances (
                tag, name, description, alliance_level, alliance_xp,
                pool_metal, pool_crystal, pool_fuel_cells, member_limit,
                created_at, updated_at
            ) VALUES ('WBX', 'World Boss X', '', 1, 0, 0, 0, 0, 50, ?, ?);
            """,
            (now, now),
        )
        aid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, 'leader', ?);
            """,
            (aid, uid, now),
        )
        spawn = spawn_world_boss(
            "planet_eater",
            conn=conn,
            galaxy=1,
            system=5,
            position=5,
            announce=False,
        )
        event_id = int(spawn["event"]["id"])
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, ?, 5000, 2, ?, ?, ?);
            """,
            (event_id, uid, aid, now, now, now),
        )
        board = list_alliance_contributions(event_id, conn=conn)
        assert board and board[0]["alliance_id"] == aid
        assert board[0]["damage"] == 5000
        payload = build_world_boss_payload(uid, conn=conn, event_id=event_id)
        assert payload["alliance_board"]
        commit(conn)
    finally:
        conn.close()


def test_attack_cooldown_blocks_send(wb_db):
    uid = _player()
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    # Avoid player's homeworld coords — use a free classic slot in galaxy 1.
    conn = db()
    try:
        begin_write_transaction(conn)
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs, hp = int(home["galaxy"]), int(home["system"]), int(home["position"])
        boss_pos = 4 if hp != 4 else 5
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        now = time.time()
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 10, 1, ?, ?, ?);
            """,
            (event_id, uid, now, now, now),
        )
        ok, err, _ = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            mission_type="attack",
            ships={"falcon_interceptor": 10},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert not ok
        assert err == "world_boss_cooldown"
        conn.execute(
            "UPDATE world_boss_contributions SET last_attack_at = ? WHERE event_id = ? AND player_id = ?;",
            (now - WAVE_COOLDOWN_SEC - 1, event_id, uid),
        )
        ok2, err2, _ = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            mission_type="attack",
            ships={"falcon_interceptor": 10},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok2, err2
        commit(conn)
    finally:
        conn.close()


def test_schedule_payload_next_eligible(wb_db):
    from game.runtime_state import set_runtime_value
    from game.world_boss import INTER_EVENT_COOLDOWN_SEC, SCHEDULE_RUNTIME_KEY

    conn = db()
    try:
        begin_write_transaction(conn)
        now = time.time()
        last_ended = now - 3600
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(last_ended), conn=conn)
        payload = build_world_boss_payload(None, conn=conn, now=now)
        schedule = payload.get("schedule") or {}
        assert schedule.get("has_active") is False
        assert schedule.get("spawn_ready") is False
        expected = last_ended + INTER_EVENT_COOLDOWN_SEC
        assert abs(float(schedule["next_eligible_at"]) - expected) < 1.0
        assert int(schedule["inter_event_cooldown_sec"]) == int(INTER_EVENT_COOLDOWN_SEC)

        # After cooldown elapsed → spawn ready (no active event).
        payload2 = build_world_boss_payload(
            None, conn=conn, now=last_ended + INTER_EVENT_COOLDOWN_SEC + 5
        )
        assert payload2["schedule"]["spawn_ready"] is True
        commit(conn)
    finally:
        conn.close()


@pytest.fixture()
def wb_admin_client(wb_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)

    ok_a, _, admin_info = create_user("wb_admin", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("wb_user", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def test_admin_world_boss_get_status_and_definitions(wb_admin_client):
    client, admin_id, user_id = wb_admin_client

    r = client.get("/api/admin/world-boss")
    assert r.status_code == 401

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    r = client.get("/api/admin/world-boss")
    assert r.status_code == 403

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    r = client.get("/api/admin/world-boss")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert isinstance(data.get("definitions"), list)
    assert len(data["definitions"]) >= 1
    assert "boss_key" in data["definitions"][0]
    assert isinstance(data.get("schedule"), dict)
    assert "next_eligible_at" in data["schedule"] or "spawn_ready" in data["schedule"]
    assert "event" in data


def test_spawn_news_uses_localized_boss_name(wb_db):
    from game.i18n import _load_locale, set_request_locale
    from game.universe_news import create_news, get_banner_entry

    _load_locale.cache_clear()
    conn = db()
    try:
        begin_write_transaction(conn)
        result = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=3,
            position=6,
            announce=False,
        )
        assert result["ok"], result
        event = result["event"]
        # Legacy English banner (as stored before i18n fix) must still render DE for DE locale.
        create_news(
            title=f"World Boss: {event['boss_key']}",
            body=(
                f"A world boss has appeared at {event['coords']}. "
                f"HP {int(event['current_hp'])}/{int(event['max_hp'])}. "
                "Attack via Galaxy or Fleet."
            ),
            category="EVENT",
            badge="EVENT",
            source_ref=f"world_boss:spawn:{int(event['id'])}",
            set_banner=True,
            conn=conn,
        )
        commit(conn)
        set_request_locale("de")
        banner = get_banner_entry(conn=conn)
        assert banner is not None
        title = str(banner.get("title") or "")
        body = str(banner.get("body") or "")
        assert "ancient_leviathan" not in title
        assert "Uralter Leviathan" in title
        assert "A world boss has appeared" not in body
        assert "erschienen" in body
        assert "World Boss" in title
    finally:
        conn.close()


def test_payload_exposes_attack_cooldown(wb_db):
    from game.world_boss import can_player_attack_boss

    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=9,
            position=7,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        now = time.time()
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 100, 1, ?, ?, ?);
            """,
            (event_id, uid, now, now, now),
        )
        ok, reason, meta = can_player_attack_boss(uid, event_id, conn=conn, now=now + 10)
        assert ok is False
        assert reason == "world_boss_cooldown"
        assert int(meta["cooldown_remaining"]) > 0
        assert meta["next_attack_at"] is not None
        assert abs(float(meta["next_attack_at"]) - (now + WAVE_COOLDOWN_SEC)) < 1.0
        assert int(meta["wave_cooldown_sec"]) == int(WAVE_COOLDOWN_SEC)

        payload = build_world_boss_payload(uid, conn=conn, event_id=event_id, now=now + 10)
        player = payload["player"]
        assert player["can_attack"] is False
        assert player["attack_block_reason"] == "world_boss_cooldown"
        assert player["attack_meta"]["next_attack_at"] is not None

        page = Path("templates/world_boss.html").read_text(encoding="utf-8")
        assert "wb_attack_cooldown" in page
        assert "next_attack_at" in page
        commit(conn)
    finally:
        conn.close()
