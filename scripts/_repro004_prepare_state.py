#!/usr/bin/env python3
"""Prepare REPRO-004 state-matrix DB copies (S0–S7) from golden seed."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from _repro004_common import STATE_IDS, copy_seed, SECRET  # noqa: E402


def _norm_s0(conn) -> None:
    from game.ranking_worker import BUSY_KEY, FULL_RECONCILE_KEY
    from game.runtime_state import set_runtime_value

    now = time.time()
    set_runtime_value(FULL_RECONCILE_KEY, str(now), conn=conn)
    set_runtime_value(BUSY_KEY, "0", conn=conn)
    conn.commit()


def _ensure_backup_today(db_path: Path, *, present: bool) -> None:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    dst = backup_dir / f"game-{day}.db"
    if present:
        if not dst.exists():
            import shutil

            shutil.copy2(db_path, dst)
    elif dst.exists():
        dst.unlink()


def _set_full_reconcile_due(conn) -> None:
    from game.ranking_worker import FULL_RECONCILE_KEY
    from game.runtime_state import set_runtime_value

    set_runtime_value(FULL_RECONCILE_KEY, "1", conn=conn)
    conn.commit()


def _player_planets(conn, player_ids: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for pid in player_ids:
        row = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? ORDER BY id LIMIT 1;",
            (int(pid),),
        ).fetchone()
        if row:
            out[int(pid)] = int(row[0])
    return out


def _many_due_fleets(conn, player_ids: list[int], *, per_player: int = 8) -> int:
    now = time.time()
    planets = _player_planets(conn, player_ids[:12])
    n = 0
    for pid, origin in planets.items():
        for i in range(per_player):
            try:
                conn.execute(
                    """
                    INSERT INTO fleet_movements (
                        player_id, origin_planet_id, target_planet_id,
                        target_galaxy, target_system, target_position,
                        mission_type, status, departure_at, arrival_at, return_at,
                        ships_json, resources_json, fuel_cost, speed_percent,
                        distance, flight_seconds, created_at, updated_at
                    ) VALUES (?, ?, NULL, 1, 1, ?, 'transport', 'outbound',
                              ?, ?, NULL, '{}', '{}', 0, 100, 1, 100, ?, ?);
                    """,
                    (
                        int(pid),
                        int(origin),
                        (i % 9) + 1,
                        now - 3600,
                        now - 60 - i,
                        now,
                        now,
                    ),
                )
                n += 1
            except sqlite3.Error:
                pass
    if player_ids:
        placeholders = ",".join("?" * len(player_ids[:20]))
        conn.execute(
            f"""
            UPDATE fleet_movements
            SET arrival_at = ?, updated_at = ?
            WHERE status = 'outbound' AND player_id IN ({placeholders});
            """,
            [now - 30, now] + [int(x) for x in player_ids[:20]],
        )
        conn.execute(
            f"""
            UPDATE fleet_movements
            SET holding_until = ?, updated_at = ?
            WHERE status = 'holding' AND player_id IN ({placeholders});
            """,
            [now - 30, now] + [int(x) for x in player_ids[:20]],
        )
        conn.execute(
            f"""
            UPDATE fleet_movements
            SET return_at = ?, updated_at = ?
            WHERE status = 'returning' AND player_id IN ({placeholders});
            """,
            [now - 30, now] + [int(x) for x in player_ids[:20]],
        )
    conn.commit()
    return n


def _many_due_queues(conn, player_ids: list[int], *, per_planet: int = 4) -> int:
    now = time.time()
    planets = _player_planets(conn, player_ids[:12])
    n = 0
    for pid, planet_id in planets.items():
        for i in range(per_planet):
            due = now - 10 - i
            try:
                conn.execute(
                    """
                    INSERT INTO build_queue (
                        planet_id, building_type, start_time, finish_time, cost_metal, cost_crystal
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (planet_id, "metal_mine", due - 120, due, 100, 50),
                )
                n += 1
            except sqlite3.Error:
                pass
            try:
                conn.execute(
                    """
                    INSERT INTO research_queue (
                        user_id, tech_key, start_at, finish_at, cost_metal, cost_crystal
                    ) VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (int(pid), "energy_tech", due - 120, due, 100, 50),
                )
                n += 1
            except sqlite3.Error:
                pass
    conn.commit()
    return n


def prepare_state(
    seed: Path,
    out_db: Path,
    state_id: str,
    *,
    player_ids: list[int] | None = None,
) -> dict:
    copy_seed(seed, out_db)
    os.environ.update(
        {
            "GC_DB_PATH": str(out_db.resolve()),
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_MAINTENANCE_WORKER": "1",
            "GC_EMBEDDED_CRON": "0",
            "SECRET_KEY": SECRET,
            "APP_ENV": "development",
            "GC_DB_BACKEND": "sqlite",
        }
    )
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    from game.db import db

    conn = db()
    try:
        meta_path = seed.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        pids = player_ids or [int(x) for x in (meta.get("players") or [])[:20]]
        if not pids:
            pids = [int(meta.get("primary_player_id") or 2)]

        flags = {
            "backup_due": False,
            "full_reconcile_due": False,
            "due_fleets": False,
            "due_queues": False,
        }
        stats: dict = {"state_id": state_id, "player_ids": pids[:12]}

        _norm_s0(conn)
        _ensure_backup_today(out_db, present=True)

        if state_id in ("S1_BACKUP_DUE", "S7_WORST_PLAUSIBLE"):
            _ensure_backup_today(out_db, present=False)
            flags["backup_due"] = True

        if state_id in (
            "S2_FULL_RECONCILE_DUE",
            "S6_RECONCILE_FLEET_QUEUES",
            "S7_WORST_PLAUSIBLE",
        ):
            _set_full_reconcile_due(conn)
            flags["full_reconcile_due"] = True

        if state_id in (
            "S3_MANY_DUE_FLEETS",
            "S5_FLEET_AND_QUEUES",
            "S6_RECONCILE_FLEET_QUEUES",
            "S7_WORST_PLAUSIBLE",
        ):
            stats["due_fleet_rows"] = _many_due_fleets(conn, pids)
            flags["due_fleets"] = True

        if state_id in (
            "S4_MANY_DUE_QUEUES",
            "S5_FLEET_AND_QUEUES",
            "S6_RECONCILE_FLEET_QUEUES",
            "S7_WORST_PLAUSIBLE",
        ):
            stats["due_queue_rows"] = _many_due_queues(conn, pids)
            flags["due_queues"] = True

        stats["flags"] = flags
        stats["db_bytes"] = out_db.stat().st_size
        return stats
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=str(ROOT / "artifacts/concurrency_repro/seed.db"))
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts/concurrency_repro/repro004/states"))
    parser.add_argument("--state", choices=STATE_IDS, default="S0_NORMALIZED")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    seed = Path(args.seed).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    states = list(STATE_IDS) if args.all else [args.state]
    summary = {}
    for sid in states:
        out_db = out_dir / f"{sid}.db"
        summary[sid] = prepare_state(seed, out_db, sid)
        print(json.dumps(summary[sid], sort_keys=True))
    (out_dir / "states_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
