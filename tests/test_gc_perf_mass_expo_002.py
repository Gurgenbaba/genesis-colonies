"""GC-PERF-MASS-EXPO-002 — mass-expedition previews must never serialize on planet writes."""

from pathlib import Path


def _block(path: str, start: str, end: str) -> str:
    src = Path(path).read_text(encoding="utf-8")
    return src.split(start, 1)[1].split(end, 1)[0]


def test_mass_expo_preview_is_resource_read_only():
    block = _block(
        "game/fleet.py",
        "def preview_mass_expedition_slot_split(",
        "def mass_expedition_from_ships(",
    )
    assert "validate_fleet_send(" in block
    assert "persist_resources=False" in block


def test_mass_expo_response_uses_fleet_mutation_slim_path():
    src = Path("app.py").read_text(encoding="utf-8")
    live = _block(
        "app.py",
        "_FLEET_MUTATION_LIVE_SOURCES = frozenset(",
        "def _use_poll_live_path(",
    )
    assert '"api_fleet_mass_expedition"' in live

    diet = _block(
        "app.py",
        "def _uses_action_state_diet(",
        "def _hud_only_game_state(",
    )
    assert '"api_fleet_mass_expedition"' in diet

    skip = _block(
        "app.py",
        "_FLEET_TICK_SKIP_ENDPOINTS = frozenset(",
        "_FLEET_TICK_SKIP_PREFIXES",
    )
    assert '"api_fleet_mass_expedition"' in skip
    assert '"api_fleet_mass_expedition_preview"' in skip

def test_action_state_diet_compacts_fleet_hud_after_batch_launch():
    src = Path("game/live_state.py").read_text(encoding="utf-8")
    action = src.split("def apply_action_state_diet(", 1)[1].split(
        "\n# ---------------------------------------------------------------------------\n# GC-PERF-REQUEST-TRACE", 1
    )[0]
    assert 'payload["active_fleets"] = active_fleets_poll_slice' in action
    assert 'payload["fleet_alerts"] = fleet_alerts_poll_slice' in action

