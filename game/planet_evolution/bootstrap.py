"""Bootstrap planet evolution state for new and existing planets."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import db
from .constants import CULTURE_ARCHETYPES
from .definitions import reload_definitions
from .dna import generate_planet_dna
from .mechanics import compile_planet_mechanics
from .repository import (
    ensure_planet_culture,
    evolution_schema_ready,
    get_planet_dna,
    get_planet_row,
    save_planet_dna,
)


def ensure_planet_evolution(planet_id: int, conn: sqlite3.Connection) -> Dict[str, Any]:
    if not evolution_schema_ready(conn):
        return {"ready": False, "reason": "schema_missing"}

    reload_definitions(conn)
    planet = get_planet_row(planet_id, conn=conn)
    if not planet:
        return {"ready": False, "reason": "planet_not_found"}

    cur = conn.cursor()
    created = False

    if not get_planet_dna(planet_id, conn=conn):
        is_homeworld = bool(planet.get("is_homeworld"))
        dna = generate_planet_dna(
            galaxy=int(planet.get("galaxy") or 1),
            system=planet.get("system"),
            position=planet.get("position"),
            planet_class=planet.get("planet_class"),
            is_homeworld=is_homeworld,
        )
        save_planet_dna(planet_id, dna, conn)
        cur.execute(
            """
            UPDATE planets SET
                dna_seed = ?,
                planet_class = ?,
                culture_archetype = COALESCE(NULLIF(culture_archetype, ''), ?)
            WHERE id = ?;
            """,
            (
                int(dna.get("dna_seed") or 0),
                str(dna.get("planet_class") or "terrestrial"),
                CULTURE_ARCHETYPES[0],
                int(planet_id),
            ),
        )
        created = True

    archetype = str(planet.get("culture_archetype") or CULTURE_ARCHETYPES[0])
    ensure_planet_culture(planet_id, conn, archetype=archetype)

    if not planet.get("last_evolution_tick"):
        cur.execute(
            "UPDATE planets SET last_evolution_tick = ? WHERE id = ?;",
            (time.time(), int(planet_id)),
        )

    compile_planet_mechanics(planet_id, conn)
    return {"ready": True, "planet_id": int(planet_id), "dna_created": created}


def backfill_all_planets_evolution(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not evolution_schema_ready(conn):
            return {"ok": False, "reason": "schema_missing", "processed": 0}

        cur = conn.cursor()
        cur.execute("SELECT id FROM planets WHERE player_id IS NOT NULL ORDER BY id ASC;")
        planet_ids = [int(r["id"]) for r in cur.fetchall()]
        results: List[Dict[str, Any]] = []
        for pid in planet_ids:
            results.append(ensure_planet_evolution(pid, conn))

        if own:
            conn.commit()

        return {
            "ok": True,
            "processed": len(planet_ids),
            "dna_created": sum(1 for r in results if r.get("dna_created")),
        }
    finally:
        if own and conn is not None:
            conn.close()
