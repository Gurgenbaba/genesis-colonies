"""
Application bootstrap: config validation, DB init, migration guard.
"""

from __future__ import annotations

import os
import sys
import time

from game.config import init_config, is_production, validate_config
from game.migrations_util import migrations_are_current


def _init_db_with_retry(*, max_attempts: int = 8) -> None:
    import sqlite3

    from game.db import get_db_backend, _is_sqlite_lock_error, format_sqlite_lock_startup_help
    from game.models import init_db

    if get_db_backend() == "postgres":
        init_db()
        return

    last_err: BaseException | None = None
    for attempt in range(max(1, int(max_attempts))):
        try:
            init_db()
            return
        except sqlite3.OperationalError as exc:
            last_err = exc
            if not _is_sqlite_lock_error(exc) or attempt + 1 >= max_attempts:
                print(format_sqlite_lock_startup_help(), file=sys.stderr)
                raise
            time.sleep(min(2.0, 0.25 * (2**attempt)))
    if last_err is not None:
        print(format_sqlite_lock_startup_help(), file=sys.stderr)
        raise last_err


def bootstrap_application(*, skip_migration_check: bool = False) -> None:
    init_config()

    if not is_production():
        from game.db import database_url_is_set, get_db_backend, resolve_db_path

        if get_db_backend() == "postgres":
            print(
                f"[GC bootstrap] Database backend: postgres "
                f"(url_set={database_url_is_set()})",
                file=sys.stderr,
            )
        else:
            try:
                db_display = resolve_db_path().resolve()
            except OSError:
                db_display = resolve_db_path()
            print(f"[GC bootstrap] SQLite database: {db_display}", file=sys.stderr)

    errors = validate_config(strict=is_production())
    if errors:
        for err in errors:
            print(f"[GC bootstrap] ERROR: {err}", file=sys.stderr)
        if is_production():
            raise SystemExit(1)

    from game.models import purge_stale_idempotency_global
    from game.schema_validation import validate_core_schema

    _init_db_with_retry()
    purge_stale_idempotency_global()

    try:
        from game.options import ensure_account_options_schema
        from game.account_email import ensure_user_email_auth_schema

        ensure_account_options_schema()
        ensure_user_email_auth_schema()
    except Exception as exc:
        print(f"[GC bootstrap] WARNING: account schema: {exc}", file=sys.stderr)

    try:
        from game.planet_evolution.bootstrap import backfill_all_planets_evolution
        from game.planet_evolution.definitions import reload_definitions

        reload_definitions()
        backfill_all_planets_evolution()
    except Exception as exc:
        print(f"[GC bootstrap] WARNING: planet evolution backfill: {exc}", file=sys.stderr)

    try:
        from game.playercard import backfill_legacy_avatar_blobs

        n = backfill_legacy_avatar_blobs()
        if n:
            print(f"[GC bootstrap] avatar backfill: {n} profile(s) normalized", file=sys.stderr)
    except Exception as exc:
        print(f"[GC bootstrap] WARNING: avatar backfill: {exc}", file=sys.stderr)

    validate_schema = os.environ.get(
        "GC_VALIDATE_SCHEMA",
        "1" if not is_production() else "0",
    ).strip().lower() in ("1", "true", "yes", "on")
    if validate_schema:
        try:
            validate_core_schema(strict=is_production())
        except RuntimeError:
            if is_production():
                raise
            print(
                "[GC bootstrap] WARNING: core schema validation failed (see logs).",
                file=sys.stderr,
            )

    if skip_migration_check:
        return

    current, pending, err = migrations_are_current()
    if err:
        print(f"[GC bootstrap] ERROR: migration check failed: {err}", file=sys.stderr)
        if is_production():
            raise SystemExit(1)
        return

    if not current:
        msg = (
            "Pending database migrations: "
            + ", ".join(pending)
            + " — run: python migrate.py"
        )
        print(f"[GC bootstrap] ERROR: {msg}", file=sys.stderr)
        if is_production():
            raise SystemExit(1)
        print("[GC bootstrap] WARNING: continuing in development with pending migrations.", file=sys.stderr)
