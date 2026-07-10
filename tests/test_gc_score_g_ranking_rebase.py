"""
GC-SCORE-G — live audit score rebase flag + admin ranking recompute.

Run: python -m pytest tests/test_gc_score_g_ranking_rebase.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.economy_live_audit import (
    FLAG_RANKING_SCORE_REBASE,
    audit_player,
    migration_recommendations,
)
from game.internal_cron import execute_ranking_recompute
from game.models import create_user, init_db, save_planet_buildings
from game.ranking import compute_player_scores, get_player_score_row, refresh_player_score

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_score_g.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])


@pytest.fixture(autouse=True)
def _db_ready(temp_db):
    _close_db()
    init_db()
    _close_db()
    _run_migrate(temp_db)
    yield
    _close_db()



def test_audit_flags_score_rebase_when_persisted_scores_stale():
    pid = _create_player("stale_scores")
    conn = db()
    try:
        refresh_player_score(pid, conn=conn)
        computed = compute_player_scores(pid, conn=conn)
        inflated = max(int(computed["total_score"] * 3), int(computed["total_score"]) + 100)
        conn.execute(
            "UPDATE player_scores SET score_buildings = ? WHERE player_id = ?;",
            (inflated, pid),
        )
        conn.commit()

        audit = audit_player(pid, conn=conn)
        assert FLAG_RANKING_SCORE_REBASE in audit.flags
        assert audit.score_total_stored != audit.score_total
        recs = migration_recommendations(audit)
        assert any("ranking/recompute" in rec.lower() for rec in recs)
    finally:
        conn.close()


def test_audit_no_score_rebase_flag_after_refresh():
    pid = _create_player("fresh_scores")
    conn = db()
    try:
        refresh_player_score(pid, conn=conn)
        audit = audit_player(pid, conn=conn)
        assert FLAG_RANKING_SCORE_REBASE not in audit.flags
        assert audit.score_total_stored == audit.score_total
    finally:
        conn.close()


def test_admin_ranking_recompute_aligns_persisted_scores():
    pid = _create_player("recompute_align")
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
            (pid,),
        ).fetchone()
        save_planet_buildings(int(row["id"]), {"metal_mine": 12, "solar_plant": 8})
        computed = compute_player_scores(pid, conn=conn)
        conn.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, 1, 1, 0, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                updated_at = excluded.updated_at
            """,
            (pid,),
        )
        conn.commit()

        audit_before = audit_player(pid, conn=conn)
        assert FLAG_RANKING_SCORE_REBASE in audit_before.flags
    finally:
        conn.close()

    payload = execute_ranking_recompute(force=True, source="test_gc_score_g")
    assert payload["ok"] is True
    assert int(payload.get("players_updated") or 0) >= 1

    conn = db()
    try:
        stored = get_player_score_row(pid, conn=conn)
        assert stored is not None
        assert int(stored["score_total"]) == int(computed["total_score"])

        audit_after = audit_player(pid, conn=conn)
        assert FLAG_RANKING_SCORE_REBASE not in audit_after.flags
    finally:
        conn.close()
