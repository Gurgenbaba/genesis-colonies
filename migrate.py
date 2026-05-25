#!/usr/bin/env python3
"""
Genesis Colonies – Simple Migration Runner (SQLite)

Usage:
    python migrate.py

- Führt alle *.sql Dateien im Ordner "migrations" aus,
  die noch nicht in migration_history eingetragen sind.
- Speichert jede ausgeführte Migration in migration_history.

Robustheit:
- Autocommit-Connection (isolation_level=None), damit Migrations-SQL selbst BEGIN/COMMIT
  enthalten darf, ohne "cannot start a transaction within a transaction".
- Führt Migrationen Statement-weise aus (Splitter), damit wir idempotente Fehler
  (duplicate column / already exists / etc.) pro Statement überspringen können.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import List


# ----------------------------------------
# Pfade
# ----------------------------------------

BASE_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = BASE_DIR / "migrations"


def _db_path() -> Path:
    from game.db import resolve_db_path
    return resolve_db_path()


# ----------------------------------------
# Helper: Environment
# ----------------------------------------

def ensure_db_exists() -> None:
    db_path = _db_path()
    if not db_path.exists():
        print(f"[INFO] DB nicht gefunden – bootstrap via init_db(): {db_path}")
        from game.models import init_db
        init_db()


def ensure_migrations_dir() -> None:
    if not MIGRATIONS_DIR.exists():
        raise SystemExit(f"[ERROR] migrations-Verzeichnis nicht gefunden: {MIGRATIONS_DIR}")


def get_connection() -> sqlite3.Connection:
    # WICHTIG: autocommit mode => keine implicit transaction von sqlite3
    conn = sqlite3.connect(_db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # Optional: slightly safer busy handling
    conn.execute("PRAGMA busy_timeout=4000;")
    return conn


# ----------------------------------------
# Migration History
# ----------------------------------------

def ensure_migration_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            applied_at  INTEGER NOT NULL
        );
        """
    )


def get_applied_migrations(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT name FROM migration_history;")
    return {row["name"] for row in cur.fetchall()}


def mark_migration_applied(conn: sqlite3.Connection, filename: str) -> None:
    ts = int(time.time())
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
    """
    text = "\n".join(statements).upper()
    # BEGIN, BEGIN IMMEDIATE, BEGIN TRANSACTION etc.
    if "BEGIN" in text:
        return True
    if "COMMIT" in text or "ROLLBACK" in text:
        return True
    return False


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


# ----------------------------------------
# Apply Migration
# ----------------------------------------

def apply_migration(conn: sqlite3.Connection, filename: str, sql_text: str) -> None:
    """
    Führt eine Migration aus:
    - split in statements
    - wenn Migration selbst BEGIN/COMMIT enthält -> so ausführen
    - sonst: wir machen BEGIN IMMEDIATE / COMMIT
    - idempotente Fehler pro Statement werden übersprungen
    """
    print(f"  -> wende Migration an: {filename}")

    statements = _split_sql_statements(sql_text)
    statements = [s.strip() for s in statements if s.strip()]

    if not statements:
        print("     (leer) -> markiere als angewendet")
        mark_migration_applied(conn, filename)
        return

    has_tx = _contains_explicit_transaction(statements)

    try:
        if not has_tx:
            conn.execute("BEGIN IMMEDIATE;")

        for s in statements:
            s_clean = s.strip()
            if not s_clean:
                continue

            try:
                conn.execute(s_clean)
            except sqlite3.Error as e:
                if _is_idempotent_sqlite_error(e):
                    print(f"     [skip idempotent] {e} | stmt: {s_clean[:80]}")
                    continue
                # Nicht-idempotent => hart stoppen
                raise

        if not has_tx:
            conn.execute("COMMIT;")

        # Migration als erfolgreich markieren (eigener Mini-Commit bei autocommit nötig? nein, autocommit schreibt sofort)
        mark_migration_applied(conn, filename)
        print(f"  OK Migration erfolgreich: {filename}")

    except sqlite3.Error as e:
        # Wenn wir selbst BEGIN gemacht haben => rollback
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
    db_path = _db_path()
    print("=== Genesis Colonies – Migration Runner ===")
    print(f"DB:         {db_path}")
    print(f"Migrations: {MIGRATIONS_DIR}")
    print("-------------------------------------------")

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
            return

        print(f"Neue Migrationen: {len(new_migrations)}")

        for path in new_migrations:
            filename = path.name
            print(f"\n==> Migration: {filename}")
            sql_text = path.read_text(encoding="utf-8")
            apply_migration(conn, filename, sql_text)

        print("\nAlle neuen Migrationen erfolgreich angewendet.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
