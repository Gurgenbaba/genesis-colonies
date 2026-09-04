#!/usr/bin/env python3
"""
Genesis Colonies – Migration Runner (SQLite default; Postgres via GC_DB_BACKEND).

Usage:
    python migrate.py

- Führt alle *.sql Dateien im Ordner "migrations" aus,
  die noch nicht in migration_history eingetragen sind.
- Speichert jede ausgeführte Migration in migration_history.
- GC-PERF-PG-SCHEMA-001: bei postgres Statements via game.sql_pg_rewrite;
  zweiter Lauf ist idempotent.

Robustheit:
- Autocommit-Connection, damit Migrations-SQL selbst BEGIN/COMMIT enthalten darf.
- Statement-weise Ausführung; idempotente Fehler werden übersprungen.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, List, Set


# ----------------------------------------
# Pfade
# ----------------------------------------

BASE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _db_path() -> Path:
    from game.db import resolve_db_path
    return resolve_db_path()


def _backend() -> str:
    from game.db import get_db_backend

    return get_db_backend()


# ----------------------------------------
# Helper: Environment
# ----------------------------------------

def ensure_db_exists() -> None:
    if _backend() == "postgres":
        # Numbered migrations start at 006 and assume init_db core tables exist.
        print("[INFO] GC_DB_BACKEND=postgres — bootstrap core schema (users/players/planets/…)")
        from game.db_pg import connect_postgres_migration
        from game.schema_bootstrap import bootstrap_core_schema, core_schema_ready

        conn = connect_postgres_migration()
        try:
            if core_schema_ready(conn):
                print("[INFO] Core schema already present.")
            else:
                n = bootstrap_core_schema(conn)
                print(f"[INFO] Core schema statements applied: {n}")
            from game.schema_bootstrap import ensure_postgres_i64_columns

            widened = ensure_postgres_i64_columns(conn)
            if widened:
                print(f"[INFO] Widened 64-bit columns: {', '.join(widened)}")
        finally:
            conn.close()
        return
    db_path = _db_path()
    if not db_path.exists():
        print(f"[INFO] DB nicht gefunden – bootstrap via init_db(): {db_path}")
        from game.models import init_db
        init_db()


def ensure_migrations_dir() -> None:
    if not MIGRATIONS_DIR.exists():
        raise SystemExit(f"[ERROR] migrations-Verzeichnis nicht gefunden: {MIGRATIONS_DIR}")


def get_connection() -> Any:
    """Autocommit connection for the configured backend."""
    if _backend() == "postgres":
        from game.db_pg import connect_postgres_migration

        return connect_postgres_migration()

    from game.db import ensure_db_parent_dir

    db_path = ensure_db_parent_dir()
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=4000;")
    return conn


# ----------------------------------------
# Migration History
# ----------------------------------------

def ensure_migration_history_table(conn: Any) -> None:
    if _backend() == "postgres":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_history (
                id          BIGSERIAL PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                applied_at  BIGINT NOT NULL
            );
            """
        )
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            applied_at  INTEGER NOT NULL
        );
        """
    )


def get_applied_migrations(conn: Any) -> Set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM migration_history;")
    rows = cur.fetchall()
    names: Set[str] = set()
    for row in rows:
        if isinstance(row, dict) or hasattr(row, "keys"):
            names.add(str(row["name"]))
        else:
            names.add(str(row[0]))
    return names


def mark_migration_applied(conn: Any, filename: str) -> None:
    ts = int(time.time())
    if _backend() == "postgres":
        conn.execute(
            "INSERT INTO migration_history (name, applied_at) VALUES (?, ?) "
            "ON CONFLICT (name) DO NOTHING;",
            (filename, ts),
        )
        return
    conn.execute(
        "INSERT INTO migration_history (name, applied_at) VALUES (?, ?);",
        (filename, ts),
    )


# ----------------------------------------
# SQL Parsing / Splitting
# ----------------------------------------

def strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def _split_sql_statements(sql_text: str) -> List[str]:
    """
    Splittet SQL in Statements, getrennt durch ';' – aber nur außerhalb von Quotes.

    Unterstützt:
    - single quotes: '...'
    - double quotes: "..."
    - line comments: -- ...
    - block comments: /* ... */

    Für unsere Migrationen (CREATE/ALTER/INSERT/UPDATE/INDEX) reicht das völlig.
    """
    s = strip_bom(sql_text)
    out: List[str] = []

    buf: List[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    n = len(s)

    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""

        # Line comment
        if not in_single and not in_double and not in_block_comment and not in_line_comment:
            if ch == "-" and nxt == "-":
                in_line_comment = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        # Block comment
        if not in_single and not in_double and not in_line_comment and not in_block_comment:
            if ch == "/" and nxt == "*":
                in_block_comment = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue

        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue

        # Quotes
        if ch == "'" and not in_double:
            # handle escaped '' inside single quotes
            if in_single and nxt == "'":
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            # handle escaped "" inside double quotes (SQLite tolerates it)
            if in_double and nxt == '"':
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        # Statement end
        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            buf = []
            if stmt:
                out.append(stmt + ";")
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)

    return out


def _contains_explicit_transaction(statements: List[str]) -> bool:
    """
    Prüft, ob Migration selbst BEGIN/COMMIT/ROLLBACK nutzt.
    Wenn ja, machen wir KEIN eigenes BEGIN.

    Word-boundary match only — column names like ``forge_cores_committed``
    must not suppress the migrate wrapper transaction (PG SAVEPOINT needs it).
    """
    import re

    text = "\n".join(statements).upper()
    return bool(
        re.search(r"\bBEGIN\b", text)
        or re.search(r"\bCOMMIT\b", text)
        or re.search(r"\bROLLBACK\b", text)
    )


# ----------------------------------------
# Idempotent Error Handling
# ----------------------------------------

def _is_idempotent_sqlite_error(e: sqlite3.Error) -> bool:
    msg = str(e).lower()

    # ALTER TABLE ADD COLUMN ...
    if "duplicate column name" in msg:
        return True

    # CREATE TABLE/INDEX ...
    if "already exists" in msg:
        return True

    # CREATE INDEX IF NOT EXISTS sollte das sowieso verhindern, aber sicher ist sicher
    if "index" in msg and "already exists" in msg:
        return True

    # Wenn man FOREIGN KEY / constraint doppelt anlegt etc. -> eher selten
    return False


def _required_backend(sql_text: str) -> Optional[str]:
    """Read an optional backend-only migration directive.

    Syntax: -- GC-BACKEND: postgres or -- GC-BACKEND: sqlite.
    Non-target migrations are recorded as applied for that backend. Migration
    history is never copied by the SQLite→PostgreSQL importer, so a later
    PostgreSQL cutover will still execute PostgreSQL-only migrations.
    """
    prefix = "-- GC-BACKEND:"
    for line in strip_bom(sql_text).splitlines()[:20]:
        stripped = line.strip()
        if not stripped.upper().startswith(prefix):
            continue
        backend = stripped[len(prefix):].strip().lower()
        if backend not in ("sqlite", "postgres"):
            raise ValueError(f"invalid GC-BACKEND value: {backend!r}")
        return backend
    return None


def _required_tables(sql_text: str) -> List[str]:
    """Read an optional migration table-precondition directive.

    Syntax: ``-- GC-REQUIRES-TABLES: table_a, table_b``.  This is used for
    data-only migrations that legitimately have nothing to do on historical
    snapshots where an optional module was never installed.
    """
    prefix = "-- GC-REQUIRES-TABLES:"
    for line in strip_bom(sql_text).splitlines()[:20]:
        stripped = line.strip()
        if not stripped.upper().startswith(prefix):
            continue
        names: List[str] = []
        for raw in stripped[len(prefix):].split(","):
            name = raw.strip()
            if not name:
                continue
            if not (name[0].isalpha() or name[0] == "_") or not all(ch.isalnum() or ch == "_" for ch in name):
                raise ValueError(f"invalid GC-REQUIRES-TABLES identifier: {name!r}")
            names.append(name)
        return names
    return []


def _table_exists(conn: Any, table_name: str) -> bool:
    cur = conn.cursor()
    if _backend() == "postgres":
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ? LIMIT 1;",
            (str(table_name),),
        )
    else:
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",
            (str(table_name),),
        )
    return cur.fetchone() is not None


# ----------------------------------------
# Apply Migration
# ----------------------------------------

def apply_migration(conn: Any, filename: str, sql_text: str) -> None:
    """
    Führt eine Migration aus:
    - optional Postgres-Dialekt-Rewrite (GC-PERF-PG-SCHEMA-001)
    - split in statements
    - SQLite: BEGIN IMMEDIATE / COMMIT
    - Postgres: SAVEPOINT pro Statement (Fehler dürfen die TX nicht aborten)
    - idempotente Fehler pro Statement werden übersprungen
    """
    print(f"  -> wende Migration an: {filename}")

    required_backend = _required_backend(sql_text)
    if required_backend and required_backend != _backend():
        print(f"     [skip not-applicable] backend={required_backend}")
        mark_migration_applied(conn, filename)
        return

    required_tables = _required_tables(sql_text)
    if required_tables:
        missing_tables = [name for name in required_tables if not _table_exists(conn, name)]
        if missing_tables:
            print(
                "     [skip not-applicable] required table(s) missing: "
                + ", ".join(missing_tables)
            )
            mark_migration_applied(conn, filename)
            return

    if _backend() == "postgres":
        from game.sql_pg_rewrite import rewrite_migration_script

        sql_text, notes = rewrite_migration_script(sql_text)
        for note in notes[:8]:
            print(f"     [pg-rewrite] {note}")
        if len(notes) > 8:
            print(f"     [pg-rewrite] … +{len(notes) - 8} further notes")

    statements = _split_sql_statements(sql_text)
    statements = [s.strip() for s in statements if s.strip()]

    if not statements:
        print("     (leer) -> markiere als angewendet")
        mark_migration_applied(conn, filename)
        return

    has_tx = _contains_explicit_transaction(statements)
    backend = _backend()

    try:
        if not has_tx:
            if backend == "postgres":
                conn.execute("BEGIN;")
            else:
                conn.execute("BEGIN IMMEDIATE;")

        for idx, s in enumerate(statements):
            s_clean = s.strip()
            if not s_clean:
                continue
            if backend == "postgres" and s_clean.upper().startswith("PRAGMA"):
                continue

            if backend == "postgres":
                sp = f"gc_mig_{idx}"
                conn.execute(f"SAVEPOINT {sp};")
                try:
                    conn.execute(s_clean)
                    conn.execute(f"RELEASE SAVEPOINT {sp};")
                except Exception as e:
                    try:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp};")
                    except Exception:
                        pass
                    from game.sql_pg_rewrite import is_idempotent_postgres_error

                    if is_idempotent_postgres_error(e):
                        print(f"     [skip idempotent] {e} | stmt: {s_clean[:80]}")
                        continue
                    raise
            else:
                try:
                    conn.execute(s_clean)
                except sqlite3.Error as e:
                    if _is_idempotent_sqlite_error(e):
                        print(f"     [skip idempotent] {e} | stmt: {s_clean[:80]}")
                        continue
                    raise

        if not has_tx:
            conn.execute("COMMIT;")

        mark_migration_applied(conn, filename)
        print(f"  OK Migration erfolgreich: {filename}")

    except Exception as e:
        try:
            if not has_tx:
                conn.execute("ROLLBACK;")
        except Exception:
            pass
        print(f"  FEHLER in Migration {filename}: {e}")
        raise


# ----------------------------------------
# Main
# ----------------------------------------

def main() -> None:
    from game.config import init_config
    from game.db import describe_db_connection

    init_config()
    backend = _backend()
    print("=== Genesis Colonies – Migration Runner ===")
    print(f"Backend:    {backend}")
    if backend == "sqlite":
        print(f"DB:         {_db_path()}")
    else:
        info = describe_db_connection()
        print(f"DB:         postgres (url_set={info.get('database_url_set')})")
    print(f"Migrations: {MIGRATIONS_DIR}")
    print("-------------------------------------------")

    if backend == "postgres":
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise SystemExit(
                "[ERROR] GC_DB_BACKEND=postgres requires DATABASE_URL. "
                "No silent SQLite fallback."
            )

    ensure_db_exists()
    ensure_migrations_dir()

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print("Keine .sql-Migrationen gefunden. Nichts zu tun.")
        return

    conn = get_connection()
    try:
        ensure_migration_history_table(conn)
        applied = get_applied_migrations(conn)

        print(f"Bereits angewendete Migrationen: {len(applied)}")
        print("-------------------------------------------")

        new_migrations = [p for p in sql_files if p.name not in applied]
        if not new_migrations:
            print("Alle Migrationen sind bereits angewendet.")
        else:
            print(f"Neue Migrationen: {len(new_migrations)}")
            if backend == "sqlite":
                _ensure_galaxy_coordinates(conn)

            for path in new_migrations:
                filename = path.name
                print(f"\n==> Migration: {filename}")
                sql_text = path.read_text(encoding="utf-8")
                apply_migration(conn, filename, sql_text)

            print("\nAlle neuen Migrationen erfolgreich angewendet.")

        if backend == "sqlite":
            _ensure_galaxy_coordinates(conn)
    finally:
        conn.close()


def _ensure_galaxy_coordinates(conn: Any) -> None:
    """Backfill / dedupe planet coordinates before unique index enforcement."""
    try:
        from game.galaxy import repair_missing_coordinates

        repaired = repair_missing_coordinates(conn)
        if repaired:
            print(f"[galaxy] Repariert: {repaired} Planet(en) ohne oder doppelte Koordinaten.")
    except Exception as e:
        print(f"[galaxy] Koordinaten-Reparatur übersprungen: {e}")


if __name__ == "__main__":
    main()
