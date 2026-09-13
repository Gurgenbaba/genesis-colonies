from __future__ import annotations

from unittest.mock import patch


def test_action_pool_has_asteroids_and_world_boss_as_real_decisions():
    from game.inactive_autoplay import INACTIVE_ACTION_DOMAINS

    assert "asteroid" in INACTIVE_ACTION_DOMAINS
    assert "world_boss" in INACTIVE_ACTION_DOMAINS


def test_shift_eviction_restores_real_presence_and_sets_revisit_cooldown():
    from game.inactive_autoplay import _park_roster_member

    item = {
        "player_id": 44,
        "presence_before_shift": 123,
        "builds_done": 0,
        "research_done": 0,
        "defense_done": 0,
    }
    with patch("game.inactive_autoplay.set_presence_last_seen") as restore, patch(
        "game.inactive_autoplay._record_revisit_cooldown"
    ) as cooldown, patch("game.inactive_autoplay._send_autoplay_report") as report:
        _park_roster_member(object(), item, now=1_000.0)

    restore.assert_called_once_with(object(), 44, last_seen=123)
    cooldown.assert_called_once_with(object(), 44, now=1_000.0)
    report.assert_called_once_with(object(), item)


def test_asteroid_activity_uses_canonical_recycle_send():
    from game.living_universe_strategy import maybe_harvest_asteroid

    planet = {"id": 7, "galaxy": 1, "system": 10}
    asteroid = {
        "id": 91,
        "galaxy": 1,
        "system": 12,
        "position": 5,
        "coords": "[1:12:5]",
        "total": 900_000,
        "recycler_slots_needed": 9,
    }
    meta = {"fleet": {"id": 123}, "effective_ships": {"harvest_reclaimer": 7}}
    with patch(
        "game.models.get_planets_by_player", return_value=[planet]
    ), patch(
        "game.asteroids.list_active_asteroids", return_value=[asteroid]
    ), patch(
        "game.fleet.get_planet_ships", return_value={"harvest_reclaimer": 7}
    ), patch(
        "game.fleet.send_fleet", return_value=(True, "", meta)
    ) as send:
        out = maybe_harvest_asteroid(
            object(), 44, now=1_000.0, action_seq=5, personality="economy"
        )

    assert out["sent"] is True
    assert out["ships"] == {"harvest_reclaimer": 7}
    kwargs = send.call_args.kwargs
    assert kwargs["mission_type"] == "recycle"
    assert kwargs["target_galaxy"] == 1
    assert kwargs["target_system"] == 12
    assert kwargs["target_position"] == 5
    assert kwargs["ships"] == {"harvest_reclaimer": 7}


def test_asteroid_activity_builds_reclaimers_before_fake_one_ship_trip():
    from game.living_universe_strategy import maybe_harvest_asteroid

    planet = {"id": 7, "galaxy": 1, "system": 10}
    asteroid = {
        "id": 91,
        "galaxy": 1,
        "system": 12,
        "position": 5,
        "coords": "[1:12:5]",
        "total": 900_000,
        "recycler_slots_needed": 9,
    }
    with patch(
        "game.models.get_planets_by_player", return_value=[planet]
    ), patch(
        "game.asteroids.list_active_asteroids", return_value=[asteroid]
    ), patch(
        "game.fleet.get_planet_ships", return_value={"harvest_reclaimer": 1}
    ), patch(
        "game.shipyard.build_ships", return_value=(True, "", {"job_id": 6})
    ) as build, patch("game.fleet.send_fleet") as send:
        out = maybe_harvest_asteroid(
            object(), 44, now=1_000.0, action_seq=5, personality="economy"
        )

    assert out["sent"] is False
    assert out["built"] is True
    assert out["reason"] == "preparing_reclaimers"
    assert build.call_args.kwargs["ship_key"] == "harvest_reclaimer"
    assert build.call_args.kwargs["amount"] > 1
    send.assert_not_called()


def test_world_boss_activity_uses_real_selector_and_never_token_ship():
    from game.living_universe_strategy import maybe_join_world_boss

    planet = {"id": 8, "galaxy": 1, "system": 1}
    event = {"id": 3, "boss_key": "test", "max_hp": 1_000_000, "current_hp": 800_000}
    hangar = {"falcon_interceptor": 40, "ironclad_frigate": 20}
    selected = {"falcon_interceptor": 12, "ironclad_frigate": 6}
    with patch(
        "game.world_boss.list_active_events", return_value=[event]
    ), patch(
        "game.world_boss.can_player_attack_boss", return_value=(True, "", {"waves": 0})
    ), patch(
        "game.models.get_planets_by_player", return_value=[planet]
    ), patch(
        "game.fleet.get_planet_ships", return_value=hangar
    ), patch(
        "game.world_boss.combat_ships_from_hangar", return_value=hangar
    ), patch(
        "game.world_boss.defender_ships_for_event", return_value={"boss_hull": 10}
    ), patch(
        "game.world_boss.select_world_boss_auto_attack_ships",
        return_value=(selected, {"damage_estimate": 20_000}),
    ) as selector, patch(
        "game.world_boss.execute_instant_attack", return_value={"ok": True, "damage": 19_500}
    ) as attack:
        out = maybe_join_world_boss(
            object(), 44, now=1_000.0, personality="aggressive", fallback_planet_id=8
        )

    assert out["joined"] is True
    assert out["sent_count"] == 18
    assert sum(out["ships"].values()) > 1
    assert selector.called
    assert attack.call_args.args[2] == selected


def test_world_boss_small_hangar_builds_instead_of_one_ship_poke():
    from game.living_universe_strategy import maybe_join_world_boss

    planet = {"id": 8, "galaxy": 1, "system": 1}
    event = {"id": 3, "boss_key": "test", "max_hp": 1_000_000, "current_hp": 800_000}
    with patch(
        "game.world_boss.list_active_events", return_value=[event]
    ), patch(
        "game.world_boss.can_player_attack_boss", return_value=(True, "", {"waves": 0})
    ), patch(
        "game.models.get_planets_by_player", return_value=[planet]
    ), patch(
        "game.fleet.get_planet_ships", return_value={"falcon_interceptor": 1}
    ), patch(
        "game.world_boss.combat_ships_from_hangar", return_value={"falcon_interceptor": 1}
    ), patch(
        "game.auto_empire.try_build_ships",
        return_value={"ok": True, "ship_key": "falcon_interceptor", "amount": 8},
    ) as build, patch("game.world_boss.execute_instant_attack") as attack:
        out = maybe_join_world_boss(
            object(), 44, now=1_000.0, personality="aggressive", fallback_planet_id=8
        )

    assert out["joined"] is False
    assert out["building"] is True
    assert out["reason"] == "preparing_combat_fleet"
    build.assert_called_once()
    attack.assert_not_called()
