"""Unbounded runtime arithmetic contract for Case Battle Share settlement."""

from __future__ import annotations

from pathlib import Path

from game.case_battles import _compute_settlement_grants, _largest_remainder_split

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_largest_remainder_split_handles_10_pow_400_weights_and_amounts():
    total = HUGE * 6
    split = _largest_remainder_split(
        total,
        {
            11: HUGE,
            22: HUGE * 2,
            33: HUGE * 3,
        },
    )
    assert split == {
        11: HUGE,
        22: HUGE * 2,
        33: HUGE * 3,
    }
    assert sum(split.values()) == total


def test_largest_remainder_tie_break_still_prefers_lower_user_id():
    assert _largest_remainder_split(1, {7: HUGE, 3: HUGE}) == {7: 0, 3: 1}


def test_share_settlement_uses_exact_reward_value_weights():
    players = [
        {"user_id": 1, "slot": 0},
        {"user_id": 2, "slot": 1},
    ]
    rolls = [
        {
            "user_id": 1,
            "round_index": 0,
            "reward_key": "fragment_dna_common",
            "reward_amount": 2,
            "reward_value": HUGE,
        },
        {
            "user_id": 2,
            "round_index": 0,
            "reward_key": "fragment_dna_common",
            "reward_amount": 2,
            "reward_value": HUGE * 3,
        },
    ]

    display, winner_ids, grants, meta = _compute_settlement_grants(
        "share",
        players,
        rolls,
    )

    by_user = {int(row["user_id"]): int(row["amount"]) for row in grants}
    assert display == 2
    assert winner_ids == [2]
    assert by_user == {1: 1, 2: 3}
    assert sum(by_user.values()) == 4
    assert int(meta["1"]) == HUGE
    assert int(meta["2"]) == HUGE * 3
    assert meta["_kind"] == "share"


def test_case_battle_share_source_has_no_reward_value_float_roundtrip():
    source = (ROOT / "game" / "case_battles.py").read_text(encoding="utf-8")

    for forbidden in (
        "sum(max(0.0, float(v)) for v in weights.values())",
        "amt * max(0.0, float(v)) / wsum",
        "float(totals.get(uid, 0)) / float(total_rv)",
    ):
        assert forbidden not in source

    assert "product = amt * weight" in source
    assert "product // wsum" in source
    assert "product % wsum" in source
