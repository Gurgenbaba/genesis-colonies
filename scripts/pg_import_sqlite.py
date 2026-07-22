#!/usr/bin/env python3
"""
GC-PERF-PG-MIGRATE-001 — ordered SQLite → PostgreSQL data importer.

Not a blind SQL dump. Not a production cutover.

Requires for a real import:
  GC_DB_BACKEND=postgres
  DATABASE_URL=postgresql://…   (or GC_TEST_POSTGRES_URL)

Dry-run works against SQLite alone (no Postgres required):

  python scripts/pg_import_sqlite.py --dry-run
  python scripts/pg_import_sqlite.py --dry-run --sqlite path/to/game.db

Real import (staging only; wipe optional):

  python scripts/pg_import_sqlite.py --sqlite game/game.db
  python scripts/pg_import_sqlite.py --wipe --sqlite game/game.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Schema bookkeeping stays on the target (SCHEMA-001 already applied).
SKIP_TABLES: frozenset[str] = frozenset(
    {
        "migration_history",
        "sqlite_sequence",
    }
)

# Prefer these parents early when the topo queue has ties.
ROOT_PRIORITY: tuple[str, ...] = (
    "users",
    "players",
    "game_settings",
    "vote_providers",
    "pe_trait_definitions",
    "pe_research_definitions",
    "pe_specialization_definitions",
    "pe_policy_definitions",
    "pe_event_definitions",
    "pe_discovery_definitions",
    "pe_special_resource_definitions",
    "pe_production_chain_definitions",
    "pe_ascension_definitions",
    "gd_directive_definitions",
    "gd_bloc_definitions",
    "gd_resolution_definitions",
    "gd_emergency_definitions",
    "gd_galaxy_personality_definitions",
    "directive_definitions",
    "player_card_badges",
    "alliances",
    "planets",
    "chat_rooms",
)

BATCH_SIZE = 500


@dataclass
class TableCopyStat:
    table: str
    sqlite_rows: int = 0
    postgres_rows: int = 0
    copied: int = 0
    skipped: bool = False
    note: str = ""


@dataclass
class ImportReport:
    dry_run: bool
    sqlite_path: str
    table_order: list[str] = field(default_factory=list)
    stats: list[TableCopyStat] = field(default_factory=list)
    sequences_reset: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def default_sqlite_path() -> Path:
    override = os.environ.get("GC_DB_PATH", "").strip()
    if override:
        return Path(override)
    return ROOT / "game" / "game.db"


def postgres_url_from_env() -> str:
    for key in ("DATABASE_URL", "GC_TEST_POSTGRES_URL"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        low = raw.lower()
        if low.startswith("postgres://") or low.startswith("postgresql://"):
            if raw.startswith("postgres://"):
                return "postgresql://" + raw[len("postgres://") :]
            return raw
    return ""


def require_postgres_config() -> str:
    backend = (os.environ.get("GC_DB_BACKEND") or "").strip().lower()
    if backend != "postgres":
        raise SystemExit(
            "GC-PERF-PG-MIGRATE-001: set GC_DB_BACKEND=postgres "
            "(no silent SQLite fallback for import)."
        )
    url = postgres_url_from_env()
    if not url:
        raise SystemExit(
            "GC-PERF-PG-MIGRATE-001: set DATABASE_URL or GC_TEST_POSTGRES_URL "
            "to a postgresql://… target (staging). Refusing to guess."
        )
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("postgres", "postgresql"):
        raise SystemExit(
            f"GC-PERF-PG-MIGRATE-001: DATABASE_URL scheme must be postgresql:// "
            f"(got {scheme!r})."
        )
    os.environ["DATABASE_URL"] = url
    os.environ["GC_DB_BACKEND"] = "postgres"
    return url


def open_sqlite(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite source not found: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def list_sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
        """
    ).fetchall()
    names = [str(r[0]) for r in rows]
    return [n for n in names if n not in SKIP_TABLES]


