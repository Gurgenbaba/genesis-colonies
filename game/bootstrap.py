"""
Application bootstrap: config validation, DB init, migration guard.
"""

from __future__ import annotations

import os
import sys

from game.config import init_config, is_production, validate_config
from game.migrations_util import migrations_are_current


def bootstrap_application(*, skip_migration_check: bool = False) -> None:
    init_config()

    errors = validate_config(strict=is_production())
    if errors:
        for err in errors:
            print(f"[GC bootstrap] ERROR: {err}", file=sys.stderr)
        if is_production():
            raise SystemExit(1)

    from game.models import init_db, purge_stale_idempotency_global
    from game.schema_validation import validate_core_schema

    init_db()
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
