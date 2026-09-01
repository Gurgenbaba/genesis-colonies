"""Regression gates for the PostgreSQL World Boss SSR request connection boundary."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _world_boss_view_block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def world_boss_view():", 1)[1].split('@app.route("/api/world-boss")', 1)[0]


def test_world_boss_ssr_uses_one_request_connection():
    block = _world_boss_view_block()
    assert block.count("conn = db()") == 1
    assert '_load_page_live_context(finish_source="world_boss", conn=conn, close_conn=False)' in block
    assert "_load_player_view_with_resources" not in block


def test_world_boss_payload_reuses_request_connection_and_stays_read_only():
    block = _world_boss_view_block()
    assert "build_world_boss_payload(player_id, conn=conn)" in block
    assert "flush_auto=True" not in block
    assert "begin_write_transaction" not in block
    assert 'player=ctx["player_view"]' in block
    assert 'buildings=ctx["buildings"]' in block
    assert 'energy_total=ctx["energy_total"]' in block
    assert 'energy_used=ctx["energy_used"]' in block
    assert 'storage_caps=ctx["storage_caps"]' in block
