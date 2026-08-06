"""GC-880 Universe Search — player / planet / alliance discovery."""

from __future__ import annotations

import time
import uuid

import pytest

from game.alliance import create_alliance, get_alliance_members, join_alliance_by_tag
from game.db import db
from game.galaxy import assign_free_coordinates, format_coordinates
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db
from game.universe_search import MIN_QUERY_LEN, search_universe


@pytest.fixture
def search_db(tmp_path, monkeypatch):
    db_path = tmp_path / "universe_search_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(*, name: str | None = None) -> int:
    ok, err, user = create_user(f"srch_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=name or f"P{uid}")
    display = name or f"P{uid}"
    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", (display, uid))
        conn.commit()
    finally:
        conn.close()
    return uid


def _add_colony(uid: int, name: str) -> dict:
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        g, s, p = assign_free_coordinates(conn)
        cur = conn.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, last_update,
                galaxy, system, position
            ) VALUES (?, ?, 0, 0, 0, 0, ?, ?, ?);
            """,
            (uid, name, g, s, p),
        )
        planet_id = int(cur.lastrowid)
        conn.commit()
        return {
            "id": planet_id,
            "name": name,
            "galaxy": g,
            "system": s,
            "position": p,
            "coords": format_coordinates(g, s, p),
        }
    finally:
        conn.close()


def test_player_search_returns_homeworld_only(search_db):
    uid = _player(name="HansCommander")
    colony = _add_colony(uid, "OutpostAlpha")
    hw = get_homeworld(uid)
    assert hw is not None

    payload = search_universe("Hans", "player")
    assert payload["ok"] is True
    assert payload["error"] is None
    assert len(payload["results"]) == 1
    row = payload["results"][0]
    assert row["type"] == "player"
    assert row["player_id"] == uid
    assert row["name"] == "HansCommander"
    assert row["homeworld"] is not None
    assert row["homeworld"]["coords"] == format_coordinates(
        int(hw["galaxy"]), int(hw["system"]), int(hw["position"])
    )
    # Must not leak colony coords on player search.
    assert colony["coords"] != row["homeworld"]["coords"]
    dumped = str(payload)
    assert "OutpostAlpha" not in dumped
    assert colony["coords"] not in dumped


def test_planet_search_finds_colony_coords(search_db):
    uid = _player(name="ColonyOwner")
    colony = _add_colony(uid, "OutpostAlpha")

    payload = search_universe("Outpost", "planet")
    assert payload["ok"] is True
    assert len(payload["results"]) >= 1
    hit = next(r for r in payload["results"] if r["planet_id"] == colony["id"])
    assert hit["type"] == "planet"
    assert hit["planet_name"] == "OutpostAlpha"
    assert hit["owner_id"] == uid
    assert hit["coords"]["coords"] == colony["coords"]
    assert hit["is_homeworld"] is False


def test_alliance_search_lists_members_with_homeworld(search_db):
    leader = _player(name="AllyLeader")
    member = _player(name="AllyMember")
    alliance = create_alliance("SRCH", "Search Alliance", leader)
    join_alliance_by_tag(member, "SRCH")

    members = get_alliance_members(int(alliance["id"]))
    assert len(members) == 2
    for m in members:
        assert m.get("homeworld") is not None
        assert m["homeworld"]["coords"].startswith("[")

    payload = search_universe("SRCH", "alliance")
    assert payload["ok"] is True
    assert len(payload["results"]) == 1
    row = payload["results"][0]
    assert row["tag"] == "SRCH"
    assert row["member_count"] == 2
    assert len(row["members"]) == 2
    names = {m["player_name"] for m in row["members"]}
    assert names == {"AllyLeader", "AllyMember"}
    for m in row["members"]:
        assert m["homeworld"] is not None
        assert "coords" in m["homeworld"]


def test_coord_query_returns_jump_meta(search_db):
    payload = search_universe("2:15:8", "player")
    assert payload["ok"] is True
    assert payload["results"] == []
    jump = payload["meta"]["coord_jump"]
    assert jump is not None
    assert jump["galaxy"] == 2
    assert jump["system"] == 15
    assert jump["position"] == 8
    assert jump["coords"] == "[2:15:8]"
    assert "/galaxy" in jump["href"]


def test_single_char_prefix_search(search_db):
    assert MIN_QUERY_LEN == 1
    uid = _player(name="HansSolo")
    payload = search_universe("H", "player")
    assert payload["ok"] is True
    assert payload["error"] is None
    assert any(r["player_id"] == uid for r in payload["results"])


def test_empty_query_ok_no_results(search_db):
    payload = search_universe("", "player")
    assert payload["ok"] is True
    assert payload["results"] == []


def test_banned_player_excluded(search_db):
    uid = _player(name="BannedHans")
    conn = db()
    try:
        conn.execute(
            "UPDATE players SET banned_until = ? WHERE id = ?;",
            (int(time.time()) + 86_400, uid),
        )
        conn.commit()
    finally:
        conn.close()

    payload = search_universe("Banned", "player")
    assert payload["ok"] is True
    assert all(r["player_id"] != uid for r in payload["results"])


def test_invalid_search_type(search_db):
    payload = search_universe("Hans", "fleet")
    assert payload["ok"] is False
    assert payload["error"] == "invalid_search_type"
