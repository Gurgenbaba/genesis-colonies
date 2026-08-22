"""EPIC-20 World Boss system tests."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.fleet import (
    add_planet_ships,
    get_planet_ships,
    resolve_fleet_target,
    resolve_world_boss_auto_attack_ships,
    send_fleet,
)
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.world_boss import (
    WAVE_COOLDOWN_SEC,
    build_world_boss_payload,
    claim_world_boss_rewards,
    execute_instant_attack,
    get_active_event,
    get_active_event_at,
    get_bosses_for_system,
    list_alliance_contributions,
    list_contributions,
    resolve_attack_arrival,
    select_world_boss_auto_attack_ships,
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
        assert link == "/world-boss"
        assert bosses[8].get("encounter_path") == "/world-boss"
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
        assert slot["world_boss"]["fleet_deep_link"] == "/world-boss"
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

    wb_page = Path("templates/world_boss.html").read_text(encoding="utf-8")
    assert "data-wb-auto-attack" in wb_page
    assert "wb_auto_attack" in wb_page
    assert "data-wb-encounter" in wb_page

    wb_block = Path("templates/partials/galaxy_world_boss_block.html").read_text(encoding="utf-8")
    assert "fleet_deep_link" in wb_block

    hover_stack = Path("templates/partials/galaxy_ring_slot_hover_stack.html").read_text(encoding="utf-8")
    assert "galaxy-ring-slot-hover-stack" in hover_stack
    assert "galaxy-ring-hover-card--wb" in hover_stack
    assert "galaxy-ring-hover-card--debris" in hover_stack
    assert "is-stacked" in hover_stack

    actions = Path("templates/partials/galaxy_fleet_actions.html").read_text(encoding="utf-8")
    assert "has_world_boss" in actions
    assert "galaxy-fleet-action--world-boss" in actions

    page = Path("templates/world_boss.html").read_text(encoding="utf-8")
    assert "img/bosses/" in page
    assert "video/bosses/" in page
    assert "data-wb-boss-video" in page
    assert "gc-world-boss-portrait-video" in page
    assert "data-wb-boss-portrait-fallback" in page
    assert "gc-world-boss-cards" in page
    assert "gc-world-boss-card" in page
    assert "gc-world-boss-board-details" in page
    assert "gc-world-boss-hp-fill" in page
    assert "wb-attack-btn" in page
    assert "data-wb-locked-until" in page
    assert "data-wb-attack-cooldown" in page
    assert "data-wb-instant-attack" in page
    assert "data-wb-formation" in page
    assert "data-wb-damage-mount" in page
    assert "gc-world-boss-rewards" in page
    assert "gc-world-boss-payout" in page
    assert "wb_rewards_show" in page
    assert "data-wb-rewards-block" in page
    assert "gc-world-boss-rewards-toggle" in page
    assert "wb_your_rewards_title" in page
    assert "wb_rewards_catalog_title" in page
    assert "rewards_preview" in page or "wb_rewards_title" in page
    assert "wb_reward_tier_alliance_xp" in page or "alliance_xp" in page
    assert "wb_your_alliance_xp" in page
    assert "wb_col_alliance_xp" in page
    assert "wb_help_alliance_xp" in page
    assert "wb_rewards_inventory_hint" in page
    # GC-WB-VISUAL-001 / Boss Window — Encounter Stage contracts
    assert "gc-world-boss-hero" in page
    assert "gc-world-boss-stage" in page
    assert "gc-wb-stage-corner" in page
    assert "gc-wb-stage-corner--tl" in page
    assert "gc-wb-stage-corner--br" in page
    assert "gc-world-boss-hero-art" in page
    assert "gc-wb-glow" in page
    assert "data-wb-encounter" in page
    assert "data-wb-hp-phase" in page
    assert "data-wb-boss-art" in page
    assert "gc-world-boss-boss-float" in page
    assert "gc-world-boss-aura" in page
    # Hero loop video: loop + muted autoplay attrs; portrait remains fallback
    assert "data-wb-boss-video" in page and "loop" in page
    assert "playsinline" in page
    assert "muted" in page
    assert "gc-world-boss-portrait" in page
    video_dir = Path("static/video/bosses")
    for boss_key in (
        "rogue_ai_nexus",
        "planet_eater",
        "void_titan",
        "ancient_leviathan",
    ):
        assert (video_dir / f"{boss_key}.mp4").is_file(), f"missing hero loop for {boss_key}"
    css = Path("static/style.css").read_text(encoding="utf-8")
    assert ".gc-world-boss-portrait-video" in css
    assert "gc-world-boss-portrait-fallback" in css
    assert ".gc-world-boss-boss-float:not(.is-portrait-fallback)" in css
    assert "animation: none" in css
    assert "min(100%, 720px)" in css
    assert "gc-world-boss-stage-overlay" in css
    assert ".gc-wb-stage-corner" in css
    assert "gc-wb-stage-corner--tl" in css
    assert "is-wb-reel-active" in css
    assert "mask-image" in css
    assert "overflow-x: clip" in css
    # Break-frame arena: stage has no hard picture border
    assert ".gc-world-boss-page .gc-world-boss-stage" in css
    stage_css_idx = css.find(".gc-world-boss-page .gc-world-boss-stage {")
    assert stage_css_idx >= 0
    stage_block = css[stage_css_idx : stage_css_idx + 1200]
    assert "border: none" in stage_block
    assert "overflow: visible" in stage_block
    assert "min-height: 420px" in stage_block
    assert ".gc-world-boss-portrait-video" in css
    video_css_idx = css.find(".gc-world-boss-page .gc-world-boss-portrait-video {")
    assert video_css_idx >= 0
    video_block = css[video_css_idx : video_css_idx + 700]
    assert "mask-image" in video_block or "-webkit-mask-image" in video_block
    rail_idx = css.find(".gc-world-boss-page .gc-world-boss-rail {")
    assert rail_idx >= 0
    rail_block = css[rail_idx : rail_idx + 500]
    assert "z-index: 4" in rail_block
    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "wbSyncBossVideoVolumes" in main_js
    assert "IntersectionObserver" in main_js
    assert "wbActivateBossVideo" in main_js
    assert "wbDeactivateBossVideo" in main_js
    assert "wbPickInViewBossVideo" in main_js
    assert "wbEnsureBossVideoBoot" in main_js
    assert "wbSeedBossVideoRatios" in main_js
    assert "softBoot" in main_js
    assert 'sfxVolumeForKind("ui", 0.1)' in main_js or "sfxVolumeForKind" in main_js
    assert "data-wb-boss-video" in main_js
    assert "wbk3" in page or "video/bosses/" in page
    assert "preload=\"auto\"" in page
    assert "--wb-ui-rgb" in css
    assert "--gc-id-rgb" in css
    assert "var(--wb-ui-border)" in css
    assert "var(--wb-ui-rgb)" in css
    assert "GC.playFightSalvoSound" in main_js
    assert "wbPlayAttackFx" in main_js
    attack_fx = main_js.split("const wbPlayAttackFx = (card, attack, boss) => {")[1].split(
        "GC.playWorldBossAttackFx = wbPlayAttackFx"
    )[0]
    assert "playFightSalvoSound" in attack_fx
    assert "GC_NOTIFY_SOUND_BASE_VOLUME = 0.1" in main_js
    assert "gc-world-boss-shadow" in page
    assert "gc-world-boss-progress" in page
    assert "gc-world-boss-layout" in page
    assert "gc-world-boss-arena" in page
    assert "gc-world-boss-rail" in page
    assert "gc-world-boss-action-bar" in page
    assert "gc-world-boss-stage-fx" in page
    assert "gc-wb-particle" in page
    assert "gc-world-boss-ship-count" in page
    assert "gc-world-boss-hp-label" in page
    assert "data-wb-damage-mount" in page
    assert "data-wb-projectiles" in page
    assert "gc-world-boss-fleet-strip" not in page
    assert "wb_combat_progress_title" in page
    assert "wb_attack_no_movement_hint" in page
    assert "gc-world-boss-card-body" not in page  # replaced by hero stage
    assert "fleet_view" not in page  # instant attack — no fleet deep-link

    alliance_page = Path("templates/alliance.html").read_text(encoding="utf-8")
    assert "alliance_xp_source_world_boss" in alliance_page
    assert "alliance_xp_source_future" not in alliance_page

    css = Path("static/style.css").read_text(encoding="utf-8")
    assert "object-fit: contain" in css
    assert "gc-wb-glow-pulse" in css or "gc-world-boss-cards" in css
    assert "gc-wb-boss-float" in css
    assert "gc-wb-phase-1" in css
    assert "min-height: 420px" in css
    assert "width: auto" in css  # HP wrap inset (not width:100% + left overflow)
    assert "gc-wb-particle-drift" in css
    assert "gc-wb-nebula-drift" in css
    assert "repeating-linear-gradient" in css
    assert "gc-wb-projectile-fly" in css
    assert ".gc-world-boss-fleet-strip {" not in css
    assert ".gc-world-boss-projectiles" in css and "z-index: 7" in css
    assert ".gc-world-boss-damage-mount" in css
    assert "--wb-ship-rot" in css  # V-formation rotation tokens
    assert "animation: gc-wb-projectile-fly" in css and "both" in css

    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "wbPlayAttackFx" in main_js
    assert "gc-wb-projectile" in main_js
    assert "GC.playWorldBossAttackFx" in main_js
    assert "GC.consumeWorldBossAutoPresentation" in main_js
    assert "flushed_attacks" in main_js
    assert "wbLivePollTick" in main_js or "wbAutoPollTick" in main_js or "wbAutoPoll" in main_js
    assert "wbSyncSharedBossHp" in main_js
    assert "consumeWorldBossAutoPresentation" in main_js
    assert "wbFlushAutoUntilFired" in main_js
    assert "wbCdUntil" in main_js
    assert "until - now > 0" in main_js
    assert "data-wb-ship-slot" in main_js
    assert "gc-world-boss-ship-count" in main_js
    assert "gc-wb-phase-2" in css
    assert "gc-wb-phase-3" in css
    assert "gc-wb-projectile" in css
    assert "gc-wb-dmg-num" in css
    assert "prefers-reduced-motion" in css
    assert "has-boss-image" in css
    assert "has-world-boss-wrap" in css

    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "/api/world-boss/attack" in main_js
    assert "wbPlayAttackFx" in main_js or "data-wb-instant-attack" in main_js
    assert "location.reload" not in main_js[main_js.find("GC.modules.world_boss") : main_js.find("GC.modules.chronicles")]
    assert "galaxy-ring-slot-hover-stack" in css
    assert "galaxy-ring-hover-card--wb" in css
    assert "galaxy-ring-hover-card--debris" in css
    assert "gc-world-boss-cards" in css
    assert "gc-nav-wb-live-pulse" in css
    assert "gc-world-boss-payout" in css
    assert "is-earned" in css
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
        assert (after > before) == (expected > 0)
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
    """Even fight follows WAVE_HP_FRACTION; mega fleets obey the hardened single-wave cap."""
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
    assert damage == int(max_hp * WAVE_HP_FRACTION)
    assert damage > 50_000

    half = compute_world_boss_hp_damage(
        defender_ships_before=stacks,
        defender_losses={"falcon_interceptor": 400, "ironclad_frigate": 100, "eclipse_runner": 20},
        max_hp=max_hp,
        attacker_ships_before=stacks,
    )
    assert 0 < half < damage
    assert abs(half - (damage // 2)) <= max(2_000, int(damage * 0.15))

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
    # GC-WB-RAID-002: a capped mega fleet now needs roughly 34 single waves.
    assert mega_damage * 30 < max_hp
    assert mega_damage * 40 >= max_hp


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
        # Ended claimable cards leave the list after claim (UI removes the card live).
        payload = build_world_boss_payload(uid, conn=conn, now=now, flush_auto=False)
        ids = [
            int((c.get("event") or {}).get("id") or 0)
            for c in (payload.get("events") or [])
        ]
        assert event_id not in ids
        commit(conn)
    finally:
        conn.close()


def test_reward_outlook_payout_clarity(wb_db):
    """Players see concrete grants for earned tiers, not only the catalog."""
    from game.world_boss import build_player_reward_outlook, build_world_boss_payload

    uid = _player()
    other = _player("wb_other")
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "planet_eater",
            conn=conn,
            galaxy=1,
            system=1,
            position=1,
            announce=False,
        )
        event_id = int(spawn["event"]["id"])
        now = time.time()
        for pid, dmg in ((uid, 9_700_000), (other, 100)):
            conn.execute(
                """
                INSERT INTO world_boss_contributions (
                    event_id, player_id, alliance_id, damage, waves,
                    last_attack_at, created_at, updated_at, alliance_xp
                ) VALUES (?, ?, NULL, ?, 2, ?, ?, ?, ?);
                """,
                (event_id, pid, dmg, now, now, now, 65 if pid == uid else 0),
            )
        conn.execute(
            "UPDATE world_boss_events SET status = 'defeated', current_hp = 0, defeated_at = ? WHERE id = ?;",
            (now, event_id),
        )
        payload = build_world_boss_payload(uid, conn=conn)
        card = next(
            c
            for c in (payload.get("events") or [])
            if int((c.get("event") or {}).get("id") or 0) == event_id
        )
        outlook = card["reward_outlook"]
        assert outlook["mode"] == "claimable"
        assert "participate" in outlook["earned_tiers"]
        assert "top1" in outlook["earned_tiers"]
        keys = {g["item_key"] for g in outlook["grants"]}
        assert "container_mythic" in keys
        assert any(r.get("earned") for r in card["rewards_preview"] if r["tier"] == "top1")
        assert not any(r.get("earned") for r in card["rewards_preview"] if r["tier"] == "alliance_top")
        direct = build_player_reward_outlook(card["event"], uid, conn=conn)
        assert direct["mode"] == "claimable"
        assert direct["grants"]
        page = (Path(__file__).resolve().parent.parent / "templates" / "world_boss.html").read_text(
            encoding="utf-8"
        )
        assert "gc-world-boss-payout" in page
        assert "wb_your_rewards_title" in page
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
        event_id = int(spawn["event"]["id"])
        hangar_before = get_planet_ships(pid, conn=conn)
        result = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 5},
            planet_id=pid,
            conn=conn,
            rng=__import__("random").Random(1),
        )
        assert result["ok"], result
        # Instant attack must not create fleet movements or consume slots.
        mov = conn.execute(
            "SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id = ? AND mission_type = 'attack';",
            (uid,),
        ).fetchone()
        assert int(mov["c"] or 0) == 0
        hangar_after = get_planet_ships(pid, conn=conn)
        assert hangar_after == hangar_before
        slots_after = get_fleet_slot_status(uid, conn=conn)
        assert int(slots_after["free"]) == 0
        assert int(slots_after["active"]) == 3
        # Fleet send path is closed for world boss.
        ok_wb, err_wb, _ = send_fleet(
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
        assert not ok_wb
        assert err_wb == "use_world_boss_attack"
        commit(conn)
    finally:
        conn.close()


def test_attack_cooldown_blocks_send(wb_db):
    """GC-WB-ATTACK-002 — cooldown blocks instant attack; fleet send rejected."""
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
        blocked = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now + 10,
            rng=__import__("random").Random(2),
        )
        assert not blocked["ok"]
        assert blocked["error"] == "world_boss_cooldown"
        ok_fleet, err_fleet, _ = send_fleet(
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
        assert not ok_fleet
        assert err_fleet == "use_world_boss_attack"
        conn.execute(
            "UPDATE world_boss_contributions SET last_attack_at = ? WHERE event_id = ? AND player_id = ?;",
            (now - WAVE_COOLDOWN_SEC - 1, event_id, uid),
        )
        ok2 = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now + 1,
            rng=__import__("random").Random(3),
        )
        assert ok2["ok"], ok2
        assert int(ok2["attack"]["damage"]) > 0
        row = conn.execute(
            "SELECT last_attack_at, waves, damage FROM world_boss_contributions "
            "WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert row is not None
        assert float(row["last_attack_at"] or 0) > 0
        assert int(row["waves"] or 0) == 2  # seeded wave + instant
        assert float(ok2["player"]["cooldown_until"]) == pytest.approx(
            float(row["last_attack_at"]) + WAVE_COOLDOWN_SEC, abs=1.5
        )
        ok3 = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 5},
            planet_id=pid,
            conn=conn,
            now=now + 2,
            rng=__import__("random").Random(4),
        )
        assert not ok3["ok"]
        assert ok3["error"] == "world_boss_cooldown"
        commit(conn)
    finally:
        conn.close()


def test_send_starts_cooldown_without_prior_contribution(wb_db):
    """Instant attack sets cooldown and wave/damage in one step."""
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
        now = time.time()
        result = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now,
            rng=__import__("random").Random(5),
        )
        assert result["ok"], result
        row = conn.execute(
            "SELECT last_attack_at, waves, damage FROM world_boss_contributions "
            "WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert row is not None
        assert float(row["last_attack_at"] or 0) > 0
        assert int(row["waves"] or 0) == 1
        assert int(row["damage"] or 0) > 0
        again = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 5},
            planet_id=pid,
            conn=conn,
            now=now + 1,
            rng=__import__("random").Random(6),
        )
        assert not again["ok"]
        assert again["error"] == "world_boss_cooldown"
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


def test_select_world_boss_auto_attack_ships_trims_overkill(wb_db):
    """Hangar past the current wave HP cap → send only what is needed for the cap."""
    hangar = {
        "ironclad_frigate": 2_000_000,
        "falcon_interceptor": 10_000,
        "mule_courier": 99_000,
    }
    defender = {"falcon_interceptor": 20}
    selected, meta = select_world_boss_auto_attack_ships(
        hangar,
        defender_ships=defender,
        max_hp=5_000_000,
        event_id=42,
        safety_parts=500,
    )
    assert meta["damage_full"] >= meta["damage_cap"] > 0
    assert meta["trimmed"] is True
    assert meta["sent_count"] < meta["pool_sent_count"]
    assert meta["sent_count"] == sum(selected.values())
    assert "mule_courier" not in selected
    assert selected
    # Trimmed fleet still hits the boss wave damage cap.
    assert meta["damage_estimate"] >= meta["damage_target"]
    assert meta["damage_estimate"] >= meta["damage_cap"]


def test_resolve_world_boss_auto_attack_ships_combat_only(wb_db):
    """GC-WB-AUTO-ATTACK-001 — only combat role + eclipse_runner; cargo ignored."""
    uid = _player(name="AutoPick")
    pid = _home(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        add_planet_ships(
            pid,
            uid,
            {
                "falcon_interceptor": 10,
                "ironclad_frigate": 2,
                "eclipse_runner": 3,
                "mule_courier": 50,
                "veil_probe": 5,
            },
            conn=conn,
        )
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs, hp = int(home["galaxy"]), int(home["system"]), int(home["position"])
        boss_pos = 8 if hp != 8 else 9
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        commit(conn)
        ok, reason, meta = resolve_world_boss_auto_attack_ships(
            uid,
            pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            conn=conn,
        )
        assert ok is True
        assert reason == ""
        assert "mule_courier" not in meta["ships"]
        assert "veil_probe" not in meta["ships"]
        assert set(meta["ships"]).issubset(
            {"falcon_interceptor", "ironclad_frigate", "eclipse_runner"}
        )
        assert meta["sent_count"] > 0
        assert meta["sent_count"] <= 15
    finally:
        conn.close()


def test_resolve_world_boss_auto_attack_ships_empty(wb_db):
    uid = _player(name="AutoEmpty")
    pid = _home(uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        add_planet_ships(pid, uid, {"mule_courier": 20}, conn=conn)
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs, hp = int(home["galaxy"]), int(home["system"]), int(home["position"])
        boss_pos = 5 if hp != 5 else 6
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        commit(conn)
        ok, reason, meta = resolve_world_boss_auto_attack_ships(
            uid,
            pid,
            target_galaxy=hg,
            target_system=hs,
            target_position=boss_pos,
            conn=conn,
        )
        assert ok is False
        assert reason == "no_combat_ships_available"
        assert meta["sent_count"] == 0
    finally:
        conn.close()


def test_api_world_boss_instant_attack(wb_db, monkeypatch):
    """GC-WB-ATTACK-002 — POST /api/world-boss/attack deals damage without hangar loss."""
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uid = _player(name="InstantAtk")
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
        boss_pos = 8 if hp != 8 else 9
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=hg,
            system=hs,
            position=boss_pos,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        commit(conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    before = get_planet_ships(pid)
    res = client.post(
        "/api/world-boss/attack",
        json={
            "event_id": event_id,
            "ships": {"falcon_interceptor": 20, "ironclad_frigate": 5},
            "request_id": "wb-atk-1",
        },
        headers={"Accept": "application/json", "X-Request-Id": "wb-atk-1"},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert body["ok"] is True
    assert body["attack"]["damage"] > 0
    assert "projectile_profile" in body["attack"]
    assert body["boss"]["hp"] < body["boss"]["max_hp"]
    assert body["player"]["cooldown_until"] > 0
    assert "state" in body
    assert get_planet_ships(pid) == before

    # Idempotent replay
    res_idemp = client.post(
        "/api/world-boss/attack",
        json={
            "event_id": event_id,
            "ships": {"falcon_interceptor": 20},
            "request_id": "wb-atk-1",
        },
        headers={"Accept": "application/json", "X-Request-Id": "wb-atk-1"},
    )
    assert res_idemp.status_code == 200
    assert res_idemp.get_json()["attack"]["damage"] == body["attack"]["damage"]

    # Cooldown blocks second distinct request
    res2 = client.post(
        "/api/world-boss/attack",
        json={
            "event_id": event_id,
            "ships": {"falcon_interceptor": 5},
            "request_id": "wb-atk-2",
        },
        headers={"Accept": "application/json"},
    )
    assert res2.status_code == 400
    assert res2.get_json()["error"] == "world_boss_cooldown"

    # Fleet send path closed
    res_fleet = client.post(
        "/api/fleet/send",
        json={
            "mission_type": "attack",
            "target_galaxy": hg,
            "target_system": hs,
            "target_position": boss_pos,
            "target_type": "world_boss",
            "ships": {"falcon_interceptor": 5},
            "resources": {},
            "speed_percent": 100,
        },
        headers={"Accept": "application/json"},
    )
    assert res_fleet.status_code == 400
    assert res_fleet.get_json()["error"] == "use_world_boss_attack"


def test_api_world_boss_instant_attack_auto_select_no_ships(wb_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uid = _player(name="InstantNone")
    pid = _home(uid)
    _fund(pid)
    conn = db()
    try:
        begin_write_transaction(conn)
        home = conn.execute(
            "SELECT galaxy, system, position FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        hg, hs, hp = int(home["galaxy"]), int(home["system"]), int(home["position"])
        boss_pos = 7 if hp != 7 else 6
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
        commit(conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.post(
        "/api/world-boss/attack",
        json={"event_id": event_id, "auto_select": True},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["error"] == "no_combat_ships_available"


def test_instant_attack_hp_never_below_zero(wb_db):
    uid = _player(name="FloorHp")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=2,
            position=9,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        conn.execute(
            "UPDATE world_boss_events SET max_hp = 1000000, current_hp = 2 WHERE id = ?;",
            (event_id,),
        )
        result = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 500, "ironclad_frigate": 100},
            planet_id=pid,
            conn=conn,
            rng=__import__("random").Random(99),
        )
        assert result["ok"], result
        assert int(result["boss"]["hp"]) == 0
        assert result["boss"]["defeated"] is True
        assert 1 <= int(result["attack"]["damage"]) <= 2
        # Direct DB floor check — never negative.
        hp_row = conn.execute(
            "SELECT current_hp FROM world_boss_events WHERE id = ?;",
            (event_id,),
        ).fetchone()
        assert int(hp_row["current_hp"]) == 0
        blocked = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=time.time() + WAVE_COOLDOWN_SEC + 5,
            rng=__import__("random").Random(100),
        )
        assert not blocked["ok"]
        assert blocked["error"] in ("world_boss_defeated", "world_boss_inactive")
        commit(conn)
    finally:
        conn.close()


def test_payload_flush_fires_ready_auto_attack(wb_db):
    """Auto on + CD free → build_world_boss_payload opportunistic fire (no worker)."""
    from game.world_boss import (
        build_world_boss_payload,
        execute_instant_attack,
        set_world_boss_auto_attack,
    )

    uid = _player(name="AutoFlush")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=1,
            system=9,
            position=4,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        now = time.time()
        first = execute_instant_attack(
            uid,
            event_id,
            None,
            planet_id=pid,
            conn=conn,
            now=now,
            auto_select=True,
        )
        assert first["ok"], first
        enabled = set_world_boss_auto_attack(
            uid,
            event_id,
            enabled=True,
            planet_id=pid,
            conn=conn,
            now=now + 10,
            auto_select=True,
        )
        assert enabled["ok"]
        assert enabled["fired"] is False
        dmg_mid = int(
            conn.execute(
                "SELECT damage FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
                (event_id, uid),
            ).fetchone()["damage"]
            or 0
        )
        # Cooldown still active — payload must not fire.
        build_world_boss_payload(uid, conn=conn, now=now + 10, flush_auto=True)
        dmg_cd = int(
            conn.execute(
                "SELECT damage FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
                (event_id, uid),
            ).fetchone()["damage"]
            or 0
        )
        assert dmg_cd == dmg_mid

        # After cooldown — payload flush fires without calling tick_world_boss_auto_attacks.
        payload = build_world_boss_payload(
            uid, conn=conn, now=now + WAVE_COOLDOWN_SEC + 5, flush_auto=True
        )
        assert payload["ready"] is True
        row = conn.execute(
            "SELECT damage, waves, auto_attack_enabled, last_attack_at "
            "FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert int(row["damage"] or 0) > dmg_mid
        assert int(row["waves"] or 0) == 2
        assert int(row["auto_attack_enabled"] or 0) == 1
        assert float(row["last_attack_at"] or 0) >= now + WAVE_COOLDOWN_SEC
        player = (payload["events"][0].get("player") or {}) if payload.get("events") else {}
        assert int((player.get("contribution") or {}).get("waves") or 0) == 2
        flushed = payload.get("flushed_attacks") or []
        assert len(flushed) >= 1
        assert flushed[0].get("attack") and flushed[0]["attack"].get("damage")
        assert flushed[0].get("boss") and "hp" in flushed[0]["boss"]
        commit(conn)
    finally:
        conn.close()


def test_auto_attack_enable_fires_immediate_when_cooldown_free(wb_db):
    """Enable with free cooldown → immediate instant strike + flag on."""
    from game.world_boss import set_world_boss_auto_attack

    uid = _player(name="AutoImmediate")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=1,
            system=5,
            position=8,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        hangar_before = get_planet_ships(pid, conn=conn)
        now = time.time()
        enabled = set_world_boss_auto_attack(
            uid,
            event_id,
            enabled=True,
            planet_id=pid,
            conn=conn,
            now=now,
            auto_select=True,
        )
        assert enabled["ok"], enabled
        assert enabled["enabled"] is True
        assert enabled["fired"] is True
        assert int(enabled["attack"]["damage"]) > 0
        assert enabled["boss"]["hp"] < enabled["boss"]["max_hp"]
        assert get_planet_ships(pid, conn=conn) == hangar_before
        row = conn.execute(
            "SELECT damage, waves, auto_attack_enabled "
            "FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert int(row["damage"] or 0) > 0
        assert int(row["waves"] or 0) == 1
        assert int(row["auto_attack_enabled"] or 0) == 1
        commit(conn)
    finally:
        conn.close()


def test_auto_attack_enable_skips_strike_on_cooldown(wb_db):
    """Enable while cooldown active → flag on, no extra damage."""
    from game.world_boss import execute_instant_attack, set_world_boss_auto_attack

    uid = _player(name="AutoCooldown")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
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
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        now = time.time()
        first = execute_instant_attack(
            uid,
            event_id,
            None,
            planet_id=pid,
            conn=conn,
            now=now,
            auto_select=True,
        )
        assert first["ok"], first
        dmg_after = int(
            conn.execute(
                "SELECT damage FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
                (event_id, uid),
            ).fetchone()["damage"]
            or 0
        )
        enabled = set_world_boss_auto_attack(
            uid,
            event_id,
            enabled=True,
            planet_id=pid,
            conn=conn,
            now=now + 10,
            auto_select=True,
        )
        assert enabled["ok"], enabled
        assert enabled["enabled"] is True
        assert enabled["fired"] is False
        assert enabled.get("on_cooldown") is True
        assert enabled.get("attack") is None
        row = conn.execute(
            "SELECT damage, waves, auto_attack_enabled "
            "FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert int(row["damage"] or 0) == dmg_after
        assert int(row["waves"] or 0) == 1
        assert int(row["auto_attack_enabled"] or 0) == 1
        commit(conn)
    finally:
        conn.close()


def test_server_auto_attack_tick_fires_and_stops(wb_db):
    """GC-WB-AUTO-004 — tick fires follow-up after cooldown; stops when disabled."""
    from game.world_boss import set_world_boss_auto_attack, tick_world_boss_auto_attacks

    uid = _player(name="AutoTick")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "void_titan",
            conn=conn,
            galaxy=1,
            system=5,
            position=8,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        hangar_before = get_planet_ships(pid, conn=conn)
        now = time.time()
        enabled = set_world_boss_auto_attack(
            uid,
            event_id,
            enabled=True,
            planet_id=pid,
            conn=conn,
            now=now,
            auto_select=True,
        )
        assert enabled["ok"], enabled
        assert enabled["enabled"] is True
        assert enabled["ships"]
        assert enabled["fired"] is True
        assert get_planet_ships(pid, conn=conn) == hangar_before
        row = conn.execute(
            "SELECT damage, waves, auto_attack_enabled, last_attack_at "
            "FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert int(row["damage"] or 0) > 0
        assert int(row["waves"] or 0) == 1
        assert int(row["auto_attack_enabled"] or 0) == 1

        # Immediate strike already consumed cooldown — same-now tick must not double-fire.
        tick1 = tick_world_boss_auto_attacks(conn=conn, now=now)
        assert tick1["fired"] == 0

        # Still on cooldown — no second fire.
        tick2 = tick_world_boss_auto_attacks(conn=conn, now=now + 10)
        assert tick2["fired"] == 0

        # After cooldown, tick fires follow-up.
        tick3 = tick_world_boss_auto_attacks(conn=conn, now=now + WAVE_COOLDOWN_SEC + 2)
        assert tick3["fired"] == 1
        row2 = conn.execute(
            "SELECT waves FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (event_id, uid),
        ).fetchone()
        assert int(row2["waves"] or 0) == 2

        disabled = set_world_boss_auto_attack(
            uid,
            event_id,
            enabled=False,
            planet_id=pid,
            conn=conn,
        )
        assert disabled["ok"]
        assert disabled["enabled"] is False
        tick4 = tick_world_boss_auto_attacks(conn=conn, now=now + WAVE_COOLDOWN_SEC * 3)
        assert tick4["fired"] == 0
        commit(conn)
    finally:
        conn.close()


def test_api_world_boss_auto_attack_toggle(wb_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uid = _player(name="AutoApi")
    pid = _home(uid)
    _fund(pid)
    _seed_combat_fleet(pid, uid)
    conn = db()
    try:
        begin_write_transaction(conn)
        spawn = spawn_world_boss(
            "planet_eater",
            conn=conn,
            galaxy=1,
            system=6,
            position=7,
            announce=False,
        )
        assert spawn["ok"], spawn
        event_id = int(spawn["event"]["id"])
        commit(conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post(
        "/api/world-boss/auto-attack",
        json={"event_id": event_id, "enabled": True, "auto_select": True},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert body["ok"] is True
    assert body["auto_attack"]["enabled"] is True
    assert body["auto_attack"]["ships"]
    assert body["auto_attack"]["fired"] is True
    assert body["attack"] and int(body["attack"]["damage"]) > 0
    assert body["boss"] and "hp" in body["boss"]
    assert body["player"] and body["player"]["cooldown_until"]

    res_off = client.post(
        "/api/world-boss/auto-attack",
        json={"event_id": event_id, "enabled": False},
        headers={"Accept": "application/json"},
    )
    assert res_off.status_code == 200
    assert res_off.get_json()["auto_attack"]["enabled"] is False

    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert "/api/world-boss/auto-attack" in main_js
    assert "wbPlayAttackFx(card, res.attack, res.boss)" in main_js
    page = Path("templates/world_boss.html").read_text(encoding="utf-8")
    assert "data-wb-auto-enabled" in page
    css = Path("static/style.css").read_text(encoding="utf-8")
    assert ".gc-world-boss-page .gc-world-boss-hero-art" in css
    assert ".gc-world-boss-page .gc-world-boss-layout" in css
    assert "minmax(220px, 280px)" in css or "gc-world-boss-layout" in css
    assert "overflow: visible" in css
    assert "border: none" in css


def test_instant_attack_hit_mult_x5_damage_and_cooldown(wb_db):
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
        x1 = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now,
            rng=__import__("random").Random(42),
            hit_mult=1,
        )
        assert x1["ok"], x1
        dmg1 = int(x1["attack"]["damage"])
        conn.execute(
            "UPDATE world_boss_contributions SET last_attack_at = 0, waves = 0, damage = 0 WHERE event_id = ? AND player_id = ?",
            (event_id, uid),
        )
        conn.execute(
            "UPDATE world_boss_events SET current_hp = max_hp, status = 'active' WHERE id = ?",
            (event_id,),
        )
        x5 = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now + 1,
            rng=__import__("random").Random(42),
            hit_mult=5,
        )
        assert x5["ok"], x5
        assert int(x5["attack"]["hit_mult"]) == 5
        dmg5 = int(x5["attack"]["damage"])
        wave_cap = max(1, int(float(x5["boss"]["max_hp"]) * 0.03))
        assert dmg5 > dmg1
        # ×5 must be able to exceed the single-wave cap and must not land on exact 5×cap.
        assert dmg5 != wave_cap * 5
        if dmg1 >= wave_cap - 1:
            assert dmg5 > wave_cap
        cd = float(x5["player"]["cooldown_until"]) - (now + 1)
        assert abs(cd - 1500) < 1.5
        assert int(x5["player"]["waves"]) == 5
        bad = execute_instant_attack(
            uid,
            event_id,
            {"falcon_interceptor": 10},
            planet_id=pid,
            conn=conn,
            now=now + 1,
            hit_mult=3,
        )
        assert not bad["ok"]
        assert bad["error"] == "invalid_hit_mult"
        page = Path("templates/world_boss.html").read_text(encoding="utf-8")
        assert 'data-wb-hit-mult="5"' in page
        assert "wb-hit-group" in page
        css = Path("static/style.css").read_text(encoding="utf-8")
        assert ".gc-world-boss-page .wb-hit-group" in css
        commit(conn)
    finally:
        conn.close()
