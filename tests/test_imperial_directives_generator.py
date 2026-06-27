"""GC-911A — Imperial Directives generator and schema tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.directives.definitions import (
    DAILY_DIRECTIVE_COUNT,
    WEEKLY_DIRECTIVE_COUNT,
    directives_schema_ready,
    list_definitions_for_cadence,
)
from game.directives.generator import (
    daily_period_key,
    ensure_player_directives,
    generate_directives_for_cadence,
    weekly_period_key,
)
from game.models import create_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def id_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperial_directives.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    yield db_file


def _create_player(conn, *, tag: str = "a") -> int:
    import uuid

    name = f"dir_{tag}_{uuid.uuid4().hex[:8]}"
    ok, _reason, user = create_user(name, "secret123")
    assert ok and user, f"create_user failed: {_reason}"
    return int(user["id"])


def test_schema_ready_after_migration(id_db):
    conn = db()
    try:
        assert directives_schema_ready(conn)
        daily_defs = list_definitions_for_cadence("daily", conn=conn)
        weekly_defs = list_definitions_for_cadence("weekly", conn=conn)
        assert len(daily_defs) >= 10
        assert len(weekly_defs) >= 5
    finally:
        conn.close()


def test_ensure_player_directives_generates_counts(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()

        state = ensure_player_directives(player_id, conn=conn, now=1_718_000_000.0)
        conn.commit()

        assert state["ready"] is True
        assert len(state["daily"]) == DAILY_DIRECTIVE_COUNT
        assert len(state["weekly"]) == WEEKLY_DIRECTIVE_COUNT
        assert state["daily_reset_at"] > 1_718_000_000
        assert state["weekly_reset_at"] > 1_718_000_000
    finally:
        conn.close()


def test_ensure_player_directives_idempotent(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        fixed_now = 1_718_100_000.0

        first = ensure_player_directives(player_id, conn=conn, now=fixed_now)
        conn.commit()
        second = ensure_player_directives(player_id, conn=conn, now=fixed_now)
        conn.commit()

        assert len(first["daily"]) == len(second["daily"]) == DAILY_DIRECTIVE_COUNT
        assert [row["id"] for row in first["daily"]] == [row["id"] for row in second["daily"]]

        count = conn.execute(
            """
            SELECT COUNT(*) AS c FROM player_directives
            WHERE player_id = ? AND period_key = ?;
            """,
            (player_id, daily_period_key(fixed_now)),
        ).fetchone()["c"]
        assert int(count) == DAILY_DIRECTIVE_COUNT
    finally:
        conn.close()


def test_generation_is_deterministic_per_period(id_db):
    conn = db()
    try:
        player_a = _create_player(conn, tag="pa")
        player_b = _create_player(conn, tag="pb")
        conn.commit()
        fixed_now = 1_718_200_000.0

        state_a1 = ensure_player_directives(player_a, conn=conn, now=fixed_now)
        state_a2 = ensure_player_directives(player_a, conn=conn, now=fixed_now,)
        state_b = ensure_player_directives(player_b, conn=conn, now=fixed_now)
        conn.commit()

        keys_a = [row["definition_key"] for row in state_a1["daily"]]
        assert keys_a == [row["definition_key"] for row in state_a2["daily"]]
        keys_b = [row["definition_key"] for row in state_b["daily"]]
        assert len(keys_a) == len(keys_b) == DAILY_DIRECTIVE_COUNT
        # Different players may roll different directives.
        assert len(set(keys_a)) == DAILY_DIRECTIVE_COUNT
    finally:
        conn.close()


def test_no_duplicate_definition_keys_in_same_period(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        state = ensure_player_directives(player_id, conn=conn, now=1_718_300_000.0)
        conn.commit()

        daily_keys = [row["definition_key"] for row in state["daily"]]
        assert len(daily_keys) == len(set(daily_keys))
    finally:
        conn.close()


def test_weekly_directive_is_at_least_rare(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        state = ensure_player_directives(player_id, conn=conn, now=1_718_400_000.0)
        conn.commit()

        assert len(state["weekly"]) == 1
        rarity = str(state["weekly"][0]["rarity"])
        assert rarity in ("rare", "epic", "legendary")
    finally:
        conn.close()


def test_directive_rows_have_scaled_target_and_reward(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        state = ensure_player_directives(player_id, conn=conn, now=1_718_500_000.0)
        conn.commit()

        row = state["daily"][0]
        assert int(row["target_value"]) >= 1
        assert int(row["progress_value"]) == 0
        assert row["status"] == "active"

        reward = json.loads(row["reward_json"])
        assert reward.get("container_key")
        assert reward.get("boosters")
    finally:
        conn.close()


def test_force_regenerates_period(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        fixed_now = 1_718_600_000.0
        period = daily_period_key(fixed_now)

        ensure_player_directives(player_id, conn=conn, now=fixed_now)
        conn.commit()
        before = conn.execute(
            "SELECT id FROM player_directives WHERE player_id = ? AND period_key = ?;",
            (player_id, period),
        ).fetchall()

        generate_directives_for_cadence(
            player_id,
            "daily",
            conn=conn,
            now=fixed_now,
            force=True,
        )
        conn.commit()
        after = conn.execute(
            "SELECT id FROM player_directives WHERE player_id = ? AND period_key = ?;",
            (player_id, period),
        ).fetchall()

        assert len(before) == DAILY_DIRECTIVE_COUNT
        assert len(after) == DAILY_DIRECTIVE_COUNT
        assert {int(r["id"]) for r in before} != {int(r["id"]) for r in after}
    finally:
        conn.close()


def test_period_keys_format(id_db):
    ts = 1_718_688_000.0  # 2024-06-17 Monday-ish UTC
    assert daily_period_key(ts).startswith("daily:")
    assert weekly_period_key(ts).startswith("weekly:")


def test_stale_overcap_directive_is_replaced(id_db):
    conn = db()
    try:
        player_id = _create_player(conn, tag="gen")
        conn.commit()
        fixed_now = 1_718_700_000.0
        period = daily_period_key(fixed_now)

        ensure_player_directives(player_id, conn=conn, now=fixed_now)
        conn.commit()
        conn.execute(
            """
            UPDATE player_directives
            SET target_value = 999999
            WHERE id = (
                SELECT id FROM player_directives
                WHERE player_id = ? AND period_key = ? AND cadence = 'daily'
                ORDER BY id ASC
                LIMIT 1
            );
            """,
            (player_id, period),
        )
        conn.commit()

        generate_directives_for_cadence(
            player_id,
            "daily",
            conn=conn,
            now=fixed_now,
        )
        conn.commit()

        rows = conn.execute(
            """
            SELECT target_value FROM player_directives
            WHERE player_id = ? AND period_key = ? AND cadence = 'daily';
            """,
            (player_id, period),
        ).fetchall()
        assert len(rows) == DAILY_DIRECTIVE_COUNT
        assert all(int(r["target_value"]) <= 50 for r in rows)
    finally:
        conn.close()