def sqlite_fk_edges(conn: sqlite3.Connection, tables: Sequence[str]) -> list[tuple[str, str]]:
    """Return (child, parent) edges for tables that exist in ``tables``."""
    wanted = set(tables)
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for child in tables:
        for row in conn.execute(f'PRAGMA foreign_key_list("{child}")'):
            parent = str(row[2] or "")
            if not parent or parent not in wanted:
                continue
            if parent == child:
                continue
            key = (child, parent)
            if key in seen:
                continue
            seen.add(key)
            edges.append(key)
    return edges


def compute_import_table_order(
    tables: Sequence[str],
    edges: Sequence[tuple[str, str]],
    *,
    root_priority: Sequence[str] = ROOT_PRIORITY,
) -> list[str]:
    """
    Parents before children (Kahn topological sort).

    ``edges`` are (child, parent). Raises ValueError on cycles.
    """
    nodes = sorted(set(tables))
    node_set = set(nodes)
    dependents: dict[str, set[str]] = defaultdict(set)  # parent → children
    indegree: dict[str, int] = {n: 0 for n in nodes}

    for child, parent in edges:
        if child not in node_set or parent not in node_set:
            continue
        if child in dependents[parent]:
            continue
        dependents[parent].add(child)
        indegree[child] = indegree.get(child, 0) + 1

    prio = {name: idx for idx, name in enumerate(root_priority)}

    def sort_key(name: str) -> tuple[int, str]:
        return (prio.get(name, 10_000), name)

    ready = deque(sorted((n for n in nodes if indegree[n] == 0), key=sort_key))
    ordered: list[str] = []
    while ready:
        node = ready.popleft()
        ordered.append(node)
        for child in sorted(dependents.get(node, ()), key=sort_key):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        # Keep ready queue ordered by priority after appends
        if len(ready) > 1:
            ready = deque(sorted(ready, key=sort_key))

    if len(ordered) != len(nodes):
        leftover = sorted(n for n in nodes if n not in set(ordered))
        raise ValueError(
            "FK cycle or unresolved dependencies among tables: " + ", ".join(leftover)
        )
    return ordered


def sqlite_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [str(r[1]) for r in rows]


def sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()
    return int(row[0] if row is not None else 0)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _pg_table_exists(pg: Any, table: str) -> bool:
    row = pg.execute(
        """
        SELECT 1
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename = %s
        LIMIT 1;
        """,
        (table,),
    ).fetchone()
    return row is not None


def _pg_table_columns(pg: Any, table: str) -> list[str]:
    rows = pg.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (table,),
    ).fetchall()
    out: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(str(r["column_name"]))
        else:
            out.append(str(r[0]))
    return out


def _pg_row_count(pg: Any, table: str) -> int:
    row = pg.execute(f"SELECT COUNT(*) AS c FROM {_quote_ident(table)};").fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row["c"])
    return int(row[0])


