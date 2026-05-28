"""Tests for commander name display helpers."""

import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, init_db
from game.player_display import (
    commander_display_name,
    commander_lookup_name,
    commander_name_candidates,
    resolve_player_by_name,
)


def test_commander_display_and_lookup_raw_only():
    assert commander_display_name("Alpha") == "Alpha"
    assert commander_display_name("Commander Alpha") == "Commander Alpha"
    assert commander_lookup_name("Alpha") == "Alpha"
    assert commander_lookup_name("") == "—"


def test_commander_name_candidates_exact_only():
    cands = commander_name_candidates("Bobby")
    assert cands == ["Bobby"]
    assert "Commander Bobby" not in cands


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "player_display_lookup.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    try:
        db().close()
    except Exception:
        pass
    return db_file


def _make_player(name: str) -> int:
    uname = f"u_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    pid = int(user["id"])
    conn = db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", (name, pid))
    conn.commit()
    conn.close()
    try:
        db().close()
    except Exception:
        pass
    return pid


def test_resolve_player_exact_stored_name_only(temp_db):
    pid = _make_player("Commander Zeta")
    conn = db()
    try:
        hit, err = resolve_player_by_name("Commander Zeta", conn)
        assert err is None
        assert hit and int(hit["id"]) == pid

        miss, err2 = resolve_player_by_name("Zeta", conn)
        assert miss is None
        assert err2 == "not_found"
    finally:
        conn.close()


def test_resolve_player_ambiguous(temp_db):
    _make_player("Alpha")
    _make_player("alpha")
    conn = db()
    try:
        hit, err = resolve_player_by_name("Alpha", conn)
        assert hit is None
        assert err == "ambiguous"
    finally:
        conn.close()
