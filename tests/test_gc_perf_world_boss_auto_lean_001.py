"""GC-PERF-WB-AUTO-LEAN-001 — background auto-fire must not build UI-only payloads."""

from __future__ import annotations

import inspect

from game import world_boss as wb


def test_execute_instant_attack_exposes_opt_in_lean_response():
    sig = inspect.signature(wb.execute_instant_attack)
    assert "lean_response" in sig.parameters
    assert sig.parameters["lean_response"].default is False


def test_lean_response_returns_before_rank_recognition_and_second_hangar_read():
    src = inspect.getsource(wb.execute_instant_attack)
    lean_pos = src.index("if lean_response:")
    contrib_pos = src.index("contrib_row = conn.execute")
    rank_pos = src.index("contribs = list_contributions")
    hangar_pos = src.index("hangar_after = get_planet_ships")
    recognition_pos = src.index("build_world_boss_recognition")

    assert lean_pos < contrib_pos < rank_pos < hangar_pos < recognition_pos
    lean_block = src[lean_pos:contrib_pos]
    assert '"damage": int(applied)' in lean_block
    assert '"defeated": bool(defeated)' in lean_block
    assert '"event_id": int(eid)' in lean_block


def test_background_tick_enables_lean_response_only_for_worker_path():
    maybe_src = inspect.getsource(wb.maybe_fire_ready_auto_attack)
    tick_src = inspect.getsource(wb.tick_world_boss_auto_attacks)
    flush_src = inspect.getsource(wb.flush_ready_auto_attacks_for_player)
    enable_src = inspect.getsource(wb.set_world_boss_auto_attack)

    assert "lean_response: bool = False" in maybe_src
    assert "lean_response=bool(lean_response)" in maybe_src
    assert "lean_response=True" in tick_src

    # Player-facing opportunistic flush and immediate enable strike keep the
    # rich response (attack/boss/player) for the UI.
    assert "lean_response=True" not in flush_src
    assert "lean_response=True" not in enable_src


def test_lean_exit_stays_after_gameplay_side_effects_and_defeat_announcement():
    src = inspect.getsource(wb.execute_instant_attack)
    lean_pos = src.index("if lean_response:")

    required_before_lean = (
        "_upsert_contribution(",
        "_advance_world_boss_raid_after_hit(",
        "grant_alliance_xp(",
        "emit_world_boss_damage_event(",
        "_announce_defeat(updated, conn=conn)",
    )
    for marker in required_before_lean:
        assert src.index(marker) < lean_pos, marker
