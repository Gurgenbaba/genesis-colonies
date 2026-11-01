#!/usr/bin/env python3
"""REPRO-006 harness-only SQLite write provenance (no production file edits).

Install via sitecustomize on PYTHONPATH when GC_REPRO006_PROVENANCE=1.
Logs JSONL events to GC_REPRO006_PROV_LOG (default /data/tx_provenance.jsonl).

GC-PROD-SQLITE-STALL-001B: fleet path emits sub_owner + movement/stage metadata
via game.tx_context; hold_ms (not wall time) is the single-TX gate metric.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

_INSTALLED = False
_TLS = threading.local()
_FILE_LOCK = threading.Lock()

_WRITE_SQL_RE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)

_FLEET_OWNERS = {
    "fleet_movement",
    "fleet_post_maintenance",
    "fleet_worker_result_persist",
    "world_boss_auto",
    "other_fleet_stage",
}


def _log_path() -> str:
    return os.environ.get("GC_REPRO006_PROV_LOG", "/data/tx_provenance.jsonl")


def _emit(event: Dict[str, Any]) -> None:
    event.setdefault("ts", time.time())
    event.setdefault("pid", os.getpid())
    event.setdefault("thread_id", threading.get_ident())
    line = json.dumps(event, ensure_ascii=False, default=str)
    path = _log_path()
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _FILE_LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


def _http_context() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from flask import has_request_context, request, session, g

        if not has_request_context():
            return out
        out["route"] = str(getattr(request, "path", "") or "")
        out["method"] = str(getattr(request, "method", "") or "")
        out["request_id"] = str(
            request.headers.get("X-Request-Id")
            or getattr(g, "request_id", "")
            or ""
        )
        try:
            out["player_id"] = int(session.get("user_id") or 0) or None
        except Exception:
            out["player_id"] = None
        endpoint = getattr(request, "endpoint", None)
        if endpoint:
            out["endpoint"] = str(endpoint)
    except Exception:
        pass
    return out


def _product_tx_context() -> Dict[str, Any]:
    try:
        from game.tx_context import current

        ctx = current()
        return dict(ctx) if isinstance(ctx, dict) else {}
    except Exception:
        return {}


def _classify_fleet(stack: List[str], joined: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sub = str(ctx.get("sub_owner") or "")
    if sub in _FLEET_OWNERS:
        out = {"owner": sub, "sub_owner": sub}
        for key in ("movement_id", "player_id", "mission", "movement_status", "phase", "stage"):
            if ctx.get(key) is not None:
                out[key] = ctx[key]
        return out

    if "record_fleet_worker_result" in joined:
        return {"owner": "fleet_worker_result_persist", "sub_owner": "fleet_worker_result_persist"}
    if "tick_world_boss_auto_attacks" in joined:
        return {"owner": "world_boss_auto", "sub_owner": "world_boss_auto"}
    if (
        "_run_one_movement_short_tx" in joined
        or "_run_one_movement_short_tx_body" in joined
        or "_handle_arrival" in joined
        or "_handle_return" in joined
        or "_handle_holding_end" in joined
    ):
        return {"owner": "fleet_movement", "sub_owner": "fleet_movement"}
    if "_maybe_run_post_fleet_maintenance" in joined or "_run_stage" in joined:
        return {
            "owner": "fleet_post_maintenance",
            "sub_owner": "fleet_post_maintenance",
            "stage": ctx.get("stage") or "unknown",
        }
    if (
        "run_fleet_worker" in joined
        or "execute_fleet_tick" in joined
        or "process_fleet_tick" in joined
    ):
        return {"owner": "other_fleet_stage", "sub_owner": "other_fleet_stage"}
    return None


def _classify_owner(stack: List[str], http: Dict[str, Any]) -> str:
    joined = " | ".join(stack)
    route = str(http.get("route") or "")
    ctx = _product_tx_context()

    fleet = _classify_fleet(stack, joined, ctx)
    if fleet:
        return str(fleet["owner"])

    rules = [
        ("sqlite_backup", ("maybe_sqlite_volume_backup", "sqlite_backup")),
        ("ranking_full", ("full_reconcile", "run_full_reconcile")),
        ("ranking_dirty", ("ranking_worker", "execute_ranking", "dirty_batch")),
        ("inactive_autoplay", ("inactive_autoplay",)),
        ("pirates", ("pirate", "run_pirates")),
        ("debris", ("debris",)),
        ("asteroids", ("asteroid",)),
        ("world_boss", ("world_boss",)),
        ("combat_bots", ("combat_bot",)),
        ("liveops", ("liveops",)),
        ("hof", ("hall_of_fame", "hof_")),
        ("account_deletion", ("account_deletion",)),
        ("privacy_retention", ("privacy_retention",)),
        ("maintenance_heartbeat", ("record_maintenance_bag_heartbeat", "maintenance_bag")),
        ("internal_cron", ("http_cron", "handle_internal_cron")),
    ]
    low = joined.lower()
    for owner, needles in rules:
        if any(n.lower() in low for n in needles):
            return owner

    if "touch_player_online" in joined:
        return "presence_touch"
    if "read_player_live_state_for_poll" in joined or route == "/api/game-state":
        if "process_fleet_tick" in joined or "player_fleet_is_dirty" in joined:
            return "game_state_fleet_tick"
        if "finish_player_due_work" in joined or "finish_due_work" in joined:
            return "game_state_queue_finish"
        if "try_claim_poll_due_finish" in joined or "record_poll_queue_finish" in joined:
            return "poll_finish_lease"
        if "update_planet_resources" in joined:
            return "resource_sync"
        return "game_state_write"
    if route.startswith("/fleet"):
        return "fleet_page"
    if "world-boss" in route or "world_boss" in low:
        return "world_boss_http"
    if "/api/chat" in route or "chat" in route:
        return "chat"
    if "/api/notifications" in route:
        return "notifications_write"
    if route in ("/login", "/api/login") or ("login" in low and "session" in low):
        return "login_session_write"
    if route:
        return f"http:{route}"
    if "finish_due_work" in joined:
        return "queue_finish"
    return "unknown_write"


def _owner_meta(stack: List[str], http: Dict[str, Any]) -> Dict[str, Any]:
    joined = " | ".join(stack)
    ctx = _product_tx_context()
    fleet = _classify_fleet(stack, joined, ctx)
    if not fleet:
        return {}
    return {k: v for k, v in fleet.items() if k != "owner" and v is not None}


def _stack_names(limit: int = 28) -> List[str]:
    frames = traceback.extract_stack(limit=limit + 8)
    names: List[str] = []
    for fr in frames[:-2]:
        mod = fr.filename.replace("\\", "/")
        if "/site-packages/" in mod or mod.endswith("sitecustomize.py"):
            continue
        if "/repro006" in mod or "_repro006" in mod:
            continue
        base = mod.rsplit("/", 1)[-1]
        names.append(f"{base}:{fr.name}")
    return names[-limit:]


def _active() -> Optional[Dict[str, Any]]:
    return getattr(_TLS, "active_tx", None)


def _bump_sql(sql: Any) -> None:
    active = _active()
    if not active:
        return
    active["sql_count"] = int(active.get("sql_count") or 0) + 1
    text = str(sql or "")
    if _WRITE_SQL_RE.match(text):
        active["sql_write_count"] = int(active.get("sql_write_count") or 0) + 1


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if os.environ.get("GC_REPRO006_PROVENANCE", "").strip() not in ("1", "true", "yes", "on"):
        return

    import game.db as gdb

    orig_begin = gdb.begin_write_transaction
    orig_commit = gdb.commit
    orig_rollback = gdb.rollback

    def begin_write_transaction(conn, *, retries: int = 12):  # type: ignore[no-untyped-def]
        if gdb.in_transaction(conn):
            return orig_begin(conn, retries=retries)

        http = _http_context()
        stack = _stack_names()
        owner = _classify_owner(stack, http)
        meta = _owner_meta(stack, http)
        # Prefer product context player_id for fleet movements over session.
        if meta.get("player_id") and not http.get("player_id"):
            http = dict(http)
            http["player_id"] = meta["player_id"]
        tx_id = uuid.uuid4().hex[:16]
        attempt_ts = time.time()
        _emit(
            {
                "event": "BEGIN_ATTEMPT",
                "transaction_id": tx_id,
                "owner": owner,
                "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
                "stack": stack[-12:],
                **meta,
                **{k: v for k, v in http.items() if v},
            }
        )
        t0 = time.perf_counter()
        try:
            orig_begin(conn, retries=retries)
        except Exception as exc:
            wait_ms = (time.perf_counter() - t0) * 1000.0
            _emit(
                {
                    "event": "BEGIN_FAILED",
                    "transaction_id": tx_id,
                    "owner": owner,
                    "wait_ms": round(wait_ms, 2),
                    "error": f"{type(exc).__name__}:{exc}",
                    "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
                    **meta,
                    **{k: v for k, v in http.items() if v},
                }
            )
            raise
        wait_ms = (time.perf_counter() - t0) * 1000.0
        acquired_ts = time.time()
        _TLS.active_tx = {
            "transaction_id": tx_id,
            "owner": owner,
            "meta": meta,
            "attempt_ts": attempt_ts,
            "acquired_ts": acquired_ts,
            "wait_ms": wait_ms,
            "http": http,
            "stack": stack,
            "sql_count": 0,
            "sql_write_count": 0,
        }
        _emit(
            {
                "event": "BEGIN_ACQUIRED",
                "transaction_id": tx_id,
                "owner": owner,
                "wait_ms": round(wait_ms, 2),
                "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
                "stack": stack[-12:],
                **meta,
                **{k: v for k, v in http.items() if v},
            }
        )
        return None

    def _finish(kind: str, conn):  # type: ignore[no-untyped-def]
        active = _active()
        if active:
            now = time.time()
            hold_ms = (now - float(active["acquired_ts"])) * 1000.0
            total_ms = (now - float(active["attempt_ts"])) * 1000.0
            tx_id = active["transaction_id"]
            owner = active["owner"]
            wait_ms = active["wait_ms"]
            http = active.get("http") or {}
            meta = dict(active.get("meta") or {})
            sql_count = int(active.get("sql_count") or 0)
            sql_write_count = int(active.get("sql_write_count") or 0)
        else:
            hold_ms = total_ms = wait_ms = None
            tx_id = owner = None
            http = _http_context()
            meta = {}
            sql_count = sql_write_count = 0
        try:
            if kind == "COMMIT":
                orig_commit(conn)
            else:
                orig_rollback(conn)
        finally:
            if active:
                _emit(
                    {
                        "event": kind,
                        "transaction_id": tx_id,
                        "owner": owner,
                        "wait_ms": round(float(wait_ms or 0), 2),
                        "hold_ms": round(float(hold_ms or 0), 2),
                        "transaction_total_ms": round(float(total_ms or 0), 2),
                        "sql_count": sql_count,
                        "sql_write_count": sql_write_count,
                        "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
                        **meta,
                        **{k: v for k, v in http.items() if v},
                    }
                )
                _TLS.active_tx = None

    def commit(conn):  # type: ignore[no-untyped-def]
        return _finish("COMMIT", conn)

    def rollback(conn):  # type: ignore[no-untyped-def]
        return _finish("ROLLBACK", conn)

    gdb.begin_write_transaction = begin_write_transaction  # type: ignore[assignment]
    gdb.commit = commit  # type: ignore[assignment]
    gdb.rollback = rollback  # type: ignore[assignment]

    try:
        import sqlite3

        _orig_conn_execute = sqlite3.Connection.execute
        _orig_cur_execute = sqlite3.Cursor.execute

        def _conn_execute(self, sql, parameters=()):  # type: ignore[no-untyped-def]
            _bump_sql(sql)
            return _orig_conn_execute(self, sql, parameters)

        def _cur_execute(self, sql, parameters=()):  # type: ignore[no-untyped-def]
            _bump_sql(sql)
            return _orig_cur_execute(self, sql, parameters)

        sqlite3.Connection.execute = _conn_execute  # type: ignore[assignment]
        sqlite3.Cursor.execute = _cur_execute  # type: ignore[method-assign]
    except Exception:
        pass

    try:
        import game.logic as logic

        orig_poll = logic.read_player_live_state_for_poll

        def read_player_live_state_for_poll(player_id, conn=None):  # type: ignore[no-untyped-def]
            flags: Dict[str, Any] = {
                "fleet_dirty": None,
                "queue_due": None,
                "fleet_tick_ran": False,
                "queue_finish_ran": False,
            }
            try:
                from game.queue_poll import player_fleet_is_dirty, player_has_due_queue_work

                own = conn is None
                c = conn
                if own:
                    from game.db import db as _db

                    c = _db()
                try:
                    flags["fleet_dirty"] = bool(player_fleet_is_dirty(int(player_id), conn=c))
                    flags["queue_due"] = bool(
                        player_has_due_queue_work(int(player_id), conn=c)
                    )
                finally:
                    if own and c is not None:
                        c.close()
            except Exception:
                pass

            _emit(
                {
                    "event": "GAME_STATE_POLL",
                    "player_id": int(player_id),
                    "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
                    **flags,
                    **_http_context(),
                }
            )
            return orig_poll(player_id, conn=conn)

        logic.read_player_live_state_for_poll = read_player_live_state_for_poll  # type: ignore[assignment]
    except Exception:
        pass

    _INSTALLED = True
    _emit(
        {
            "event": "PROVENANCE_INSTALLED",
            "process": os.environ.get("GC_REPRO006_PROCESS", "unknown"),
            "log": _log_path(),
            "fleet_tx_split": True,
        }
    )


if os.environ.get("GC_REPRO006_PROVENANCE", "").strip() in ("1", "true", "yes", "on"):
    try:
        install()
    except Exception:
        pass
