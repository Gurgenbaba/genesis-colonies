"""
Genesis Colonies – DB access layer.

SQLite default; PostgreSQL via GC_DB_BACKEND=postgres + DATABASE_URL (GC-PERF-DB-002).

Transaction rules:
- Use begin_write_transaction() for all writes (SQLite: BEGIN IMMEDIATE).
- Use commit() / rollback() explicitly in multi-step game logic.
- Use with_transaction() for short atomic blocks.
- Postgres: BEGIN + lock_planet_for_update() / lock_player_for_update().
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "game.db"

_SQLITE_WRITE_MUTEX = threading.RLock()
_WRITE_MUTEX_DEPTH = threading.local()

# Connection type used across call sites (sqlite3 or PgConnection wrapper).
DbConn = Any


def _write_mutex_depth() -> int:
    return int(getattr(_WRITE_MUTEX_DEPTH, "n", 0) or 0)


def _write_mutex_acquire() -> None:
    if get_db_backend() != "sqlite":
        return
    if _write_mutex_depth() == 0:
        _SQLITE_WRITE_MUTEX.acquire()
    _WRITE_MUTEX_DEPTH.n = _write_mutex_depth() + 1


def _write_mutex_release() -> None:
    if get_db_backend() != "sqlite":
        return
    depth = _write_mutex_depth()
    if depth <= 0:
        return
    depth -= 1
    _WRITE_MUTEX_DEPTH.n = depth
    if depth == 0:
        _SQLITE_WRITE_MUTEX.release()


def _is_sqlite_lock_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def is_db_lock_error(exc: BaseException) -> bool:
    """True for SQLite busy/locked or Postgres lock_timeout / deadlock.

    Presence touches and similar best-effort writes should soft-skip these
    instead of blocking the request for the full ``GC_PG_LOCK_TIMEOUT``.
    """
    if _is_sqlite_lock_error(exc):
        return True
    name = type(exc).__name__
    if name in ("LockNotAvailable", "DeadlockDetected"):
        return True
    msg = str(exc).lower()
    return (
        "lock timeout" in msg
        or "deadlock detected" in msg
        or "could not serialize access" in msg
        or "canceling statement due to lock timeout" in msg
    )


def is_sqlite_lock_error(exc: BaseException) -> bool:
    """Public alias — includes Postgres lock timeout/deadlock (dual-backend)."""
    return is_db_lock_error(exc)


def format_sqlite_lock_startup_help() -> str:
    """Actionable hint when bootstrap cannot open the SQLite file for writing."""
    db_path = resolve_db_path()
    try:
        resolved = str(db_path.resolve())
    except OSError:
        resolved = str(db_path)
    lines = [
        "[GC bootstrap] database is locked — another process is using the SQLite file.",
        f"[GC bootstrap] DB path: {resolved}",
        "[GC bootstrap] Local dev: GC_DB_PATH=game/game.db (see .env).",
        "[GC bootstrap] Railway: GC_DB_PATH=/data/game.db on the web service volume.",
        "[GC bootstrap] Fix: stop other python app.py / pytest instances, then retry.",
    ]
    if sys.platform == "win32":
        lines.append(
            "[GC bootstrap] Windows: Get-Process python | "
            "Stop-Process -Id <pid> -Force"
        )
    return "\n".join(lines)


def get_db_backend() -> str:
    return os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()


_POSTGRES_NOT_CONFIGURED = (
    "PostgreSQL backend selected (GC_DB_BACKEND=postgres) but not usable. "
    "Set DATABASE_URL=postgresql://… and install: pip install 'psycopg[binary]' psycopg_pool"
)


def resolve_db_path() -> Path:
    override = os.environ.get("GC_DB_PATH", "").strip()
    if override:
        return Path(override)
    return Path(DB_PATH)


def ensure_db_parent_dir() -> Path:
    """Create parent directory for GC_DB_PATH (e.g. Railway volume mount /data)."""
    db_path = resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


class TxAbort(Exception):
    """Rollback the current write transaction without treating it as an error."""

    def __init__(self, result: Any = None) -> None:
        super().__init__()
        self.result = result


def write_mutex_depth() -> int:
    """Process-local SQLite writer mutex depth (0 = idle). Always 0 on Postgres."""
    if get_db_backend() != "sqlite":
        return 0
    return _write_mutex_depth()


def db() -> DbConn:
    """Open a DB connection for the configured backend."""
    backend = get_db_backend()
    if backend == "postgres":
        conn_t0 = time.perf_counter()
        try:
            from game.db_pg import connect_postgres

            conn = connect_postgres()
        except NotImplementedError:
            raise
        except Exception as exc:
            raise NotImplementedError(f"{_POSTGRES_NOT_CONFIGURED} ({exc})") from exc
        try:
            from game.live_state import (
                attach_request_perf_sql_trace,
                is_request_perf_active,
                record_request_perf_db_connection_open,
                record_request_perf_phase,
            )

            record_request_perf_db_connection_open()
            if is_request_perf_active():
                record_request_perf_phase(
                    "db_connection_ms",
                    (time.perf_counter() - conn_t0) * 1000.0,
                )
            attach_request_perf_sql_trace(conn)
        except Exception:
            pass
        return conn

    if backend != "sqlite":
        raise NotImplementedError(f"Unsupported GC_DB_BACKEND={backend!r}")

    db_path = ensure_db_parent_dir()
    conn_t0 = time.perf_counter()
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        from game.live_state import (
            attach_request_perf_sql_trace,
            is_request_perf_active,
            record_request_perf_db_connection_open,
            record_request_perf_phase,
        )

        record_request_perf_db_connection_open()
        if is_request_perf_active():
            record_request_perf_phase(
                "db_connection_ms",
                (time.perf_counter() - conn_t0) * 1000.0,
            )
        attach_request_perf_sql_trace(conn)
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # GC-PERF-LOCK-001: wait for writers (fleet short-TX / autoplay) instead of
    # immediate SQLITE_BUSY on HTTP touch / game-state paths.
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def in_transaction(conn: DbConn) -> bool:
    if hasattr(conn, "in_transaction"):
        return bool(conn.in_transaction)
    return False


def recover_aborted_transaction(conn: DbConn) -> None:
    """
    Clear an aborted Postgres transaction so later statements can run.

    No-op on SQLite. Call after swallowed DB errors on a shared connection,
    and before begin_write_transaction when the connection may be INERROR.
    """
    if get_db_backend() != "postgres":
        return
    try:
        raw = getattr(conn, "_conn", None)
        info = getattr(raw, "info", None) if raw is not None else None
        status = getattr(info, "transaction_status", None) if info is not None else None
        # psycopg: 0=IDLE 1=ACTIVE 2=INTRANS 3=INERROR
        if status is not None and int(status) == 3:
            rollback(conn)
            return
    except Exception:
        pass
    try:
        conn.execute("SELECT 1 AS gc_tx_ok;")
    except Exception:
        rollback(conn)


def begin_write_transaction(conn: DbConn, *, retries: int = 12) -> None:
    """
    Start a write transaction with appropriate locking.

    SQLite: BEGIN IMMEDIATE (single-writer lock, race-safe queues).
    Postgres: BEGIN — pair with lock_planet_for_update() / lock_player_for_update().

    Serializes writers within the process on SQLite to avoid SQLITE_BUSY under Flask threading.
    GC-PERF-LOCK-001: default retries raised so HTTP can wait out fleet short-TXs.
    """
    if get_db_backend() == "postgres":
        recover_aborted_transaction(conn)
    if in_transaction(conn):
        return
    _write_mutex_acquire()
    try:
        last_err: Optional[BaseException] = None
        begin_t0 = time.perf_counter()
        for attempt in range(max(1, int(retries))):
            try:
                if get_db_backend() == "postgres":
                    conn.execute("BEGIN")
                    if hasattr(conn, "_in_tx"):
                        conn._in_tx = True  # type: ignore[attr-defined]
                else:
                    conn.execute("BEGIN IMMEDIATE")
                begin_ms = (time.perf_counter() - begin_t0) * 1000.0
                try:
                    from game.live_state import (
                        mark_request_perf_write_tx_started,
                        record_request_perf_phase,
                    )

                    record_request_perf_phase("db_begin_immediate_ms", begin_ms)
                    mark_request_perf_write_tx_started()
                except Exception:
                    pass
                return
            except sqlite3.OperationalError as exc:
                last_err = exc
                if not _is_sqlite_lock_error(exc) or attempt + 1 >= retries:
                    _write_mutex_release()
                    raise
                time.sleep(min(0.25, 0.02 * (2**attempt)))
        if last_err is not None:
            _write_mutex_release()
            raise last_err
    except Exception:
        if not in_transaction(conn):
            _write_mutex_release()
        raise


def commit(conn: DbConn) -> None:
    try:
        from game.live_state import mark_request_perf_write_tx_finished

        mark_request_perf_write_tx_finished()
    except Exception:
        pass
    conn.commit()
    if not in_transaction(conn):
        _write_mutex_release()


def rollback(conn: DbConn) -> None:
    try:
        from game.live_state import mark_request_perf_write_tx_finished

        mark_request_perf_write_tx_finished()
    except Exception:
        pass
    conn.rollback()
    if not in_transaction(conn):
        _write_mutex_release()


@contextmanager
def sqlite_write_lock() -> Generator[None, None, None]:
    """Process-wide writer lock for short multi-statement blocks outside transactions."""
    _write_mutex_acquire()
    try:
        yield
    finally:
        _write_mutex_release()


def lock_planet_for_update(conn: DbConn, planet_id: int) -> None:
    """Postgres: row-level lock before queue/spend. SQLite: no-op (IMMEDIATE covers writers)."""
    if get_db_backend() != "postgres":
        return
    conn.execute("SELECT id FROM planets WHERE id = ? FOR UPDATE;", (int(planet_id),))


def lock_player_for_update(conn: DbConn, user_id: int) -> None:
    """Postgres: serialize research queue mutations per player."""
    if get_db_backend() != "postgres":
        return
    conn.execute("SELECT id FROM players WHERE id = ? FOR UPDATE;", (int(user_id),))


@contextmanager
def with_transaction(
    conn: Optional[DbConn] = None,
    *,
    close: bool = False,
) -> Generator[DbConn, None, None]:
    """
    Context manager: begin → yield → commit on success, rollback on error/TxAbort.
    Does not close conn unless close=True or conn was created here.
    """
    own = conn is None
    if own:
        conn = db()
        close = True

    began = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began = True
        yield conn
        if began:
            commit(conn)
    except TxAbort:
        if began:
            rollback(conn)
    except Exception:
        if began:
            rollback(conn)
        raise
    finally:
        if close and conn is not None:
            conn.close()


def table_exists(conn: DbConn, table_name: str) -> bool:
    if get_db_backend() == "postgres":
        from game.db_pg import postgres_table_exists

        return postgres_table_exists(conn, table_name)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
        (str(table_name),),
    )
    return cur.fetchone() is not None


def tables_exist(conn: DbConn, table_names) -> bool:
    """Check multiple table names with one backend-safe schema query.

    This intentionally does not cache across requests or processes: callers keep
    current schema visibility while hot paths avoid one round-trip per table.
    """
    names = tuple(
        dict.fromkeys(
            str(name).strip()
            for name in (table_names or ())
            if str(name or "").strip()
        )
    )
    if not names:
        return True

    placeholders = ",".join("?" for _ in names)
    if get_db_backend() == "postgres":
        sql = f"""
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ({placeholders});
        """
    else:
        sql = f"""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ({placeholders});
        """

    rows = conn.execute(sql, names).fetchall()
    found = {str(row["name"]) for row in rows}
    return set(names).issubset(found)


def index_exists(conn: DbConn, index_name: str) -> bool:
    if get_db_backend() == "postgres":
        from game.db_pg import postgres_index_exists

        return postgres_index_exists(conn, index_name)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ? LIMIT 1;",
        (str(index_name),),
    )
    return cur.fetchone() is not None


def table_columns(conn: DbConn, table_name: str) -> set[str]:
    if get_db_backend() == "postgres":
        from game.db_pg import postgres_table_columns

        return postgres_table_columns(conn, table_name)
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    return {str(row["name"]) for row in cur.fetchall()}


def column_exists(conn: DbConn, table_name: str, column_name: str) -> bool:
    return column_name in table_columns(conn, table_name)


def ensure_column(conn: DbConn, table_name: str, column_name: str, typedef: str) -> None:
    """Idempotent ``ALTER TABLE ... ADD COLUMN`` for lazy/self-heal schema ensures.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, so callers historically did a
    check-then-add (``if column_exists(...): ...``) which races under
    concurrent requests: two threads can both see the column missing before
    either commits its ALTER, and the loser gets
    ``OperationalError: duplicate column name`` (GC-STABILIZE-002). Centralize
    the add + swallow-if-lost-the-race handling here (single Owner for
    "ensure_*_schema" helpers in game/options.py, game/account_email.py, ...)
    instead of duplicating the race in every call site.
    """
    if column_exists(conn, table_name, column_name):
        return
    from game.sql_pg_rewrite import is_idempotent_postgres_error

    cur = conn.cursor()
    try:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {typedef};")
    except Exception as exc:
        if not is_idempotent_postgres_error(exc):
            raise


def is_integrity_error(exc: BaseException) -> bool:
    """
    True for unique/check/FK violations on SQLite or PostgreSQL.

    Owner for dual-backend Integrity handling (GC-PERF-PG-PARITY-001).
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        from psycopg.errors import ForeignKeyViolation, IntegrityError, UniqueViolation

        if isinstance(exc, (IntegrityError, UniqueViolation, ForeignKeyViolation)):
            return True
    except Exception:
        pass
    name = type(exc).__name__
    if name in ("IntegrityError", "UniqueViolation", "ForeignKeyViolation", "CheckViolation"):
        return True
    msg = str(exc).lower()
    return "unique" in msg or "foreign key" in msg or "check constraint" in msg


