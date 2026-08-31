"""Hotfix guards for Postgres cutover TX / case-battles ORDER BY."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_case_battles_list_my_battles_pg_order_by():
    source = (ROOT / "game" / "case_battles.py").read_text(encoding="utf-8")
    assert "ORDER BY COALESCE(b.finished_at, b.started_at, b.created_at) DESC" not in source
    assert "GROUP BY b.id" in source
    assert "MAX(COALESCE(b.finished_at, b.started_at, b.created_at))" in source


def test_runtime_state_uses_savepoint_on_shared_conn():
    source = (ROOT / "game" / "runtime_state.py").read_text(encoding="utf-8")
    assert "SAVEPOINT" in source
    assert "ROLLBACK TO SAVEPOINT" in source
    assert "deadlock" in source.lower()


def test_page_live_context_rolls_back_after_initiation_failure():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "initiation page visit failed" in source
    assert "_rollback_conn(conn)" in source
