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
    assert "has-boss-image" in ring
    assert "img/bosses/" in ring
    assert "galaxy_ring_world_boss_marker.html" in ring
    assert "galaxy_ring_slot_hover_stack.html" in ring
    assert "galaxy_world_boss_block.html" in ring

    marker = Path("templates/partials/galaxy_ring_world_boss_marker.html").read_text(encoding="utf-8")
    assert "galaxy-ring-wb-marker" in marker
    assert "fleet_deep_link" in marker

    hover_stack = Path("templates/partials/galaxy_ring_slot_hover_stack.html").read_text(encoding="utf-8")
    assert "galaxy-ring-slot-hover-stack" in hover_stack
    assert "galaxy-ring-hover-card--wb" in hover_stack
    assert "galaxy-ring-hover-card--debris" in hover_stack
    assert "is-stacked" in hover_stack

    actions = Path("templates/partials/galaxy_fleet_actions.html").read_text(encoding="utf-8")
    assert "has_world_boss" in actions
    assert "galaxy-fleet-action--world-boss" in actions

    page = Path("templates/world_boss.html").read_text(encoding="utf-8")
    assert "target_galaxy=" in page
    assert "target_system=" in page
    assert "target_position=" in page
    assert "img/bosses/" in page
    assert "gc-world-boss-cards" in page
    assert "gc-world-boss-card" in page
    assert "gc-world-boss-board-details" in page
    assert "gc-world-boss-hp-fill" in page
    assert "wb-attack-btn" in page
    assert "data-wb-locked-until" in page
    assert "data-wb-attack-cooldown" in page
    assert "gc-world-boss-rewards" in page
    assert "rewards_preview" in page or "wb_rewards_title" in page
    assert "wb_reward_tier_alliance_xp" in page or "alliance_xp" in page
    assert "wb_your_alliance_xp" in page
    assert "wb_col_alliance_xp" in page
    assert "wb_help_alliance_xp" in page

    alliance_page = Path("templates/alliance.html").read_text(encoding="utf-8")
    assert "alliance_xp_source_world_boss" in alliance_page
    assert "alliance_xp_source_future" not in alliance_page

    css = Path("static/style.css").read_text(encoding="utf-8")
    assert "object-fit: contain" in css
    assert "gc-wb-glow-pulse" in css or "gc-world-boss-cards" in css
    assert "has-boss-image" in css
    assert "has-world-boss-wrap" in css
    assert "galaxy-ring-slot-hover-stack" in css
    assert "galaxy-ring-hover-card--wb" in css
    assert "galaxy-ring-hover-card--debris" in css
    assert "gc-world-boss-cards" in css
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


