"""
PostgreSQL adapter for game.db (GC-PERF-DB-002).

Owner remains game.db — this module is a private dialect adapter:
- ``?`` placeholders → ``%s``
- sqlite3.Row-like access via dict rows
- Connection checkout from a process-local pool
"""

from __future__ import annotations

import os
import threading
from typing import Any, Iterable, Optional, Sequence


def _needs_sqlite_dialect_rewrite(sql: str) -> bool:
    """True when runtime SQL still uses SQLite-only idioms (ensure_* / legacy helpers)."""
    upper = str(sql or "").upper()
    if "PRAGMA" in upper:
        return True
    if "AUTOINCREMENT" in upper:
        return True
    if "INSERT OR IGNORE" in upper or "INSERT OR REPLACE" in upper:
        return True
    if "REPLACE INTO" in upper:
        return True
    if "BEGIN IMMEDIATE" in upper or "BEGIN EXCLUSIVE" in upper or "BEGIN DEFERRED" in upper:
        return True
    if "DATETIME('NOW')" in upper or 'DATETIME("NOW")' in upper:
        return True
    if "STRFTIME" in upper:
        return True
    # SQLite scalar MAX(a,b) / MIN(a,b) — Postgres only has aggregate MAX/MIN
    from game.sql_pg_rewrite import has_sqlite_scalar_minmax

    if has_sqlite_scalar_minmax(sql):
        return True
    return False


def rewrite_sqlite_placeholders(sql: str) -> str:
    """Rewrite unbound ``?`` placeholders to psycopg ``%s`` (skip quotes/comments)."""
    out: list[str] = []
    i = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    text = str(sql or "")
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line_comment:
            out.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            out.append(ch)
            if ch == "*" and nxt == "/":
                out.append(nxt)
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            out.append(ch)
            if ch == "'" and nxt == "'":
                out.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            out.append(ch)
            out.append(nxt)
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            out.append(ch)
            out.append(nxt)
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            out.append("%s")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class PgRow(dict):
    """Mapping row with optional integer index access (sqlite3.Row compatibility)."""

    __slots__ = ("_keys",)

    def __init__(self, mapping: dict[str, Any]):
        super().__init__(mapping)
        self._keys = tuple(mapping.keys())

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return super().__getitem__(self._keys[key])
        return super().__getitem__(key)

    def keys(self):  # type: ignore[override]
        return self._keys


