"""GC-2505 — Story pack validation + admin preview contract."""

from __future__ import annotations

import pytest

from game.story.packs import PackValidationError, validate_all_packs, validate_pack
from game.story.service import admin_preview_packs


def test_all_story_packs_valid():
    ids = validate_all_packs()
    assert "ark_signal" in ids


def test_invalid_pack_rejected():
    with pytest.raises(PackValidationError):
        validate_pack({"pack_id": "x", "version": 1, "arcs": []}, source="bad")


def test_admin_preview_packs_lists_ark_signal():
    preview = admin_preview_packs()
    assert preview["ready"]
    pack_ids = {p["pack_id"] for p in preview["packs"]}
    assert "ark_signal" in pack_ids
    assert "living_lattice" in pack_ids
    assert "birth_of_worlds" in pack_ids
    assert "heat_and_shadow" in pack_ids
    assert "anomaly_protocol" in pack_ids
    assert "unlabeled_depth" in pack_ids
    assert "side_ops_year" in pack_ids
    ark = next(p for p in preview["packs"] if p["pack_id"] == "ark_signal")
    arc_ids = {a["arc_id"] for a in ark["arcs"]}
    assert {"main", "androgyn_echo", "void_patrol"} <= arc_ids
    assert int(ark.get("version") or 0) >= 3


def test_all_story_packs_include_living_lattice():
    ids = validate_all_packs()
    assert "living_lattice" in ids
    assert len(ids) >= 7


def test_year_one_packs_have_season_and_side_ops():
    preview = admin_preview_packs()
    by_id = {p["pack_id"]: p for p in preview["packs"]}
    assert by_id["ark_signal"].get("season_code") == "Q1"
    assert by_id["birth_of_worlds"].get("season_code") == "Q2"
    assert by_id["heat_and_shadow"].get("season_code") == "Q3"
    assert by_id["anomaly_protocol"].get("season_code") == "Q4"
    assert by_id["side_ops_year"].get("season_code") == "Y1"
    side = by_id["side_ops_year"]
    arc_ids = {a["arc_id"] for a in side["arcs"]}
    assert {
        "debris_choir",
        "steel_ledger",
        "fortress_line",
        "expo_return",
        "rare_ash",
        "void_teeth",
        "salt_watch",
    } <= arc_ids
