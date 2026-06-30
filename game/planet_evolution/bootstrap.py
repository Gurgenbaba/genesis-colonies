"""Bootstrap planet evolution state for new and existing planets."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import db
from .constants import CULTURE_ARCHETYPES
from .definitions import reload_definitions
from .dna import effective_planet_class, expected_planet_class, generate_planet_dna
from .mechanics import compile_planet_mechanics
from .repository import (
    ensure_planet_culture,
    evolution_schema_ready,
    get_planet_dna,
    get_planet_row,
    save_planet_dna,
)


def planet_evolution_needs_bootstrap(planet_id: int, conn: sqlite3.Connection) -> bool:
    """True when DNA/culture/mechanics still need to be created or repaired."""
    planet = get_planet_row(planet_id, conn=conn)
    if not planet:
        return False

    expected_class = expected_planet_class(planet)
    stored_class = str(planet.get("planet_class") or "").strip().lower()
    existing_dna = get_planet_dna(planet_id, conn=conn)
    if not existing_dna or stored_class != expected_class or int(planet.get("dna_seed") or 0) <= 0:
        return True
    if not planet.get("last_evolution_tick"):
        return True

    cur = conn.cursor()
    cur.execute("SELECT 1 FROM planet_culture WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    if not cur.fetchone():
        return True
    cur.execute("SELECT 1 FROM planet_mechanics WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    return cur.fetchone() is None


def ensure_planet_evolution(planet_id: int, conn: sqlite3.Connection) -> Dict[str, Any]:
    from ..db import begin_write_transaction, commit, in_transaction, rollback

    if not evolution_schema_ready(conn):
        return {"ready": False, "reason": "schema_missing"}

    reload_definitions(conn)
    if not planet_evolution_needs_bootstrap(planet_id, conn):
        from .expansion_protocol import bootstrap_legacy_establishment

        bootstrap_legacy_establishment(planet_id, conn=conn)
        return {"ready": True, "planet_id": int(planet_id), "dna_created": False}

    began = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began = True

        planet = get_planet_row(planet_id, conn=conn)
        if not planet:
            if began:
                rollback(conn)
            return {"ready": False, "reason": "planet_not_found"}

        cur = conn.cursor()
        created = False
        regen_dna = False

        expected_class = expected_planet_class(planet)
        stored_class = str(planet.get("planet_class") or "").strip().lower()
        existing_dna = get_planet_dna(planet_id, conn=conn)
        if not existing_dna or stored_class != expected_class or int(planet.get("dna_seed") or 0) <= 0:
            regen_dna = True

        if regen_dna:
            is_homeworld = bool(planet.get("is_homeworld"))
            dna = generate_planet_dna(
                galaxy=int(planet.get("galaxy") or 1),
                system=planet.get("system"),
                position=planet.get("position"),
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
                    str(dna.get("planet_class") or expected_class),
                    CULTURE_ARCHETYPES[0],
                    int(planet_id),
                ),
            )
            created = not bool(existing_dna)
        elif stored_class != expected_class:
            cur.execute(
                "UPDATE planets SET planet_class = ? WHERE id = ?;",
                (expected_class, int(planet_id)),
            )

        archetype = str(planet.get("culture_archetype") or CULTURE_ARCHETYPES[0])
        ensure_planet_culture(planet_id, conn, archetype=archetype)

        if not planet.get("last_evolution_tick"):
            cur.execute(
                "UPDATE planets SET last_evolution_tick = ? WHERE id = ?;",
                (time.time(), int(planet_id)),
            )

        compile_planet_mechanics(planet_id, conn)
        from .expansion_protocol import bootstrap_legacy_establishment

        bootstrap_legacy_establishment(planet_id, conn=conn)
        if began:
            commit(conn)
        return {"ready": True, "planet_id": int(planet_id), "dna_created": created}
    except Exception:
        if began:
            rollback(conn)
        raise


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