class PgCursor:
    def __init__(self, raw_cursor: Any, connection: Any = None) -> None:
        self._cur = raw_cursor
        # sqlite3.Cursor.connection — used by _ensure_game_settings commit path
        self.connection = connection
        self._lastrowid: Optional[int] = None
        # True after INSERT until lastrowid is read — avoid lastval() RTT on bulk seeds
        self._lastrowid_pending = False
        self.rowcount: int = -1
        self.description = None
        self._skipped_result = False

    @property
    def lastrowid(self) -> Optional[int]:
        if self._lastrowid_pending:
            self._resolve_lastrowid()
        return self._lastrowid

    @lastrowid.setter
    def lastrowid(self, value: Optional[int]) -> None:
        self._lastrowid = value
        self._lastrowid_pending = False

    def _resolve_lastrowid(self) -> None:
        """Resolve serial/identity id via lastval() (SAVEPOINT — must not abort TX)."""
        self._lastrowid_pending = False
        self._lastrowid = None
        try:
            self._cur.execute("SAVEPOINT gc_lastval")
            try:
                lv = self._cur.execute("SELECT lastval() AS id").fetchone()
                if lv is not None:
                    self._lastrowid = int(lv["id"] if isinstance(lv, dict) else lv[0])
                self._cur.execute("RELEASE SAVEPOINT gc_lastval")
            except Exception:
                self._lastrowid = None
                try:
                    self._cur.execute("ROLLBACK TO SAVEPOINT gc_lastval")
                except Exception:
                    pass
        except Exception:
            self._lastrowid = None

    def execute(self, sql: str, params: Sequence[Any] | None = None):
        text = str(sql or "")
        self._skipped_result = False
        if _needs_sqlite_dialect_rewrite(text):
            from game.sql_pg_rewrite import rewrite_sqlite_statement

            dialect = rewrite_sqlite_statement(text)
            if not dialect:
                # e.g. PRAGMA — no-op on Postgres (fetchall → [])
                self.description = None
                self.rowcount = -1
                # keep lastrowid (sqlite keeps it across no-ops)
                self._skipped_result = True
                return self
            text = dialect
        rewritten = rewrite_sqlite_placeholders(text)
        if params is None:
            self._cur.execute(rewritten)
        else:
            self._cur.execute(rewritten, tuple(params))
        self.description = self._cur.description
        self.rowcount = int(getattr(self._cur, "rowcount", -1) or -1)
        # Match sqlite3: lastrowid persists across non-INSERT statements.
        # Resolve lazily — bulk INSERT seeds (game_settings) must not pay lastval RTT.
        if rewritten.lstrip().upper().startswith("INSERT"):
            self._lastrowid = None
            self._lastrowid_pending = True
        return self

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]):
        text = str(sql or "")
        if _needs_sqlite_dialect_rewrite(text):
            from game.sql_pg_rewrite import rewrite_sqlite_statement

            dialect = rewrite_sqlite_statement(text)
            if not dialect:
                self.rowcount = -1
                return self
            text = dialect
        rewritten = rewrite_sqlite_placeholders(text)
        self._cur.executemany(rewritten, list(seq_of_params))
        self.rowcount = int(getattr(self._cur, "rowcount", -1) or -1)
        if rewritten.lstrip().upper().startswith("INSERT"):
            self._lastrowid = None
            self._lastrowid_pending = True
        return self

    def _wrap_row(self, row: Any) -> Any:
        if row is None:
            return None
        if isinstance(row, dict):
            return PgRow(row)
        if hasattr(row, "keys"):
            return PgRow({k: row[k] for k in row.keys()})
        return row

    def fetchone(self):
        if self._skipped_result:
            return None
        return self._wrap_row(self._cur.fetchone())

    def fetchall(self):
        if self._skipped_result:
            return []
        rows = self._cur.fetchall() or []
        return [self._wrap_row(r) for r in rows]

    def close(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass


class PgConnection:
    """Thin sqlite3.Connection-shaped wrapper around a psycopg connection."""

    def __init__(self, raw_conn: Any) -> None:
        self._conn = raw_conn
        self.row_factory = None
        self._in_tx = False

    @property
    def in_transaction(self) -> bool:
        try:
            info = getattr(self._conn, "info", None)
            if info is not None and getattr(info, "transaction_status", None) is not None:
                # 0 = IDLE in psycopg
                status = int(info.transaction_status)
                return status != 0
        except Exception:
            pass
        return bool(self._in_tx)

    def cursor(self) -> PgCursor:
        from psycopg.rows import dict_row

        return PgCursor(self._conn.cursor(row_factory=dict_row), connection=self)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> PgCursor:
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self) -> None:
        self._conn.commit()
        self._in_tx = False

    def rollback(self) -> None:
        self._conn.rollback()
        self._in_tx = False

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def set_trace_callback(self, callback) -> None:  # noqa: ANN001
        """No-op — Postgres path uses optional logging elsewhere."""
        return None


_POOL_LOCK = threading.Lock()
_POOL: Any = None


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        # psycopg expects postgresql://
        url = "postgresql://" + url[len("postgres://") :]
    return url


def get_pool_max_size() -> int:
    raw = os.environ.get("GC_PG_POOL_MAX", "10").strip()
    try:
        return max(1, min(64, int(raw)))
    except ValueError:
        return 10


def get_connect_timeout_s() -> int:
    raw = os.environ.get("GC_PG_CONNECT_TIMEOUT", "20").strip()
    try:
        return max(3, min(120, int(raw)))
    except ValueError:
        return 20


