"""
GC-PERF-PG-PARITY-001 — PostgreSQL test database owner.

Default (fast, Railway-friendly):
  Reuse ``GC_TEST_POSTGRES_URL`` (already migrated staging DB), wipe a small
  set of game tables between tests. Do not run parallel parity suites against
  the same DB. Do not keep ``python app.py`` connected to the same DB.

Opt-in isolation (slow over public proxy):
  ``GC_TEST_POSTGRES_ISOLATE=1`` → CREATE DATABASE gc_parity_<id> + full migrate.

Progress prints go to stdout — run with ``pytest -s`` to see them live.
Never prints connection passwords.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import urlparse, urlunparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATE_SCRIPT = ROOT / "migrate.py"

# Keep wipe small/fast over Railway public proxy (parity A/B only needs these).
_WIPE_TABLES: tuple[str, ...] = (
    "action_idempotency",
    "build_queue",
    "research_queue",
    "research_levels",
    "shipyard_queue",
    "defense_queue",
    "planet_ships",
    "planet_defense",
    "planet_buildings",
    "player_scores",
    "planets",
    "players",
    "users",
    "game_settings",
    "player_avatars",
    "player_cards",
    "player_card_unlocked_badges",
    "fleet_movements",
    "fleet_batches",
    "fleet_presets",
)


def postgres_test_url() -> str:
    """
    Prefer GC_TEST_POSTGRES_URL. Fall back to DATABASE_URL only when it is
    actually PostgreSQL (ignore sqlite:///… leftovers in the shell).
    """
    for key in ("GC_TEST_POSTGRES_URL", "DATABASE_URL"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        low = raw.lower()
        if low.startswith("postgres://") or low.startswith("postgresql://"):
            return raw
    return ""


def postgres_isolate_enabled() -> bool:
    return os.environ.get("GC_TEST_POSTGRES_ISOLATE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


requires_postgres = pytest.mark.skipif(
    not postgres_test_url(),
    reason="Set GC_TEST_POSTGRES_URL for PostgreSQL parity tests",
)


def _log(msg: str) -> None:
    print(f"[pg_fixtures] {msg}", flush=True)


def _safe_db_label(url: str) -> str:
    parsed = urlparse(url)
    db = (parsed.path or "/").lstrip("/").split("/")[0] or "?"
    return f"{parsed.hostname or '?'}/{db}"


def _replace_database(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path="/" + database.strip("/")))


def _database_name(url: str) -> str:
    path = urlparse(url).path or ""
    name = path.lstrip("/").split("/")[0]
    return name or "postgres"


def _connect_kwargs(**extra: Any) -> dict[str, Any]:
    kw: dict[str, Any] = {"connect_timeout": 15, "autocommit": True}
    kw.update(extra)
    return kw


def close_pg_pool() -> None:
    try:
        from game.db_pg import close_pool

        close_pool()
    except Exception:
        pass


def run_migrate(*, env: Optional[dict[str, str]] = None) -> None:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    _log("migrate.py …")
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=run_env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "migrate.py failed for parity DB:\n"
            + (result.stderr or result.stdout or "no output")
        )
    _log("migrate.py OK")


def _migration_count(url: str) -> int:
    import psycopg

    _log(f"connect (migration probe) {_safe_db_label(url)} …")
    with psycopg.connect(url, **_connect_kwargs()) as conn:
        conn.execute("SET statement_timeout = '15s'")
        try:
            row = conn.execute("SELECT COUNT(*) AS c FROM migration_history;").fetchone()
        except Exception:
            return 0
        if row is None:
            return 0
        return int(row["c"] if isinstance(row, dict) else row[0])


def wipe_postgres_game_data(conn: Any) -> None:
    """
    Truncate parity-relevant tables (not full public schema).

    Prefer this over TRUNCATE-all: fewer round-trips and less lock wait on Railway.
    """
    existing: list[str] = []
    for name in _WIPE_TABLES:
        row = conn.execute(
            """
            SELECT 1
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = ?
            LIMIT 1;
            """,
            (name,),
        ).fetchone()
        if row:
            existing.append(name)
    if not existing:
        return
    joined = ", ".join(f'"{n}"' for n in existing)
    conn.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE;")
    conn.commit()


def wipe_postgres_game_data_direct(url: str) -> None:
    """Wipe via a short-lived direct connection (timeouts, no app pool)."""
    import psycopg

    _log("wipe (direct connection) …")
    with psycopg.connect(url, **_connect_kwargs()) as raw:
        raw.execute("SET lock_timeout = '8s'")
        raw.execute("SET statement_timeout = '45s'")
        # psycopg: list → PG array; tuple would become a composite/record literal
        rows = raw.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename = ANY(%s)
            ORDER BY tablename;
            """,
            (list(_WIPE_TABLES),),
        ).fetchall()
        names = [str(r["tablename"] if isinstance(r, dict) else r[0]) for r in rows]
        if not names:
            _log("wipe: nothing to truncate")
            return
        joined = ", ".join(f'"{n}"' for n in names)
        try:
            raw.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE;")
        except Exception as exc:
            raise RuntimeError(
                "Postgres wipe timed out or blocked (lock). "
                "Stop any python app.py using the same DATABASE_URL, "
                "Ctrl+C hung pytest processes, then retry. "
                f"Detail: {exc}"
            ) from exc
    _log(f"wipe OK ({len(names)} tables)")


