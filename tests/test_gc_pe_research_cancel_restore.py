"""Planet research cancel: server safety rules, card-job flag and UI contract."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from game.models import db, create_user, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.bootstrap import backfill_all_planets_evolution, ensure_planet_evolution
from game.planet_evolution.definitions import reload_definitions
from game.planet_evolution.planet_research import (
    cancel_planet_research_job,
    get_planet_research_levels,
    get_planet_research_queue,
    queue_planet_research,
)

ROOT = Path(__file__).resolve().parents[1]
TECH = "industry_t1_automation"


@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_DB_PATH", str(tmp_path / "cancel_test.db"))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    conn = db()
    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None


def _player_with_job(name: str):
    ok, err, user = create_user(name, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    ensure_player_and_homeworld(uid, player_name=name, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;", (pid,))
    conn.execute("UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;", (pid,))
    conn.commit()
    ok, reason, extra = queue_planet_research(pid, TECH, player_id=uid, conn=conn)
    assert ok is True, reason
    job_id = int(extra["job_id"])
    conn.close()
    return uid, pid, job_id


def _resources(pid: int):
    conn = db()
    row = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)).fetchone()
    conn.close()
    return int(row["metal"]), int(row["crystal"])


def test_cancel_refunds_once_and_double_cancel_is_noop(evo_db):
    uid, pid, job_id = _player_with_job("cancel_once")
    spent = _resources(pid)
    ok, reason = cancel_planet_research_job(pid, job_id)
    assert (ok, reason) == (True, "ok")
    after_first = _resources(pid)
    assert after_first[0] > spent[0] and after_first[1] > spent[1]
    # a refund never exceeds what the job cost
    assert after_first[0] <= 500000 and after_first[1] <= 500000
    ok2, reason2 = cancel_planet_research_job(pid, job_id)
    assert (ok2, reason2) == (False, "job_not_found")
    assert _resources(pid) == after_first
    conn = db()
    assert get_planet_research_queue(pid, conn=conn) == []
    conn.close()


def test_cancel_of_due_job_completes_it_instead_of_deleting(evo_db):
    uid, pid, job_id = _player_with_job("cancel_due")
    before = _resources(pid)
    conn = db()
    now = time.time()
    conn.execute(
        "UPDATE planet_research_queue SET start_at = ?, finish_at = ? WHERE id = ?;",
        (now - 120, now - 5, job_id),
    )
    conn.commit()
    conn.close()

    ok, reason = cancel_planet_research_job(pid, job_id)
    assert (ok, reason) == (False, "job_not_found")
    assert _resources(pid) == before  # no refund for finished work
    conn = db()
    assert get_planet_research_queue(pid, conn=conn) == []
    assert int(get_planet_research_levels(pid, conn=conn).get(TECH, 0)) >= 1  # tech granted
    conn.close()


def test_cancel_rejects_job_of_another_planet(evo_db):
    _uid_a, pid_a, job_a = _player_with_job("cancel_owner_a")
    _uid_b, pid_b, _job_b = _player_with_job("cancel_owner_b")
    ok, reason = cancel_planet_research_job(pid_b, job_a)
    assert (ok, reason) == (False, "job_not_found")
    conn = db()
    assert [int(r["id"]) for r in get_planet_research_queue(pid_a, conn=conn)] == [job_a]
    conn.close()


def test_cancel_route_forbidden_for_foreign_planet(evo_db):
    _uid_a, pid_a, job_a = _player_with_job("cancel_route_a")
    uid_b, _pid_b, _job_b = _player_with_job("cancel_route_b")
    from app import app

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = uid_b
        r = client.post(f"/api/planets/{pid_a}/research/cancel", json={"job_id": job_a})
        assert r.status_code == 403
        assert r.get_json().get("reason") == "forbidden"
        assert client.post(f"/api/planets/{pid_a}/research/cancel", json={}).status_code == 400
    conn = db()
    assert [int(r["id"]) for r in get_planet_research_queue(pid_a, conn=conn)] == [job_a]
    conn.close()


def test_card_job_cancellable_only_while_running(evo_db):
    from game.queue_card import map_planet_research_queue_to_card_jobs

    now = time.time()
    status = {
        "queue": [
            {"id": 7, "tech_key": TECH, "target_level": 1, "start_at": now - 10, "finish_at": now + 60},
            {"id": 0, "tech_key": TECH, "target_level": 1, "start_at": now, "finish_at": now + 90},
        ]
    }
    jobs = map_planet_research_queue_to_card_jobs(status, now=now)
    flags = {int(j["job_id"]): j.get("cancellable") for j in jobs}
    assert flags.get(7) is True
    assert all(j.get("cancellable") is False for j in jobs if int(j["job_id"]) == 0)


def test_cancel_ui_contract_server_and_client():
    tpl = (ROOT / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    macro = tpl.split("{% macro pe_card_queue_block")[1].split("{% endmacro %}")[0]
    assert "data-planet-research-cancel-id" in macro
    assert "qj.cancellable" in macro
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert 'e.target.closest("[data-planet-research-cancel-id]")' in js
    assert "/research/cancel" in js
    assert 'queueJob.cancellable === true' in js
