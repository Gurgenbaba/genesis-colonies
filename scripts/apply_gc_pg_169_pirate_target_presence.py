from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "game" / "pirates" / "brain.py"
TEST = ROOT / "tests" / "test_gc_pg_169_pirate_target_presence.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


text = BRAIN.read_text(encoding="utf-8")

text = replace_once(
    text,
    "def _candidate_planets(conn, galaxy: int, *, limit: int = 40) -> List[Dict[str, Any]]:\n    from ..db import column_exists\n\n",
    "def _candidate_planets(conn, galaxy: int, *, limit: int = 40) -> List[Dict[str, Any]]:\n"
    "    from ..db import column_exists\n"
    "    from ..presence_store import effective_last_seen_scalar_sql\n\n",
    "candidate helper import",
)
text = replace_once(
    text,
    "    vac_col = (\n        \"COALESCE(pl.vacation_mode_active, 0)\"\n        if column_exists(conn, \"players\", \"vacation_mode_active\")\n        else \"0\"\n    )\n    cur = conn.execute(\n",
    "    vac_col = (\n        \"COALESCE(pl.vacation_mode_active, 0)\"\n        if column_exists(conn, \"players\", \"vacation_mode_active\")\n        else \"0\"\n    )\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"pl\")\n"
    "    cur = conn.execute(\n",
    "candidate effective expression",
)
text = replace_once(
    text,
    "               pl.name AS owner_name,\n               COALESCE(pl.last_seen, 0) AS last_seen,\n               {vac_col} AS vacation_mode_active\n",
    "               pl.name AS owner_name,\n               {last_seen_expr} AS last_seen,\n               {vac_col} AS vacation_mode_active\n",
    "candidate select",
)

old_spy = '''    last_seen = 0.0\n    if target_player_id:\n        cur = conn.execute(\n            "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ?;",\n            (target_player_id,),\n        )\n        last_seen = float((cur.fetchone() or {"last_seen": 0})["last_seen"] or 0)\n'''
new_spy = '''    last_seen = 0.0\n    if target_player_id:\n        from ..presence_store import get_effective_last_seen\n\n        last_seen = float(get_effective_last_seen(conn, target_player_id))\n'''
text = replace_once(text, old_spy, new_spy, "spy intel presence read")

BRAIN.write_text(text, encoding="utf-8")

TEST.write_text(
    '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _function_block(text: str, start: str, end: str) -> str:\n    a = text.index(start)\n    b = text.index(end, a)\n    return text[a:b]\n\n\ndef test_pirate_target_candidates_read_effective_presence():\n    text = (ROOT / "game" / "pirates" / "brain.py").read_text(encoding="utf-8")\n    block = _function_block(text, "def _candidate_planets", "def _planet_military")\n\n    assert "effective_last_seen_scalar_sql" in block\n    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="pl")' in block\n    assert "{last_seen_expr} AS last_seen" in block\n    assert "pl.last_seen" not in block\n\n\ndef test_pirate_spy_intel_opportunity_reads_effective_presence():\n    text = (ROOT / "game" / "pirates" / "brain.py").read_text(encoding="utf-8")\n    block = _function_block(text, "def ingest_spy_report_for_intel", "def _pick_best_target")\n\n    assert "get_effective_last_seen" in block\n    assert "get_effective_last_seen(conn, target_player_id)" in block\n    assert "SELECT COALESCE(last_seen, 0) AS last_seen FROM players" not in block\n''',
    encoding="utf-8",
)

print("GC-PG-169 pirate target activity reader cutover applied")
