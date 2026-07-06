"""Galaxy empty-slot colonize vs relocate UI contract."""

from __future__ import annotations

from pathlib import Path


def test_galaxy_fleet_actions_empty_slot_relocate_when_no_ark():
    tpl = Path("templates/partials/galaxy_fleet_actions.html").read_text(encoding="utf-8")
    assert "has_seed_ark" in tpl
    assert "data-galaxy-relocation-start" in tpl
    assert "galaxy-fleet-action--colonize" in tpl
    assert "galaxy-fleet-action--relocate" in tpl


def test_galaxy_ring_view_exposes_seed_ark_flag():
    tpl = Path("templates/partials/galaxy_ring_view.html").read_text(encoding="utf-8")
    assert "data-has-seed-ark" in tpl
