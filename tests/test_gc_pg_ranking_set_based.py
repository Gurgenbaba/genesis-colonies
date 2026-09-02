"""PostgreSQL ranking rewrite must be set-based and bigint-lossless."""
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
