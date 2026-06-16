"""
GC-804: Research queue timer stability after PJAX navigation / reload.

Run: python -m pytest tests/test_gc804_research_timer.py -v
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.research import get_research_status

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def research_timer_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc804_research.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    return db_file


def _player_with_lab(db_file) -> tuple[int, str]:
    uname = f"gc804_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    pid = int(user["id"])
    planet = get_homeworld(player_id=pid)
    save_planet_buildings(int(planet["id"]), {"research_lab": 3, "metal_mine": 1, "crystal_mine": 1})
    try:
        db().close()
    except Exception:
        pass
    return pid, uname


def test_research_queue_times_stable_across_status_reads(research_timer_db):
    pid, _ = _player_with_lab(research_timer_db)
    now = time.time()
    finish_at = now + 600
    start_at = now - 120

    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "energy_tech", start_at, finish_at),
    )
    conn.commit()
    conn.close()

    first = get_research_status(pid, skip_finish=True)
    time.sleep(0.05)
    second = get_research_status(pid, skip_finish=True)

    q1 = first["queue"][0]
    q2 = second["queue"][0]

    assert q1["finish_at"] == pytest.approx(q2["finish_at"], abs=0.01)
    assert q1["total_seconds"] == q2["total_seconds"]
    assert q2["remaining"] <= q1["remaining"]
    assert q1["remaining"] - q2["remaining"] <= 2


def test_api_game_state_research_queue_consistent_on_panel_poll(research_timer_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setattr(dbmod, "DB_PATH", research_timer_db)
    monkeypatch.setattr(models, "DB_PATH", research_timer_db)
    importlib.reload(app_module)

    pid, uname = _player_with_lab(research_timer_db)
    now = time.time()
    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "mining_tech", now - 30, now + 450),
    )
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    r_panel = client.get("/api/game-state?include_panel=1")
    r_poll = client.get("/api/game-state")
    assert r_panel.status_code == 200
    assert r_poll.status_code == 200

    panel = r_panel.get_json()
    poll = r_poll.get_json()
    p_job = panel["research"]["queue"][0]
    l_job = poll["research"]["queue"][0]

    assert p_job["finish_at"] == pytest.approx(l_job["finish_at"], abs=0.01)
    assert p_job["total_seconds"] == l_job["total_seconds"]
    assert abs(p_job["remaining"] - l_job["remaining"]) <= 2


def test_research_pjax_page_queue_subtitle_matches_status(research_timer_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setattr(dbmod, "DB_PATH", research_timer_db)
    monkeypatch.setattr(models, "DB_PATH", research_timer_db)
    importlib.reload(app_module)

    pid, uname = _player_with_lab(research_timer_db)
    now = time.time()
    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "storage_tech", now - 10, now + 300),
    )
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    res = client.get("/research", headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    status = get_research_status(pid, skip_finish=True)
    expected_remaining = int(status["summary"]["first_finish_in"])
    assert "gc-card-queue-timer" in html
    assert 'data-timer-kind="research"' in html
    import re

    timer_match = re.search(r'gc-card-queue-timer[^>]*>(\d+)s</div>', html)
    assert timer_match, "research queue timer SSR contract missing"
    rendered_remaining = int(timer_match.group(1))
    assert abs(rendered_remaining - expected_remaining) <= 2
    assert "data-server-remaining=" in html
