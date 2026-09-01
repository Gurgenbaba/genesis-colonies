from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "game" / "admin_api.py"
PIRATES = ROOT / "game" / "pirates" / "accounts.py"
OPTIONS = ROOT / "game" / "options.py"
TEST = ROOT / "tests" / "test_gc_pg_170_admin_legacy_presence.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_count(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new)


# ------------------------------------------------------------------
# Admin player search/detail + inactive-storage maintenance reader.
# ------------------------------------------------------------------
text = ADMIN.read_text(encoding="utf-8")
search_start = text.index("def search_players(")
effects_start = text.index("def get_player_effects_debug", search_start)
prefix = text[:search_start]
player_block = text[search_start:effects_start]
suffix = text[effects_start:]

player_block = replace_count(
    player_block,
    "    conn = db()\n    try:\n",
    "    from game.presence_store import effective_last_seen_scalar_sql\n\n"
    "    conn = db()\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"p\")\n"
    "    try:\n",
    2,
    "admin search/detail presence setup",
)
player_block = replace_count(
    player_block,
    "                       p.last_seen, p.banned_until\n",
    "                       {last_seen_expr} AS last_seen, p.banned_until\n",
    3,
    "admin search last_seen projections",
)
player_block = replace_once(
    player_block,
    "                   p.last_seen, p.banned_until\n",
    "                   {last_seen_expr} AS last_seen, p.banned_until\n",
    "admin detail last_seen projection",
)
player_block = replace_count(
    player_block,
    'cur.execute(\n                """\n',
    'cur.execute(\n                f"""\n',
    3,
    "admin search f-sql",
)
player_block = replace_once(
    player_block,
    'cur.execute(\n            """\n            SELECT u.id, u.username, u.is_admin AS user_is_admin,\n',
    'cur.execute(\n            f"""\n            SELECT u.id, u.username, u.is_admin AS user_is_admin,\n',
    "admin detail f-sql",
)
text = prefix + player_block + suffix

