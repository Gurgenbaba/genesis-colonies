from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "game/db.py",
        '''def index_exists(conn: DbConn, index_name: str) -> bool:\n''',
        '''def tables_exist(conn: DbConn, table_names) -> bool:\n    """Check multiple table names with one backend-safe schema query.\n\n    This intentionally does not cache across requests or processes: callers keep\n    current schema visibility while hot paths avoid one round-trip per table.\n    """\n    names = tuple(\n        dict.fromkeys(\n            str(name).strip()\n            for name in (table_names or ())\n            if str(name or "").strip()\n        )\n    )\n    if not names:\n        return True\n\n    placeholders = ",".join("?" for _ in names)\n    if get_db_backend() == "postgres":\n        sql = f"""\n            SELECT table_name AS name\n            FROM information_schema.tables\n            WHERE table_schema = 'public'\n              AND table_name IN ({placeholders});\n        """\n    else:\n        sql = f"""\n            SELECT name\n            FROM sqlite_master\n            WHERE type = 'table'\n              AND name IN ({placeholders});\n        """\n\n    rows = conn.execute(sql, names).fetchall()\n    found = {str(row["name"]) for row in rows}\n    return set(names).issubset(found)\n\n\ndef index_exists(conn: DbConn, index_name: str) -> bool:\n''',
        "bulk table helper",
    )

    replace_once(
        "game/alliance.py",
        '''from .db import begin_write_transaction, column_exists, commit, db, rollback, table_exists\n''',
        '''from .db import (\n    begin_write_transaction,\n    column_exists,\n    commit,\n    db,\n    rollback,\n    table_exists,\n    tables_exist,\n)\n''',
        "alliance db imports",
    )
    replace_once(
        "game/alliance.py",
        '''    return all(table_exists(conn, t) for t in required)\n''',
        '''    return tables_exist(conn, required)\n''',
        "alliance bulk schema guard",
    )

    replace_once(
        "game/auction_house.py",
        '''from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback\n''',
        '''from .db import (\n    begin_write_transaction,\n    commit,\n    db,\n    lock_planet_for_update,\n    rollback,\n    tables_exist,\n)\n''',
        "auction db imports",
    )
    replace_once(
        "game/auction_house.py",
        '''def auction_schema_ready(conn) -> bool:\n    return (\n        table_exists(conn, "lootbox_inventory")\n        and table_exists(conn, "auction_house_listings")\n        and table_exists(conn, "auction_house_bids")\n    )\n''',
        '''def auction_schema_ready(conn) -> bool:\n    return tables_exist(\n        conn,\n        ("lootbox_inventory", "auction_house_listings", "auction_house_bids"),\n    )\n''',
        "auction bulk schema guard",
    )

    replace_once(
        "game/case_battles.py",
        '''from game.db import table_exists\n''',
        '''from game.db import table_exists, tables_exist\n''',
        "case battles db imports",
    )
    replace_once(
        "game/case_battles.py",
        '''def case_battles_schema_ready(conn) -> bool:\n    return bool(\n        table_exists(conn, "case_battles")\n        and table_exists(conn, "case_battle_players")\n        and table_exists(conn, "case_battle_rolls")\n        and table_exists(conn, "case_battle_settlements")\n    )\n''',
        '''def case_battles_schema_ready(conn) -> bool:\n    return tables_exist(\n        conn,\n        (\n            "case_battles",\n            "case_battle_players",\n            "case_battle_rolls",\n            "case_battle_settlements",\n        ),\n    )\n''',
        "case battles bulk schema guard",
    )

    replace_once(
        ".github/workflows/ci.yml",
        '''            tests/test_gc_perf_fleet_idle_001.py tests/test_gc_perf_state_006.py tests/test_gc_perf_state_007.py \\\n''',
        '''            tests/test_gc_perf_fleet_idle_001.py tests/test_gc_perf_state_006.py tests/test_gc_perf_state_007.py tests/test_gc_perf_state_008.py \\\n''',
        "state 008 smoke gate",
    )


if __name__ == "__main__":
    main()