def get_connection() -> DbConn:
    """Canonical DB connection helper (alias for db())."""
    return db()


def database_url_is_set() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def describe_db_connection() -> dict[str, Any]:
    """Runtime DB target for workers and health diagnostics."""
    backend = get_db_backend()
    info: dict[str, Any] = {
        "db_backend": backend,
        "database_url_set": database_url_is_set(),
    }
    if backend == "sqlite":
        info["db_path"] = str(resolve_db_path())
    elif backend == "postgres":
        try:
            from game.db_pg import get_pool_max_size

            info["pg_pool_max"] = get_pool_max_size()
        except Exception:
            pass
    return info


def count_table_rows(conn: DbConn, table_name: str) -> int:
    if not table_exists(conn, table_name):
        return 0
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table_name};")
    row = cur.fetchone()
    return int(row["cnt"] if row and row["cnt"] is not None else 0)


def get_db_identity(conn: Optional[DbConn] = None) -> str:
    """Short fingerprint: backend, path, row counts, top score."""
    owns = conn is None
    if owns:
        conn = db()
    try:
        players = count_table_rows(conn, "players")
        planets = count_table_rows(conn, "planets")
        scores = count_table_rows(conn, "player_scores")
        top_score = 0
        if table_exists(conn, "player_scores"):
            cur = conn.cursor()
            # score_total is TEXT (big-score); prefer Python int max for precision.
            cur.execute("SELECT score_total FROM player_scores;")
            for srow in cur.fetchall():
                raw = srow["score_total"] if srow is not None else None
                if raw is None:
                    continue
                try:
                    val = int(str(raw).strip() or "0")
                except (TypeError, ValueError):
                    continue
                if val > top_score:
                    top_score = val
        path_part = str(resolve_db_path()) if get_db_backend() == "sqlite" else "postgres"
        return (
            f"backend={get_db_backend()} path={path_part} "
            f"players={players} planets={planets} scores={scores} top={top_score}"
        )
    finally:
        if owns and conn is not None:
            conn.close()


