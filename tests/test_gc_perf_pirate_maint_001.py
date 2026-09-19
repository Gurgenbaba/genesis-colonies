from __future__ import annotations

from unittest.mock import patch


def _planet() -> dict:
    return {"id": 17, "is_homeworld": 1}


def test_gc_perf_pirate_maint_001_busy_queues_are_probed_once():
    """Busy queues must short-circuit the whole candidate ladder."""
    from game.auto_empire import plan_passive_planet_tick

    with (
        patch("game.auto_empire._finish_due", return_value={}),
        patch("game.auto_empire._queue_has_building", return_value=True) as build_busy,
        patch("game.auto_empire._queue_has_research", return_value=True) as research_busy,
        patch("game.auto_empire.try_enqueue_building") as enqueue_build,
        patch("game.auto_empire.try_enqueue_research") as enqueue_research,
    ):
        result = plan_passive_planet_tick(
            object(),
            player_id=7,
            planet=_planet(),
            is_home=True,
            allow_ships=False,
            allow_defense=False,
            chain_limit=3,
        )

    assert result["build"] is None
    assert result["research"] is None
    assert build_busy.call_count == 1
    assert research_busy.call_count == 1
    enqueue_build.assert_not_called()
    enqueue_research.assert_not_called()


def test_gc_perf_pirate_maint_001_free_build_queue_reuses_probe_across_candidates():
    """Failed target candidates reuse the same known-free queue snapshot."""
    from game.auto_empire import plan_passive_planet_tick

    attempts = [
        {"ok": False, "error": "at_target"},
        {"ok": False, "error": "requirements"},
        {"ok": True, "job_id": 41, "building_type": "solar_plant", "target_level": 7},
    ]

    with (
        patch("game.auto_empire._finish_due", return_value={}),
        patch("game.auto_empire._queue_has_building", return_value=False) as build_busy,
        patch("game.auto_empire.try_enqueue_building", side_effect=attempts) as enqueue_build,
    ):
        result = plan_passive_planet_tick(
            object(),
            player_id=7,
            planet=_planet(),
            is_home=True,
            allow_research=False,
            allow_ships=False,
            allow_defense=False,
            chain_limit=1,
        )

    assert result["build"]["job_id"] == 41
    assert build_busy.call_count == 1
    assert enqueue_build.call_count == 3
    assert all(call.kwargs["queue_known_free"] is True for call in enqueue_build.call_args_list)


def test_gc_perf_pirate_maint_001_free_research_queue_reuses_probe_across_candidates():
    """Research candidate scans also issue only one account queue probe."""
    from game.auto_empire import plan_passive_planet_tick

    attempts = [
        {"ok": False, "error": "at_target"},
        {"ok": True, "job_id": 51, "tech_key": "mining_tech", "target_level": 8},
    ]

    with (
        patch("game.auto_empire._finish_due", return_value={}),
        patch("game.auto_empire._queue_has_research", return_value=False) as research_busy,
        patch("game.auto_empire.try_enqueue_research", side_effect=attempts) as enqueue_research,
    ):
        result = plan_passive_planet_tick(
            object(),
            player_id=7,
            planet=_planet(),
            is_home=True,
            allow_buildings=False,
            allow_research=True,
            allow_ships=False,
            allow_defense=False,
            chain_limit=1,
        )

    assert result["research"]["job_id"] == 51
    assert research_busy.call_count == 1
    assert enqueue_research.call_count == 2
    assert all(call.kwargs["queue_known_free"] is True for call in enqueue_research.call_args_list)