def get_pool_checkout_timeout_s() -> float:
    raw = os.environ.get("GC_PG_POOL_TIMEOUT", "30").strip()
    try:
        return float(max(3, min(300, int(raw))))
    except ValueError:
        return 30.0


def _pool_configure(conn: Any) -> None:
    """Apply session timeouts so remote PG (Railway proxy) cannot hang forever."""
    stmt = os.environ.get("GC_PG_STATEMENT_TIMEOUT", "60s").strip() or "60s"
    lock = os.environ.get("GC_PG_LOCK_TIMEOUT", "15s").strip() or "15s"
    # SET does not accept bind params for these units; values come from env only.
    conn.execute(f"SET statement_timeout = '{stmt}'")
    conn.execute(f"SET lock_timeout = '{lock}'")
    # Persist session SETs even if a later TX rolls back (see PostgreSQL SET docs).
    conn.commit()


def _ensure_pool() -> Any:
    global _POOL
    if _POOL is not None:
        return _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise NotImplementedError(
                "PostgreSQL backend requires psycopg and psycopg_pool. "
                "Install: pip install 'psycopg[binary]' psycopg_pool"
            ) from exc
        url = get_database_url()
        if not url:
            raise NotImplementedError(
                "GC_DB_BACKEND=postgres requires DATABASE_URL (postgresql://…)."
            )
        _POOL = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=get_pool_max_size(),
            timeout=get_pool_checkout_timeout_s(),
            open=True,
            kwargs={
                "autocommit": False,
                "connect_timeout": get_connect_timeout_s(),
            },
            configure=_pool_configure,
        )
        return _POOL


def connect_postgres_migration() -> PgConnection:
    """
    Direct autocommit connection for migrate.py (not pooled).

    GC-PERF-PG-SCHEMA-001: migration runner must not hold pool checkout across DDL.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise NotImplementedError(
            "PostgreSQL migrations require: pip install 'psycopg[binary]'"
        ) from exc
    url = get_database_url()
    if not url:
        raise NotImplementedError(
            "GC_DB_BACKEND=postgres requires DATABASE_URL for migrate.py"
        )
    raw = psycopg.connect(
        url,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=get_connect_timeout_s(),
    )
    return PgConnection(raw)


def connect_postgres() -> PgConnection:
    """Checkout a pooled connection wrapped for sqlite-style call sites."""
    pool = _ensure_pool()
    raw = pool.getconn()
    wrapped = PgConnection(raw)

    # Return to pool on close
    original_close = wrapped.close

    def _close_and_return() -> None:
        try:
            if wrapped.in_transaction:
                wrapped.rollback()
        except Exception:
            pass
        try:
            pool.putconn(raw)
        except Exception:
            try:
                raw.close()
            except Exception:
                pass
        # avoid double-return
        wrapped.close = original_close  # type: ignore[method-assign]

    wrapped.close = _close_and_return  # type: ignore[method-assign]
    return wrapped


def close_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            try:
                _POOL.close()
            except Exception:
                pass
            _POOL = None


# Schema is immutable mid-process after migrate; cache cuts PG information_schema chatter.
_PG_TABLE_EXISTS_CACHE: dict[str, bool] = {}


def postgres_table_exists(conn: PgConnection, table_name: str) -> bool:
    key = str(table_name)
    cached = _PG_TABLE_EXISTS_CACHE.get(key)
    if cached is not None:
        return cached
    cur = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = ?
        LIMIT 1;
        """,
        (key,),
    )
    found = cur.fetchone() is not None
    _PG_TABLE_EXISTS_CACHE[key] = found
    return found


def postgres_index_exists(conn: PgConnection, index_name: str) -> bool:
    cur = conn.execute(
        """
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = ?
        LIMIT 1;
        """,
        (str(index_name),),
    )
    return cur.fetchone() is not None


def postgres_table_columns(conn: PgConnection, table_name: str) -> set[str]:
    cur = conn.execute(
        """
        SELECT column_name AS name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?;
        """,
        (str(table_name),),
    )
    return {str(row["name"]) for row in cur.fetchall()}
