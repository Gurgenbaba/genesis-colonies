"""
GC-512: static contracts for build/research queues, polling, and AJAX state.

Run: python -m pytest tests/test_queue_static_contract.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc512_manual_qa_doc_exists():
    assert (ROOT / "docs/GC-512_QUEUE_MANUAL_QA.md").is_file()


def test_build_queue_reschedule_wired_on_enqueue_and_cancel():
    text = _read("game/buildings.py")
    assert "def recalculate_build_queue_finish_times(" in text
    cancel_block = text.split("def cancel_build_job_for_planet", 1)[1].split(
        "def ", 1
    )[0]
    enqueue_block = text.split("def queue_build_for_planet", 1)[1].split(
        "def cancel_build_job_for_planet", 1
    )[0]
    assert "recalculate_build_queue_finish_times(" in cancel_block
    assert "recalculate_build_queue_finish_times(" in enqueue_block
    assert "finish_due_work(" in enqueue_block
    assert "finish_due_work(" in cancel_block
    assert cancel_block.index("finish_due_work") < cancel_block.index("delete_build_job")
    assert "refund_build_job" in cancel_block or "queue_refund" in cancel_block
    assert cancel_block.index("delete_build_job") < cancel_block.index(
        "recalculate_build_queue_finish_times"
    )


def test_research_queue_reschedule_wired_on_enqueue_and_cancel():
    text = _read("game/research.py")
    assert "def recalculate_research_queue_finish_times(" in text
    cancel_block = text.split("def cancel_research_job", 1)[1].split("def ", 1)[0]
    enqueue_block = text.split("def queue_research(", 1)[1].split("def cancel_research_job", 1)[0]
    assert "recalculate_research_queue_finish_times(" in cancel_block
    assert "recalculate_research_queue_finish_times(" in enqueue_block
    assert "finish_due_work(" in enqueue_block
    assert "finish_due_work(" in cancel_block
    assert "refund_research_job" in cancel_block or "queue_refund" in cancel_block


def test_server_queue_remaining_non_negative():
    buildings = _read("game/buildings.py")
    assert re.search(r"remaining\s*=\s*max\s*\(\s*0\s*,", buildings)
    research = _read("game/research.py")
    assert re.search(r"remain\s*=\s*max\s*\(\s*0\s*,", research)


def test_single_game_state_poll_entrypoint_in_static():
    """Spiel-State nur über main.js — kein paralleles /api/game-state in Modul-JS."""
    offenders: list[str] = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in ("static/main.js", "static/admin.js"):
            continue
        text = path.read_text(encoding="utf-8")
        if "/api/game-state" in text or "/api/status" in text:
            offenders.append(rel)
    assert not offenders, f"Parallel game-state fetch in: {offenders}"


def test_main_js_queue_actions_use_apply_action_state():
    text = _read("static/main.js")
    for snippet in (
        '"/api/buildings/upgrade"',
        '"/api/buildings/cancel"',
        '"/api/research/start"',
        '"/api/research/cancel"',
    ):
        assert snippet in text
    assert text.count("applyActionState(json") >= 4
    assert "GC.polling" in text
    assert "function applyActionState(" in text or "function applyActionState (" in text
    assert "GC.cleanupPage" in text
    assert "GC.registerCleanup" in text


def test_main_js_clamps_queue_progress_display():
    text = _read("static/main.js")
    assert "Math.max(0, Math.min(100" in text
    assert "function assignMonotonicServerRemaining" in text
    assert "el.dataset.serverRemaining = String(next)" in text


def test_build_research_cancel_api_routes_return_action_state():
    text = _read("app.py")
    assert '"/api/buildings/cancel"' in text
    assert '"/api/research/cancel"' in text
    assert "_action_json_response" in text
