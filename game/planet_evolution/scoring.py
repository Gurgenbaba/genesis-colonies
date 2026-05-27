"""Planet evolution score component for ranking."""

from __future__ import annotations

import sqlite3
from typing import Optional

from ..db import column_exists, table_exists
from .constants import DISCOVERY_RARITY_MULT
from .repository import get_discoveries, get_legacy_tags


def compute_single_planet_score(planet_id: int, conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    if not row:
        return 0
    planet = dict(row)

    level = int(planet.get("planet_level") or 1)
    tier = int(planet.get("specialization_tier") or 0)
    asc = int(planet.get("ascension_rank") or 0)
    total = max(0, level - 1) * 100 + tier * 500 + asc * 5000
    for disc in get_discoveries(planet_id, conn=conn):
        rarity = str(disc.get("rarity") or "common")
        total += 1000 * DISCOVERY_RARITY_MULT.get(rarity, 1)
    total += len(get_legacy_tags(planet_id, conn=conn)) * 50
    return max(0, int(total))


def compute_player_evolution_score(player_id: int, conn: sqlite3.Connection) -> int:
    if not table_exists(conn, "planets") or not column_exists(conn, "planets", "planet_level"):
        return 0

    from ..models import get_planets_by_player

    total = 0
    for planet in get_planets_by_player(int(player_id), conn=conn):
        total += compute_single_planet_score(int(planet["id"]), conn)
    return max(0, int(total))
