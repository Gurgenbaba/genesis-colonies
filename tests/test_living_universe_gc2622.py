from __future__ import annotations

from unittest.mock import patch


def test_gc2622_ambition_is_stable_but_not_cloned():
    from game.auto_empire import personality_for_player
    from game.inactive_autoplay import _ambition_scale

    values = []
    for player_id in range(1, 80):
        personality = personality_for_player(player_id)
        value = _ambition_scale(player_id, personality)
        assert value == _ambition_scale(player_id, personality)
        assert 0.72 <= value <= 1.55
        values.append(value)
    assert len(set(values)) >= 15


def test_gc2622_strategic_phases_are_stable_and_rotate():
    from game.inactive_autoplay import INACTIVE_STRATEGIC_PHASES, _strategic_phase_for_player

    seen = set()
    for player_id in range(1, 30):
        p0 = _strategic_phase_for_player(player_id, 0)
        assert p0 == _strategic_phase_for_player(player_id, 0)
        assert p0 in INACTIVE_STRATEGIC_PHASES
        seen.add(p0)
        for seq in (36, 72, 108, 144, 216, 288):
            seen.add(_strategic_phase_for_player(player_id, seq))
    assert seen == set(INACTIVE_STRATEGIC_PHASES)


def test_gc2622_planner_threads_target_scale_without_parallel_systems():
    from game.auto_empire import plan_passive_planet_tick

    build_result = {"ok": True, "job_id": 7, "building_type": "metal_mine", "target_level": 2, "duration": 60}
    with patch("game.auto_empire._finish_due", return_value={}), patch(
        "game.auto_empire.try_enqueue_building", return_value=build_result
    ) as enqueue:
        out = plan_passive_planet_tick(
            object(),
            player_id=17,
            planet={"id": 91},
            now=12345.0,
            allow_buildings=True,
            allow_research=False,
            allow_ships=False,
            allow_defense=False,
            target_scale=1.37,
        )
    assert out["build"]["job_id"] == 7
    assert enqueue.call_args.kwargs["target_scale"] == 1.37


def test_gc2622_inactive_decision_passes_personal_ambition():
    from game.auto_empire import personality_for_player
    from game.inactive_autoplay import _ambition_scale, _run_player_economy

    player_id = 23
    expected = _ambition_scale(player_id, personality_for_player(player_id))
    home = {"id": 101, "is_homeworld": 1}
    with patch("game.models.get_homeworld", return_value=home), patch(
        "game.models.get_planets_by_player", return_value=[home]
    ), patch("game.inactive_autoplay._stockpile_snapshot", return_value={}), patch(
        "game.inactive_autoplay.plan_passive_planet_tick"
    ) as planner, patch(
        "game.inactive_autoplay._maybe_join_world_boss", return_value={"ok": True, "joined": False}
    ):
        planner.return_value = {
            "build": None,
            "research": None,
            "defense": None,
            "builds": [],
            "researches": [],
            "finished": {},
        }
        result = _run_player_economy(object(), player_id, now=50000.0, action_seq=4)

    assert planner.call_args.kwargs["target_scale"] == expected
    assert result["ambition_scale"] == expected
    assert result["strategic_phase"]
