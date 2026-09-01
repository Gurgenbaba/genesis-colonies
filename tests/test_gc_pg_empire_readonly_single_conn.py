"""Regression gates for PostgreSQL Empire GET pressure boundaries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _route_block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def empire_view():", 1)[1].split('@app.route("/trader-hub")', 1)[0]


def _context_block() -> str:
    src = (ROOT / "game" / "empire_page.py").read_text(encoding="utf-8")
    return src.split("def build_empire_context(", 1)[1]


def test_empire_ssr_uses_one_request_connection():
    block = _route_block()
    assert block.count("conn = db()") == 1
    assert '_load_page_live_context(finish_source="empire", conn=conn, close_conn=False)' in block
    assert "build_empire_context(uid, conn=conn, sync_resources=False)" in block
    assert "build_empire_context(uid)" not in block


def test_empire_get_does_not_sync_every_colony():
    block = _context_block()
    assert "sync_resources: bool = True" in block
    assert "if sync_resources:" in block
    assert "sync_player_planet_resources(" in block
    assert "finish_queue_first=True" in block
    assert "sync_resources=False" in _route_block()


def test_empire_score_read_reuses_caller_connection():
    block = _context_block()
    assert "get_player_score_cached(uid, read_only=True, conn=conn)" in block
