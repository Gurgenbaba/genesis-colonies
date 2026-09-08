"""GC-PERF-NAV-CONN-027 — read-page routes keep one request-owned DB connection."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _route_block(name: str) -> str:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    start = src.index(f"def {name}(")
    end = src.index("\ndef ", start + 5)
    return src[start:end]


def _assert_single_conn_live_context(name: str, finish_source: str, page_call: str) -> str:
    block = _route_block(name)
    assert block.count("conn = db()") == 1
    assert block.index("conn = db()") < block.index("_load_page_live_context(")
    live_call = block.split("_load_page_live_context(", 1)[1].split(")", 1)[0]
    assert f'finish_source="{finish_source}"' in live_call
    assert "conn=conn" in live_call
    assert "close_conn=False" in live_call
    page_args = block.split(page_call, 1)[1]
    assert "conn=conn" in page_args
    return block


def test_combat_simulator_reuses_request_connection():
    _assert_single_conn_live_context(
        "combat_simulator_view",
        "combat_simulator",
        "build_combat_simulator_page_context(",
    )


def test_vote_center_reuses_request_connection():
    _assert_single_conn_live_context(
        "vote_center_view",
        "vote_center",
        "get_vote_center_state(",
    )


def test_galactic_politics_reuses_request_connection():
    _assert_single_conn_live_context(
        "galactic_politics_view",
        "galactic_politics",
        "get_galactic_politics_state(",
    )


def test_inventory_reuses_request_connection_and_context_planet():
    block = _assert_single_conn_live_context(
        "inventory_view",
        "inventory",
        "build_inventory_state(",
    )
    assert "get_context_planet(" not in block
    assert 'planet = ctx.get("planet") or {}' in block
    assert "build_case_battles_state(int(user_id), conn=conn)" in block
