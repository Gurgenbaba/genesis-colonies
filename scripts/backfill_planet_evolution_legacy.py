#!/usr/bin/env python3
"""
One-shot maintenance backfill for Planet Evolution legacy colonies (GC-976).

Runs ensure_planet_evolution() on all owned planets so world-bound pre-outpost
colonies receive bootstrap_legacy_establishment() and missing DNA/mechanics rows.

Idempotent — safe to run multiple times. Does not touch resources, building
levels, or queues.

Examples:
  python scripts/backfill_planet_evolution_legacy.py --dry-run
  python scripts/backfill_planet_evolution_legacy.py
  python scripts/backfill_planet_evolution_legacy.py --player-id 42 --dry-run
  python scripts/backfill_planet_evolution_legacy.py --planet-id 17
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fetch_planet_ids(
    conn,
    *,
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[int]:
    sql = "SELECT id FROM planets WHERE player_id IS NOT NULL"
    params: List[Any] = []
    if planet_id is not None:
        sql += " AND id = ?"
        params.append(int(planet_id))
    if player_id is not None:
        sql += " AND player_id = ?"
        params.append(int(player_id))
    sql += " ORDER BY id ASC"
    if limit is not None and int(limit) > 0:
        sql += " LIMIT ?"
        params.append(int(limit))

    cur = conn.cursor()
    cur.execute(sql + ";", tuple(params))
    return [int(row["id"]) for row in cur.fetchall()]


def _planet_row(conn, planet_id: int) -> Dict[str, Any]:
    from game.planet_evolution.repository import get_planet_row

    return dict(get_planet_row(int(planet_id), conn=conn) or {})


def _has_evolution_rows(planet_id: int, conn) -> Tuple[bool, bool]:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM planet_dna WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    has_dna = cur.fetchone() is not None
    cur.execute("SELECT 1 FROM planet_mechanics WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    has_mechanics = cur.fetchone() is not None
    return has_dna, has_mechanics


def snapshot_planet_state(planet_id: int, conn) -> Dict[str, Any]:
    from game.planet_evolution.bootstrap import planet_evolution_needs_bootstrap
    from game.planet_evolution.expansion_phase import is_establishment_complete
    from game.planet_evolution.expansion_protocol import (
        is_legacy_full_colony,
        is_outpost_planet,
    )

    planet = _planet_row(conn, planet_id)
    has_dna, has_mechanics = _has_evolution_rows(planet_id, conn)
    world_key = str(planet.get("world_key") or "").strip()
    origin_world_key = str(planet.get("origin_world_key") or "").strip()

    return {
        "planet_id": int(planet_id),
        "player_id": int(planet.get("player_id") or 0),
        "name": str(planet.get("name") or ""),
        "world_key": world_key or None,
        "origin_world_key": origin_world_key or None,
        "is_homeworld": int(planet.get("is_homeworld") or 0) == 1,
        "planet_level": int(planet.get("planet_level") or 0),
        "dna_reveal_tier": int(planet.get("dna_reveal_tier") or 0),
        "has_dna": has_dna,
        "has_mechanics": has_mechanics,
        "needs_bootstrap": bool(planet_evolution_needs_bootstrap(planet_id, conn)),
        "is_legacy_full_colony": bool(is_legacy_full_colony(planet_id, planet=planet, conn=conn)),
        "is_outpost_planet": bool(is_outpost_planet(planet_id, conn=conn)),
        "establishment_complete": bool(is_establishment_complete(planet_id, conn=conn)),
        "would_grandfather": bool(_would_grandfather_legacy(planet, conn=conn)),
    }


def _would_grandfather_legacy(planet: Dict[str, Any], *, conn) -> bool:
    from game.planet_evolution.expansion_phase import is_establishment_complete
    from game.planet_evolution.expansion_protocol import is_legacy_full_colony

    pid = int(planet.get("id") or 0)
    if pid <= 0:
        return False
    if int(planet.get("is_homeworld") or 0) == 1:
        return False
    wk = str(planet.get("world_key") or planet.get("origin_world_key") or "").strip()
    if not wk:
        return False
    if not is_legacy_full_colony(pid, planet=planet, conn=conn):
        return False
    return not is_establishment_complete(pid, conn=conn)


def preview_planet_backfill(planet_id: int, conn) -> Dict[str, Any]:
    snap = snapshot_planet_state(planet_id, conn)
    would_change = bool(
        snap["needs_bootstrap"]
        or snap["would_grandfather"]
        or not snap["has_dna"]
        or not snap["has_mechanics"]
    )
    return {
        **snap,
        "action": "would_update" if would_change else "skip",
        "dry_run": True,
    }


def apply_planet_backfill(planet_id: int, conn) -> Dict[str, Any]:
    from game.db import commit, rollback
    from game.planet_evolution.bootstrap import ensure_planet_evolution

    before = snapshot_planet_state(planet_id, conn)
    try:
        result = ensure_planet_evolution(int(planet_id), conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise

    after = snapshot_planet_state(planet_id, conn)
    dna_created = bool(result.get("dna_created"))
    grandfathered = bool(
        before["would_grandfather"]
        and (
            after["dna_reveal_tier"] > before["dna_reveal_tier"]
            or after["planet_level"] > before["planet_level"]
            or (before["is_outpost_planet"] and not after["is_outpost_planet"])
            or after["establishment_complete"]
        )
    )
    evo_bootstrapped = bool(
        before["needs_bootstrap"] and not after["needs_bootstrap"]
    )
    updated = bool(dna_created or grandfathered or evo_bootstrapped)

    return {
        **after,
        "action": "updated" if updated else "skip",
        "dna_created": dna_created,
        "grandfathered": grandfathered,
        "evo_bootstrapped": evo_bootstrapped,
        "ready": bool(result.get("ready")),
        "reason": str(result.get("reason") or ""),
        "dry_run": False,
    }


def run_backfill(
    conn,
    planet_ids: Sequence[int],
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for pid in planet_ids:
        try:
            if dry_run:
                row = preview_planet_backfill(int(pid), conn)
            else:
                row = apply_planet_backfill(int(pid), conn)
            results.append(row)
            _log_planet_row(row)
        except Exception as exc:
            err = {
                "planet_id": int(pid),
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            errors.append(err)
            print(f"ERROR planet_id={pid}: {exc}", file=sys.stderr)

    updated = sum(1 for r in results if r.get("action") == "updated" or r.get("action") == "would_update")
    skipped = sum(1 for r in results if r.get("action") == "skip")
    return {
        "total": len(planet_ids),
        "processed": len(results),
        "updated": updated,
        "skipped": skipped,
        "errors": len(errors),
        "dry_run": dry_run,
        "results": results,
        "error_rows": errors,
    }


def _log_planet_row(row: Dict[str, Any]) -> None:
    parts = [
        f"planet_id={row.get('planet_id')}",
        f"player_id={row.get('player_id')}",
        f"name={row.get('name')!r}",
        f"world_key={row.get('world_key')!r}",
        f"origin_world_key={row.get('origin_world_key')!r}",
        f"action={row.get('action')}",
    ]
    if row.get("dry_run"):
        parts.append(f"would_grandfather={row.get('would_grandfather')}")
        parts.append(f"needs_bootstrap={row.get('needs_bootstrap')}")
    else:
        parts.append(f"dna_created={row.get('dna_created', False)}")
        parts.append(f"grandfathered={row.get('grandfathered', False)}")
        parts.append(f"evo_bootstrapped={row.get('evo_bootstrapped', False)}")
    parts.append(f"outpost={row.get('is_outpost_planet')}")
    print("  ".join(str(p) for p in parts))


def _print_summary(summary: Dict[str, Any]) -> None:
    mode = "DRY-RUN" if summary.get("dry_run") else "APPLIED"
    print()
    print(f"=== Legacy Planet Evolution Backfill ({mode}) ===")
    print(f"total planets: {summary.get('total', 0)}")
    print(f"processed:     {summary.get('processed', 0)}")
    print(f"updated:       {summary.get('updated', 0)}")
    print(f"skipped:       {summary.get('skipped', 0)}")
    print(f"errors:        {summary.get('errors', 0)}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Planet Evolution state and grandfather legacy outpost colonies",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no writes")
    parser.add_argument("--player-id", type=int, default=None, help="Limit to one player")
    parser.add_argument("--planet-id", type=int, default=None, help="Limit to one planet")
    parser.add_argument("--limit", type=int, default=None, help="Max planets to process")
    args = parser.parse_args(list(argv) if argv is not None else None)

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application
    from game.db import db, resolve_db_path
    from game.planet_evolution.repository import evolution_schema_ready

    bootstrap_application(skip_migration_check=True)
    conn = db()

    try:
        if not evolution_schema_ready(conn):
            print("Planet Evolution schema not ready — run migrations first.", file=sys.stderr)
            return 1

        planet_ids = fetch_planet_ids(
            conn,
            player_id=args.player_id,
            planet_id=args.planet_id,
            limit=args.limit,
        )
        if not planet_ids:
            print(f"No planets matched (db={resolve_db_path()}).")
            _print_summary(
                {
                    "total": 0,
                    "processed": 0,
                    "updated": 0,
                    "skipped": 0,
                    "errors": 0,
                    "dry_run": bool(args.dry_run),
                }
            )
            return 0

        print(f"DB: {resolve_db_path()}")
        print(f"Planets to process: {len(planet_ids)}")
        summary = run_backfill(conn, planet_ids, dry_run=bool(args.dry_run))
        _print_summary(summary)
        return 1 if int(summary.get("errors") or 0) > 0 else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
