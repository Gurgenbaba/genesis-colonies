#!/usr/bin/env python3
"""Materialize the PostgreSQL set-based rank rewrite + regression test.

Temporary branch apply helper. The generated source/test are the reviewable product;
this helper is removed before merge.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANKING = ROOT / "game" / "ranking.py"
TEST = ROOT / "tests" / "test_gc_pg_ranking_set_based.py"


def apply() -> None:
    text = RANKING.read_text(encoding="utf-8")

    old_import = (
        "from .db import begin_write_transaction, column_exists, commit, db, rollback, table_exists"
    )
    new_import = (
        "from .db import (\n"
        "    begin_write_transaction,\n"
        "    column_exists,\n"
        "    commit,\n"
        "    db,\n"
        "    get_db_backend,\n"
        "    rollback,\n"
        "    table_exists,\n"
        ")"
    )
    if old_import not in text and "get_db_backend," not in text:
        raise SystemExit("ranking db import anchor missing")
    text = text.replace(old_import, new_import, 1)

    helper_marker = "\ndef recalculate_ranks(conn=None) -> int:\n"
    helper = r'''

def _recalculate_ranks_postgres_set_based(conn) -> int:
    """Rewrite all current rank columns with one PostgreSQL UPDATE.

    ``player_scores.score_*`` are decimal TEXT for arbitrary-precision score
    semantics. PostgreSQL NUMERIC preserves those values exactly while window
    functions eliminate the previous one-UPDATE-per-player round trips.

    Ordering intentionally mirrors the mature Python ranking path exactly.
    """
    _ensure_score_rows(conn)
    cur = conn.cursor()
    cur.execute(
        """
        WITH scored AS (
            SELECT
                p.id AS player_id,
                GREATEST(CAST(COALESCE(ps.score_buildings, '0') AS NUMERIC), 0) AS building_score,
                GREATEST(CAST(COALESCE(ps.score_research, '0') AS NUMERIC), 0) AS research_score,
                GREATEST(CAST(COALESCE(ps.score_fleet, '0') AS NUMERIC), 0) AS fleet_score,
                GREATEST(CAST(COALESCE(ps.score_defense, '0') AS NUMERIC), 0) AS defense_score,
                GREATEST(CAST(COALESCE(ps.score_planet_evolution, '0') AS NUMERIC), 0) AS evolution_score,
                GREATEST(CAST(COALESCE(ps.score_combat, '0') AS NUMERIC), 0) AS combat_score,
                GREATEST(CAST(COALESCE(ps.score_destroyed, '0') AS NUMERIC), 0) AS destroyed_score
            FROM players p
            INNER JOIN player_scores ps ON ps.player_id = p.id
        ),
        effective AS (
            SELECT
                player_id,
                building_score,
                research_score,
                fleet_score,
                combat_score,
                destroyed_score,
                (building_score + research_score + fleet_score + defense_score + evolution_score) AS total_score,
                (fleet_score + defense_score + destroyed_score) AS military_score
            FROM scored
        ),
        ranked AS (
            SELECT
                player_id,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY total_score DESC, building_score DESC, research_score DESC, player_id ASC
                ) AS INTEGER) AS rank_total,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY building_score DESC, research_score DESC, player_id ASC
                ) AS INTEGER) AS rank_building,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY research_score DESC, building_score DESC, player_id ASC
                ) AS INTEGER) AS rank_research,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY fleet_score DESC, building_score DESC, player_id ASC
                ) AS INTEGER) AS rank_fleet,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY combat_score DESC, fleet_score DESC, player_id ASC
                ) AS INTEGER) AS rank_combat,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY destroyed_score DESC, fleet_score DESC, player_id ASC
                ) AS INTEGER) AS rank_destroyed,
                CAST(ROW_NUMBER() OVER (
                    ORDER BY military_score DESC, fleet_score DESC, player_id ASC
                ) AS INTEGER) AS rank_military
            FROM effective
        )
        UPDATE player_scores ps
        SET
            rank_total = ranked.rank_total,
            rank_building = ranked.rank_building,
            rank_research = ranked.rank_research,
            rank_fleet = ranked.rank_fleet,
            rank_combat = ranked.rank_combat,
            rank_destroyed = ranked.rank_destroyed,
            rank_military = ranked.rank_military
        FROM ranked
        WHERE ps.player_id = ranked.player_id;
        """
    )
    return max(0, int(cur.rowcount or 0))
'''
    if "def _recalculate_ranks_postgres_set_based" not in text:
        if helper_marker not in text:
            raise SystemExit("recalculate_ranks anchor missing")
        text = text.replace(helper_marker, helper + helper_marker, 1)

    old_apply = """    def _apply() -> int:\n        rows = _fetch_all_score_rows(conn)\n"""
    new_apply = """    def _apply() -> int:\n        has_rank_fleet = column_exists(conn, \"player_scores\", \"rank_fleet\")\n        has_rank_combat = column_exists(conn, \"player_scores\", \"rank_combat\")\n        if get_db_backend() == \"postgres\" and has_rank_combat:\n            return _recalculate_ranks_postgres_set_based(conn)\n\n        rows = _fetch_all_score_rows(conn)\n"""
    if old_apply not in text and "return _recalculate_ranks_postgres_set_based(conn)" not in text:
        raise SystemExit("recalculate_ranks apply anchor missing")
    text = text.replace(old_apply, new_apply, 1)

    old_duplicate_flags = """        has_rank_fleet = column_exists(conn, \"player_scores\", \"rank_fleet\")\n        has_rank_combat = column_exists(conn, \"player_scores\", \"rank_combat\")\n        cur = conn.cursor()\n"""
    # After moving these checks above the PG fast-path, the Python fallback reuses them.
    if text.count(old_duplicate_flags) == 1:
        text = text.replace(old_duplicate_flags, "        cur = conn.cursor()\n", 1)

    RANKING.write_text(text, encoding="utf-8")

    TEST.write_text(
        r'''"""PostgreSQL ranking rewrite must be set-based and bigint-lossless."""
from __future__ import annotations

import time

import pytest

from tests.pg_fixtures import close_pg_pool, requires_postgres


@requires_postgres
def test_pg_rank_rewrite_is_set_based_exact_and_matches_python_order(pg_parity_db, monkeypatch):
    from game.db import db
    from game.models import create_user
    import game.ranking as ranking

    huge = 10**30
    seeds = [
        # building, research, fleet, defense, evolution, combat, destroyed
        (huge, 5, 10, 2, 0, 12, 3),
        (huge, 5, 9, 100, 0, 109, 0),
        (7, huge + 20, 1, 1, 0, 2, 200),
        (huge, 5, 10, 2, 0, 12, 3),  # exact tie: player_id must decide
        (1, 1, huge + 50, 4, 3, huge + 54, 2),
    ]

    player_ids = []
    stamp = int(time.time() * 1000) % 1_000_000
    for idx in range(len(seeds)):
        ok, reason, user = create_user(f"PgRank{stamp}_{idx}", f"Rank!{idx}Pass99xx")
        assert ok and user, reason
        player_ids.append(int(user["id"]))

    conn = db()
    try:
        for pid, (building, research, fleet, defense, evolution, combat, destroyed) in zip(player_ids, seeds):
            total = building + research + fleet + defense + evolution
            conn.execute(
                """
                UPDATE player_scores
                SET score_total = ?, score_buildings = ?, score_research = ?,
                    score_fleet = ?, score_defense = ?, score_planet_evolution = ?,
                    score_combat = ?, score_destroyed = ?
                WHERE player_id = ?;
                """,
                tuple(str(v) for v in (total, building, research, fleet, defense, evolution, combat, destroyed))
                + (pid,),
            )
        conn.commit()

        # A PG run must never fall back to fetching/sorting every player in Python.
        monkeypatch.setattr(
            ranking,
            "_fetch_all_score_rows",
            lambda _conn: (_ for _ in ()).throw(AssertionError("Python rank fallback used on PostgreSQL")),
        )

        assigned = ranking.recalculate_ranks(conn=conn)
        conn.commit()
        assert assigned >= len(player_ids)

        rows = conn.execute(
            """
            SELECT player_id, rank_total, rank_building, rank_research, rank_fleet,
                   rank_combat, rank_destroyed, rank_military
            FROM player_scores
            WHERE player_id IN (?, ?, ?, ?, ?);
            """,
            tuple(player_ids),
        ).fetchall()
        actual = {int(row["player_id"]): dict(row) for row in rows}

        data = []
        for pid, (building, research, fleet, defense, evolution, combat, destroyed) in zip(player_ids, seeds):
            data.append(
                {
                    "player_id": pid,
                    "building": building,
                    "research": research,
                    "fleet": fleet,
                    "defense": defense,
                    "evolution": evolution,
                    "combat": combat,
                    "destroyed": destroyed,
                    "total": building + research + fleet + defense + evolution,
                    "military": fleet + defense + destroyed,
                }
            )

        def ranks(key):
            ordered = sorted(data, key=key)
            return {row["player_id"]: idx for idx, row in enumerate(ordered, start=1)}

        expected = {
            "rank_total": ranks(lambda r: (-r["total"], -r["building"], -r["research"], r["player_id"])),
            "rank_building": ranks(lambda r: (-r["building"], -r["research"], r["player_id"])),
            "rank_research": ranks(lambda r: (-r["research"], -r["building"], r["player_id"])),
            "rank_fleet": ranks(lambda r: (-r["fleet"], -r["building"], r["player_id"])),
            "rank_combat": ranks(lambda r: (-r["combat"], -r["fleet"], r["player_id"])),
            "rank_destroyed": ranks(lambda r: (-r["destroyed"], -r["fleet"], r["player_id"])),
            "rank_military": ranks(lambda r: (-r["military"], -r["fleet"], r["player_id"])),
        }
        for column, rank_map in expected.items():
            for pid in player_ids:
                assert int(actual[pid][column]) == rank_map[pid], (column, pid, actual[pid], rank_map[pid])
    finally:
        conn.close()
        close_pg_pool()
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    apply()
