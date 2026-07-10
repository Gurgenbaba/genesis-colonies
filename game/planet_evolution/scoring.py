"""Planet evolution score component for ranking (GC-SCORE-E)."""

from __future__ import annotations

import sqlite3

from ..db import column_exists, table_exists
from ..resource_score import add_score_from_cost_dicts
from .ascension import ascension_invested_resource_totals
from .planet_research import cumulative_planet_research_resource_totals


def compute_single_planet_score(planet_id: int, conn: sqlite3.Connection) -> int:
    if not table_exists(conn, "planets"):
        return 0
    cur = conn.cursor()
    cur.execute("SELECT id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    if not cur.fetchone():
        return 0

    research = cumulative_planet_research_resource_totals(int(planet_id), conn=conn)
    ascension = ascension_invested_resource_totals(int(planet_id), conn)
    return add_score_from_cost_dicts(research, ascension)


def compute_player_evolution_score(player_id: int, conn: sqlite3.Connection) -> int:
    if not table_exists(conn, "planets") or not column_exists(conn, "planets", "planet_level"):
        return 0

    from ..models import get_planets_by_player

    total = 0
    for planet in get_planets_by_player(int(player_id), conn=conn):
        total += compute_single_planet_score(int(planet["id"]), conn)
    return max(0, int(total))
