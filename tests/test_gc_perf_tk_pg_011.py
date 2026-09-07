"""GC-PERF-TK-PG-011 — Timekeeper must not scan unrelated queues on PostgreSQL."""

from unittest.mock import patch

from game.inventory_use import _finish_inventory_due_work


def test_domain_targeted_inventory_finish_runs_one_central_pass():
    result = {"ok": True, "errors": [], "finished": {}}
    with patch("game.queue_engine.finish_due_work", return_value=result) as finish, patch(
        "game.queue_poll.player_has_due_queue_work"
    ) as any_due:
        out = _finish_inventory_due_work(
            object(),
            7,
            planet_id=11,
            source="timekeeper_apply",
            domains=["build"],
        )

    assert out is result
    finish.assert_called_once()
    kwargs = finish.call_args.kwargs
    assert kwargs["queue_domains"] == {"build"}
    assert kwargs["include_fleet"] is False
    assert kwargs["include_relocations"] is False
    any_due.assert_not_called()


def test_timekeeper_calls_domain_scoped_finisher_and_skips_partial_build_post_pass():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tk = (root / "game" / "timekeeper.py").read_text(encoding="utf-8")
    engine = (root / "game" / "queue_engine.py").read_text(encoding="utf-8")

    assert "_finish_before_apply(conn, uid, pid if pid > 0 else None, dom)" in tk
    assert 'if dom in ("build", "research"):' in tk
    assert 'post_finish_needed = dom not in ("build", "research")' in tk
    assert "queue_domains: Optional[Set[str]] = None" in engine
    assert 'run_build = _domain_enabled("build")' in engine
    assert 'run_shipyard = _domain_enabled("shipyard")' in engine
    assert 'run_defense = _domain_enabled("defense")' in engine
    assert 'run_troops = _domain_enabled("troops")' in engine


def test_committed_build_response_reuses_mutation_connection_and_skips_generic_state():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")

    helper = app.split("def _timekeeper_apply_game_state(", 1)[1].split(
        "\ndef _is_buildings_queue_action_source(", 1
    )[0]
    fast = helper.split(
        'if post_mutation_committed and conn is not None and uid > 0 and dom in ("build", "research"):',
        1,
    )[1].split('    state, _ = _build_game_state_payload(', 1)[0]
    assert "get_build_queue_status_for_planet(" in fast
    assert "skip_finish=True" in fast
    assert "_build_game_state_payload(" not in fast
    assert '"nav_badges"' not in fast
    assert '"score"' not in fast
    assert '"active_fleets"' not in fast

    route = app.split("def api_timekeeper_apply():", 1)[1].split(
        '\n\n@app.route("/api/inventory/craft"', 1
    )[0]
    success = route.split("commit(conn)", 1)[1]
    assert "conn=conn" in success.split("_timekeeper_apply_game_state(", 1)[1]
    assert "SELECT balance_sec FROM timekeeper_balances" not in success
