"""GC-PERF-FLEET-LOGISTICS-002 — Logistics page context must not persist colony ticks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_logistics_page_context_resource_ticks_are_read_only():
    src = _read("game/fleet.py")
    block = src.split("def build_logistics_page_context(", 1)[1].split(
        "def build_fleet_page_context(", 1
    )[0]

    assert "GC-PERF-FLEET-LOGISTICS-002" in block
    assert "update_planet_resources(" in block
    assert "persist=False" in block
    assert "stock = planet_resource_stock(planet_live)" in block


def test_mutating_logistics_paths_keep_persisting_behavior():
    src = _read("game/fleet.py")
    page_block = src.split("def build_logistics_page_context(", 1)[1].split(
        "def build_fleet_page_context(", 1
    )[0]
    rest = src.replace(page_block, "", 1)

    # The optimization is page-context scoped; do not globally turn resource
    # persistence off for Collect/Distribute previews/actions/settlement.
    assert rest.count("update_planet_resources(") >= 1
    assert "persist=bool(persist_resources)" in rest
