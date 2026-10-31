"""Activate VOIDFALL Release 1 on real PostgreSQL production boot only.

Run by docker-entrypoint.sh *after* migrations. Unlike an SQL migration, this
never seeds an active campaign into CI / test fixture databases.
Existing server_events is the sole owner of mechanics, visibility, and expiry.
"""

from __future__ import annotations

import os
import time

SLUG = "voidfall-rift-opening-2026"
TITLE = "VOIDFALL: Rift Opening"
START_AT = 1793404800  # 2026-10-31 00:00:00 UTC
END_AT = 1794095999    # 2026-11-07 23:59:59 UTC
EFFECTS = [
    {"kind": "expedition_hold_mult", "mult": 0.85},
    {"kind": "research_time_speed", "mult": 1.10},
]


def runtime_allowed(app_env: str, db_backend: str) -> bool:
    """Never seed a campaign in CI, tests, SQLite or local development."""
    return str(app_env).strip().lower() == "production" and str(db_backend).strip().lower() in (
        "postgres",
        "postgresql",
    )


def activate(now: float | None = None) -> str:
    from game.config import init_config
    from game.db import db, get_db_backend

    init_config()
    if not runtime_allowed(os.environ.get("APP_ENV", ""), get_db_backend()):
        return "skipped: not PostgreSQL production"

    ts = float(time.time() if now is None else now)
    if ts > END_AT:
        return "skipped: campaign expired"
    if ts < START_AT:
        return "skipped: campaign not yet started"

    from game.server_events import create_event, schema_ready

    conn = db()
    try:
        if not schema_ready(conn):
            raise RuntimeError("VOIDFALL requires existing server_events schema")
        existing = conn.execute(
            "SELECT id, enabled FROM server_events WHERE slug = ? LIMIT 1;",
            (SLUG,),
        ).fetchone()
        if existing is not None:
            # Respect admin pause / edits; never overwrite existing effects.
            return "existing: operator state preserved"

        event, error = create_event(
            slug=SLUG,
            title=TITLE,
            starts_at=START_AT,
            ends_at=END_AT,
            effects=EFFECTS,
            enabled=True,
            created_by=None,
            conn=conn,
        )
        if event is None:
            # A concurrent process may have inserted it first.
            existing = conn.execute(
                "SELECT id FROM server_events WHERE slug = ? LIMIT 1;",
                (SLUG,),
            ).fetchone()
            if existing is not None:
                return "existing: inserted by another process"
            raise RuntimeError(f"VOIDFALL seed failed: {error}")
        return "created"
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"[GC VOIDFALL] {activate()}", flush=True)
