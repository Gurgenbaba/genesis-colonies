"""
GC-845 — Fleet init must not crash (syncFleetShipPickQtyMarks in scope).

Run: python -m pytest tests/test_gc845_fleet_init_contract.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc845_sync_fleet_ship_pick_qty_marks_module_scope():
    src = _read("static/main.js")
    sync_idx = src.index("function syncFleetShipPickQtyMarks(page)")
    init_idx = src.index("function initFleet()")
    assert sync_idx < init_idx
    assert "GC.syncFleetShipPickQtyMarks = syncFleetShipPickQtyMarks" in src
    init = src.split("function initFleet()")[1].split("function applyFleetUrlPrefill")[0]
    assert "GC.syncFleetShipPickQtyMarks(page)" in init


def test_gc845_init_fleet_before_module_registration():
    src = _read("static/main.js")
    assert src.index("function syncFleetShipPickQtyMarks(page)") < src.index("function initFleet()")
    assert src.index("GC.modules.fleet = initFleet") > src.index("function initFleet()")
