#!/usr/bin/env python3
"""Single-tree probe for prod infinity-load A/B (invoked per historical worktree).

Loads game code from --code-root (historical tree), measures:
- count_claimable_directives / count_pending_government_votes SQL time
- EXPLAIN QUERY PLAN
- repeated /api/game-state + SSR routes
- optional writer-contention (BEGIN IMMEDIATE hold) to split lock-wait vs SQL

Does not modify production. Temp DB path via --db.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional


def _pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def _summarize(samples_ms: List[float]) -> Dict[str, float]:
    if not samples_ms:
        return {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}
    s = sorted(samples_ms)
    return {
        "n": len(s),
        "p50_ms": round(_pct(s, 50), 3),
        "p95_ms": round(_pct(s, 95), 3),
        "p99_ms": round(_pct(s, 99), 3),
        "max_ms": round(s[-1], 3),
        "mean_ms": round(statistics.mean(s), 3),
    }


def _bootstrap(code_root: Path, db_path: Path) -> Any:
    os.environ["GC_DB_PATH"] = str(db_path)
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    os.environ.setdefault("SECRET_KEY", "prod-infinity-load-ab-secret-key-32c")
    os.environ.setdefault("GC_PERF_INTEL", "1")
    os.environ.setdefault("GC_REQUEST_PERF_SAMPLE", "1")
    os.environ.setdefault("GC_PERF_INTEL_SAMPLE", "1")
    os.environ.setdefault("APP_ENV", "development")

    # Prefer historical tree modules.
    root = str(code_root.resolve())
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    import game.db as gdb

    gdb._DB_PATH = None
    if hasattr(gdb, "DB_PATH"):
        gdb.DB_PATH = db_path

    import game.models as models

    if hasattr(models, "DB_PATH"):
        models.DB_PATH = db_path

    import app as app_module

    importlib.reload(gdb)
    gdb._DB_PATH = None
    if hasattr(gdb, "DB_PATH"):
        gdb.DB_PATH = db_path
    importlib.reload(models)
    if hasattr(models, "DB_PATH"):
        models.DB_PATH = db_path
    importlib.reload(app_module)
    return app_module


def _explain(conn: sqlite3.Connection, sql: str, params: tuple) -> List[str]:
    rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
    out = []
    for row in rows:
        if hasattr(row, "keys"):
            out.append(" | ".join(str(row[k]) for k in row.keys()))
        else:
            out.append(" | ".join(str(x) for x in row))
    return out


def _timed_call(fn, *args, **kwargs):
    t0 = time.perf_counter()
    err = None
    result = None
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — probe must capture failures
        err = f"{type(exc).__name__}: {exc}"
    ms = (time.perf_counter() - t0) * 1000.0
    return ms, result, err


def _measure_fn_loop(fn, loops: int) -> Dict[str, Any]:
    samples = []
    last_err = None
    last_result = None
    for _ in range(loops):
        ms, result, err = _timed_call(fn)
        samples.append(ms)
        if err:
            last_err = err
        else:
            last_result = result
    return {"timing": _summarize(samples), "last_result": last_result, "error": last_err}


class _WriterHold:
    """Hold BEGIN IMMEDIATE for `hold_ms` to force lock waits on writers."""

    def __init__(self, db_path: Path, hold_ms: float, cycles: int):
        self.db_path = db_path
        self.hold_ms = hold_ms
        self.cycles = cycles
        self.stop = threading.Event()
        self.events: List[Dict[str, Any]] = []
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="writer-hold", daemon=True)
        self._thread.start()

    def join(self) -> None:
        self.stop.set()
        if self._thread:
            self._thread.join(timeout=60)

    def _run(self) -> None:
        for i in range(self.cycles):
            if self.stop.is_set():
                break
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout=20000")
                t0 = time.perf_counter()
                busy = False
                try:
                    conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:
                    busy = True
                    self.events.append(
                        {
                            "cycle": i,
                            "phase": "begin_immediate",
                            "busy": True,
                            "error": str(exc),
                            "wait_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                        }
                    )
                    conn.close()
                    time.sleep(0.05)
                    continue
                begin_ms = (time.perf_counter() - t0) * 1000.0
                self.events.append(
                    {
                        "cycle": i,
                        "phase": "begin_immediate",
                        "busy": busy,
                        "wait_ms": round(begin_ms, 3),
                    }
                )
                time.sleep(max(0.0, self.hold_ms / 1000.0))
                conn.execute("COMMIT")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            time.sleep(0.02)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--player-id", type=int, required=True)
    parser.add_argument("--loops", type=int, default=50)
    parser.add_argument("--game-state-loops", type=int, default=100)
    parser.add_argument("--with-writer-hold", action="store_true")
    parser.add_argument("--writer-hold-ms", type=float, default=50.0)
    parser.add_argument("--writer-cycles", type=int, default=40)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    code_root = Path(args.code_root).resolve()
    db_path = Path(args.db).resolve()
    os.environ["GC_DB_PATH"] = str(db_path)
    report: Dict[str, Any] = {
        "label": args.label,
        "code_root": str(code_root),
        "db": str(db_path),
        "player_id": args.player_id,
        "sha_hint": None,
        "error": None,
    }

    try:
        app_module = _bootstrap(code_root, db_path)
        from game.db import db
        from game.directives.service import count_claimable_directives
        from game.galactic_directives.state import count_pending_government_votes

        conn = db()
        try:
            # Table sizes
            tables = [
                "players",
                "planets",
                "player_directives",
                "gd_cycles",
                "gd_votes",
                "vote_rewards",
                "auction_house_listings",
                "auction_house_bids",
            ]
            sizes = {}
            for t in tables:
                try:
                    sizes[t] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"])
                except Exception:
                    sizes[t] = None
            report["table_counts"] = sizes

            # Indexes
            idx_rows = conn.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name IN ('player_directives','gd_cycles','gd_votes','planets') "
                "ORDER BY tbl_name, name;"
            ).fetchall()
            report["indexes"] = [
                {"name": r["name"], "table": r["tbl_name"], "sql": r["sql"]} for r in idx_rows
            ]

            # Direct function timings (SQL / Python path of historical tree)
            report["count_claimable_directives"] = _measure_fn_loop(
                lambda: count_claimable_directives(args.player_id, conn=conn),
                args.loops,
            )
            report["count_pending_government_votes"] = _measure_fn_loop(
                lambda: count_pending_government_votes(args.player_id, conn=conn),
                args.loops,
            )

            # EXPLAIN for the STATE-012 / STATE-013 shaped queries (diagnostic; historical
            # trees may use different Python paths — still useful against same data).
            now = int(time.time())
            try:
                from game.directives.service import daily_period_key, weekly_period_key
                from game.directives.definitions import STATUS_COMPLETED

                sql_012 = (
                    "SELECT COUNT(*) AS claimable_count FROM player_directives "
                    "WHERE player_id = ? AND status = ? AND ("
                    "(cadence = 'daily' AND period_key = ?) OR "
                    "(cadence = 'weekly' AND period_key = ?))"
                )
                params_012 = (
                    args.player_id,
                    STATUS_COMPLETED,
                    daily_period_key(),
                    weekly_period_key(),
                )
                report["explain_state_012_shape"] = {
                    "sql": sql_012,
                    "plan": _explain(conn, sql_012, params_012),
                    "one_shot_ms": round(
                        _timed_call(lambda: conn.execute(sql_012, params_012).fetchone())[0],
                        3,
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                report["explain_state_012_shape"] = {"error": str(exc)}

            sql_013 = (
                "SELECT COUNT(*) AS c FROM gd_cycles c "
                "WHERE c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
                "AND EXISTS (SELECT 1 FROM planets p WHERE p.player_id = ? AND p.galaxy = c.galaxy) "
                "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
            )
            params_013 = (now, now, args.player_id, args.player_id)
            report["explain_state_013_shape"] = {
                "sql": sql_013,
                "plan": _explain(conn, sql_013, params_013),
                "one_shot_ms": round(
                    _timed_call(lambda: conn.execute(sql_013, params_013).fetchone())[0],
                    3,
                ),
            }

            # Stable-shape government query (galaxy IN list) for comparison
            galaxies = [
                int(r["galaxy"])
                for r in conn.execute(
                    "SELECT DISTINCT galaxy FROM planets WHERE player_id = ? AND galaxy IS NOT NULL",
                    (args.player_id,),
                ).fetchall()
            ]
            if galaxies:
                ph = ",".join("?" * len(galaxies))
                sql_stable = (
                    f"SELECT COUNT(*) AS c FROM gd_cycles c WHERE c.galaxy IN ({ph}) "
                    "AND c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
                    "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
                )
                params_stable = (*galaxies, now, now, args.player_id)
                report["explain_stable_gov_shape"] = {
                    "sql": sql_stable,
                    "plan": _explain(conn, sql_stable, params_stable),
                    "one_shot_ms": round(
                        _timed_call(lambda: conn.execute(sql_stable, params_stable).fetchone())[0],
                        3,
                    ),
                }
        finally:
            conn.close()

        # HTTP journeys
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = int(args.player_id)

        def _hit(path: str) -> Dict[str, Any]:
            t0 = time.perf_counter()
            in_tx_note = None
            try:
                resp = client.get(path)
                status = resp.status_code
                body_len = len(resp.get_data() or b"")
            except Exception as exc:  # noqa: BLE001
                return {
                    "path": path,
                    "error": f"{type(exc).__name__}: {exc}",
                    "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                }
            return {
                "path": path,
                "status": status,
                "bytes": body_len,
                "total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                "in_transaction_note": in_tx_note,
            }

        gs_samples = []
        gs_errors = 0
        for _ in range(args.game_state_loops):
            hit = _hit("/api/game-state")
            gs_samples.append(float(hit.get("total_ms") or 0.0))
            if hit.get("error") or int(hit.get("status") or 0) >= 500:
                gs_errors += 1
        report["api_game_state"] = {
            "timing": _summarize(gs_samples),
            "errors": gs_errors,
            "outlier_gt_2000ms": sum(1 for x in gs_samples if x > 2000),
            "outlier_gt_5000ms": sum(1 for x in gs_samples if x > 5000),
        }

        ssr_paths = ["/overview", "/fleet", "/world-boss", "/messages"]
        ssr = {}
        for path in ssr_paths:
            samples = []
            errors = 0
            for _ in range(max(5, min(20, args.loops))):
                hit = _hit(path)
                samples.append(float(hit.get("total_ms") or 0.0))
                if hit.get("error") or int(hit.get("status") or 0) >= 500:
                    errors += 1
            ssr[path] = {
                "timing": _summarize(samples),
                "errors": errors,
                "outlier_gt_5000ms": sum(1 for x in samples if x > 5000),
            }
        report["ssr"] = ssr

        if args.with_writer_hold:
            holder = _WriterHold(db_path, args.writer_hold_ms, args.writer_cycles)
            holder.start()
            contended = []
            t_start = time.perf_counter()
            for _ in range(max(20, args.loops // 2)):
                # Force a write on the request path via ensure/commit when present,
                # plus a direct BEGIN IMMEDIATE to observe lock wait.
                t0 = time.perf_counter()
                busy = False
                err = None
                begin_ms = None
                try:
                    wconn = sqlite3.connect(str(db_path), timeout=30.0)
                    wconn.execute("PRAGMA busy_timeout=20000")
                    b0 = time.perf_counter()
                    try:
                        wconn.execute("BEGIN IMMEDIATE")
                        begin_ms = (time.perf_counter() - b0) * 1000.0
                        wconn.execute("COMMIT")
                    except sqlite3.OperationalError as exc:
                        busy = True
                        err = str(exc)
                        begin_ms = (time.perf_counter() - b0) * 1000.0
                    finally:
                        wconn.close()
                except Exception as exc:  # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"
                hit = _hit("/api/game-state")
                contended.append(
                    {
                        "request_start_offset_ms": round((t0 - t_start) * 1000.0, 3),
                        "begin_immediate_ms": round(begin_ms or 0.0, 3),
                        "busy_locked": busy,
                        "begin_error": err,
                        "game_state_ms": hit.get("total_ms"),
                        "game_state_status": hit.get("status"),
                    }
                )
            holder.join()
            begin_samples = [float(x["begin_immediate_ms"]) for x in contended]
            gs_c = [float(x["game_state_ms"] or 0.0) for x in contended]
            report["lock_contention"] = {
                "writer_events": holder.events[:20],
                "writer_event_count": len(holder.events),
                "samples": contended[:20],
                "begin_immediate_timing": _summarize(begin_samples),
                "game_state_during_writer": _summarize(gs_c),
                "busy_locked_count": sum(1 for x in contended if x["busy_locked"]),
            }
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": report.get("error") is None, "out": str(out), "label": args.label}))
    return 0 if report.get("error") is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
