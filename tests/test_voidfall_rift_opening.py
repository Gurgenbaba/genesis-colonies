"""VOIDFALL 2026 Release 1 — additive, idempotent live event migration."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = 1793404800
END = 1794095999
SLUG = "voidfall-rift-opening-2026"


def _migrate(conn):
    conn.executescript((ROOT / "migrations/128_server_events.sql").read_text(encoding="utf-8"))
    conn.executescript((ROOT / "migrations/186_voidfall_rift_opening.sql").read_text(encoding="utf-8"))


def test_voidfall_is_time_boxed_and_only_uses_existing_gameplay_effects():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    row = conn.execute("SELECT * FROM server_events WHERE slug = ?", (SLUG,)).fetchone()
    assert row is not None
    assert row["enabled"] == 1
    assert (row["starts_at"], row["ends_at"]) == (START, END)
    assert datetime.fromtimestamp(START, tz=timezone.utc).isoformat() == "2026-10-31T00:00:00+00:00"
    assert datetime.fromtimestamp(END, tz=timezone.utc).isoformat() == "2026-11-07T23:59:59+00:00"
    assert json.loads(row["effects_json"]) == [
        {"kind": "expedition_hold_mult", "mult": 0.85},
        {"kind": "research_time_speed", "mult": 1.10},
    ]
    assert row["created_by"] is None
    conn.close()


def test_voidfall_migration_is_idempotent_and_preserves_admin_changes():
    conn = sqlite3.connect(":memory:")
    _migrate(conn)
    conn.execute(
        "UPDATE server_events SET enabled = 0, title = ? WHERE slug = ?",
        ("Operator paused event", SLUG),
    )
    conn.commit()
    _migrate(conn)
    count, enabled, title = conn.execute(
        "SELECT COUNT(*), MAX(enabled), MAX(title) FROM server_events WHERE slug = ?",
        (SLUG,),
    ).fetchone()
    assert (count, enabled, title) == (1, 0, "Operator paused event")
    conn.close()
