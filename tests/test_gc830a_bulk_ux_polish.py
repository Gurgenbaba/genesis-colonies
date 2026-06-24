"""GC-830A — Genesis bulk UX polish for MAX queue buttons."""

from __future__ import annotations

from game.buildings import (
    get_upgrade_cost,
    preview_max_queueable_build_jobs,
    summarize_max_queueable_build_jobs,
)
from game.economy_balance import power_build_seconds
from game.research import (
    get_research_cost,
    get_research_time,
    preview_max_queueable_research_jobs,
    summarize_max_queueable_research_jobs,
)


def test_summarize_max_queueable_build_jobs_totals():
    jobs = preview_max_queueable_build_jobs(
        "metal_mine",
        current_level=10,
        queued_same=0,
        max_level=50,
        metal=1_000_000.0,
        crystal=1_000_000.0,
        queue_free_slots=3,
    )
    assert jobs >= 1
    preview = summarize_max_queueable_build_jobs(
        "metal_mine",
        current_level=10,
        queued_same=0,
        max_level=50,
        metal=1_000_000.0,
        crystal=1_000_000.0,
        queue_free_slots=3,
    )
    assert preview["jobs"] == jobs
    assert preview["from_level"] == 10
    assert preview["to_level"] == 10 + jobs

    total_m = 0.0
    total_c = 0.0
    total_sec = 0
    for i in range(jobs):
        eff = 10 + i
        cm, cc = get_upgrade_cost("metal_mine", eff)
        total_m += float(cm)
        total_c += float(cc)
        total_sec += int(power_build_seconds("metal_mine", eff + 1))
    assert preview["cost_metal"] == int(round(total_m))
    assert preview["cost_crystal"] == int(round(total_c))
    assert preview["time_seconds"] == total_sec


def test_summarize_max_queueable_research_jobs_totals():
    jobs = preview_max_queueable_research_jobs(
        "energy_tech",
        current_level=0,
        queued_same=0,
        metal=1_000_000.0,
        crystal=1_000_000.0,
        queue_free_slots=2,
    )
    assert jobs == 2
    preview = summarize_max_queueable_research_jobs(
        "energy_tech",
        current_level=0,
        queued_same=0,
        metal=1_000_000.0,
        crystal=1_000_000.0,
        queue_free_slots=2,
        user_id=1,
        buildings={"research_lab": 1},
    )
    assert preview["jobs"] == 2
    assert preview["from_level"] == 0
    assert preview["to_level"] == 2

    total_m = 0.0
    total_c = 0.0
    total_sec = 0
    for lvl in (1, 2):
        cm, cc = get_research_cost("energy_tech", lvl)
        total_m += float(cm)
        total_c += float(cc)
        total_sec += int(get_research_time("energy_tech", lvl, 1, buildings={"research_lab": 1}))
    assert preview["cost_metal"] == int(round(total_m))
    assert preview["cost_crystal"] == int(round(total_c))
    assert preview["time_seconds"] == total_sec


def test_buildings_template_gc830a_polish():
    text = open("templates/buildings.html", encoding="utf-8").read()
    assert "progression_btn_plus_one" in text
    assert "progression_btn_max_queue_count" in text
    assert "gc-max-queue-hover-trigger" in text
    assert "max_queue_preview" in text
    assert "gc-bld-head-action-btn--plus-one" in text


def test_research_template_gc830a_polish():
    text = open("templates/research.html", encoding="utf-8").read()
    assert "progression_btn_plus_one" in text
    assert "progression_btn_max_queue_count" in text
    assert "gc-max-queue-hover-trigger" in text
    assert "max_queue_preview" in text