@contextmanager
def temporary_postgres_database(base_url: Optional[str] = None) -> Iterator[str]:
    """
    Create an isolated database, yield its URL, drop it on exit.

    Requires CREATEDB. Slow over Railway public proxy — use only with
    GC_TEST_POSTGRES_ISOLATE=1.
    """
    base = (base_url or postgres_test_url()).strip()
    if not base:
        raise RuntimeError("GC_TEST_POSTGRES_URL is required for isolated Postgres tests")

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg required for Postgres parity fixtures") from exc

    run_id = uuid.uuid4().hex[:12]
    dbname = f"gc_parity_{run_id}"
    admin_db = _database_name(base)
    admin_url = _replace_database(base, admin_db)
    test_url = _replace_database(base, dbname)

    _log(f"CREATE DATABASE {dbname} on {_safe_db_label(admin_url)} …")
    with psycopg.connect(admin_url, **_connect_kwargs()) as admin:
        admin.execute(f'CREATE DATABASE "{dbname}"')
    _log(f"database {dbname} created")

    try:
        yield test_url
    finally:
        close_pg_pool()
        _log(f"DROP DATABASE {dbname} …")
        with psycopg.connect(admin_url, **_connect_kwargs()) as admin:
            try:
                admin.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
            except Exception:
                try:
                    admin.execute(
                        """
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = %s AND pid <> pg_backend_pid();
                        """,
                        (dbname,),
                    )
                    admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
                except Exception:
                    pass


@pytest.fixture(scope="session")
def pg_parity_database_url() -> Iterator[str]:
    """
    Session Postgres target.

    Default: reuse GC_TEST_POSTGRES_URL (expect SCHEMA-001 already applied).
    Isolate: GC_TEST_POSTGRES_ISOLATE=1 → new DB + migrate (slow).
    """
    _log("session setup start")
    url = postgres_test_url()
    if not url:
        pytest.skip("Set GC_TEST_POSTGRES_URL for PostgreSQL parity tests")

    if postgres_isolate_enabled():
        with temporary_postgres_database(url) as isolated:
            close_pg_pool()
            run_migrate(
                env={
                    "GC_DB_BACKEND": "postgres",
                    "DATABASE_URL": isolated,
                    "GC_SKIP_MIGRATION_CHECK": "1",
                    "SECRET_KEY": "parity-pg-test-secret-key-xxxxxxxx",
                    "APP_ENV": "development",
                }
            )
            yield isolated
            close_pg_pool()
        return

    _log(
        f"reuse mode (fast): {_safe_db_label(url)} "
        f"— set GC_TEST_POSTGRES_ISOLATE=1 for CREATE DATABASE"
    )
    try:
        applied = _migration_count(url)
    except Exception as exc:
        pytest.fail(
            f"Cannot connect to Postgres within connect_timeout "
            f"({_safe_db_label(url)}): {exc}"
        )
    _log(f"migration_history={applied}")
    if applied <= 0:
        close_pg_pool()
        run_migrate(
            env={
                "GC_DB_BACKEND": "postgres",
                "DATABASE_URL": url,
                "GC_SKIP_MIGRATION_CHECK": "1",
                "SECRET_KEY": "parity-pg-test-secret-key-xxxxxxxx",
                "APP_ENV": "development",
            }
        )
    else:
        _log("schema already present — skip migrate")
    _log("session setup ready")
    yield url
    close_pg_pool()


@pytest.fixture()
def pg_parity_db(monkeypatch, pg_parity_database_url):
    """
    Function-scoped Postgres backend: wipe data, seed via init_db, expose URL.
    """
    close_pg_pool()
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", pg_parity_database_url)
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "parity-pg-test-secret-key-xxxxxxxx")
    monkeypatch.setenv("APP_ENV", "development")
    # Fail fast over Railway public proxy instead of hanging forever.
    monkeypatch.setenv("GC_PG_CONNECT_TIMEOUT", "20")
    monkeypatch.setenv("GC_PG_POOL_TIMEOUT", "30")
    monkeypatch.setenv("GC_PG_STATEMENT_TIMEOUT", "60s")
    monkeypatch.setenv("GC_PG_LOCK_TIMEOUT", "15s")
    monkeypatch.setenv("GC_PG_INIT_PROGRESS", "1")
    # Nested checkout during seed must not starve (default 10 is fine; enforce floor).
    monkeypatch.setenv("GC_PG_POOL_MAX", os.environ.get("GC_PG_POOL_MAX", "10") or "10")

    wipe_postgres_game_data_direct(pg_parity_database_url)

    from game.models import init_db

    _log("init_db …")
    init_db()
    _log("ready")
    yield pg_parity_database_url
    close_pg_pool()


@pytest.fixture()
def sqlite_parity_db(tmp_path, monkeypatch):
    """SQLite twin for the same Auth assertions (always available)."""
    db_file = tmp_path / "parity_auth.db"
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "parity-sqlite-test-secret-key-xxxx")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import game.db as dbmod
    import game.models as models

    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    run_migrate(
        env={
            "GC_DB_BACKEND": "sqlite",
            "GC_DB_PATH": str(db_file),
            "GC_SKIP_MIGRATION_CHECK": "1",
            "SECRET_KEY": "parity-sqlite-test-secret-key-xxxx",
        }
    )
    from game.models import init_db

    init_db()
    yield db_file
