"""One-shot GC-PG-QUEUE-LOCK-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    if new in src:
        print(f"{label}: already applied")
        return
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, got {count}")
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: applied")


def main() -> int:
    db_py = ROOT / "game" / "db.py"
    qe_py = ROOT / "game" / "queue_engine.py"
    tick_py = ROOT / "game" / "tick_runner.py"

    replace_once(
        db_py,
        '''def lock_planet_for_update(conn: DbConn, planet_id: int) -> None:\n    """Postgres: row-level lock before queue/spend. SQLite: no-op (IMMEDIATE covers writers)."""\n    if get_db_backend() != "postgres":\n        return\n    conn.execute("SELECT id FROM planets WHERE id = ? FOR UPDATE;", (int(planet_id),))\n\n\ndef lock_player_for_update''',
        '''def lock_planet_for_update(conn: DbConn, planet_id: int) -> None:\n    """Postgres: row-level lock before queue/spend. SQLite: no-op (IMMEDIATE covers writers)."""\n    if get_db_backend() != "postgres":\n        return\n    conn.execute("SELECT id FROM planets WHERE id = ? FOR UPDATE;", (int(planet_id),))\n\n\ndef try_lock_planet_for_update(conn: DbConn, planet_id: int) -> bool:\n    """Claim a planet without waiting. Used by background queue workers only.\n\n    PostgreSQL returns ``False`` when another transaction already owns the\n    planet row lock (``FOR UPDATE SKIP LOCKED``). SQLite already serializes\n    writers with ``BEGIN IMMEDIATE`` and therefore always returns ``True``.\n    """\n    if get_db_backend() != "postgres":\n        return True\n    row = conn.execute(\n        "SELECT id FROM planets WHERE id = ? FOR UPDATE SKIP LOCKED;",\n        (int(planet_id),),\n    ).fetchone()\n    return row is not None\n\n\ndef lock_player_for_update''',
        "db try-lock helper",
    )

    replace_once(
        qe_py,
        '''        "derived_sync_count": 0,\n    }''',
        '''        "derived_sync_count": 0,\n        "skipped_locked_planets": [],\n    }''',
        "queue result locked skips",
    )
    replace_once(
        qe_py,
        '''    include_fleet: bool = True,\n    include_relocations: bool = True,\n) -> Dict[str, Any]:''',
        '''    include_fleet: bool = True,\n    include_relocations: bool = True,\n    skip_locked_planets: bool = False,\n) -> Dict[str, Any]:''',
        "queue finish signature",
    )
    replace_once(
        qe_py,
        '''        for pid_planet, pid_player in planet_targets:\n            if vacation_freezes_account_progress(pid_player, conn=conn):''',
        '''        for pid_planet, pid_player in planet_targets:\n            # GC-PG-QUEUE-LOCK-001: background workers must never wait behind\n            # an active request that already owns this planet. Claim the planet\n            # first and let the next heartbeat retry a contended scope.\n            if skip_locked_planets:\n                from .db import try_lock_planet_for_update\n\n                if not try_lock_planet_for_update(conn, pid_planet):\n                    result["skipped_locked_planets"].append(int(pid_planet))\n                    continue\n            if vacation_freezes_account_progress(pid_player, conn=conn):''',
        "queue planet claim",
    )

    replace_once(
        tick_py,
        '''        "derived_sync_count": 0,\n    }''',
        '''        "derived_sync_count": 0,\n        "skipped_locked_planets": [],\n    }''',
        "tick result locked skips",
    )
    replace_once(
        tick_py,
        '''    target["duration_ms"] = int(target.get("duration_ms", 0)) + int(batch.get("duration_ms", 0))\n    target["derived_sync_count"] = int(target.get("derived_sync_count", 0)) + int(\n        batch.get("derived_sync_count", 0)\n    )''',
        '''    target["duration_ms"] = int(target.get("duration_ms", 0)) + int(batch.get("duration_ms", 0))\n    target["derived_sync_count"] = int(target.get("derived_sync_count", 0)) + int(\n        batch.get("derived_sync_count", 0)\n    )\n    locked = set(int(pid) for pid in (target.get("skipped_locked_planets") or []))\n    locked.update(int(pid) for pid in (batch.get("skipped_locked_planets") or []))\n    target["skipped_locked_planets"] = sorted(locked)''',
        "tick merge locked skips",
    )
    replace_once(
        tick_py,
        '''                    include_account_research=False,\n                    include_fleet=False,\n                    include_relocations=False,\n                )''',
        '''                    include_account_research=False,\n                    include_fleet=False,\n                    include_relocations=False,\n                    skip_locked_planets=True,\n                )''',
        "worker skip locked flag",
    )
    replace_once(
        tick_py,
        '''        "queue tick done source=%s finished=%s players=%s batches=%s duration_ms=%s errors=%s",\n        source,\n        result.get("finished"),\n        len(result.get("affected_players") or []),\n        result.get("batches"),\n        result.get("duration_ms"),\n        len(result.get("errors") or []),\n    )''',
        '''        "queue tick done source=%s finished=%s players=%s batches=%s duration_ms=%s errors=%s locked_skips=%s",\n        source,\n        result.get("finished"),\n        len(result.get("affected_players") or []),\n        result.get("batches"),\n        result.get("duration_ms"),\n        len(result.get("errors") or []),\n        len(result.get("skipped_locked_planets") or []),\n    )''',
        "tick locked skip log",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
