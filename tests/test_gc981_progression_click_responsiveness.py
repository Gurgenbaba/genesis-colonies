"""
GC-981 — Progression action click responsiveness (no global actionLocks).

Run: python -m pytest tests/test_gc981_progression_click_responsiveness.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_progression_actions_use_per_button_busy_not_global_lock():
    src = _read("static/main.js")
    block = src.split("function initGameActions()")[1].split("function initToastStack()")[0]
    assert "function setProgressionActionBusy(el, busy)" in src
    assert "GC.actionLocks.build" not in block
    assert "GC.actionLocks.research" not in block
    assert "setProgressionActionBusy(upgradeEl, true)" in block


def test_queue_cancel_uses_per_button_busy():
    """GC-GUI-DECLUTTER-004: header HUD cancel removed; mini-queue / page cancels stay per-button."""
    src = _read("static/main.js")
    assert "_handleGlobalQueueHudCancel" not in src
    assert "setProgressionActionBusy" in src
    assert "GC.actionLocks.build" not in src.split("function initGameActions()")[1].split(
        "function initToastStack()"
    )[0]
    # Mini-queue / build cancel paths still arm busy on the clicked control.
    assert "setProgressionActionBusy(" in src
