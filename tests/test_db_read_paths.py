"""
Read-path vs write-path tests (SQLite locking architecture).

Run: python -m pytest tests/test_db_read_paths.py -v
"""

from __future__ import annotations

import re
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, init_db, load_player
from game.playercard import build_public_card
from game.ranking import build_ranking_api_payload, get_sorted_ranking_entries

ROOT_WRITE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b",
    re.IGNORECASE,
)


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "read_paths.db"
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


def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    try:
        db().close()
    except Exception:
        pass
    return int(user["id"])


def _connection_with_write_trace():
    conn = db()
    writes: list[str] = []

    def trace(stmt: str) -> None:
        if ROOT_WRITE.match(stmt):
            writes.append(stmt.strip().split()[0].upper())

    conn.set_trace_callback(trace)
    return conn, writes


def test_ranking_list_is_read_only(temp_db):
    pid = _create_player("rank_read")
    conn, writes = _connection_with_write_trace()
    try:
        rows = get_sorted_ranking_entries(limit=50, conn=conn)
    finally:
        conn.set_trace_callback(None)
        conn.close()
    assert any(r["player_id"] == pid for r in rows)
    assert writes == [], f"unexpected writes: {writes}"


def test_playercard_get_is_read_only(temp_db):
    pid = _create_player("pc_read")
    other = _create_player("pc_viewer")
    build_public_card(pid, viewer_id=other)
    conn, writes = _connection_with_write_trace()
    try:
        card, err = build_public_card(pid, viewer_id=other, conn=conn)
    finally:
        conn.set_trace_callback(None)
        conn.close()
    assert err is None and card is not None
    assert writes == [], f"unexpected writes: {writes}"


def test_read_player_scores_for_playercard_field_names(temp_db):
    from game.ranking import format_scores_for_playercard, read_player_scores_for_playercard

    pid = _create_player("pc_fields")
    conn = db()
    conn.execute(
        "UPDATE player_scores SET score_total=5000, score_buildings=3000, score_research=2000 WHERE player_id=?",
        (pid,),
    )
    conn.commit()
    conn.close()

    scores = read_player_scores_for_playercard(pid)
    assert scores["score_total"] == 5000
    assert scores["score_buildings"] == 3000
    assert scores["score_research"] == 2000
    assert scores["total_score"] == 5000

    mapped = format_scores_for_playercard(
        {"total_score": 42, "building_score": 10, "research_score": 5, "fleet_score": 1, "defense_score": 2, "evolution_score": 0}
    )
    assert mapped["score_total"] == 42
    assert mapped["score_fleet"] == 1


def test_playercard_get_never_calls_ensure_score_rows(temp_db, monkeypatch):
    from game import ranking as ranking_mod

    pid = _create_player("pc_no_seed")
    other = _create_player("pc_no_seed_viewer")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))
    conn.commit()
    conn.close()

    def _forbidden(*_a, **_k):
        raise AssertionError("_ensure_score_rows must not run on PlayerCard GET")

    monkeypatch.setattr(ranking_mod, "_ensure_score_rows", _forbidden)
    card, err = build_public_card(pid, viewer_id=other)
    assert err is None and card is not None
    assert card.get("rank") is not None
    assert int(card.get("score_total", 0) or 0) == 0


def test_playercard_rank_survives_operational_error(temp_db, monkeypatch):
    import sqlite3

    from game import ranking as ranking_mod

    pid = _create_player("pc_lock")
    other = _create_player("pc_lock_viewer")

    def _locked(_player_id, conn=None):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ranking_mod, "get_player_rank_from_snapshot", _locked)
    card, err = build_public_card(pid, viewer_id=other)
    assert err is None and card is not None
    assert int(card.get("score_total", 0) or 0) >= 0
    assert card.get("rank") is None
    assert int(card.get("total_players", 0) or 0) >= 1


def test_api_player_card_without_score_row_returns_200(temp_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", temp_db)
    monkeypatch.setattr(models, "DB_PATH", temp_db)
    importlib.reload(app_module)

    target = _create_player("pc_api_target")
    viewer = _create_player("pc_api_viewer")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (target,))
    conn.commit()
    conn.close()

    conn = db()
    row = conn.execute("SELECT username FROM users WHERE id = ?", (viewer,)).fetchone()
    conn.close()
    assert row
    uname = row["username"]

    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    res = client.get(f"/api/player-card/{target}")
    assert res.status_code == 200
    assert b"gc-player-card-shell" in res.data or b"gc-player-card-error-state" in res.data


def test_sqlite_write_mutex_serializes_parallel_begins(temp_db):
    import threading

    from game.db import begin_write_transaction, commit, db, rollback

    errors: list[str] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        conn = db()
        try:
            barrier.wait(timeout=5)
            begin_write_transaction(conn)
            conn.execute("UPDATE players SET last_seen = last_seen WHERE id = (SELECT MIN(id) FROM players);")
            commit(conn)
        except Exception as exc:
            errors.append(str(exc))
            try:
                rollback(conn)
            except Exception:
                pass
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == [], errors


def test_new_player_has_score_row_and_appears_in_ranking(temp_db):
    pid = _create_player("fresh_zero")
    conn = db()
    try:
        row = conn.execute(
            "SELECT score_total FROM player_scores WHERE player_id = ?;",
            (pid,),
        ).fetchone()
        assert row is not None
        assert int(row["score_total"]) == 0
    finally:
        conn.close()

    entries = get_sorted_ranking_entries(limit=200)
    assert any(e["player_id"] == pid and e["total_score"] == 0 for e in entries)


def test_player_without_score_row_still_in_ranking_via_left_join(temp_db):
    pid = _create_player("left_join")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))
    conn.commit()
    conn.close()

    entries = get_sorted_ranking_entries(limit=200)
    match = next((e for e in entries if e["player_id"] == pid), None)
    assert match is not None
    assert match["total_score"] == 0
