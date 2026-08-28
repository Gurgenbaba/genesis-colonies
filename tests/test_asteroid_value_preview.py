from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from game.asteroids import (
    STANDARD_BELT_BASE_MULTIPLIER,
    _roll_loot,
    _standard_belt_scale_map,
)


def _mine_conn(level: int) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE planet_buildings (metal_mine INTEGER, crystal_mine INTEGER, fuel_cell_plant INTEGER);"
    )
    for _ in range(10):
        conn.execute(
            "INSERT INTO planet_buildings (metal_mine, crystal_mine, fuel_cell_plant) VALUES (?, ?, ?);",
            (level, level, level),
        )
    return conn


def test_standard_belt_level30_floor_is_materially_higher_than_legacy_roll():
    conn = _mine_conn(30)
    try:
        legacy = _roll_loot("mixed_belt", rng=random.Random(77))
        scaled = _roll_loot("mixed_belt", rng=random.Random(77), conn=conn)
        assert STANDARD_BELT_BASE_MULTIPLIER == 5.0
        for resource in ("metal", "crystal", "fuel_cells"):
            assert scaled[resource] >= int(legacy[resource] * 4.99)
    finally:
        conn.close()


def test_standard_belt_keeps_scaling_beyond_level30_without_hard_cap():
    low = _mine_conn(30)
    high = _mine_conn(80)
    try:
        low_scale = _standard_belt_scale_map(low)
        high_scale = _standard_belt_scale_map(high)
        for resource in ("metal", "crystal", "fuel_cells"):
            assert low_scale[resource] >= 5.0
            assert high_scale[resource] > low_scale[resource]
    finally:
        low.close()
        high.close()


def test_galaxy_asteroid_preview_uses_server_fleet_preview_and_no_client_fuel_math():
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    assert 'fetchGameAction("/api/fleet/preview"' in js
    assert "loadAsteroidFlightPreview" in js
    assert "data-galaxy-asteroid-flight-preview" in js
    assert "preview.fuel_cost" in js
    assert "preview.fuel_available" in js
    assert 'mission_type: "recycle"' in js
    assert "calculate_fuel_cost" not in js


def test_galaxy_asteroid_fuel_preview_uses_resource_artwork_without_layout_shift():
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    resource_js = (root / "static/js/galaxy-asteroid-resource-ui.js").read_text(encoding="utf-8")
    galaxy = (root / "templates/galaxy.html").read_text(encoding="utf-8")
    board = (root / "templates/partials/galaxy_asteroid_board.html").read_text(encoding="utf-8")
    block = (root / "templates/partials/galaxy_asteroid_block.html").read_text(encoding="utf-8")

    for template in (board, block):
        assert "img/res/Brennzellen.webp" in template
        assert "data-galaxy-asteroid-flight-preview>—</span>" in template
        assert "data-galaxy-asteroid-flight-preview>⛽ —</span>" not in template

    assert "img/res/Ferronit.webp" in board
    assert "img/res/Crytite.webp" in board
    assert "img/res/Ferronit.webp" in block
    assert "img/res/Crytite.webp" in block
    assert 'if (!line) return;' in js
    assert "const fuelIcon = String.fromCodePoint(0x26fd);" in js
    assert 'line = document.createElement("span")' not in js
    assert "galaxy-asteroid-resource-ui.js" in galaxy
    assert "legacyFuelGlyph = String.fromCodePoint(0x26fd)" in resource_js
    assert "value.slice(legacyFuelGlyph.length + 1)" in resource_js


def test_galaxy_asteroid_board_preloads_fuel_on_open_and_has_scoped_layout_css():
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    board = (root / "templates/partials/galaxy_asteroid_board.html").read_text(encoding="utf-8")
    css = (root / "static/css/galaxy-asteroid-board.css").read_text(encoding="utf-8")

    assert "ASTEROID_PREVIEW_CONCURRENCY = 3" in js
    assert "preloadAsteroidFlightPreviews" in js
    assert "if (preferOpen) void this.preloadAsteroidFlightPreviews(root, board);" in js
    assert "if (open) void this.preloadAsteroidFlightPreviews(root, board);" in js
    assert "Promise.allSettled(workers)" in js
    assert "css/galaxy-asteroid-board.css" in board
    assert ".galaxy-asteroid-board-row-meta" in css
    assert ".galaxy-asteroid-board-harvest-wrap" in css
    assert ".galaxy-asteroid-resource-icon" in css
    assert "border-radius: 0 !important;" in css
    assert "border-radius: 3px" not in css
    assert "border-radius: 4px" not in css
