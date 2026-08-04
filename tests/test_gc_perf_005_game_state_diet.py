"""GC-PERF-005 — lightweight /api/game-state poll payload diet."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_live_state_diet_drops_page_catalog_blocks():
    live = _read("game/live_state.py")
    diet = live.split("def apply_lightweight_game_state_diet(payload")[1].split("def apply_action_state_diet")[0]
    for key in (
        "buildings",
        "codex",
        "imperial_directives",
        "planet_relocation",
        "has_seed_ark",
    ):
        assert f'"{key}"' in diet
    assert "active_planet_poll_slice" in live
    assert "planets_poll_slice" in live
    assert "active_fleets_poll_slice" in live
    assert "fleet_alerts_poll_slice" in live
    assert "notification_revision" in diet
    assert "fleet_alerts_poll_slice" in diet


def test_app_skips_heavy_blocks_on_lightweight_payload():
    app = _read("app.py")
    block = app.split("def _payload_from_live_context(")[1].split("def _build_game_state_payload(")[0]
    assert "if not lightweight:" in block
    assert "codex_for_game_state" in block
    assert "imperial_directives_for_game_state" in block
    assert "get_relocation_client_state" in block
    assert "player_has_seed_ark" in block
