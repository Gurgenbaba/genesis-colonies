"""Regression gates for the PostgreSQL Shipyard SSR request connection boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _shipyard_block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def shipyard_view():", 1)[1].split('@app.route("/defense")', 1)[0]


def test_shipyard_ssr_uses_one_request_connection():
    block = _shipyard_block()
    assert block.count("conn = db()") == 1
    assert '_load_page_live_context(finish_source="shipyard", conn=conn, close_conn=False)' in block
    assert "_load_player_view_with_resources()" not in block


def test_shipyard_reuses_live_context_planet_and_resources():
    block = _shipyard_block()
    assert 'player_view = ctx["player_view"]' in block
    assert 'planet = ctx.get("planet")' in block
    assert "get_request_context_planet" in block
    assert 'energy_total=ctx["energy_total"]' in block
    assert 'energy_used=ctx["energy_used"]' in block
    assert 'storage_caps=ctx["storage_caps"]' in block
    assert "planet=planet" in block


def test_shipyard_page_builder_keeps_caller_owned_connection():
    block = _shipyard_block()
    assert "build_shipyard_page_context" in block
    assert "conn=conn" in block
    assert "fleet_schema_ready(conn)" in block
