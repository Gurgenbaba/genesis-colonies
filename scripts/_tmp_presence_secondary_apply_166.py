from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "game/pirates/accounts.py",
    '''def _touch_bot_presence(conn, player_id: int) -> None:\n    """Keep AI commanders out of inactive ranking/galaxy styling."""\n    now = time.time()\n    try:\n        conn.execute(\n            "UPDATE players SET last_seen = ? WHERE id = ?;",\n            (now, int(player_id)),\n        )\n    except Exception:\n        logger.exception("pirate bot last_seen touch failed player=%s", player_id)\n''',
    '''def _touch_bot_presence(conn, player_id: int) -> None:\n    """Keep AI commanders active via the backend-appropriate presence owner."""\n    from ..presence_store import touch_presence\n\n    now = int(time.time())\n    try:\n        touch_presence(conn, int(player_id), now=now)\n    except Exception:\n        logger.exception("pirate bot presence touch failed player=%s", player_id)\n''',
    "pirate writer",
)

replace_once(
    "game/shop_promos.py",
    '''def _buyer_last_seen(player_id: int, *, conn) -> float:\n    if not column_exists(conn, "players", "last_seen"):\n        return 0.0\n    row = conn.execute(\n        "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ? LIMIT 1;",\n        (int(player_id),),\n    ).fetchone()\n    return float(row["last_seen"] or 0) if row else 0.0\n''',
    '''def _buyer_last_seen(player_id: int, *, conn) -> float:\n    if not column_exists(conn, "players", "last_seen"):\n        return 0.0\n    from .presence_store import get_effective_last_seen\n\n    return float(get_effective_last_seen(conn, int(player_id)))\n''',
    "shop buyer last seen",
)

replace_once(
    "game/shop_promos.py",
    '''        if column_exists(conn, "players", "last_seen"):\n            row7 = conn.execute(\n                """\n                SELECT COUNT(*) AS c\n                FROM player_referrals r\n                JOIN players p ON p.id = r.referred_player_id\n                WHERE r.referrer_player_id = ?\n                  AND COALESCE(p.last_seen, 0) >= ?;\n                """,\n                (referrer_id, ts - 7 * 24 * 3600),\n            ).fetchone()\n            active_7d = int(row7["c"] or 0) if row7 else 0\n            row30 = conn.execute(\n                """\n                SELECT COUNT(*) AS c\n                FROM player_referrals r\n                JOIN players p ON p.id = r.referred_player_id\n                WHERE r.referrer_player_id = ?\n                  AND COALESCE(p.last_seen, 0) >= ?;\n                """,\n                (referrer_id, ts - 30 * 24 * 3600),\n            ).fetchone()\n            active_30d = int(row30["c"] or 0) if row30 else 0\n''',
    '''        if column_exists(conn, "players", "last_seen"):\n            from .presence_store import effective_last_seen_scalar_sql\n\n            last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")\n            row7 = conn.execute(\n                f"""\n                SELECT COUNT(*) AS c\n                FROM player_referrals r\n                JOIN players p ON p.id = r.referred_player_id\n                WHERE r.referrer_player_id = ?\n                  AND {last_seen_expr} >= ?;\n                """,\n                (referrer_id, ts - 7 * 24 * 3600),\n            ).fetchone()\n            active_7d = int(row7["c"] or 0) if row7 else 0\n            row30 = conn.execute(\n                f"""\n                SELECT COUNT(*) AS c\n                FROM player_referrals r\n                JOIN players p ON p.id = r.referred_player_id\n                WHERE r.referrer_player_id = ?\n                  AND {last_seen_expr} >= ?;\n                """,\n                (referrer_id, ts - 30 * 24 * 3600),\n            ).fetchone()\n            active_30d = int(row30["c"] or 0) if row30 else 0\n''',
    "shop creator active counts",
)

replace_once(
    "game/alliance.py",
    '''        rows = []\n        for r in cur.fetchall():\n            d = dict(r)\n''',
    '''        raw_rows = [dict(r) for r in cur.fetchall()]\n        from .presence_store import get_effective_last_seen_by_ids\n\n        effective_seen = get_effective_last_seen_by_ids(\n            conn, [int(r.get("player_id") or 0) for r in raw_rows]\n        )\n        rows = []\n        for d in raw_rows:\n            d["last_seen"] = effective_seen.get(int(d.get("player_id") or 0), 0)\n''',
    "alliance effective presence",
)

Path("tests/test_gc_pg_166_presence_secondary.py").write_text(
    '''from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _read(path):\n    return (ROOT / path).read_text(encoding="utf-8")\n\n\ndef test_pirate_presence_uses_canonical_store():\n    text = _read("game/pirates/accounts.py")\n    block = text[text.index("def _touch_bot_presence"):text.index("def _ensure_public_ai_card")]\n    assert "touch_presence(" in block\n    assert "UPDATE players SET last_seen" not in block\n\n\ndef test_creator_activity_uses_effective_presence():\n    text = _read("game/shop_promos.py")\n    assert "get_effective_last_seen(conn" in text\n    assert "effective_last_seen_scalar_sql" in text\n\n\ndef test_alliance_member_activity_is_overridden_from_effective_presence():\n    text = _read("game/alliance.py")\n    start = text.index("def get_alliance_members(")\n    end = text.index("def get_alliance_member(", start + 1)\n    block = text[start:end]\n    assert "get_effective_last_seen_by_ids" in block\n    assert 'd["last_seen"] = effective_seen.get' in block\n''',
    encoding="utf-8",
)
