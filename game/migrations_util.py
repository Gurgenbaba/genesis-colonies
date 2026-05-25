"""
Migration status helpers (shared by migrate.py, health check, bootstrap).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT_DIR / "migrations"


def list_migration_files() -> List[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


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


def get_applied_migration_names(conn: sqlite3.Connection) -> Set[str]:
    ensure_migration_history_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT name FROM migration_history;")
    return {str(row[0]) for row in cur.fetchall()}


def get_pending_migration_names() -> Tuple[List[str], Optional[str]]:
    """
    Returns (pending_file_names, error_message).
    If DB does not exist yet, all migration files are considered pending.
    """
    files = list_migration_files()
    all_names = [p.name for p in files]

    from game.db import db, resolve_db_path

    db_path = resolve_db_path()
    if not db_path.exists():
        return all_names, None

    conn = db()
    try:
        applied = get_applied_migration_names(conn)
        pending = [name for name in all_names if name not in applied]
        return pending, None
    except Exception as exc:
        return [], str(exc)
    finally:
        conn.close()


def migrations_are_current() -> Tuple[bool, List[str], Optional[str]]:
    pending, err = get_pending_migration_names()
    if err:
        return False, pending, err
    return len(pending) == 0, pending, None
