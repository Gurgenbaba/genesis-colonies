from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_block(source: str, name: str, next_name: str) -> str:
    return source.split(f"def {name}(", 1)[1].split(f"\ndef {next_name}(", 1)[0]


def test_fleet_hud_payload_never_finishes_movements():
    source = (ROOT / "game" / "live_state.py").read_text(encoding="utf-8")
    block = _function_block(source, "fleet_hud_for_game_state", "shipyard_panel_for_game_state")

    assert "GC-NAV-FLEET-READONLY-001" in block
    assert "process_fleet_tick" not in block
    assert "player_fleet_is_dirty" not in block
    assert "build_active_fleets_payload" in block
    assert "build_fleet_incoming_attack_alerts" in block
    assert "get_fleet_slot_status" in block


def test_poll_live_path_remains_the_only_http_fleet_finish_safety_net():
    source = (ROOT / "game" / "logic.py").read_text(encoding="utf-8")
    block = source.split("def read_player_live_state_for_poll(", 1)[1].split(
        "\ndef refresh_player_live_state(", 1
    )[0]

    assert "if fleet_dirty:" in block
    assert "process_player_due_fleets_now(uid, now=now)" in block
    assert "is_fleet_worker_heartbeat_fresh" not in block
    # HUD payload stays read-only; only the poll live-state owner may invoke
    # the bounded dedicated fleet deadline pass.
    assert "process_fleet_tick(" not in block


def test_pjax_navigation_uses_poll_live_path():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    block = source.split("def _use_poll_live_path(finish_source: str)", 1)[1].split("\ndef ", 1)[0]
    assert "_is_pjax_request()" in block
