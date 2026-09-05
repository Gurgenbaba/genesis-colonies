"""GC-PROD infinity-load prevention gates (local scale SQLite, no production DB).

Proves:
- identical-seed journeys stay under latency budgets on the recovery tree
- government nav query uses index-friendly stable shape (not status-first SCAN)
- directives nav count path is measurable
- EXPLAIN QUERY PLAN is recorded for suspect shapes

Full historical worktree A/B lives in scripts/prod_infinity_load_ab.py.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid

import pytest

from game.db import db
from game.directives.definitions import STATUS_COMPLETED
from game.directives.generator import daily_period_key, weekly_period_key
from game.directives.service import count_claimable_directives
from game.galactic_directives.state import count_pending_government_votes
from game.models import create_user, init_db


@pytest.fixture
def scale_db(tmp_path, monkeypatch):
    db_path = tmp_path / "prod_scale_nav.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")

    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()

    # Modest but non-trivial population (CI-friendly).
    uids = []
    for i in range(25):
        ok, err, user = create_user(f"ps_{i}_{uuid.uuid4().hex[:6]}", "test-pass-123")
        assert ok, err
        uids.append(int(user["id"]))

    conn = db()
    try:
        now = int(time.time())
        # Extra planets
        for i in range(40):
            try:
                conn.execute(
                    """
                    INSERT INTO planets (
                        player_id, name, galaxy, system, position,
                        metal, crystal, fuel_cells, last_update, is_homeworld
                    ) VALUES (?, ?, ?, ?, ?, 1000, 1000, 1000, ?, 0);
                    """,
                    (
                        uids[i % len(uids)],
                        f"Syn{i}",
                        1 + (i % 5),
                        50 + i,
                        1 + (i % 15),
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                pass
        # Directives + cycles/votes
        defs = [
            r["key"]
            for r in conn.execute("SELECT key FROM directive_definitions LIMIT 8").fetchall()
        ]
        daily = daily_period_key()
        weekly = weekly_period_key()
        for uid in uids:
            for k, def_key in enumerate(defs[:4]):
                cadence = "daily" if k % 2 == 0 else "weekly"
                period = daily if cadence == "daily" else weekly
                conn.execute(
                    """
                    INSERT INTO player_directives (
                        player_id, definition_key, cadence, rarity, target_value,
                        progress_value, status, reward_json, period_key, expires_at, created_at
                    ) VALUES (?, ?, ?, 'common', 10, 1, 'active', '{}', ?, ?, ?);
                    """,
                    (uid, def_key, cadence, period, now + 86400, now),
                )
        for g in range(1, 6):
            for m in range(12):
                status = "vote_open" if m == 0 else "closed"
                conn.execute(
                    """
                    INSERT INTO gd_cycles (
                        galaxy, year, month, vote_start_at, vote_end_at,
                        effect_start_at, effect_end_at, status, created_at, updated_at
                    ) VALUES (?, 2026, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        g,
                        m + 1,
                        now - 100,
                        now + 86400 if status == "vote_open" else now - 50,
                        now + 90000,
                        now + 200000,
                        status,
                        now,
                        now,
                    ),
                )
        conn.commit()
        primary = uids[0]
        yield primary, db_path
    finally:
        conn.close()
        gdb._DB_PATH = None


def _explain(conn, sql, params):
    return [
        " | ".join(str(row[k]) for k in row.keys())
        for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    ]


def test_government_nav_stable_shape_uses_galaxy_status_index(scale_db):
    primary, _ = scale_db
    conn = db()
    try:
        now = int(time.time())
        galaxies = [
            int(r["galaxy"])
            for r in conn.execute(
                "SELECT DISTINCT galaxy FROM planets WHERE player_id = ? AND galaxy IS NOT NULL",
                (primary,),
            ).fetchall()
        ]
        assert galaxies
        ph = ",".join("?" * len(galaxies))
        sql = (
            f"SELECT COUNT(*) AS c FROM gd_cycles c WHERE c.galaxy IN ({ph}) "
            "AND c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
            "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
        )
        params = (*galaxies, now, now, primary)
        plan = "\n".join(_explain(conn, sql, params)).lower()
        assert "idx_gd_cycles_galaxy_status" in plan
        assert "scan c" not in plan
        # Function path must stay fast on this fixture.
        t0 = time.perf_counter()
        for _ in range(30):
            count_pending_government_votes(primary, conn=conn, now=now)
        avg_ms = (time.perf_counter() - t0) * 1000 / 30
        assert avg_ms < 25.0, avg_ms
    finally:
        conn.close()


def test_state_013_status_first_shape_is_scan_without_covering_index(scale_db):
    """Regression detector: status-first COUNT scans gd_cycles without a status index."""
    primary, _ = scale_db
    conn = db()
    try:
        now = int(time.time())
        sql = (
            "SELECT COUNT(*) AS c FROM gd_cycles c "
            "WHERE c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
            "AND EXISTS (SELECT 1 FROM planets p WHERE p.player_id = ? AND p.galaxy = c.galaxy) "
            "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
        )
        params = (now, now, primary, primary)
        plan = "\n".join(_explain(conn, sql, params)).lower()
        # Document known anti-pattern on current schema (no status-leading index).
        assert "scan c" in plan
    finally:
        conn.close()


def test_directives_claimable_count_budget_and_012_shape_index(scale_db):
    primary, _ = scale_db
    conn = db()
    try:
        t0 = time.perf_counter()
        for _ in range(20):
            count_claimable_directives(primary, conn=conn)
        avg_ms = (time.perf_counter() - t0) * 1000 / 20
        # Recovery tree still may write via ensure; keep a soft budget.
        assert avg_ms < 200.0, avg_ms

        sql = (
            "SELECT COUNT(*) AS claimable_count FROM player_directives "
            "WHERE player_id = ? AND status = ? AND ("
            "(cadence = 'daily' AND period_key = ?) OR "
            "(cadence = 'weekly' AND period_key = ?))"
        )
        params = (primary, STATUS_COMPLETED, daily_period_key(), weekly_period_key())
        plan = "\n".join(_explain(conn, sql, params)).lower()
        assert "idx_player_directives_player_status" in plan or "player_id" in plan
    finally:
        conn.close()


def test_repeated_game_state_has_no_multi_second_outliers(scale_db, monkeypatch):
    primary, db_path = scale_db
    import importlib

    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = str(db_path)
    models.DB_PATH = str(db_path)
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = primary

    samples = []
    for _ in range(40):
        t0 = time.perf_counter()
        resp = client.get("/api/game-state")
        samples.append((time.perf_counter() - t0) * 1000.0)
        assert resp.status_code == 200
    assert max(samples) < 2000.0, max(samples)
    assert sorted(samples)[len(samples) // 2] < 1000.0
