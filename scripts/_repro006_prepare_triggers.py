#!/usr/bin/env python3
"""Prepare REPRO-006 trigger states T0–T10 from golden seed (harness only)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from _repro004_common import copy_seed, SECRET  # noqa: E402
from _repro004_prepare_state import (  # noqa: E402
    _ensure_backup_today,
    _many_due_fleets,
    _many_due_queues,
    _norm_s0,
    _set_full_reconcile_due,
)

TRIGGERS = (
    "T0_NORMALIZED",
    "T1_MANY_DUE_FLEETS",
    "T2_MANY_DUE_QUEUES",
    "T3_FLEETS_AND_QUEUES",
    "T4_RANKING_DIRTY_BATCH",
    "T5_FULL_RECONCILE_DUE",
    "T6_BACKUP_DUE",
    "T7_AUTOPLAY_PRESSURE",  # mark many inactive players if schema allows
    "T8_WORLD_BOSS_LIVEOPS",  # light touch — ensure tables exist / due markers
    "T9_INTERNAL_CRON_PARALLEL",  # same as T0; harness runs cron during load
    "T10_COMBINED_WORST",
)


def _player_ids(meta: dict) -> list[int]:
    pids = [int(x) for x in (meta.get("players") or []) if x]
    return pids or [int(meta.get("primary_player_id") or 2)]


def _ranking_dirty_batch(conn, player_ids: list[int], *, n: int = 80) -> int:
    """Mark many players dirty for ranking without full reconcile."""
    from game.ranking_worker import FULL_RECONCILE_KEY
    from game.runtime_state import set_runtime_value

    set_runtime_value(FULL_RECONCILE_KEY, str(time.time()), conn=conn)
    # Common dirty patterns in this codebase
    count = 0
    for pid in player_ids[:n]:
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO ranking_dirty_players (player_id, dirty_at)
                VALUES (?, ?);
                """,
                (int(pid), time.time()),
            )
            count += 1
        except sqlite3.Error:
            try:
                conn.execute(
                    "UPDATE players SET score_dirty = 1 WHERE id = ?;",
                    (int(pid),),
                )
                count += 1
            except sqlite3.Error:
                pass
    conn.commit()
    return count


def _autoplay_pressure(conn, player_ids: list[int]) -> int:
    now = time.time()
    n = 0
    # Soft-on candidates: last_login far in the past
    for pid in player_ids[:40]:
        try:
            conn.execute(
                "UPDATE players SET last_login = ? WHERE id = ?;",
                (now - 14 * 86400, int(pid)),
            )
            n += 1
        except sqlite3.Error:
            try:
                conn.execute(
                    "UPDATE players SET last_active = ? WHERE id = ?;",
                    (now - 14 * 86400, int(pid)),
                )
                n += 1
            except sqlite3.Error:
                pass
    conn.commit()
    return n


def prepare_trigger(seed: Path, out_db: Path, trigger_id: str) -> dict:
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
    from game.db import db

    bootstrap_application(skip_migration_check=True)
    meta_path = seed.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    pids = _player_ids(meta)
    flags = {
        "backup_due": False,
        "full_reconcile_due": False,
        "due_fleets": False,
        "due_queues": False,
        "ranking_dirty": False,
        "autoplay_pressure": False,
        "internal_cron_parallel": trigger_id == "T9_INTERNAL_CRON_PARALLEL",
    }
    stats: dict = {"trigger_id": trigger_id, "player_ids": pids[:12], "flags": flags}

    conn = db()
    try:
        _norm_s0(conn)
        _ensure_backup_today(out_db, present=True)

        if trigger_id in ("T1_MANY_DUE_FLEETS", "T3_FLEETS_AND_QUEUES", "T10_COMBINED_WORST"):
            stats["due_fleet_rows"] = _many_due_fleets(conn, pids)
            flags["due_fleets"] = True
        if trigger_id in ("T2_MANY_DUE_QUEUES", "T3_FLEETS_AND_QUEUES", "T10_COMBINED_WORST"):
            stats["due_queue_rows"] = _many_due_queues(conn, pids)
            flags["due_queues"] = True
        if trigger_id in ("T4_RANKING_DIRTY_BATCH", "T10_COMBINED_WORST"):
            stats["dirty_marked"] = _ranking_dirty_batch(conn, pids)
            flags["ranking_dirty"] = True
        if trigger_id in ("T5_FULL_RECONCILE_DUE", "T10_COMBINED_WORST"):
            _set_full_reconcile_due(conn)
            flags["full_reconcile_due"] = True
        if trigger_id in ("T6_BACKUP_DUE", "T10_COMBINED_WORST"):
            _ensure_backup_today(out_db, present=False)
            flags["backup_due"] = True
        if trigger_id in ("T7_AUTOPLAY_PRESSURE", "T10_COMBINED_WORST"):
            stats["autoplay_marked"] = _autoplay_pressure(conn, pids)
            flags["autoplay_pressure"] = True
        # T8: no schema surgery — harness may nudge world-boss endpoints under load
        stats["db_bytes"] = out_db.stat().st_size
        return stats
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=str(ROOT / "artifacts/concurrency_repro/seed.db"))
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts/concurrency_repro/repro006/states"))
    parser.add_argument("--trigger", choices=TRIGGERS, default="T0_NORMALIZED")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--subset",
        default="",
        help="Comma-separated trigger ids",
    )
    args = parser.parse_args()
    seed = Path(args.seed).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.all:
        ids = list(TRIGGERS)
    elif args.subset:
        ids = [x.strip() for x in args.subset.split(",") if x.strip()]
    else:
        ids = [args.trigger]
    summary = {}
    for tid in ids:
        out_db = out_dir / f"{tid}.db"
        summary[tid] = prepare_trigger(seed, out_db, tid)
        print(json.dumps(summary[tid], sort_keys=True))
    (out_dir / "triggers_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
