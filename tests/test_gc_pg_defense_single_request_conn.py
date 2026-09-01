"""Regression gates for the PostgreSQL Defense SSR request connection boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _defense_block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def defense_view():", 1)[1].split('@app.route("/combat-simulator")', 1)[0]


def test_defense_ssr_uses_one_request_connection():
    block = _defense_block()
    assert block.count("conn = db()") == 1
    assert '_load_page_live_context(finish_source="defense", conn=conn, close_conn=False)' in block
    assert "_load_player_view_with_resources()" not in block


def test_defense_reuses_live_context_planet_and_resources():
    block = _defense_block()
    assert 'player_view = ctx["player_view"]' in block
    assert 'planet = ctx.get("planet")' in block
    assert "get_request_context_planet" in block
    assert 'energy_total=ctx["energy_total"]' in block
    assert 'energy_used=ctx["energy_used"]' in block
    assert 'storage_caps=ctx["storage_caps"]' in block


def test_defense_page_builder_keeps_caller_owned_connection():
    block = _defense_block()
    assert "build_defense_page_context" in block
    assert "conn=conn" in block
