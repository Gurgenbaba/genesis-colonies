"""Live-safety regression for GC-SCORE-BIGNUM migration 154.

This test models the production upgrade shape: an already populated legacy
``player_scores`` table with INTEGER score columns and cached ranks is migrated
through the real migration runner. Every score/rank must survive bit-for-bit.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"
MIGRATE_SCRIPT = ROOT / "migrate.py"
MIGRATION_NAME = "154_big_score_ranking.sql"
PLAYER_COUNT = 122

_SCORE_COLUMNS = (
    "score_total",
    "score_resources",
    "score_buildings",
    "score_research",
    "score_fleet",
    "score_defense",
    "score_planet_evolution",
    "score_destroyed_raw",
    "score_combat",
    "score_destroyed",
)
_RANK_COLUMNS = (
    "rank_total",
    "rank_building",
    "rank_research",
    "rank_fleet",
    "rank_combat",
    "rank_destroyed",
    "rank_military",
)


def _legacy_row(player_id: int) -> dict[str, int]:
    # Keep values valid for the old SQLite INTEGER schema while exercising the
    # exact precision region that motivated GC-SCORE-BIGNUM.
    base = 9_000_000_000_000_000 - player_id * 1_000_003
    building = base - 4_000_000 - player_id
    research = 1_500_000 + player_id * 11
    fleet = 1_000_000 + player_id * 13
    defense = 750_000 + player_id * 17
    evolution = 750_000 + player_id * 19
    total = building + research + fleet + defense + evolution
    destroyed_raw = 500_000_000_000 + player_id * 23
    destroyed = destroyed_raw // 1000
    combat = fleet + defense
    return {
        "player_id": player_id,
        "score_total": total,
        "score_resources": 7_000_000_000_000 + player_id * 29,
        "score_buildings": building,
        "score_research": research,
        "score_fleet": fleet,
        "score_defense": defense,
        "score_planet_evolution": evolution,
        "score_destroyed_raw": destroyed_raw,
        "score_combat": combat,
        "score_destroyed": destroyed,
        "updated_at": 1_780_000_000 + player_id,
        "rank_total": player_id,
        "rank_building": PLAYER_COUNT - player_id + 1,
        "rank_research": ((player_id * 7) % PLAYER_COUNT) + 1,
        "rank_fleet": ((player_id * 11) % PLAYER_COUNT) + 1,
        "rank_combat": ((player_id * 13) % PLAYER_COUNT) + 1,
        "rank_destroyed": ((player_id * 17) % PLAYER_COUNT) + 1,
        "rank_military": ((player_id * 19) % PLAYER_COUNT) + 1,
    }


def _create_populated_legacy_db(path: Path) -> list[dict[str, int]]:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE migration_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at INTEGER NOT NULL
            );

            CREATE TABLE player_scores (
                player_id INTEGER PRIMARY KEY,
                score_total INTEGER NOT NULL DEFAULT 0,
                score_resources INTEGER NOT NULL DEFAULT 0,
                score_buildings INTEGER NOT NULL DEFAULT 0,
                score_research INTEGER NOT NULL DEFAULT 0,
                score_fleet INTEGER NOT NULL DEFAULT 0,
                score_defense INTEGER NOT NULL DEFAULT 0,
                score_planet_evolution INTEGER NOT NULL DEFAULT 0,
                score_destroyed_raw INTEGER NOT NULL DEFAULT 0,
                score_combat INTEGER NOT NULL DEFAULT 0,
                score_destroyed INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                rank_total INTEGER,
                rank_building INTEGER,
                rank_research INTEGER,
                rank_fleet INTEGER,
                rank_combat INTEGER,
                rank_destroyed INTEGER,
                rank_military INTEGER
            );

            CREATE INDEX idx_player_scores_updated ON player_scores (updated_at DESC);
            CREATE INDEX idx_player_scores_rank_total ON player_scores (rank_total ASC);
            CREATE INDEX idx_player_scores_rank_fleet ON player_scores (rank_fleet ASC);
            """
        )

        # This is a surgical migration-154 fixture. Mark every other migration as
        # already applied so adding a later unrelated migration cannot silently
        # broaden this regression into a partial-schema full-run test.
        other_migrations = sorted(
            p.name for p in MIGRATIONS_DIR.glob("*.sql") if p.name != MIGRATION_NAME
        )
        conn.executemany(
            "INSERT INTO migration_history (name, applied_at) VALUES (?, 1770000000);",
            [(name,) for name in other_migrations],
        )

        rows = [_legacy_row(player_id) for player_id in range(1, PLAYER_COUNT + 1)]
        columns = (
            "player_id",
            *_SCORE_COLUMNS,
            "updated_at",
            *_RANK_COLUMNS,
        )
        placeholders = ",".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO player_scores ({','.join(columns)}) VALUES ({placeholders});",
            [tuple(row[col] for col in columns) for row in rows],
        )
        conn.commit()
        return rows
    finally:
        conn.close()


def test_migration_154_preserves_122_populated_legacy_score_rows(tmp_path):
    db_path = tmp_path / "legacy_live_scores.db"
    before = _create_populated_legacy_db(db_path)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    env["GC_DB_BACKEND"] = "sqlite"
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert f"Migration erfolgreich: {MIGRATION_NAME}" in result.stdout

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        applied = conn.execute(
            "SELECT 1 FROM migration_history WHERE name = ?;", (MIGRATION_NAME,)
        ).fetchone()
        assert applied is not None

        cols = {row["name"]: str(row["type"]).upper() for row in conn.execute("PRAGMA table_info(player_scores);")}
        for column in _SCORE_COLUMNS:
            assert cols[column] == "TEXT"
        for column in _RANK_COLUMNS:
            assert cols[column] == "INTEGER"

        after = conn.execute(
            "SELECT * FROM player_scores ORDER BY player_id ASC;"
        ).fetchall()
        assert len(after) == PLAYER_COUNT

        for expected, actual in zip(before, after, strict=True):
            assert int(actual["player_id"]) == expected["player_id"]
            for column in _SCORE_COLUMNS:
                # Decimal TEXT must preserve the exact legacy INTEGER value.
                assert actual[column] == str(expected[column])
            assert int(actual["updated_at"]) == expected["updated_at"]
            for column in _RANK_COLUMNS:
                assert int(actual[column]) == expected[column]

        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(player_scores);")}
        assert "idx_player_scores_updated" in indexes
        assert "idx_player_scores_rank_total" in indexes
        assert "idx_player_scores_rank_fleet" in indexes

        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_scores_bigint';"
        ).fetchone() is None
    finally:
        conn.close()
