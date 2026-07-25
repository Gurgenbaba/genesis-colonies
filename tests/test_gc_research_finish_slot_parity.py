"""
Research finish / slot parity (GC-833 alignment with buildings).

Run: python -m pytest tests/test_gc_research_finish_slot_parity.py -v
"""

from __future__ import annotations

import time
import uuid

import pytest

from game.models import (
    add_research_job,
    create_user,
    get_homeworld,
    get_research_levels,
    get_research_queue_rows,
    init_db,
    save_planet_buildings,
)
from game.research import (
    RESEARCH_QUEUE_LIMIT_AT_LAB4,
    get_research_status,
    queue_research,
    recalculate_research_queue_finish_times,
)


@pytest.fixture()
def research_player(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_research_finish_slot.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")

    import game.db as dbmod
    import game.models as models

    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()

    uname = f"rfin_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    pid = int(user["id"])
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    # Lab ≥4 → 3 research slots
    save_planet_buildings(
        planet_id,
        {
            "metal_mine": 1,
            "crystal_mine": 1,
            "research_lab": 4,
        },
    )
    # Afford several research enqueues
    from game.db import db
    from game.models import commit

    conn = db()
    conn.execute(
        "UPDATE planets SET metal = 5000000, crystal = 5000000 WHERE id = ?;",
        (planet_id,),
    )
    commit(conn)
    conn.close()
    return pid, planet_id, {"id": pid}


def test_research_status_finishes_past_due_job(research_player):
    pid, _planet_id, _player = research_player
    now = time.time()
    add_research_job(pid, "energy_tech", now - 60, now - 1)

    from flask import Flask

    from game.db import db
    from game.models import commit

    app = Flask("research_finish_past")
    conn = db()
    with app.test_request_context("/"):
        payload = get_research_status(pid, conn=conn)
        commit(conn)
    conn.close()

    assert payload["queue"] == []
    assert payload["summary"]["count"] == 0
    assert payload["summary"]["limit"] == RESEARCH_QUEUE_LIMIT_AT_LAB4
    levels = get_research_levels(pid)
    assert int(levels.get("energy_tech") or 0) >= 1


def test_research_status_finishes_display_zero_truncation_job(research_player):
    """finish_at = now+0.7 → remaining int() == 0; must finish and free the slot."""
    pid, _planet_id, _player = research_player
    now = time.time()
    add_research_job(pid, "energy_tech", now - 30, now + 0.7)

    from flask import Flask

    from game.db import db
    from game.models import commit

    app = Flask("research_finish_trunc")
    conn = db()
    with app.test_request_context("/"):
        payload = get_research_status(pid, conn=conn)
        commit(conn)
    conn.close()

    assert payload["queue"] == []
    assert payload["summary"]["count"] == 0
    assert get_research_queue_rows(pid) == []
    assert int(get_research_levels(pid).get("energy_tech") or 0) >= 1
    free = max(0, int(payload["summary"]["limit"]) - int(payload["summary"]["count"]))
    assert free == RESEARCH_QUEUE_LIMIT_AT_LAB4


def test_enqueue_three_after_truncation_zombies_cleared(research_player):
    """Three display-zero leftovers must not block all three lab4 slots."""
    pid, _planet_id, player = research_player
    now = time.time()
    add_research_job(pid, "energy_tech", now - 40, now + 0.6)
    add_research_job(pid, "mining_tech", now - 40, now + 0.7)
    add_research_job(pid, "storage_tech", now - 40, now + 0.8)

    ok1, r1, _ = queue_research(player, "weapon_tech", user_id=pid)
    ok2, r2, _ = queue_research(player, "buildtime_tech", user_id=pid)
    ok3, r3, _ = queue_research(player, "drone_tech", user_id=pid)

    assert ok1 and r1 == "ok", (ok1, r1)
    assert ok2 and r2 == "ok", (ok2, r2)
    assert ok3 and r3 == "ok", (ok3, r3)
    assert len(get_research_queue_rows(pid)) == 3


def test_recalculate_does_not_revive_due_research_head(research_player):
    pid, _planet_id, _player = research_player
    now = time.time()
    add_research_job(pid, "energy_tech", now - 20, now - 2)
    add_research_job(pid, "mining_tech", now + 100, now + 200)

    from game.db import db
    from game.models import commit

    conn = db()
    recalculate_research_queue_finish_times(pid, conn=conn, now=now)
    commit(conn)

    rows = get_research_queue_rows(pid, conn=conn)
    conn.close()
    assert len(rows) == 2
    head = rows[0]
    # Due head must keep past finish_at — not extended to a fresh full duration
    assert float(head["finish_at"]) <= now
    # Follower chains from now, not from a revived head
    assert float(rows[1]["start_at"]) == pytest.approx(now, abs=2.0)


def test_main_js_research_uses_timer_zero_finish_path():
    from pathlib import Path

    src = Path("static/main.js").read_text(encoding="utf-8")
    finish = src.split("function requestFinishRefresh(type)")[1].split(
        "let _overviewWidgetsPlanetId"
    )[0]
    assert 'type === "research"' in finish
    assert "requestQueueTimerZeroRefresh" in finish
    assert 'type === "research" || type === "planet_evolution"' not in finish