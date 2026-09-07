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


def test_timekeeper_commit_does_not_reread_balance_before_existing_state_rebuild():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    route = app.split("def api_timekeeper_apply():", 1)[1].split(
        '\n\n@app.route("/api/inventory/craft"', 1
    )[0]
    success = route.split("commit(conn)", 1)[1]

    assert "SELECT balance_sec FROM timekeeper_balances" not in success
    assert "conn.close()" in success
    assert "_timekeeper_apply_game_state(" in success
    assert "post_mutation_committed=True" in success
