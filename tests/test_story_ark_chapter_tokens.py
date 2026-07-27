"""GC — Engine-owned Ark-Token chapter drip."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import begin_write_transaction, commit, db
from game.inventory import inventory_amount
from game.models import create_user
from game.story.engine import advance_active_beat, ensure_player_story
from game.story.flags import has_flag, set_flag
from game.story.free_shop import ARK_TOKEN_KEY
from game.story.packs import clear_pack_cache, get_arc, get_pack, load_all_packs
from game.story.rewards import (
    DEFAULT_MAIN_CHAPTER_TOKENS,
    DEFAULT_MAIN_FINALE_TOKENS,
    DEFAULT_SIDE_CHAPTER_TOKENS,
    chapter_ark_token_amount,
    chapter_receipt_flag,
    grant_chapter_ark_tokens,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def token_db(tmp_path, monkeypatch):
    db_file = tmp_path / "story_ark_tokens.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    clear_pack_cache()
    yield db_file


def _pid() -> int:
    ok, _r, user = create_user(f"arktok_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def test_chapter_amounts_main_and_side():
    clear_pack_cache()
    arc = get_arc("ark_signal", "main")
    assert arc
    n = len(arc["chapters"])
    assert chapter_ark_token_amount(arc, 0) == DEFAULT_MAIN_CHAPTER_TOKENS
    assert chapter_ark_token_amount(arc, n - 1) == DEFAULT_MAIN_FINALE_TOKENS
    side = get_arc("side_ops_year", "debris_choir")
    assert side
    assert chapter_ark_token_amount(side, 0) == DEFAULT_SIDE_CHAPTER_TOKENS


def test_grant_chapter_idempotent(token_db):
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        arc = get_arc("ark_signal", "main")
        pack = get_pack("ark_signal")
        r1 = grant_chapter_ark_tokens(
            pid,
            pack_id="ark_signal",
            arc_id="main",
            chapter_index=0,
            arc_def=arc,
            pack=pack,
            conn=conn,
            notify=False,
        )
        assert r1["granted"] == DEFAULT_MAIN_CHAPTER_TOKENS
        assert inventory_amount(pid, ARK_TOKEN_KEY, conn=conn) == DEFAULT_MAIN_CHAPTER_TOKENS
        assert has_flag(pid, chapter_receipt_flag("ark_signal", "main", 0), conn=conn)
        r2 = grant_chapter_ark_tokens(
            pid,
            pack_id="ark_signal",
            arc_id="main",
            chapter_index=0,
            arc_def=arc,
            pack=pack,
            conn=conn,
            notify=False,
        )
        assert r2["granted"] == 0
        assert r2["already"] is True
        assert inventory_amount(pid, ARK_TOKEN_KEY, conn=conn) == DEFAULT_MAIN_CHAPTER_TOKENS
        commit(conn)
    finally:
        conn.close()


def test_finale_and_side_amounts(token_db):
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        main = get_arc("ark_signal", "main")
        n = len(main["chapters"])
        r = grant_chapter_ark_tokens(
            pid,
            pack_id="ark_signal",
            arc_id="main",
            chapter_index=n - 1,
            arc_def=main,
            pack=get_pack("ark_signal"),
            conn=conn,
            notify=False,
        )
        assert r["granted"] == DEFAULT_MAIN_FINALE_TOKENS
        side = get_arc("side_ops_year", "debris_choir")
        r2 = grant_chapter_ark_tokens(
            pid,
            pack_id="side_ops_year",
            arc_id="debris_choir",
            chapter_index=0,
            arc_def=side,
            pack=get_pack("side_ops_year"),
            conn=conn,
            notify=False,
        )
        assert r2["granted"] == DEFAULT_SIDE_CHAPTER_TOKENS
        commit(conn)
    finally:
        conn.close()


def test_backfill_completed_arc(token_db):
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        # Simulate completed main without chapter receipt flags.
        set_flag(pid, "ark_signal_main_done", conn=conn, now=1)
        set_flag(pid, "codex_ark_signal", conn=conn, now=1)
        conn.execute(
            """
            INSERT INTO player_story_arcs (
                player_id, pack_id, arc_id, status,
                chapter_index, beat_index, progress_value, target_value,
                started_at, updated_at, completed_at
            ) VALUES (?, 'ark_signal', 'main', 'completed', 0, 0, 0, 0, 1, 1, 1);
            """,
            (pid,),
        )
        ensure_player_story(pid, conn=conn, now=10.0)
        arc = get_arc("ark_signal", "main")
        expect = sum(
            chapter_ark_token_amount(arc, i, pack=get_pack("ark_signal"))
            for i in range(len(arc["chapters"]))
        )
        assert inventory_amount(pid, ARK_TOKEN_KEY, conn=conn) == expect
        # Second ensure does not double.
        ensure_player_story(pid, conn=conn, now=11.0)
        assert inventory_amount(pid, ARK_TOKEN_KEY, conn=conn) == expect
        commit(conn)
    finally:
        conn.close()


def test_packs_have_no_ark_token_reward_grants():
    clear_pack_cache()
    for pack_id, pack in load_all_packs().items():
        for arc in pack.get("arcs") or []:
            for ch in arc.get("chapters") or []:
                for beat in ch.get("beats") or []:
                    if str(beat.get("type")) != "reward":
                        continue
                    for g in beat.get("grants") or []:
                        assert g.get("item_key") != ARK_TOKEN_KEY, (
                            f"{pack_id}/{arc.get('arc_id')}/{beat.get('beat_id')}"
                        )


def test_advance_chapter_boundary_grants_tokens(token_db):
    """Force chapter boundary by jumping near end of chapter 0 and advancing."""
    conn = db()
    try:
        pid = _pid()
        begin_write_transaction(conn)
        ensure_player_story(pid, conn=conn)
        arc = get_arc("ark_signal", "main")
        # Last beat of chapter 0 is a transmission — set indices there.
        beats0 = list((arc["chapters"][0] or {}).get("beats") or [])
        last_bi = len(beats0) - 1
        conn.execute(
            """
            UPDATE player_story_arcs
            SET chapter_index = 0, beat_index = ?, progress_value = 0, target_value = 0
            WHERE player_id = ? AND pack_id = 'ark_signal' AND arc_id = 'main';
            """,
            (last_bi, pid),
        )
        before = inventory_amount(pid, ARK_TOKEN_KEY, conn=conn)
        res = advance_active_beat(pid, pack_id="ark_signal", arc_id="main", conn=conn)
        assert res["ok"]
        assert int(res.get("ark_tokens_gained") or 0) == DEFAULT_MAIN_CHAPTER_TOKENS
        assert inventory_amount(pid, ARK_TOKEN_KEY, conn=conn) == before + DEFAULT_MAIN_CHAPTER_TOKENS
        commit(conn)
    finally:
        conn.close()
