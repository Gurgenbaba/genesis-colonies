#!/usr/bin/env python3
"""
GC-PERF-PG-SCHEMA-001 — interactive acceptance against empty staging Postgres.

Never prints connection passwords. Requires:

  GC_DB_BACKEND=postgres
  DATABASE_URL=<staging public URL>   # or GC_TEST_POSTGRES_URL

Usage:
  python scripts/pg_schema_accept.py
  python scripts/pg_schema_accept.py --skip-migrate   # inventory only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _url() -> str:
    return (
        os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("GC_TEST_POSTGRES_URL", "").strip()
    )


def _assert_postgres_ready() -> None:
    backend = (os.environ.get("GC_DB_BACKEND") or "").strip().lower()
    if backend != "postgres":
        raise SystemExit("Set GC_DB_BACKEND=postgres (no silent SQLite fallback).")
    url = _url()
    if not url:
        raise SystemExit(
            "Set DATABASE_URL or GC_TEST_POSTGRES_URL to the empty staging Postgres "
            "public URL (never commit it)."
        )
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("postgres", "postgresql"):
        raise SystemExit(
            f"DATABASE_URL scheme must be postgresql:// (got {scheme!r}). "
            "Local sqlite: URLs are rejected for this acceptance script."
        )
    # Sync both vars for migrate.py + pytest live test
    os.environ["DATABASE_URL"] = url
    os.environ["GC_TEST_POSTGRES_URL"] = url
    os.environ["GC_DB_BACKEND"] = "postgres"
    print("backend= postgres")
    print("url_set= True")
    print(f"host= {urlparse(url).hostname}")
    print(f"db= {(urlparse(url).path or '').lstrip('/')}")


def _run_migrate() -> None:
    print("\n=== migrate.py (pass) ===")
    rc = subprocess.call([sys.executable, str(ROOT / "migrate.py")], cwd=str(ROOT))
    if rc != 0:
        raise SystemExit(f"migrate.py failed with exit {rc}")


def _probe() -> None:
    from game.db import db, get_db_backend

    assert get_db_backend() == "postgres"
    conn = db()
    try:
        row = conn.execute("SELECT current_database() AS db, current_user AS usr").fetchone()
        print(f"\nactive_db= {row['db']} user= {row['usr']}")

        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).fetchall()
        print(f"public_tables= {len(tables)}")

        migs = conn.execute("SELECT COUNT(*) AS cnt FROM migration_history").fetchone()
        print(f"migration_history= {int(migs['cnt'])}")

        bad = conn.execute(
            "SELECT conrelid::regclass::text AS rel, conname "
            "FROM pg_constraint WHERE NOT convalidated"
        ).fetchall()
        print(f"unvalidated_constraints= {len(bad)}")
        if bad:
            for r in bad:
                print(f"  ! {r['rel']} {r['conname']}")
            raise SystemExit("Unvalidated constraints present")

        seqs = conn.execute(
            "SELECT sequence_name FROM information_schema.sequences "
            "WHERE sequence_schema='public' ORDER BY sequence_name"
        ).fetchall()
        print(f"sequences= {len(seqs)}")
    finally:
        conn.close()


def _bootstrap() -> None:
    print("\n=== bootstrap_application ===")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=False)
    print("BOOTSTRAP_OK")


def _pytest_live() -> None:
    print("\n=== pytest live schema ===")
    rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_gc_perf_pg_schema_001.py",
            "-v",
            "--tb=short",
        ],
        cwd=str(ROOT),
    )
    if rc != 0:
        raise SystemExit(f"pytest failed with exit {rc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-bootstrap", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    _assert_postgres_ready()

    try:
        if not args.skip_migrate:
            _run_migrate()
            _run_migrate()  # idempotency

        _probe()

        if not args.skip_bootstrap:
            _bootstrap()

        if not args.skip_pytest:
            _pytest_live()

        print("\nGC-PERF-PG-SCHEMA-001 acceptance probe: OK")
        return 0
    finally:
        try:
            from game.db_pg import close_pool

            close_pool()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
