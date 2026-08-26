from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_one(path: str, old: str, new: str, label: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


helper_block = '''\n\ndef _required_tables(sql_text: str) -> List[str]:\n    """Read an optional migration table-precondition directive.\n\n    Syntax: ``-- GC-REQUIRES-TABLES: table_a, table_b``.  This is used for\n    data-only migrations that legitimately have nothing to do on historical\n    snapshots where an optional module was never installed.\n    """\n    prefix = "-- GC-REQUIRES-TABLES:"\n    for line in strip_bom(sql_text).splitlines()[:20]:\n        stripped = line.strip()\n        if not stripped.upper().startswith(prefix):\n            continue\n        names: List[str] = []\n        for raw in stripped[len(prefix):].split(","):\n            name = raw.strip()\n            if not name:\n                continue\n            if not (name[0].isalpha() or name[0] == "_") or not all(ch.isalnum() or ch == "_" for ch in name):\n                raise ValueError(f"invalid GC-REQUIRES-TABLES identifier: {name!r}")\n            names.append(name)\n        return names\n    return []\n\n\ndef _table_exists(conn: Any, table_name: str) -> bool:\n    cur = conn.cursor()\n    if _backend() == "postgres":\n        cur.execute(\n            "SELECT 1 FROM information_schema.tables "\n            "WHERE table_schema = current_schema() AND table_name = ? LIMIT 1;",\n            (str(table_name),),\n        )\n    else:\n        cur.execute(\n            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1;",\n            (str(table_name),),\n        )\n    return cur.fetchone() is not None\n'''

replace_one(
    "migrate.py",
    "\n\n# ----------------------------------------\n# Apply Migration\n# ----------------------------------------\n",
    helper_block + "\n\n# ----------------------------------------\n# Apply Migration\n# ----------------------------------------\n",
    "migration precondition helpers",
)

replace_one(
    "migrate.py",
    '    print(f"  -> wende Migration an: {filename}")\n\n    if _backend() == "postgres":\n',
    '    print(f"  -> wende Migration an: {filename}")\n\n    required_tables = _required_tables(sql_text)\n    if required_tables:\n        missing_tables = [name for name in required_tables if not _table_exists(conn, name)]\n        if missing_tables:\n            print(\n                "     [skip not-applicable] required table(s) missing: "\n                + ", ".join(missing_tables)\n            )\n            mark_migration_applied(conn, filename)\n            return\n\n    if _backend() == "postgres":\n',
    "migration precondition application",
)

replace_one(
    "migrations/156_pe_mechanics_contract_reconciliation.sql",
    "-- GC-PE-MECH-01: remove silently inert/deferred PE mechanics from the active\n",
    "-- GC-REQUIRES-TABLES: pe_research_definitions, pe_policy_definitions, pe_discovery_definitions, pe_ascension_definitions\n-- GC-PE-MECH-01: remove silently inert/deferred PE mechanics from the active\n",
    "migration 156 precondition directive",
)
