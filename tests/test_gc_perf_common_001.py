"""GC-PERF-COMMON-001 — common shell/action reads must not re-run heavy live mutations."""

from pathlib import Path

import pytest

pytest_plugins = ("tests.test_game_state_live",)


def test_read_only_live_state_reuses_effect_snapshot_for_storage(game_client, monkeypatch):
    import game.logic as logic
    from game.db import db
    from game.models import load_player
    from game.planet_evolution.repository import get_context_planet

    _client, uid = game_client
    conn = db()
    try:
        player = load_player(int(uid), conn=conn)
        planet = get_context_planet(int(uid), conn=conn)

        def duplicate_modifier_stack(*_args, **_kwargs):
            raise AssertionError("storage must reuse the already-built EffectResolver modifiers")

        monkeypatch.setattr(logic, "_get_research_modifiers", duplicate_modifier_stack)
        player_view, buildings, ratio, energy_total, energy_used, caps = (
            logic._read_player_live_state_no_writes(int(uid), conn, player, planet)
        )
        assert int(player_view["id"]) == int(uid)
        assert isinstance(buildings, dict)
        assert ratio >= 0
        assert energy_total >= 0
        assert energy_used >= 0
        assert int(caps["metal"]) > 0
    finally:
        conn.close()


def test_admin_shell_read_only_bypasses_page_live_refresh(game_client, monkeypatch):
    import app as app_module

    _client, uid = game_client

    def forbidden(*_args, **_kwargs):
        raise AssertionError("admin shell must not finish queues through _load_page_live_context")

    monkeypatch.setattr(app_module, "_load_page_live_context", forbidden)
    with app_module.app.test_request_context("/admin"):
        from flask import session

        session["user_id"] = int(uid)
        player_view, buildings, ratio, energy_total, energy_used, caps = (
            app_module._load_player_view_with_resources(
                finish_source="admin_panel",
                read_only=True,
            )
        )
        assert int(player_view["id"]) == int(uid)
        assert isinstance(buildings, dict)
        assert ratio >= 0
        assert energy_total >= 0
        assert energy_used >= 0
        assert int(caps["metal"]) > 0


def test_inventory_post_mutation_context_uses_read_mostly_game_state_source():
    src = Path("app.py").read_text(encoding="utf-8")
    block = src.split("def _inventory_action_context(", 1)[1].split(
        "def _inventory_action_error_response(", 1
    )[0]
    assert 'include_panel=False' in block
    assert 'finish_source="game_state"' in block
    assert 'include_panel=True' not in block


def test_admin_route_declares_read_only_shell():
    src = Path("app.py").read_text(encoding="utf-8")
    block = src.split("def admin_panel():", 1)[1].split(
        '@app.route("/admin/update"', 1
    )[0]
    assert 'read_only=True' in block
    assert 'finish_source="admin_panel"' in block
