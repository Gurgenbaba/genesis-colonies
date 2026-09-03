"""GC-PERF-SHIPYARD-CATALOG-001 — one shared Shipyard catalog snapshot per payload."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src() -> str:
    return (ROOT / "game" / "shipyard.py").read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_shipyard_catalog_public_paths_are_defined_once():
    src = _src()

    assert src.count("\ndef list_buildable_ships(") == 1
    assert src.count("\ndef list_locked_ships(") == 1
    assert src.count("\ndef build_shipyard_api_payload(") == 1
    assert src.count("\ndef _build_shipyard_catalogs_shared(") == 1


def test_shipyard_api_payload_uses_one_shared_catalog_snapshot():
    src = _src()
    block = _block(
        src,
        "def build_shipyard_api_payload(",
        "def build_shipyard_page_context(",
    )

    assert "GC-PERF-SHIPYARD-CATALOG-001" in block
    assert block.count("_build_shipyard_catalogs_shared(") == 1
    assert "list_buildable_ships(" not in block
    assert "list_locked_ships(" not in block
    assert "get_ship_inventory(" not in block
    assert "get_shipyard_level(" not in block


def test_shared_catalog_loads_expensive_context_once_before_one_ship_loop():
    src = _src()
    block = _block(
        src,
        "def _build_shipyard_catalogs_shared(",
        "def list_buildable_ships(",
    )

    assert "GC-PERF-SHIPYARD-CATALOG-001" in block
    assert block.count("get_planet_buildings(") == 1
    assert block.count("get_research_levels(") == 1
    assert block.count("get_ship_inventory(") == 1
    assert block.count("resolve_unit_effect_context(") == 1
    assert block.count("forge_rank_for_planet(") == 1
    assert block.count("_shipyard_speed_multiplier(") == 1
    assert block.count("_directive_time_speed(") == 1
    assert block.count("for key in sort_ship_keys_by_role(ACTIVE_SHIP_KEYS):") == 1
    assert "locked.append(entry)" in block
    assert "buildable.append(entry)" in block


def test_per_ship_helpers_accept_shared_inputs_but_keep_fallbacks():
    src = _src()

    speed_block = _block(src, "def _effective_build_seconds(", "def unit_build_seconds(")
    assert "build_time_speed: float | None = None" in speed_block
    assert "if build_time_speed is not None" in speed_block
    assert "_shipyard_speed_multiplier(conn=conn)" in speed_block
    assert "_directive_time_speed(" in speed_block

    unlock_block = _block(src, "def ship_unlocked(", "def _ship_catalog_entry(")
    assert "buildings: Mapping[str, Any] | None = None" in unlock_block
    assert "research: Mapping[str, Any] | None = None" in unlock_block
    assert "if buildings is None:" in unlock_block
    assert "if research is None:" in unlock_block

    max_block = _block(src, "def max_build_amount_for_planet(", "def can_build_ship(")
    assert "unlocked: bool | None = None" in max_block
    assert "unit_cost: Mapping[str, Any] | None = None" in max_block
