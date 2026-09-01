"""Regression gate for Trader Hub PostgreSQL request connection ownership."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _block() -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("def trader_hub_view():", 1)[1].split('# --------------------------------------------------------------------------\n# BUILDINGS', 1)[0]


def test_trader_hub_uses_one_request_connection():
    block = _block()
    assert block.count("conn = db()") == 1
    assert 'finish_source="trader_hub"' in block
    assert "conn=conn" in block
    assert "close_conn=False" in block
    assert 'planet = ctx.get("planet") or get_context_planet' in block


def test_trader_hub_state_builders_share_request_connection():
    block = _block()
    assert "exchange_schema_ready(conn)" in block
    assert "get_exchange_status(" in block
    assert "scrapyard_status(uid, pid, conn=conn)" in block
    assert "build_collector_exchange_payload(uid, conn=conn)" in block
