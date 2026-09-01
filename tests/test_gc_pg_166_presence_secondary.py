from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_pirate_presence_uses_canonical_store():
    text = _read("game/pirates/accounts.py")
    block = text[text.index("def _touch_bot_presence"):text.index("def _ensure_public_ai_card")]
    assert "touch_presence(" in block
    assert "UPDATE players SET last_seen" not in block


def test_creator_activity_uses_effective_presence():
    text = _read("game/shop_promos.py")
    assert "get_effective_last_seen(conn" in text
    assert "effective_last_seen_scalar_sql" in text


def test_alliance_member_activity_is_overridden_from_effective_presence():
    text = _read("game/alliance.py")
    start = text.index("def get_alliance_members(")
    end = text.index("def get_alliance_members_public(", start + 1)
    block = text[start:end]
    assert "get_effective_last_seen_by_ids" in block
    assert 'd["last_seen"] = effective_seen.get' in block
    assert "p.last_seen" not in block
