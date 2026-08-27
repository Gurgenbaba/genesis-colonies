from __future__ import annotations

from unittest.mock import patch


def test_v5_action_pool_has_ships_and_expeditions():
    from game.inactive_autoplay import INACTIVE_ACTION_DOMAINS

    assert "ships" in INACTIVE_ACTION_DOMAINS
    assert "expedition" in INACTIVE_ACTION_DOMAINS


def test_v5_cadence_has_short_returns_and_long_breaks():
    from game.inactive_autoplay import _next_action_delay_sec

    gaps = [
        _next_action_delay_sec(pid, "aggressive", seq)
        for pid in range(1, 12)
        for seq in range(1, 40)
    ]
    assert min(gaps) <= 11 * 60
    assert max(gaps) >= 45 * 60


def test_v5_planet_choice_spreads_local_actions():
    from game.inactive_autoplay import _pick_progression_planet

    planets = [{"id": 1}, {"id": 2}, {"id": 3}]
    picked = {
        _pick_progression_planet(17, planets, action_seq=seq)["id"]
        for seq in range(20)
    }
    assert len(picked) >= 2


def test_v5_expedition_uses_canonical_send_fleet():
    from game.inactive_autoplay import _maybe_send_expedition

    force = {
        "planet": {"id": 77, "galaxy": 2, "system": 19},
        "planet_id": 77,
        "galaxy": 2,
        "system": 19,
        "ships": {"solar_skiff": 1},
    }
    meta = {"fleet": {"id": 555}}
    with patch(
        "game.inactive_autoplay._pick_expedition_force",
        return_value=force,
    ), patch(
        "game.inactive_autoplay._sync_planet_for_decision",
        return_value={},
    ), patch(
        "game.fleet.send_fleet",
        return_value=(True, "ok", meta),
    ) as send:
        out = _maybe_send_expedition(
            object(),
            9,
            now=12345.0,
            action_seq=6,
            home_id=77,
            personality="spy",
            ambition_scale=1.0,
        )

    assert out["sent"] is True
    assert out["fleet_id"] == 555
    kwargs = send.call_args.kwargs
    assert kwargs["mission_type"] == "expedition"
    assert kwargs["ships"] == {"solar_skiff": 1}
    assert 1 <= kwargs["expedition_hours"] <= 4


def test_v5_runtime_never_uses_resource_injection_floor():
    from game.inactive_autoplay import _run_player_economy

    home = {"id": 5, "is_homeworld": 1, "galaxy": 1, "system": 1}
    with patch("game.models.get_homeworld", return_value=home), patch(
        "game.models.get_planets_by_player", return_value=[home]
    ), patch(
        "game.inactive_autoplay._stockpile_snapshot",
        return_value={"metal": 0, "crystal": 0, "fuel_cells": 0, "raised": 0},
    ), patch(
        "game.inactive_autoplay._ensure_resource_floor"
    ) as floor, patch(
        "game.inactive_autoplay._action_domain_for_player",
        return_value="building",
    ), patch(
        "game.inactive_autoplay.plan_passive_planet_tick",
        return_value={"build": None, "finished": {}},
    ), patch(
        "game.inactive_autoplay._maybe_join_world_boss",
        return_value={"ok": True, "joined": False},
    ):
        out = _run_player_economy(object(), 4, now=1000.0, action_seq=0)

    assert out["ok"] is True
    floor.assert_not_called()


def test_v5_ship_decision_uses_real_shipyard_without_timekeeper_boost():
    from game.inactive_autoplay import _run_player_economy

    home = {"id": 5, "is_homeworld": 1, "galaxy": 1, "system": 1}
    ship_result = {
        "ok": True,
        "ship_key": "solar_skiff",
        "amount": 1,
        "meta": {},
    }
    with patch("game.models.get_homeworld", return_value=home), patch(
        "game.models.get_planets_by_player", return_value=[home]
    ), patch(
        "game.inactive_autoplay._stockpile_snapshot",
        return_value={},
    ), patch(
        "game.inactive_autoplay._action_domain_for_player",
        return_value="ships",
    ), patch(
        "game.inactive_autoplay._stable_roll", return_value=999
    ), patch(
        "game.inactive_autoplay._sync_planet_for_decision",
        return_value={"finished": {}},
    ), patch(
        "game.auto_empire.try_build_ships", return_value=ship_result
    ) as build, patch(
        "game.auto_empire._auto_boost_timekeeper"
    ) as boost, patch(
        "game.inactive_autoplay._maybe_join_world_boss",
        return_value={"ok": True, "joined": False},
    ):
        out = _run_player_economy(object(), 4, now=1000.0, action_seq=0)

    assert out["enqueued"] is True
    build.assert_called_once()
    boost.assert_not_called()
