"""Read-only telemetry queries: how much planet XP do real players take from expeditions, and onto which planets?

The colony-gate comparison (``docs/GC_COLONY_GATE_FINAL.md``) shows that the expedition rate sent from the colony under development moves the
colony chain more than any gate level, and the simulator cannot say what real players do.  The answer is already in ``activity_xp_log``
(``game/activity_xp.py`` writes one row per granted activity XP: player, planet, source, amount, day).  These queries only read.

    python scripts/expedition_xp_telemetry.py --print-sql
    python scripts/expedition_xp_telemetry.py --db path/to/COPY_of_the_database.sqlite --days 30

Run it against a copy of a DEV / UNI1 database (or paste the SQL into a read-only PostgreSQL session; ``:since`` is the unix timestamp from
which to look).  It never writes: the SQLite connection is opened ``mode=ro``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

QUERIES: Dict[str, str] = {
    # per player: expedition XP against all activity XP, and on how many planets the expedition XP landed
    "player_share": """
SELECT player_id,
       SUM(CASE WHEN source_key IN ('expedition', 'expedition_bonus') THEN amount ELSE 0 END) AS expedition_xp,
       SUM(amount) AS activity_xp,
       COUNT(DISTINCT CASE WHEN source_key IN ('expedition', 'expedition_bonus') THEN planet_id END) AS planets_with_expedition_xp
FROM activity_xp_log
WHERE created_at >= :since
GROUP BY player_id
""".strip(),
    # per player and UTC day: completed expeditions (the daily count that triggers the +75 XP bonus every 10th)
    "daily_expeditions": """
SELECT player_id, day_bucket, COUNT(*) AS expeditions
FROM activity_xp_log
WHERE source_key = 'expedition' AND created_at >= :since
GROUP BY player_id, day_bucket
""".strip(),
    # where the expedition XP lands: the player's first planet (proxy for the homeworld) against every later planet (colonies)
    "landing_planet": """
SELECT CASE WHEN l.planet_id = (SELECT MIN(p2.id) FROM planets p2 WHERE p2.player_id = l.player_id) THEN 'first_planet' ELSE 'later_planet' END AS landing,
       COUNT(*) AS grants,
       SUM(l.amount) AS xp
FROM activity_xp_log l
WHERE l.source_key IN ('expedition', 'expedition_bonus') AND l.created_at >= :since
GROUP BY landing
""".strip(),
}


def run(conn: sqlite3.Connection, since: float) -> Dict[str, List[Dict[str, Any]]]:
    conn.row_factory = sqlite3.Row
    return {name: [dict(r) for r in conn.execute(sql, {"since": float(since)})] for name, sql in QUERIES.items()}


def summarize(result: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Few numbers an owner can read: how many players run expeditions, how often, and what share of their XP they bring and where it lands."""
    daily: Dict[int, List[int]] = {}
    for r in result["daily_expeditions"]:
        daily.setdefault(int(r["player_id"]), []).append(int(r["expeditions"]))
    players = result["player_share"]
    with_exp = [p for p in players if int(p["expedition_xp"] or 0) > 0]
    per_day = sorted(sum(v) / len(v) for v in daily.values())
    landing = {r["landing"]: {"grants": int(r["grants"]), "xp": int(r["xp"] or 0)} for r in result["landing_planet"]}
    total_exp_xp = sum(int(p["expedition_xp"] or 0) for p in players)
    total_xp = sum(int(p["activity_xp"] or 0) for p in players)
    later = landing.get("later_planet", {}).get("xp", 0)
    return {
        "players": len(players),
        "players_with_expedition_xp": len(with_exp),
        "expedition_share_of_activity_xp": (total_exp_xp / total_xp) if total_xp else None,
        "expeditions_per_active_day_median": per_day[len(per_day) // 2] if per_day else None,
        "expeditions_per_active_day_p90": per_day[min(len(per_day) - 1, int(0.9 * len(per_day)))] if per_day else None,
        "share_of_expedition_xp_on_later_planets": (later / total_exp_xp) if total_exp_xp else None,
        "landing": landing,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print-sql", action="store_true")
    ap.add_argument("--db", default="", help="path of a COPY of the SQLite database (opened read-only)")
    ap.add_argument("--days", type=float, default=30.0)
    args = ap.parse_args(argv)
    if args.print_sql or not args.db:
        for name, sql in QUERIES.items():
            print(f"-- {name}\n{sql};\n")
        return 0
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        out = summarize(run(conn, time.time() - args.days * 86400.0))
    finally:
        conn.close()
    for k, v in out.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
