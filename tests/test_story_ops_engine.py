"""GC-2501 / GC-2503 — Genesis Story Ops engine tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.directives.progress import apply_directive_events
from game.models import create_user
from game.story.engine import advance_active_beat, apply_choice, ensure_player_story
from game.story.flags import has_flag
from game.story.service import get_story_state

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def story_db(tmp_path, monkeypatch):
    db_file = tmp_path / "story_ops.db"
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
    yield db_file


def _create_player() -> int:
    ok, _reason, user = create_user(f"story_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def _advance_until(pid, *, pack_id: str, arc_id: str, conn, pred, max_steps: int = 12):
    """Advance transmission beats until predicate(beat) is true or steps exhausted."""
    for _ in range(max_steps):
        state = get_story_state(pid, conn=conn, ensure=True)
        focus = next(
            (
                a
                for a in state["arcs"]
                if a["pack_id"] == pack_id and a["arc_id"] == arc_id and a["status"] == "active"
            ),
            None,
        )
        beat = (focus or {}).get("beat") or {}
        if pred(beat):
            return beat
        if beat.get("type") != "transmission":
            return beat
        res = advance_active_beat(pid, pack_id=pack_id, arc_id=arc_id, conn=conn)
        assert res["ok"], res
    raise AssertionError("advance_until exhausted")


def test_story_main_arc_starts_and_advances(story_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_story(pid, conn=conn)
        state = get_story_state(pid, conn=conn, ensure=False)
        assert state["ready"]
        active = [a for a in state["arcs"] if a["status"] == "active"]
        assert any(a["pack_id"] == "ark_signal" and a["arc_id"] == "main" for a in active)
        focus = state["focus"]
        assert focus and focus["beat"]["type"] == "transmission"
        assert focus.get("status_label") not in ("active", "completed")
        assert focus.get("chapters")
        assert focus["chapters"][0]["status"] == "current"
        assert focus["chapters"][0]["title"]
        assert "story_ch_" not in focus["chapters"][0]["title"]

        # Chapter I is multi-transmission; advance until building objective.
        beat = _advance_until(
            pid,
            pack_id="ark_signal",
            arc_id="main",
            conn=conn,
            pred=lambda b: b.get("type") == "objective",
        )
        assert beat.get("objective_key") == "upgrade_buildings"
        assert beat.get("title")
        assert not str(beat.get("title") or "").startswith("story_")
    finally:
        conn.close()


def test_story_fanout_from_directive_events(story_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_story(pid, conn=conn)
        _advance_until(
            pid,
            pack_id="ark_signal",
            arc_id="main",
            conn=conn,
            pred=lambda b: b.get("type") == "objective" and b.get("objective_key") == "upgrade_buildings",
        )
        state = get_story_state(pid, conn=conn, ensure=True)
        main = next(a for a in state["arcs"] if a["arc_id"] == "main" and a["status"] == "active")
        target = max(1, int(main.get("target") or 5))
        before = int(main.get("progress") or 0)

        # Year-One packs use hardened targets (e.g. 5 builds); fan-out must meet target.
        for _ in range(target):
            apply_directive_events(
                pid,
                [
                    {
                        "kind": "build_complete",
                        "building_type": "metal_mine",
                        "amount": 1,
                        "source_event_id": f"test_build:{uuid.uuid4().hex}",
                    }
                ],
                conn=conn,
            )
        state = get_story_state(pid, conn=conn, ensure=True)
        main = next(a for a in state["arcs"] if a["arc_id"] == "main" and a["status"] == "active")
        beat = main.get("beat") or {}
        # Objective auto-advances into chapter close, then fleet objective.
        assert beat.get("type") in ("objective", "transmission")
        if beat.get("type") == "objective":
            assert beat.get("objective_key") == "send_fleet_missions"
        else:
            assert int(main.get("progress") or 0) >= before or beat.get("type") == "transmission"
    finally:
        conn.close()


def test_story_androgyn_choice_after_main(story_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_story(pid, conn=conn)
        from game.story.flags import set_flag

        set_flag(pid, "ark_signal_main_done", conn=conn)
        conn.execute(
            """
            UPDATE player_story_arcs
            SET status = 'completed', completed_at = 1, updated_at = 1
            WHERE player_id = ? AND pack_id = 'ark_signal' AND arc_id = 'main';
            """,
            (pid,),
        )
        ensure_player_story(pid, conn=conn)
        state = get_story_state(pid, conn=conn, ensure=False)
        androgyn = next(
            (a for a in state["arcs"] if a["arc_id"] == "androgyn_echo" and a["status"] == "active"),
            None,
        )
        assert androgyn is not None
        _advance_until(
            pid,
            pack_id="ark_signal",
            arc_id="androgyn_echo",
            conn=conn,
            pred=lambda b: b.get("type") == "choice",
        )
        res = apply_choice(
            pid,
            pack_id="ark_signal",
            arc_id="androgyn_echo",
            choice_id="pursue",
            conn=conn,
        )
        assert res["ok"]
        assert has_flag(pid, "androgyn_pursue", conn=conn)
        assert has_flag(pid, "codex_androgyn_echo", conn=conn)
    finally:
        conn.close()


def test_story_reopens_false_completion_without_flags(story_db):
    """Completed without reward flags (pack migration) must reopen, not stay idle."""
    conn = db()
    try:
        pid = _create_player()
        ensure_player_story(pid, conn=conn)
        conn.execute(
            """
            UPDATE player_story_arcs
            SET status = 'completed', completed_at = 1, updated_at = 1,
                chapter_index = 0, beat_index = 3
            WHERE player_id = ? AND pack_id = 'ark_signal' AND arc_id = 'main';
            """,
            (pid,),
        )
        ensure_player_story(pid, conn=conn)
        state = get_story_state(pid, conn=conn, ensure=False)
        main = next(a for a in state["arcs"] if a["arc_id"] == "main")
        assert main["status"] == "active"
        assert main["beat"] and main["beat"]["type"] == "transmission"
        assert main["chapters"][0]["status"] == "current"
        title = str(main["chapters"][0]["title"] or "")
        assert "Erwachen" in title or "Awakening" in title or "Kapitel" in title
    finally:
        conn.close()


def test_story_no_raw_status_keys_in_state(story_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_story(pid, conn=conn)
        state = get_story_state(pid, conn=conn, ensure=False)
        for arc in state["arcs"]:
            assert arc["status_label"] not in ("active", "completed", "locked", "done", "current")
            for ch in arc.get("chapters") or []:
                assert ch["status_label"] not in ("active", "completed", "locked", "done", "current")
                assert not str(ch.get("title") or "").startswith("story_")
            beat = arc.get("beat") or {}
            if beat:
                assert not str(beat.get("title") or "").startswith("story_")
                assert not str(beat.get("cta") or "").startswith("story_")
    finally:
        conn.close()
