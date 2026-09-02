"""
Throttled queue-finish policy for high-frequency polling (game-state).

Avoids BEGIN IMMEDIATE on every /api/game-state tick while still finishing due jobs
within a bounded interval.

GC-PROD-SQLITE-STALL-001A:
- Queue finishes are deferred only when ``QUEUE_TICK_KEY`` heartbeat is fresh
  (not fleet/maintenance).
- Due finishes use ``try_claim_poll_due_finish`` (claim BEFORE finish) so parallel
  polls for the same player cannot stampede into ``finish_player_due_work``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

from .db import begin_write_transaction, commit, db, in_transaction, rollback

# Minimum seconds between queue-finish passes triggered by game-state polling.
POLL_FINISH_INTERVAL_SEC = float(os.environ.get("GC_POLL_FINISH_INTERVAL_SEC", "25"))

# Due-finish single-flight lease TTL (claim before expensive finish).
POLL_DUE_CLAIM_SEC = float(os.environ.get("GC_POLL_DUE_CLAIM_SEC", "5"))

# Sub-second tolerance so jobs with 1s duration are not stuck between float ticks.
DUE_TIME_EPSILON_SEC = float(os.environ.get("GC_DUE_TIME_EPSILON_SEC", "0.05"))

# Align finish/due detection with UI remaining = int(finish_at - now):
# when remaining displays as 0, the job is treated as due (≤ ~1s early).
DISPLAY_DUE_WINDOW_SEC = float(os.environ.get("GC_DISPLAY_DUE_WINDOW_SEC", "1.0"))

# Process-local suppression: avoids writer herds on lease CAS inside one process.
_LOCAL_CLAIM_LOCK = threading.Lock()
_LOCAL_CLAIMS: Dict[int, float] = {}


def due_cutoff_ts(now: Optional[float] = None) -> float:
    """Timestamp at/below which a queue job finish_at is considered due."""
    ts = float(now if now is not None else time.time())
    return ts + max(float(DUE_TIME_EPSILON_SEC), float(DISPLAY_DUE_WINDOW_SEC))


def player_fleet_is_dirty(
    player_id: int,
    conn=None,
    *,
    now: Optional[float] = None,
) -> bool:
    """
    True when any fleet movement phase is past due but not yet transitioned (GC-557C).

    Used to force process_fleet_tick before returning stale outbound/returning state.
    Each phase lives in its own EXISTS branch so SQLite can use the matching
    (player_id, status, deadline) index instead of scanning all active rows behind
    one OR predicate.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    ts = float(now if now is not None else time.time()) + DUE_TIME_EPSILON_SEC
    try:
        from .fleet import fleet_schema_ready

        if not fleet_schema_ready(conn):
            return False
        row = conn.execute(
            """
            SELECT 1
            WHERE EXISTS (
                SELECT 1 FROM fleet_movements
                WHERE player_id = ? AND status = 'outbound' AND arrival_at <= ?
                LIMIT 1
            ) OR EXISTS (
                SELECT 1 FROM fleet_movements
                WHERE player_id = ? AND status = 'holding' AND holding_until <= ?
                LIMIT 1
            ) OR EXISTS (
                SELECT 1 FROM fleet_movements
                WHERE player_id = ? AND status = 'returning' AND return_at <= ?
                LIMIT 1
            )
            LIMIT 1;
            """,
            (int(player_id), ts, int(player_id), ts, int(player_id), ts),
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _optional_due_queue_readiness(conn) -> tuple[bool, bool, bool, bool]:
    """Return readiness for evolution, shipyard, defense and troop queue tables.

    PostgreSQL schema metadata is process-cached (GC-PERF-PG-SCHEMA-CACHE-001),
    so these guards are cheap after warmup while legacy/dev databases remain safe.
    """
    evolution_ready = False
    shipyard_ready = False
    defense_ready = False
    troop_ready = False
    try:
        from .planet_evolution.repository import evolution_schema_ready

        evolution_ready = bool(evolution_schema_ready(conn))
    except Exception:
        pass
    try:
        from .shipyard_queue import shipyard_queue_table_ready

        shipyard_ready = bool(shipyard_queue_table_ready(conn))
    except Exception:
        pass
    try:
        from .defense import defense_queue_table_ready

        defense_ready = bool(defense_queue_table_ready(conn))
    except Exception:
        pass
    try:
        from .troops import troop_queue_table_ready

        troop_ready = bool(troop_queue_table_ready(conn))
    except Exception:
        pass
    return evolution_ready, shipyard_ready, defense_ready, troop_ready


def player_has_due_queue_work(
    player_id: int,
    conn=None,
    *,
    now: Optional[float] = None,
    planet_id: Optional[int] = None,
) -> bool:
    """
    Read-only check for due queue jobs; fleet movements are intentionally excluded.

    GC-PERF-PG-DUE-PROBE-001: all ready queue domains are folded into one
    ``SELECT ... WHERE EXISTS(...) OR ...`` statement. The former implementation
    performed one remote PostgreSQL round trip per domain on every game-state poll.
    Optional schema guards stay fail-open for legacy/dev databases.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    ts = due_cutoff_ts(now)
    uid = int(player_id)
    pid_filter = int(planet_id) if planet_id is not None else None
    try:
        evolution_ready, shipyard_ready, defense_ready, troop_ready = (
            _optional_due_queue_readiness(conn)
        )
        clauses: list[str] = []
        params: list[object] = []

        def add(clause: str, *values: object) -> None:
            clauses.append(f"EXISTS ({clause})")
            params.extend(values)

        if pid_filter is not None:
            add(
                "SELECT 1 FROM build_queue bq WHERE bq.planet_id = ? AND bq.finish_time <= ? LIMIT 1",
                pid_filter,
                ts,
            )
        else:
            add(
                "SELECT 1 FROM build_queue bq INNER JOIN planets p ON p.id = bq.planet_id "
                "WHERE p.player_id = ? AND bq.finish_time <= ? LIMIT 1",
                uid,
                ts,
            )

        # Account research remains account-scoped even when a planet filter is supplied,
        # matching the pre-collapse behavior.
        add(
            "SELECT 1 FROM research_queue WHERE user_id = ? AND finish_at <= ? LIMIT 1",
            uid,
            ts,
        )

        if evolution_ready:
            if pid_filter is not None:
                add(
                    "SELECT 1 FROM planet_research_queue prq "
                    "WHERE prq.planet_id = ? AND prq.finish_at <= ? LIMIT 1",
                    pid_filter,
                    ts,
                )
                add(
                    "SELECT 1 FROM planet_ascension_queue paq "
                    "WHERE paq.planet_id = ? AND paq.state = 'active' AND paq.finish_at <= ? LIMIT 1",
                    pid_filter,
                    ts,
                )
            else:
                add(
                    "SELECT 1 FROM planet_research_queue prq "
                    "INNER JOIN planets p ON p.id = prq.planet_id "
                    "WHERE p.player_id = ? AND prq.finish_at <= ? LIMIT 1",
                    uid,
                    ts,
                )
                add(
                    "SELECT 1 FROM planet_ascension_queue paq "
                    "INNER JOIN planets p ON p.id = paq.planet_id "
                    "WHERE p.player_id = ? AND paq.state = 'active' AND paq.finish_at <= ? LIMIT 1",
                    uid,
                    ts,
                )

        if shipyard_ready:
            if pid_filter is not None:
                add(
                    "SELECT 1 FROM shipyard_queue sq "
                    "WHERE sq.planet_id = ? AND sq.status = 'queued' AND sq.finish_at <= ? LIMIT 1",
                    pid_filter,
                    ts,
                )
            else:
                add(
                    "SELECT 1 FROM shipyard_queue sq "
                    "INNER JOIN planets p ON p.id = sq.planet_id "
                    "WHERE p.player_id = ? AND sq.status = 'queued' AND sq.finish_at <= ? LIMIT 1",
                    uid,
                    ts,
                )

        if defense_ready:
            if pid_filter is not None:
                add(
                    "SELECT 1 FROM defense_queue dq "
                    "WHERE dq.planet_id = ? AND dq.status = 'queued' AND dq.finish_at <= ? LIMIT 1",
                    pid_filter,
                    ts,
                )
            else:
                add(
                    "SELECT 1 FROM defense_queue dq "
                    "INNER JOIN planets p ON p.id = dq.planet_id "
                    "WHERE p.player_id = ? AND dq.status = 'queued' AND dq.finish_at <= ? LIMIT 1",
                    uid,
                    ts,
                )

        # Troops are finished by the queue engine/worker too. Including them here
        # closes the old poll-safety-net blind spot if the queue worker ever goes stale.
        if troop_ready:
            if pid_filter is not None:
                add(
                    "SELECT 1 FROM troop_queue tq "
                    "WHERE tq.planet_id = ? AND tq.status = 'queued' AND tq.finish_at <= ? LIMIT 1",
                    pid_filter,
                    ts,
                )
            else:
                add(
                    "SELECT 1 FROM troop_queue tq "
                    "WHERE tq.player_id = ? AND tq.status = 'queued' AND tq.finish_at <= ? LIMIT 1",
                    uid,
                    ts,
                )

        row = conn.execute(
            "SELECT 1 WHERE " + " OR ".join(clauses) + " LIMIT 1;",
            tuple(params),
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _lease_key(player_id: int) -> str:
    return f"queue_finish_poll:{int(player_id)}"


def _claim_key(player_id: int) -> str:
    return f"queue_finish_poll_claim:{int(player_id)}"


def _poll_due_claim_sec() -> float:
    raw = os.environ.get("GC_POLL_DUE_CLAIM_SEC", "").strip()
    if raw:
        try:
            return max(0.5, float(raw))
        except (TypeError, ValueError):
            pass
    return max(0.5, float(POLL_DUE_CLAIM_SEC))


def _parse_claim_until(raw: Optional[str]) -> float:
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return float(data.get("until") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _process_local_try_claim(player_id: int, lease_sec: float, *, now: float) -> bool:
    """Cheap same-process suppression — no DB. Losers never touch SQLite."""
    pid = int(player_id)
    with _LOCAL_CLAIM_LOCK:
        until = float(_LOCAL_CLAIMS.get(pid) or 0.0)
        if until > now:
            return False
        _LOCAL_CLAIMS[pid] = now + float(lease_sec)
        if len(_LOCAL_CLAIMS) > 512:
            stale = [k for k, v in _LOCAL_CLAIMS.items() if float(v) <= now]
            for k in stale[:256]:
                _LOCAL_CLAIMS.pop(k, None)
        return True


def _persisted_claim_active(player_id: int, conn, *, now: float) -> bool:
    from .runtime_state import get_runtime_value

    raw = get_runtime_value(_claim_key(player_id), conn=conn)
    return _parse_claim_until(raw) > now


def try_claim_poll_due_finish(
    player_id: int,
    conn=None,
    *,
    lease_sec: Optional[float] = None,
    now: Optional[float] = None,
) -> bool:
    """
    Single-flight claim for poll due-finish (GC-PROD-SQLITE-STALL-001A).

    Call BEFORE ``finish_player_due_work``. Exactly one winner per player window.

    Design (two-step):
    1. Process-local suppression — losers return False with zero DB I/O.
    2. Cross-process lease on ``runtime_state`` — read-only peek first; only a
       contender that still looks free opens ``BEGIN IMMEDIATE`` and CAS-sets
       ``until``. Losers after peek never write; losers after lock wait re-check
       and roll back without finishing queues.

    TTL ensures a crashed winner cannot block a player forever.
    """
    pid = int(player_id)
    now_f = float(now if now is not None else time.time())
    ttl = float(lease_sec if lease_sec is not None else _poll_due_claim_sec())

    if not _process_local_try_claim(pid, ttl, now=now_f):
        return False

    owns_conn = conn is None
    if owns_conn:
        conn = db()

    from .runtime_state import ensure_runtime_state_table, set_runtime_value

    try:
        # Read-only peek — do not BEGIN just to discover an active lease.
        if _persisted_claim_active(pid, conn, now=now_f):
            return False

        nested = in_transaction(conn)
        if not nested:
            begin_write_transaction(conn)
        try:
            ensure_runtime_state_table(conn)
            if _persisted_claim_active(pid, conn, now=time.time()):
                if not nested:
                    rollback(conn)
                return False
            payload = {
                "until": now_f + ttl,
                "token": uuid.uuid4().hex[:12],
                "claimed_at": now_f,
            }
            set_runtime_value(
                _claim_key(pid), json.dumps(payload, ensure_ascii=False), conn=conn
            )
            if not nested:
                commit(conn)
            return True
        except Exception as claim_exc:
            if not nested:
                try:
                    rollback(conn)
                except Exception:
                    pass
            from .db import is_db_lock_error

            # Claim is single-flight coordination only — never 500 a page/poll.
            if is_db_lock_error(claim_exc):
                return False
            raise
    finally:
        if owns_conn and conn is not None:
            conn.close()


def clear_poll_due_claim_for_tests(player_id: int, conn=None) -> None:
    """Test helper: drop process-local + persisted claim for one player."""
    pid = int(player_id)
    with _LOCAL_CLAIM_LOCK:
        _LOCAL_CLAIMS.pop(pid, None)
    from .runtime_state import ensure_runtime_state_table

    owns = conn is None
    if owns:
        conn = db()
    try:
        ensure_runtime_state_table(conn)
        if not in_transaction(conn):
            begin_write_transaction(conn)
            conn.execute("DELETE FROM runtime_state WHERE key = ?;", (_claim_key(pid),))
            commit(conn)
        else:
            conn.execute("DELETE FROM runtime_state WHERE key = ?;", (_claim_key(pid),))
    finally:
        if owns and conn is not None:
            conn.close()


def seconds_until_poll_finish_allowed(player_id: int, conn=None) -> float:
    """Read-only: seconds remaining until poll may trigger queue finish (0 = allowed now)."""
    from .runtime_state import get_runtime_value

    raw = get_runtime_value(_lease_key(player_id), conn=conn)
    if not raw:
        return 0.0
    try:
        last = float(raw)
    except (TypeError, ValueError):
        return 0.0
    remaining = POLL_FINISH_INTERVAL_SEC - (time.time() - last)
    return max(0.0, remaining)


def should_run_queue_finish_for_poll(
    player_id: int,
    conn=None,
    *,
    force_due: bool = True,
    planet_id: Optional[int] = None,
) -> bool:
    """
    True when game-state polling may *attempt* a due/interval finish.

    Does not claim the single-flight lease — callers must use
    ``try_claim_poll_due_finish`` before ``finish_player_due_work``.
    """
    if force_due and player_has_due_queue_work(
        player_id,
        conn=conn,
        planet_id=planet_id,
    ):
        return True
    return seconds_until_poll_finish_allowed(player_id, conn=conn) <= 0.0


def should_poll_attempt_queue_finish(
    player_id: int,
    conn=None,
    *,
    now: Optional[float] = None,
    planet_id: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Decide whether the poll path may run queue finish (before claim).

    Returns (allowed, reason).
    Queue health uses ``is_queue_tick_heartbeat_fresh`` only — never fleet/maintenance.
    """
    from game.config import is_game_worker_primary
    from .runtime_state import is_queue_tick_heartbeat_fresh

    now_f = float(now if now is not None else time.time())
    queue_due = player_has_due_queue_work(
        player_id, conn=conn, now=now_f, planet_id=planet_id
    )

    # GC-PERF-PG-DUE-PROBE-001: production queue worker owns interval cadence.
    # In worker-primary mode pending-but-not-due state is irrelevant, so never pay
    # a second multi-domain pending probe just to return no_queue_due/defer.
    if is_game_worker_primary():
        if not queue_due:
            return False, "no_queue_due"
        if is_queue_tick_heartbeat_fresh(conn=conn, now=now_f):
            return False, "queue_tick_fresh_defer"
        return True, "safety_net_due"

    has_pending = player_has_pending_queue_work(
        player_id, conn=conn, planet_id=planet_id
    )
    if queue_due:
        return True, "due"
    if has_pending and seconds_until_poll_finish_allowed(player_id, conn=conn) <= 0.0:
        return True, "interval"
    return False, "throttled"


def record_poll_queue_finish(player_id: int, conn=None) -> None:
    """Persist poll finish timestamp (single small write, not per GET row)."""
    from .runtime_state import set_runtime_value

    set_runtime_value(_lease_key(player_id), str(time.time()), conn=conn)


def player_has_pending_queue_work(
    player_id: int,
    conn=None,
    *,
    planet_id: Optional[int] = None,
) -> bool:
    """Read-only: any queued build/research job still open (due or not)."""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        cur = conn.cursor()
        pid_filter = int(planet_id) if planet_id is not None else None

        if pid_filter is not None:
            cur.execute(
                "SELECT 1 FROM build_queue WHERE planet_id = ? LIMIT 1;",
                (pid_filter,),
            )
        else:
            cur.execute(
                """
                SELECT 1
                FROM build_queue bq
                INNER JOIN planets p ON p.id = bq.planet_id
                WHERE p.player_id = ?
                LIMIT 1;
                """,
                (int(player_id),),
            )
        if cur.fetchone():
            return True

        cur.execute(
            "SELECT 1 FROM research_queue WHERE user_id = ? LIMIT 1;",
            (int(player_id),),
        )
        if cur.fetchone():
            return True

        try:
            from .planet_evolution.repository import evolution_schema_ready

            if evolution_schema_ready(conn):
                if pid_filter is not None:
                    cur.execute(
                        "SELECT 1 FROM planet_research_queue WHERE planet_id = ? LIMIT 1;",
                        (pid_filter,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1
                        FROM planet_research_queue prq
                        INNER JOIN planets p ON p.id = prq.planet_id
                        WHERE p.player_id = ?
                        LIMIT 1;
                        """,
                        (int(player_id),),
                    )
                if cur.fetchone():
                    return True
                if pid_filter is not None:
                    cur.execute(
                        "SELECT 1 FROM planet_ascension_queue WHERE planet_id = ? AND state = 'active' LIMIT 1;",
                        (pid_filter,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1
                        FROM planet_ascension_queue paq
                        INNER JOIN planets p ON p.id = paq.planet_id
                        WHERE p.player_id = ? AND paq.state = 'active'
                        LIMIT 1;
                        """,
                        (int(player_id),),
                    )
                if cur.fetchone():
                    return True
        except Exception:
            pass
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()
