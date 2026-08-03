"""Story Ops lore drawer + earned rewards summary."""

from __future__ import annotations

from game.story.service import _earned_rewards_summary, _lore_fragments


def test_lore_fragments_only_codex_flags():
    frags = _lore_fragments(
        {
            "codex_ark_signal": "1",
            "ark_signal_main_done": "1",
            "other": "1",
        }
    )
    assert len(frags) == 1
    assert frags[0]["flag"] == "codex_ark_signal"
    assert frags[0]["title"]


def test_earned_rewards_picks_inventory_when_reward_flag_set():
    summary = _earned_rewards_summary(
        {
            "codex_ark_signal": "1",
            "ark_signal_main_done": "1",
        }
    )
    assert summary["fragment_count"] == 1
    keys = {row["item_key"] for row in summary["items"]}
    assert "container_basic" in keys
