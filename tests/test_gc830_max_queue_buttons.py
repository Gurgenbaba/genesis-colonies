"""GC-830 — MAX build / MAX research queue buttons."""

from __future__ import annotations

from game.buildings import preview_max_queueable_build_jobs, queue_build_for_planet
from game.economy_balance import power_upgrade_cost
from game.research import preview_max_queueable_research_jobs, queue_research


def test_preview_max_queueable_build_jobs_respects_resources():
    m11, c11 = power_upgrade_cost("metal_mine", 11)
    n = preview_max_queueable_build_jobs(
        "metal_mine",
        current_level=10,
        queued_same=0,
        max_level=50,
        metal=float(m11),
        crystal=float(c11),
        queue_free_slots=5,
    )
    assert n == 1


def test_preview_max_queueable_research_jobs_respects_slots():
    from game.research import get_research_cost

    m, c = get_research_cost("energy_tech", 1)
    n = preview_max_queueable_research_jobs(
        "energy_tech",
        current_level=0,
        queued_same=0,
        metal=float(m) * 3,
        crystal=float(c) * 3,
        queue_free_slots=2,
    )
    assert n == 2


def test_buildings_template_has_max_queue_button():
    text = open("templates/buildings.html", encoding="utf-8").read()
    assert "btn-upgrade-max" in text
    assert "max_queueable" in text


def test_research_template_has_max_queue_button():
    text = open("templates/research.html", encoding="utf-8").read()
    assert "btn-research-max" in text
    assert "max_queueable" in text