boost_start = text.index("def apply_inactive_storage_boost(")
boost_end = text.index("def boost_inactive_storage", boost_start)
boost = text[boost_start:boost_end]
boost = replace_once(
    boost,
    "    from game.ranking import RANKING_INACTIVE_AFTER_SEC\n",
    "    from game.presence_store import effective_last_seen_scalar_sql\n"
    "    from game.ranking import RANKING_INACTIVE_AFTER_SEC\n",
    "inactive storage helper import",
)
boost = replace_once(
    boost,
    "    cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)\n",
    "    cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"p\")\n",
    "inactive storage presence expression",
)
boost = replace_once(
    boost,
    '''        cur.execute(\n            """\n            SELECT p.id AS player_id, pl.id AS planet_id\n            FROM players p\n            JOIN users u ON u.id = p.id\n            JOIN planets pl ON pl.player_id = p.id\n            WHERE COALESCE(p.last_seen, 0) > 0\n              AND COALESCE(p.last_seen, 0) <= ?\n              AND COALESCE(p.banned_until, 0) <= ?\n            ORDER BY p.id ASC, pl.id ASC;\n            """,\n''',
    '''        cur.execute(\n            f"""\n            SELECT p.id AS player_id, pl.id AS planet_id\n            FROM players p\n            JOIN users u ON u.id = p.id\n            JOIN planets pl ON pl.player_id = p.id\n            WHERE {last_seen_expr} > 0\n              AND {last_seen_expr} <= ?\n              AND COALESCE(p.banned_until, 0) <= ?\n            ORDER BY p.id ASC, pl.id ASC;\n            """,\n''',
    "inactive storage activity filter",
)
text = text[:boost_start] + boost + text[boost_end:]
ADMIN.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------
# Pirate Bot-Log roster: admin presentation should read canonical presence.
# ------------------------------------------------------------------
text = PIRATES.read_text(encoding="utf-8")
text = replace_once(
    text,
    "def list_bot_roster(*, conn) -> List[Dict[str, Any]]:\n"
    "    \"\"\"Admin Bot-Log roster: presence, buildings, score, outbound fleets.\"\"\"\n"
    "    out: List[Dict[str, Any]] = []\n",
    "def list_bot_roster(*, conn) -> List[Dict[str, Any]]:\n"
    "    \"\"\"Admin Bot-Log roster: presence, buildings, score, outbound fleets.\"\"\"\n"
    "    from ..presence_store import effective_last_seen_scalar_sql\n\n"
    "    last_seen_expr = effective_last_seen_scalar_sql(player_alias=\"p\")\n"
    "    out: List[Dict[str, Any]] = []\n",
    "pirate roster presence setup",
)
text = replace_once(
    text,
    '''        cur = conn.execute(\n            """\n            SELECT u.id AS player_id, u.username, p.name AS display_name,\n                   COALESCE(p.last_seen, 0) AS last_seen\n            FROM users u\n            LEFT JOIN players p ON p.id = u.id\n            WHERE u.username = ?\n            LIMIT 1;\n            """,\n''',
    '''        cur = conn.execute(\n            f"""\n            SELECT u.id AS player_id, u.username, p.name AS display_name,\n                   {last_seen_expr} AS last_seen\n            FROM users u\n            LEFT JOIN players p ON p.id = u.id\n            WHERE u.username = ?\n            LIMIT 1;\n            """,\n''',
    "pirate roster last_seen projection",
)
PIRATES.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------
# Options snapshot selected last_seen but never consumed it. Remove the dead
# legacy dependency instead of adding another presence lookup.
# ------------------------------------------------------------------
text = OPTIONS.read_text(encoding="utf-8")
text = replace_once(
    text,
    "            SELECT id, name, last_seen, vacation_mode_active,\n",
    "            SELECT id, name, vacation_mode_active,\n",
    "options dead last_seen projection",
)
OPTIONS.write_text(text, encoding="utf-8")


TEST.write_text(
    '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _read(path: str) -> str:\n    return (ROOT / path).read_text(encoding="utf-8")\n\n\ndef _block(text: str, start: str, end: str) -> str:\n    a = text.index(start)\n    b = text.index(end, a)\n    return text[a:b]\n\n\ndef test_admin_player_search_and_detail_use_effective_presence():\n    text = _read("game/admin_api.py")\n    block = _block(text, "def search_players(", "def get_player_effects_debug")\n    assert block.count("effective_last_seen_scalar_sql") >= 4\n    assert block.count("{last_seen_expr} AS last_seen") == 4\n    assert "p.last_seen" not in block\n\n\ndef test_inactive_storage_admin_reader_uses_effective_presence():\n    text = _read("game/admin_api.py")\n    block = _block(text, "def apply_inactive_storage_boost(", "def boost_inactive_storage")\n    assert "effective_last_seen_scalar_sql" in block\n    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in block\n    assert "WHERE {last_seen_expr} > 0" in block\n    assert "AND {last_seen_expr} <= ?" in block\n    assert "p.last_seen" not in block\n\n\ndef test_pirate_admin_roster_uses_effective_presence():\n    text = _read("game/pirates/accounts.py")\n    block = _block(text, "def list_bot_roster", "def bootstrap_faction_bots")\n    assert "effective_last_seen_scalar_sql" in block\n    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in block\n    assert "{last_seen_expr} AS last_seen" in block\n    assert "p.last_seen" not in block\n\n\ndef test_options_snapshot_drops_unused_legacy_last_seen_projection():\n    text = _read("game/options.py")\n    block = _block(text, "def get_options_snapshot", "def update_player_name")\n    assert "SELECT id, name, last_seen" not in block\n    assert "last_seen" not in block\n''',
    encoding="utf-8",
)

print("GC-PG-170 admin/legacy presence cleanup applied")
