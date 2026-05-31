"""
Genesis Colonies – DB access layer.

SQLite today; Postgres migration path via GC_DB_BACKEND=postgres (future).

Transaction rules:
- Use begin_write_transaction() for all writes (SQLite: BEGIN IMMEDIATE).
- Use commit() / rollback() explicitly in multi-step game logic.
- Use with_transaction() for short atomic blocks.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "game.db"

_SQLITE_WRITE_MUTEX = threading.RLock()
_WRITE_MUTEX_DEPTH = threading.local()


def _write_mutex_depth() -> int:
    return int(getattr(_WRITE_MUTEX_DEPTH, "n", 0) or 0)


def _write_mutex_acquire() -> None:
    if _write_mutex_depth() == 0:
        _SQLITE_WRITE_MUTEX.acquire()
    _WRITE_MUTEX_DEPTH.n = _write_mutex_depth() + 1


def _write_mutex_release() -> None:
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

def get_db_backend() -> str:
    return os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()


_POSTGRES_NOT_IMPLEMENTED = (
    "PostgreSQL (GC_DB_BACKEND=postgres) is not implemented yet. "
    "Use GC_DB_BACKEND=sqlite with GC_DB_PATH=/data/game.db and a Railway Volume "
    "mounted at /data. Do not link a PostgreSQL service on Railway until this backend ships."
)


def _postgres_not_implemented_message() -> str:
    return _POSTGRES_NOT_IMPLEMENTED


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


def db() -> sqlite3.Connection:
    if get_db_backend() != "sqlite":
        raise NotImplementedError(_postgres_not_implemented_message())
    db_path = ensure_db_parent_dir()
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def in_transaction(conn: sqlite3.Connection) -> bool:
    if hasattr(conn, "in_transaction"):
        return bool(conn.in_transaction)
    return False


def begin_write_transaction(conn: sqlite3.Connection, *, retries: int = 8) -> None:
    """
    Start a write transaction with appropriate locking.

    SQLite: BEGIN IMMEDIATE (single-writer lock, race-safe queues).
    Postgres (future): BEGIN — pair with lock_planet_for_update() / lock_player_for_update().

    Serializes writers within the process to avoid SQLITE_BUSY under Flask threading.
    """
    if in_transaction(conn):
        return
    _write_mutex_acquire()
    try:
        last_err: Optional[BaseException] = None
        for attempt in range(max(1, int(retries))):
            try:
                if get_db_backend() == "postgres":
                    conn.execute("BEGIN")
                else:
                    conn.execute("BEGIN IMMEDIATE")
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


def commit(conn: sqlite3.Connection) -> None:
    conn.commit()
    if not in_transaction(conn):
        _write_mutex_release()


def rollback(conn: sqlite3.Connection) -> None:
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


def lock_planet_for_update(conn: sqlite3.Connection, planet_id: int) -> None:
    """Postgres: row-level lock before queue/spend. SQLite: no-op (IMMEDIATE covers writers)."""
    if get_db_backend() != "postgres":
        return
    conn.execute("SELECT id FROM planets WHERE id = ? FOR UPDATE;", (int(planet_id),))


def lock_player_for_update(conn: sqlite3.Connection, user_id: int) -> None:
    """Postgres: serialize research queue mutations per player."""
    if get_db_backend() != "postgres":
        return
    conn.execute("SELECT id FROM players WHERE id = ? FOR UPDATE;", (int(user_id),))


@contextmanager
def with_transaction(
    conn: Optional[sqlite3.Connection] = None,
    *,
    close: bool = False,
) -> Generator[sqlite3.Connection, None, None]:
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


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
        (str(table_name),),
    )
    return cur.fetchone() is not None


def index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ? LIMIT 1;",
        (str(index_name),),
    )
    return cur.fetchone() is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    return {str(row["name"]) for row in cur.fetchall()}


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return column_name in table_columns(conn, table_name)
