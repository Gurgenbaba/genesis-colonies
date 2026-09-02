"""GC-PERF-FLEET-LOGISTICS-002/003 — lean read-only Logistics page context."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _page_block() -> str:
    src = _read("game/fleet.py")
    return src.split("def build_logistics_page_context(", 1)[1].split(
        "def build_fleet_page_context(", 1
    )[0]


def test_logistics_page_context_resource_ticks_are_read_only():
    block = _page_block()

    assert "GC-PERF-FLEET-LOGISTICS-002" in block
    assert "update_planet_resources(" in block
    assert "persist=False" in block
    assert "stock = planet_resource_stock(planet_live)" in block


def test_logistics_page_context_batches_hangar_reads():
    block = _page_block()

    assert "GC-PERF-FLEET-LOGISTICS-003" in block
    assert "SELECT planet_id, ship_key, amount" in block
    assert "FROM planet_ships" in block
    assert "WHERE player_id = ? AND amount > 0" in block
    assert "ships_by_planet" in block
    assert "get_planet_ships(pid, conn=conn)" not in block
    assert '"ships": get_planet_ships(planet_id, conn=conn)' not in block
    assert '"ships": dict(ships_by_planet.get(int(planet_id)) or {})' in block


def test_mutating_logistics_paths_keep_persisting_behavior():
    src = _read("game/fleet.py")
    page_block = _page_block()
    rest = src.replace(page_block, "", 1)

    # The optimization is page-context scoped; do not globally turn resource
    # persistence off for Collect/Distribute previews/actions/settlement.
    assert rest.count("update_planet_resources(") >= 1
    assert "persist=bool(persist_resources)" in rest