def gather_score_stats(conn: DbConn) -> dict[str, int]:
    """Aggregate player_scores snapshot for worker before/after logs.

    ``score_total`` is TEXT (big-score). Positive-count uses NUMERIC cast so
    PostgreSQL accepts the predicate. ``top_score`` is computed in Python as
    ``int`` so values beyond float64/int64 stay exact on both backends.
    """
    if not table_exists(conn, "player_scores"):
        return {"scores_rows": 0, "scores_positive": 0, "top_score": 0}
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM player_scores;")
    rows = int(cur.fetchone()["cnt"] or 0)
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM player_scores "
        "WHERE COALESCE(CAST(score_total AS NUMERIC), 0) > 0;"
    )
    positive = int(cur.fetchone()["cnt"] or 0)
    cur.execute("SELECT score_total FROM player_scores;")
    top = 0
    for row in cur.fetchall():
        raw = row["score_total"] if row is not None else None
        if raw is None:
            continue
        try:
            val = int(str(raw).strip() or "0")
        except (TypeError, ValueError):
            continue
        if val > top:
            top = val
    return {"scores_rows": rows, "scores_positive": positive, "top_score": top}


def gather_db_startup_diagnostics(conn: Optional[DbConn] = None) -> dict[str, Any]:
    """DB target fingerprint for ranking worker / cron startup logs."""
    owns = conn is None
    if owns:
        conn = db()
    try:
        backend = get_db_backend()
        info: dict[str, Any] = {
            "db_backend": backend,
            "database_url_set": database_url_is_set(),
            "players": count_table_rows(conn, "players"),
            "planets": count_table_rows(conn, "planets"),
        }
        if backend == "sqlite":
            path = resolve_db_path()
            info["db_path"] = str(path)
            info["db_exists"] = path.exists()
            info["db_size_bytes"] = int(path.stat().st_size) if path.exists() else 0
        try:
            from game.migrations_util import get_applied_migration_names, list_migration_files

            applied = get_applied_migration_names(conn)
            total = len(list_migration_files())
            info["migrations_applied"] = len(applied)
            info["migrations_total"] = total
            info["migrations_current"] = len(applied) >= total and total > 0
        except Exception as exc:
            info["migrations_readable"] = False
            info["migrations_error"] = str(exc)
        else:
            info["migrations_readable"] = True
        return info
    finally:
        if owns and conn is not None:
            conn.close()