def _chunked(rows: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def wipe_postgres_tables(pg: Any, tables: Sequence[str]) -> None:
    """Truncate in reverse import order (children first)."""
    existing = [t for t in reversed(list(tables)) if _pg_table_exists(pg, t)]
    if not existing:
        return
    joined = ", ".join(_quote_ident(t) for t in existing)
    pg.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE;")
    pg.commit()


def copy_table(
    sqlite_conn: sqlite3.Connection,
    pg: Any,
    table: str,
    *,
    batch_size: int = BATCH_SIZE,
) -> TableCopyStat:
    stat = TableCopyStat(table=table, sqlite_rows=sqlite_row_count(sqlite_conn, table))
    if not _pg_table_exists(pg, table):
        stat.skipped = True
        stat.note = "missing on postgres"
        return stat

    src_cols = sqlite_table_columns(sqlite_conn, table)
    dst_cols = set(_pg_table_columns(pg, table))
    cols = [c for c in src_cols if c in dst_cols]
    if not cols:
        stat.skipped = True
        stat.note = "no overlapping columns"
        return stat

    col_sql = ", ".join(_quote_ident(c) for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = (
        f"INSERT INTO {_quote_ident(table)} ({col_sql}) VALUES ({placeholders})"
    )
    select_sql = f'SELECT {", ".join(_quote_ident(c) for c in cols)} FROM "{table}"'

    src_rows = sqlite_conn.execute(select_sql).fetchall()
    copied = 0
    for batch in _chunked(src_rows, batch_size):
        params = [tuple(row[c] for c in cols) for row in batch]
        pg.cursor().executemany(insert_sql, params)
        copied += len(params)
    pg.commit()
    stat.copied = copied
    stat.postgres_rows = _pg_row_count(pg, table)
    missing_dst = [c for c in src_cols if c not in dst_cols]
    if missing_dst:
        stat.note = f"omitted columns not on PG: {', '.join(missing_dst)}"
    return stat


def reset_postgres_sequences(pg: Any, tables: Sequence[str]) -> int:
    """
    Align serial/identity sequences with MAX(column) after explicit-ID inserts.

    Returns number of sequences successfully reset.
    """
    reset = 0
    for table in tables:
        if not _pg_table_exists(pg, table):
            continue
        cols = _pg_table_columns(pg, table)
        for col in cols:
            row = pg.execute(
                "SELECT pg_get_serial_sequence(%s, %s) AS seq;",
                (table, col),
            ).fetchone()
            if row is None:
                continue
            seq = row["seq"] if isinstance(row, dict) else row[0]
            if not seq:
                continue
            max_row = pg.execute(
                f"SELECT COALESCE(MAX({_quote_ident(col)}), 0) AS m "
                f"FROM {_quote_ident(table)};"
            ).fetchone()
            max_val = int(
                (max_row["m"] if isinstance(max_row, dict) else max_row[0]) or 0
            )
            # is_called=true → next nextval returns max_val+1 (or 1 when empty)
            next_base = max(max_val, 1) if max_val > 0 else 1
            is_called = max_val > 0
            pg.execute(
                "SELECT setval(%s::regclass, %s, %s);",
                (seq, next_base, is_called),
            )
            reset += 1
        pg.commit()
    return reset


def build_dry_run_report(sqlite_path: Path) -> ImportReport:
    report = ImportReport(dry_run=True, sqlite_path=str(sqlite_path))
    conn = open_sqlite(sqlite_path)
    try:
        tables = list_sqlite_tables(conn)
        edges = sqlite_fk_edges(conn, tables)
        try:
            order = compute_import_table_order(tables, edges)
        except ValueError as exc:
            report.errors.append(str(exc))
            return report
        report.table_order = order
        for table in order:
            report.stats.append(
                TableCopyStat(
                    table=table,
                    sqlite_rows=sqlite_row_count(conn, table),
                    note="dry-run",
                )
            )
    finally:
        conn.close()
    return report


def run_import(
    *,
    sqlite_path: Path,
    wipe: bool = False,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
) -> ImportReport:
    if dry_run:
        return build_dry_run_report(sqlite_path)

    require_postgres_config()
    report = ImportReport(dry_run=False, sqlite_path=str(sqlite_path))

    from game.db_pg import close_pool, connect_postgres_migration

    sqlite_conn = open_sqlite(sqlite_path)
    pg = None
    try:
        tables = list_sqlite_tables(sqlite_conn)
        edges = sqlite_fk_edges(sqlite_conn, tables)
        try:
            order = compute_import_table_order(tables, edges)
        except ValueError as exc:
            report.errors.append(str(exc))
            return report
        report.table_order = order

        close_pool()
        pg = connect_postgres_migration()
        # Migration wrapper uses autocommit=True; still call commit() no-ops safely.
        raw = getattr(pg, "_conn", None)
        if raw is not None and getattr(raw, "autocommit", False):
            raw.autocommit = False

        if wipe:
            wipe_postgres_tables(pg, order)
        else:
            nonempty = []
            for table in order:
                if _pg_table_exists(pg, table) and _pg_row_count(pg, table) > 0:
                    nonempty.append(table)
            if nonempty:
                sample = ", ".join(nonempty[:12])
                more = "" if len(nonempty) <= 12 else f" (+{len(nonempty) - 12} more)"
                report.errors.append(
                    "Target Postgres tables already contain rows "
                    f"({sample}{more}). Re-run with --wipe or use an empty DB."
                )
                return report

        # Optional safety net for residual FK quirks (needs privilege on some hosts).
        replication_role_set = False
        try:
            pg.execute("SET session_replication_role = replica;")
            pg.commit()
            replication_role_set = True
        except Exception:
            try:
                pg.rollback()
            except Exception:
                pass

        try:
            for table in order:
                stat = copy_table(
                    sqlite_conn, pg, table, batch_size=batch_size
                )
                report.stats.append(stat)
                if not stat.skipped and stat.sqlite_rows != stat.postgres_rows:
                    if not stat.note:
                        stat.note = (
                            f"row mismatch sqlite={stat.sqlite_rows} "
                            f"pg={stat.postgres_rows}"
                        )
        finally:
            if replication_role_set:
                try:
                    pg.execute("SET session_replication_role = origin;")
                    pg.commit()
                except Exception:
                    try:
                        pg.rollback()
                    except Exception:
                        pass

        report.sequences_reset = reset_postgres_sequences(pg, order)
    except Exception as exc:
        report.errors.append(f"{type(exc).__name__}: {exc}")
        if pg is not None:
            try:
                pg.rollback()
            except Exception:
                pass
    finally:
        sqlite_conn.close()
        if pg is not None:
            try:
                pg.close()
            except Exception:
                pass
        try:
            from game.db_pg import close_pool as _close

            _close()
        except Exception:
            pass
    return report


def print_report(report: ImportReport) -> None:
    mode = "DRY-RUN" if report.dry_run else "IMPORT"
    print(f"=== GC-PERF-PG-MIGRATE-001 {mode} ===")
    print(f"sqlite= {report.sqlite_path}")
    print(f"tables= {len(report.table_order)}")
    if report.dry_run:
        print("(no Postgres writes)")
    print("\n-- copy order --")
    for i, name in enumerate(report.table_order, 1):
        print(f"{i:3d}. {name}")
    print("\n-- row counts --")
    print(f"{'table':40s} {'sqlite':>10s} {'postgres':>10s} {'copied':>10s} note")
    for st in report.stats:
        pg_disp = "-" if report.dry_run else str(st.postgres_rows)
        copied_disp = "-" if report.dry_run else str(st.copied)
        note = st.note or ("skip" if st.skipped else "")
        print(
            f"{st.table:40s} {st.sqlite_rows:10d} {pg_disp:>10s} "
            f"{copied_disp:>10s} {note}"
        )
    if not report.dry_run:
        print(f"\nsequences_reset= {report.sequences_reset}")
    if report.errors:
        print("\n-- errors --")
        for err in report.errors:
            print(f"! {err}")
    else:
        print("\nok= True")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="GC-PERF-PG-MIGRATE-001 ordered SQLite→Postgres importer"
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=None,
        help="Source SQLite path (default: GC_DB_PATH or game/game.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze SQLite only: order + row counts, no Postgres writes",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="TRUNCATE target tables (CASCADE) before import",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"INSERT batch size (default {BATCH_SIZE})",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    sqlite_path = Path(args.sqlite) if args.sqlite else default_sqlite_path()

    if not args.dry_run and args.wipe is False:
        # Still validate postgres early so misconfig fails before long work.
        pass

    try:
        report = run_import(
            sqlite_path=sqlite_path,
            wipe=bool(args.wipe),
            dry_run=bool(args.dry_run),
            batch_size=max(1, int(args.batch_size)),
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        # argparse / require_postgres_config
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        print(str(code), file=sys.stderr)
        return 1

    print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
