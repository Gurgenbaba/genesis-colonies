"""Regression gates for Imperial Directives PostgreSQL request connection ownership."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _view_block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def imperial_directives_view():", 1)[1].split('@app.route("/api/initiation/state")', 1)[0]


def test_imperial_directives_ssr_uses_one_request_connection():
    block = _view_block()
    assert block.count("conn = db()") == 1
    assert 'finish_source="imperial_directives"' in block
    assert "conn=conn" in block
    assert "close_conn=False" in block
    assert "get_imperial_directives_state(" in block


def test_directive_score_scaling_reuses_caller_connection():
    src = (ROOT / "game" / "directives" / "generator.py").read_text(encoding="utf-8")
    block = src.split("def _player_total_score(", 1)[1].split("\n\ndef ", 1)[0]
    assert "get_player_score_cached(int(player_id), read_only=True, conn=conn)" in block
    assert "get_player_score_cached(int(player_id), read_only=True)" not in block
