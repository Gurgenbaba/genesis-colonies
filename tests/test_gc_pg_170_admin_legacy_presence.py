from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _block(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a)
    return text[a:b]


def test_admin_player_search_and_detail_use_effective_presence():
    text = _read("game/admin_api.py")
    block = _block(text, "def search_players(", "def get_player_effects_debug")
    assert block.count("effective_last_seen_scalar_sql") >= 4
    assert block.count("{last_seen_expr} AS last_seen") == 4
    assert "p.last_seen" not in block


def test_inactive_storage_admin_reader_uses_effective_presence():
    text = _read("game/admin_api.py")
    block = _block(text, "def apply_inactive_storage_boost(", "def boost_inactive_storage")
    assert "effective_last_seen_scalar_sql" in block
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in block
    assert "WHERE {last_seen_expr} > 0" in block
    assert "AND {last_seen_expr} <= ?" in block
    assert "p.last_seen" not in block


def test_pirate_admin_roster_uses_effective_presence():
    text = _read("game/pirates/accounts.py")
    block = text[text.index("def list_bot_roster") :]
    assert "effective_last_seen_scalar_sql" in block
    assert 'last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")' in block
    assert "{last_seen_expr} AS last_seen" in block
    assert "p.last_seen" not in block


def test_options_snapshot_drops_unused_legacy_last_seen_projection():
    text = _read("game/options.py")
    block = _block(text, "def get_options_snapshot", "def update_player_name")
    assert "SELECT id, name, last_seen" not in block
    assert "last_seen" not in block
