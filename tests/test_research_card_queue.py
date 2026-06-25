"""
GC-536C — research card queue payload and static contracts.

Run: python -m pytest tests/test_research_card_queue.py -q
"""

from __future__ import annotations

from pathlib import Path

from game.queue_card import STATUS_ACTIVE, STATUS_QUEUED


ROOT = Path(__file__).resolve().parents[1]


def _tech_row(techs: list, tech_key: str) -> dict | None:
    for row in techs:
        if row.get("key") == tech_key:
            return row
    return None


def test_active_research_tech_has_queue_job():
    from game.research import _attach_queue_jobs_to_research_techs

    queue_list = [
        {
            "id": 5,
            "tech_key": "energy_tech",
            "key": "energy_tech",
            "label": "Energy Tech",
            "current_level": 2,
            "target_level": 3,
            "remaining": 40,
            "total_seconds": 100,
            "total": 100,
            "start_at": 1_700_000_000.0,
            "finish_at": 1_700_000_040.0,
            "position": 1,
        }
    ]

    techs = [{"key": "energy_tech", "level": 2, "target_level": 3}]
    _attach_queue_jobs_to_research_techs(techs, queue_list, now=1_700_000_000.0)
    row = _tech_row(techs, "energy_tech")
    assert row is not None
    qj = row["queue_job"]
    assert qj["owner_key"] == "energy_tech"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["queue_position"] == 1
    assert qj["target_level"] == 3
    assert qj["current_level"] == 2


def test_queued_research_tech_has_queue_position():
    from game.research import _attach_queue_jobs_to_research_techs

    queue_list = [
        {
            "id": 1,
            "tech_key": "energy_tech",
            "current_level": 2,
            "target_level": 3,
            "remaining": 30,
            "total_seconds": 80,
            "finish_at": 1_700_000_030.0,
            "start_at": 1_699_999_950.0,
            "position": 1,
        },
        {
            "id": 2,
            "tech_key": "mining_tech",
            "current_level": 1,
            "target_level": 2,
            "remaining": 120,
            "total_seconds": 90,
            "finish_at": 1_700_000_120.0,
            "start_at": 1_700_000_030.0,
            "position": 2,
        },
    ]
    techs = [
        {"key": "energy_tech", "level": 2},
        {"key": "mining_tech", "level": 1},
    ]
    _attach_queue_jobs_to_research_techs(techs, queue_list, now=1_700_000_000.0)
    mining = _tech_row(techs, "mining_tech")
    assert mining is not None
    qj = mining["queue_job"]
    assert qj["status"] == STATUS_QUEUED
    assert qj["queue_position"] == 2


def test_tech_without_job_has_no_queue_job():
    from game.research import _attach_queue_jobs_to_research_techs

    queue_list = [
        {
            "id": 1,
            "tech_key": "energy_tech",
            "current_level": 0,
            "target_level": 1,
            "remaining": 30,
            "total_seconds": 80,
            "finish_at": 1_700_000_030.0,
            "start_at": 1_699_999_950.0,
            "position": 1,
        }
    ]
    techs = [{"key": "energy_tech"}, {"key": "storage_tech"}]
    _attach_queue_jobs_to_research_techs(techs, queue_list, now=1_700_000_000.0)
    storage = _tech_row(techs, "storage_tech")
    assert storage is not None
    assert "queue_job" not in storage


def test_queue_engine_unchanged_static():
    text = (ROOT / "game/queue_engine.py").read_text(encoding="utf-8")
    assert "queue_card" not in text


def test_research_template_card_queue_markers():
    html = (ROOT / "templates/research.html").read_text(encoding="utf-8")
    macro = (ROOT / "templates/partials/page_mini_queue_strip.html").read_text(encoding="utf-8")
    assert "data-research-card" in html
    assert "research-mini-queue" in html
    assert "render_page_mini_queue_strip" in html
    assert "gc-mini-queue-strip" in macro
    assert "gc-card-queue-block" in html
    assert "research-queue-root" not in html
