#!/usr/bin/env python3
"""Analyze REPRO-006 provenance JSONL — holders vs waiters, occupancy, chains."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_events(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _pct(vals: List[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return float(s[idx])


def _summary(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"n": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0}
    return {
        "n": len(vals),
        "p50": round(_pct(vals, 50), 2),
        "p95": round(_pct(vals, 95), 2),
        "p99": round(_pct(vals, 99), 2),
        "max": round(max(vals), 2),
        "mean": round(statistics.mean(vals), 2),
    }


def analyze(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    holds: Dict[str, List[float]] = defaultdict(list)
    waits: Dict[str, List[float]] = defaultdict(list)
    completed: List[Dict[str, Any]] = []
    polls = [e for e in events if e.get("event") == "GAME_STATE_POLL"]

    by_tx: Dict[str, Dict[str, Any]] = {}
    for e in events:
        tid = str(e.get("transaction_id") or "")
        if not tid:
            continue
        rec = by_tx.setdefault(tid, {"events": []})
        rec["events"].append(e)
        if e.get("event") == "BEGIN_ATTEMPT":
            rec["owner"] = e.get("owner")
            rec["attempt_ts"] = e.get("ts")
            rec["route"] = e.get("route")
            rec["player_id"] = e.get("player_id")
            rec["process"] = e.get("process")
        if e.get("event") == "BEGIN_ACQUIRED":
            rec["acquired_ts"] = e.get("ts")
            rec["wait_ms"] = float(e.get("wait_ms") or 0)
            waits[str(e.get("owner") or "unknown")].append(float(e.get("wait_ms") or 0))
        if e.get("event") in ("COMMIT", "ROLLBACK"):
            rec["end_ts"] = e.get("ts")
            rec["hold_ms"] = float(e.get("hold_ms") or 0)
            rec["wait_ms"] = float(e.get("wait_ms") or rec.get("wait_ms") or 0)
            rec["owner"] = e.get("owner") or rec.get("owner")
            holds[str(rec.get("owner") or "unknown")].append(float(rec["hold_ms"]))
            completed.append(rec)

    # Occupancy: union of [acquired_ts, end_ts]
    intervals: List[Tuple[float, float]] = []
    for rec in completed:
        a = rec.get("acquired_ts")
        b = rec.get("end_ts")
        if a is None or b is None:
            continue
        intervals.append((float(a), float(b)))
    intervals.sort()
    merged: List[Tuple[float, float]] = []
    for a, b in intervals:
        if not merged or a > merged[-1][1]:
            merged.append((a, b))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
    busy_ms = sum((b - a) * 1000.0 for a, b in merged)
    if intervals:
        window_ms = (intervals[-1][1] - intervals[0][0]) * 1000.0
    else:
        window_ms = 0.0
    occupancy_pct = round(100.0 * busy_ms / window_ms, 2) if window_ms > 0 else 0.0

    # Longest continuous busy window
    longest_busy_ms = 0.0
    for a, b in merged:
        longest_busy_ms = max(longest_busy_ms, (b - a) * 1000.0)

    # Chains: for high-wait acquires, find overlapping holders
    chains: List[Dict[str, Any]] = []
    waiters = sorted(
        [r for r in completed if float(r.get("wait_ms") or 0) >= 500],
        key=lambda r: -float(r.get("wait_ms") or 0),
    )[:20]
    for w in waiters:
        attempt = float(w.get("attempt_ts") or 0)
        acquired = float(w.get("acquired_ts") or 0)
        holders = []
        for h in completed:
            ha = float(h.get("acquired_ts") or 0)
            hb = float(h.get("end_ts") or 0)
            if ha <= attempt and hb >= attempt:
                # held during waiter's attempt
                holders.append(
                    {
                        "owner": h.get("owner"),
                        "hold_ms": round(float(h.get("hold_ms") or 0), 2),
                        "process": h.get("process"),
                        "player_id": h.get("player_id"),
                        "route": h.get("route"),
                        "transaction_id": (h.get("events") or [{}])[0].get("transaction_id")
                        if False
                        else None,
                        "acquired_ts": ha,
                        "end_ts": hb,
                    }
                )
            elif ha < acquired and hb > attempt:
                holders.append(
                    {
                        "owner": h.get("owner"),
                        "hold_ms": round(float(h.get("hold_ms") or 0), 2),
                        "process": h.get("process"),
                        "player_id": h.get("player_id"),
                        "route": h.get("route"),
                        "acquired_ts": ha,
                        "end_ts": hb,
                    }
                )
        # dedupe by owner+acquired
        uniq = {}
        for h in holders:
            key = (h.get("owner"), h.get("acquired_ts"))
            uniq[key] = h
        chains.append(
            {
                "waiter_owner": w.get("owner"),
                "waiter_wait_ms": round(float(w.get("wait_ms") or 0), 2),
                "waiter_hold_ms": round(float(w.get("hold_ms") or 0), 2),
                "waiter_route": w.get("route"),
                "waiter_player_id": w.get("player_id"),
                "holders_during_wait": list(uniq.values()),
            }
        )

    top_holders = sorted(
        (
            {"owner": k, **_summary(v)}
            for k, v in holds.items()
        ),
        key=lambda r: -float(r.get("max") or 0),
    )
    top_waiters = sorted(
        (
            {"owner": k, **_summary(v)}
            for k, v in waits.items()
        ),
        key=lambda r: -float(r.get("max") or 0),
    )

    # game-state write rate
    gs_polls = len(polls)
    gs_write_tx = sum(
        1
        for r in completed
        if str(r.get("route") or "") == "/api/game-state"
        or str(r.get("owner") or "").startswith("game_state")
        or str(r.get("owner") or "") in ("poll_finish_lease", "resource_sync")
    )
    write_per_100 = round(100.0 * gs_write_tx / gs_polls, 2) if gs_polls else None

    longest_holder = top_holders[0] if top_holders else None
    longest_waiter = top_waiters[0] if top_waiters else None

    # GC-PROD-SQLITE-STALL-001B: named fleet TX holds (hold_ms only)
    fleet_completed = [
        r
        for r in completed
        if str(r.get("owner") or "")
        in {
            "fleet_movement",
            "fleet_post_maintenance",
            "fleet_worker_result_persist",
            "world_boss_auto",
            "other_fleet_stage",
            "fleet_worker",  # legacy broad label
        }
    ]

    def _fleet_detail(rec: Dict[str, Any]) -> Dict[str, Any]:
        # Pull movement/stage fields from COMMIT event if present on rec events
        detail: Dict[str, Any] = {
            "owner": rec.get("owner"),
            "hold_ms": round(float(rec.get("hold_ms") or 0), 2),
            "wait_ms": round(float(rec.get("wait_ms") or 0), 2),
            "transaction_total_ms": None,
            "sql_count": None,
            "sql_write_count": None,
            "movement_id": None,
            "player_id": rec.get("player_id"),
            "mission": None,
            "movement_status": None,
            "phase": None,
            "stage": None,
            "process": None,
        }
        for e in rec.get("events") or []:
            if e.get("event") in ("COMMIT", "ROLLBACK", "BEGIN_ATTEMPT"):
                for k in (
                    "movement_id",
                    "mission",
                    "movement_status",
                    "phase",
                    "stage",
                    "sub_owner",
                    "sql_count",
                    "sql_write_count",
                    "transaction_total_ms",
                    "process",
                    "player_id",
                ):
                    if e.get(k) is not None and detail.get(k) in (None,):
                        detail[k] = e.get(k)
        if detail.get("transaction_total_ms") is not None:
            detail["transaction_total_ms"] = round(float(detail["transaction_total_ms"]), 2)
        return detail

    def _longest_for(owner: str) -> Optional[Dict[str, Any]]:
        rows = [r for r in fleet_completed if str(r.get("owner") or "") == owner]
        if not rows:
            return None
        best = max(rows, key=lambda r: float(r.get("hold_ms") or 0))
        return _fleet_detail(best)

    top_fleet_holds = sorted(
        (_fleet_detail(r) for r in fleet_completed),
        key=lambda r: -float(r.get("hold_ms") or 0),
    )[:15]

    return {
        "event_count": len(events),
        "completed_tx": len(completed),
        "TOP_WRITE_LOCK_HOLDERS": top_holders[:15],
        "TOP_WRITE_LOCK_WAITERS": top_waiters[:15],
        "LONGEST_WRITE_HOLDER": longest_holder,
        "LONGEST_WRITE_WAIT": longest_waiter,
        "writer_occupancy_percent": occupancy_pct,
        "longest_continuous_writer_busy_window_ms": round(longest_busy_ms, 2),
        "window_ms": round(window_ms, 2),
        "busy_ms": round(busy_ms, 2),
        "LONGEST_CHAINS": chains[:10],
        "game_state_polls": gs_polls,
        "game_state_write_tx": gs_write_tx,
        "GAME_STATE_WRITE_RATE_per_100_GETS": write_per_100,
        "poll_fleet_dirty_true": sum(1 for p in polls if p.get("fleet_dirty") is True),
        "poll_queue_due_true": sum(1 for p in polls if p.get("queue_due") is True),
        "LONGEST_FLEET_MOVEMENT_TX": _longest_for("fleet_movement"),
        "LONGEST_POST_MAINT_TX": _longest_for("fleet_post_maintenance"),
        "LONGEST_RESULT_PERSIST_TX": _longest_for("fleet_worker_result_persist"),
        "LONGEST_AUTO_ATTACK_TX": _longest_for("world_boss_auto"),
        "TOP_FLEET_TX_HOLDS": top_fleet_holds,
        "FLEET_TX_HOLD_GT_800MS": [
            d for d in top_fleet_holds if float(d.get("hold_ms") or 0) > 800
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    path = Path(args.log)
    report = analyze(load_events(path))
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