def test_attack_grants_alliance_xp(wb_db):
    from game.alliance import create_alliance, get_player_alliance
    from game.world_boss import alliance_xp_from_boss_damage, build_world_boss_payload

    assert alliance_xp_from_boss_damage(0) == 0
    assert alliance_xp_from_boss_damage(39_999) == 0
    assert alliance_xp_from_boss_damage(40_000) == 1
    assert alliance_xp_from_boss_damage(1_600_000) == 40  # capped

    uid = _player(name="AllyBoss")
    conn = db()
    try:
        create_alliance("WBX", "World Boss XP", uid, conn=conn)
        membership = get_player_alliance(uid, conn=conn)
        assert membership
        aid = int(membership["alliance_id"])
        before = int(
            conn.execute(
                "SELECT alliance_xp FROM alliances WHERE id = ?;",
                (aid,),
            ).fetchone()["alliance_xp"]
            or 0
        )

        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=5,
            system=5,
            position=5,
            announce=False,
        )
        assert spawn["ok"], spawn
        event = spawn["event"]
        conn.execute(
            "UPDATE world_boss_events SET max_hp = 5000000, current_hp = 5000000, "
            "fleet_stacks_json = ? WHERE id = ?;",
            ('{"falcon_interceptor":5}', int(event["id"])),
        )
        result = resolve_attack_arrival(
            movement={
                "id": 900777,
                "player_id": uid,
                "origin_planet_id": 0,
                "target_galaxy": 5,
                "target_system": 5,
                "target_position": 5,
                "resources": {},
            },
            ships={"falcon_interceptor": 500, "ironclad_frigate": 100},
            player_id=uid,
            conn=conn,
        )
        assert result["ok"], result
        assert int(result["damage"]) > 0
        assert int(result.get("alliance_id") or 0) == aid
        expected = alliance_xp_from_boss_damage(int(result["damage"]))
        assert int(result.get("alliance_xp_granted") or 0) == expected
        after = int(
            conn.execute(
                "SELECT alliance_xp FROM alliances WHERE id = ?;",
                (aid,),
            ).fetchone()["alliance_xp"]
            or 0
        )
        assert after == before + expected
        assert after > before
        # Ledger on contribution
        from game.world_boss import list_contributions

        rows = list_contributions(int(event["id"]), conn=conn)
        mine = next(r for r in rows if int(r["player_id"]) == uid)
        assert int(mine["alliance_xp"]) == expected
        payload = build_world_boss_payload(uid, conn=conn, event_id=int(event["id"]))
        card = next(
            c
            for c in (payload.get("events") or [])
            if int((c.get("event") or {}).get("id") or 0) == int(event["id"])
        )
        assert int((card.get("player") or {}).get("alliance_xp_earned") or 0) == expected
        assert any(r.get("tier") == "alliance_xp" for r in (card.get("rewards_preview") or []))
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
    """Even fight full wipe ≈ WAVE_HP_FRACTION; mega fleet hits soft overkill cap (~10–20 waves)."""
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
    assert damage == 100_000
    assert damage > 50_000

    half = compute_world_boss_hp_damage(
        defender_ships_before=stacks,
        defender_losses={"falcon_interceptor": 400, "ironclad_frigate": 100, "eclipse_runner": 20},
        max_hp=max_hp,
        attacker_ships_before=stacks,
    )
    assert 40_000 <= half <= 60_000

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
    assert mega_damage > damage
    assert mega_damage <= cap
    # Solo mega: at least 10 waves, at most ~20 waves to clear the bar.
    assert mega_damage * 10 <= max_hp
    assert mega_damage * 20 >= max_hp


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
        # void_titan loot_pool_key → container_void_artifact
        pool_loot = next(
            (r for r in claim["rewards"] if r["item_key"] == "container_void_artifact"),
            None,
        )
        assert pool_loot is not None
        assert int(pool_loot["amount"]) >= 2
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

        # After inter-event cooldown, next tick spawns weighted boss.
        from game.world_boss import SPAWN_RUNTIME_KEY

        set_runtime_value(
            SCHEDULE_RUNTIME_KEY,
            str(time.time() - INTER_EVENT_COOLDOWN_SEC - 1),
            conn=conn,
        )
        set_runtime_value(
            SPAWN_RUNTIME_KEY,
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


def test_world_boss_attack_ignores_fleet_slot_cap(wb_db):
    """WB attacks must work when all normal slots are full (mass-expo reserve independent)."""
    from game.fleet import get_fleet_slot_status
    from game.models import get_planets_by_player

    uid = _player(name="SlotFull")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        # Ensure baseline 3 slots (nav 0).
        conn.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, 'navigation_tech', 0)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = 0;
            """,
            (uid,),
        )
        slots0 = get_fleet_slot_status(uid, conn=conn)
        assert int(slots0["max"]) == 3
        # Fill all slots with expedition fleets.
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs = int(home["galaxy"]), int(home["system"])
        for i in range(3):
            ok, err, _ = send_fleet(
                player_id=uid,
                origin_planet_id=pid,
                target_galaxy=hg,
                target_system=hs,
                target_position=16,
                mission_type="expedition",
                ships={"falcon_interceptor": 1},
                resources={},
                speed_percent=100,
                conn=conn,
            )
            assert ok, (i, err)
        slots_full = get_fleet_slot_status(uid, conn=conn)
        assert int(slots_full["free"]) == 0

        boss_pos = 8 if int(home["position"]) != 8 else 9
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        ok_wb, err_wb, res_wb = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            mission_type="attack",
            ships={"falcon_interceptor": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok_wb, err_wb
        assert res_wb
        # WB must not consume the normal slot pool.
        slots_after = get_fleet_slot_status(uid, conn=conn)
        assert int(slots_after["free"]) == 0
        assert int(slots_after["active"]) == 3
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
        # Send starts cooldown immediately.
        row = conn.execute(
            "SELECT last_attack_at, waves, damage FROM world_boss_contributions "
            "WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert row is not None
        assert float(row["last_attack_at"] or 0) > 0
        assert int(row["waves"] or 0) == 1  # prior seeded wave
        # Second send while outbound / on CD fails.
        ok3, err3, _ = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            mission_type="attack",
            ships={"falcon_interceptor": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert not ok3
        assert err3 in ("world_boss_cooldown", "world_boss_inflight")
        commit(conn)
    finally:
        conn.close()


def test_send_starts_cooldown_without_prior_contribution(wb_db):
    uid = _player()
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs, hp = int(home["galaxy"]), int(home["system"]), int(home["position"])
        boss_pos = 6 if hp != 6 else 7
        spawn = spawn_world_boss(
            "planet_eater",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
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
        assert ok, err
        row = conn.execute(
            "SELECT last_attack_at, waves, damage FROM world_boss_contributions "
            "WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert row is not None
        assert float(row["last_attack_at"] or 0) > 0
        assert int(row["waves"] or 0) == 0
        assert int(row["damage"] or 0) == 0
        ok2, err2, _ = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            mission_type="attack",
            ships={"falcon_interceptor": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert not ok2
        assert err2 in ("world_boss_cooldown", "world_boss_inflight")
        commit(conn)
    finally:
        conn.close()


def test_spawn_coords_unique_across_active_bosses(wb_db):
    from game.world_boss import list_active_events

    conn = db()
    try:
        begin_write_transaction(conn)
        first = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=4,
            system=4,
            position=8,
            announce=False,
        )
        assert first["ok"], first
        # Explicit same coords must fail — no overlap.
        clash = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=4,
            system=4,
            position=8,
            announce=False,
        )
        assert not clash["ok"]
        assert clash["error"] == "coords_occupied"
        # Auto-pick must land on a free slot.
        second = spawn_world_boss("void_titan", conn=conn, announce=False)
        assert second["ok"], second
        e1 = first["event"]
        e2 = second["event"]
        assert (e1["galaxy"], e1["system"], e1["position"]) != (
            e2["galaxy"],
            e2["system"],
            e2["position"],
        )
        active = list_active_events(conn=conn)
        coords = {(e["galaxy"], e["system"], e["position"]) for e in active}
        assert len(coords) == len(active)
        commit(conn)
    finally:
        conn.close()


def test_multi_concurrent_spawn_cap(wb_db):
    from game.world_boss import MAX_CONCURRENT_EVENTS, list_active_events

    conn = db()
    try:
        begin_write_transaction(conn)
        keys = ["ancient_leviathan", "void_titan", "planet_eater", "rogue_ai_nexus"]
        for i, key in enumerate(keys[:MAX_CONCURRENT_EVENTS]):
            r = spawn_world_boss(
                key, conn=conn, galaxy=2, system=10 + i, position=3, announce=False
            )
            assert r["ok"], r
        blocked = spawn_world_boss(
            "rogue_ai_nexus", conn=conn, galaxy=2, system=20, position=3, announce=False
        )
        assert not blocked["ok"]
        assert blocked["error"] == "concurrent_cap"
        active = list_active_events(conn=conn)
        assert len(active) == MAX_CONCURRENT_EVENTS
        forced = spawn_world_boss(
            "rogue_ai_nexus",
            conn=conn,
            galaxy=2,
            system=21,
            position=4,
            announce=False,
            force=True,
        )
        assert forced["ok"], forced
        commit(conn)
    finally:
        conn.close()


def test_expo_discovery_spawns_when_under_cap(wb_db):
    from game.world_boss import try_discover_world_boss_from_expedition

    class Always:
        def random(self):
            return 0.0

    uid = _player(name="Scout")
    conn = db()
    try:
        begin_write_transaction(conn)
        result = try_discover_world_boss_from_expedition(
            uid, conn=conn, rng=Always()
        )
        assert result["ok"], result
        assert result.get("coords")
        assert int(result.get("discovered_by") or 0) == uid
        from game.world_boss import get_event_by_id

        event = get_event_by_id(int(result["event_id"]), conn=conn)
        assert event is not None
        assert int(event.get("discovered_by_player_id") or 0) == uid
        commit(conn)
    finally:
        conn.close()


def test_rewards_preview_uses_boss_loot_pool(wb_db):
    from game.world_boss import build_rewards_preview, build_world_boss_payload

    preview_void = build_rewards_preview("container_void_artifact")
    participate = next(r for r in preview_void if r["tier"] == "participate")
    assert participate["grants"][0]["item_key"] == "container_void_artifact"
    assert int(participate["grants"][0]["amount"]) == 2
    ally = next(r for r in preview_void if r["tier"] == "alliance_xp")
    assert int(ally["divisor"]) == 40_000
    assert int(ally["wave_cap"]) == 40

    preview_nexus = build_rewards_preview("container_ancient_relic")
    participate_nx = next(r for r in preview_nexus if r["tier"] == "participate")
    assert participate_nx["grants"][0]["item_key"] == "container_ancient_relic"

    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "rogue_ai_nexus",
            conn=conn,
            galaxy=2,
            system=2,
            position=2,
            announce=False,
        )
        assert spawn["ok"], spawn
        payload = build_world_boss_payload(None, conn=conn)
        card = next(
            c
            for c in (payload.get("events") or [])
            if (c.get("event") or {}).get("boss_key") == "rogue_ai_nexus"
        )
        assert card.get("rewards_preview")
        part = next(r for r in card["rewards_preview"] if r["tier"] == "participate")
        assert part["grants"][0]["item_key"] == "container_ancient_relic"
        commit(conn)
    finally:
        conn.close()


def test_discoverer_tier_extra_reward(wb_db):
    from game.world_boss import claim_world_boss_rewards

    uid = _player(name="Finder")
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=3,
            system=3,
            position=3,
            announce=False,
            discovered_by=uid,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        now = time.time()
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 500, 1, ?, ?, ?);
            """,
            (event_id, uid, now, now, now),
        )
        conn.execute(
            "UPDATE world_boss_events SET status = 'defeated', current_hp = 0, defeated_at = ? WHERE id = ?;",
            (now, event_id),
        )
        claim = claim_world_boss_rewards(uid, event_id, conn=conn, now=now)
        assert claim["ok"], claim
        assert "discoverer" in claim["tiers"]
        # void_titan pool: participate 2 + discoverer 1
        pool_loot = next(
            (r for r in claim["rewards"] if r["item_key"] == "container_void_artifact"),
            None,
        )
        assert pool_loot is not None
        assert int(pool_loot["amount"]) >= 3
        commit(conn)
    finally:
        conn.close()


def test_schedule_payload_next_eligible(wb_db):
    from game.runtime_state import set_runtime_value
    from game.world_boss import INTER_EVENT_COOLDOWN_SEC, SCHEDULE_RUNTIME_KEY, SPAWN_RUNTIME_KEY

    conn = db()
    try:
        begin_write_transaction(conn)
        now = time.time()
        last_ended = now - 3600
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(last_ended), conn=conn)
        set_runtime_value(SPAWN_RUNTIME_KEY, str(last_ended), conn=conn)
        payload = build_world_boss_payload(None, conn=conn, now=now)
        schedule = payload.get("schedule") or {}
        assert schedule.get("has_active") is False
        assert schedule.get("spawn_ready") is False
        expected = last_ended + INTER_EVENT_COOLDOWN_SEC
        assert abs(float(schedule["next_eligible_at"]) - expected) < 1.0
        assert int(schedule["inter_event_cooldown_sec"]) == int(INTER_EVENT_COOLDOWN_SEC)
        assert int(schedule["max_concurrent"]) == 3

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
