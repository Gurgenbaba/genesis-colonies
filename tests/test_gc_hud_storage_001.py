"""GC-HUD-STORAGE-001: visible storage capacity in resource bar from server caps."""

from __future__ import annotations

import uuid
from pathlib import Path

from game.db import db
from game.effects import EffectResolver
from game.models import get_homeworld, get_planet_buildings, get_research_levels, save_planet_buildings
from game.planet_evolution.service import colonize_planet

pytest_plugins = ["tests.test_game_state_live"]


def test_game_state_exposes_storage_caps_without_nested_duplicate(game_client):
    client, uid = game_client
    planet = get_homeworld(player_id=int(uid))
    save_planet_buildings(
        int(planet["id"]),
        {"metal_storage": 3, "crystal_storage": 2, "fuel_storage": 1, "solar_plant": 3},
    )
    expected = EffectResolver(
        get_planet_buildings(int(planet["id"])),
        get_research_levels(int(uid)),
    ).get_storage_capacity()

    body = client.get("/api/game-state").get_json()
    assert body.get("ok") is True
    storage = body.get("storage") or {}
    assert int(storage.get("metal") or 0) == int(expected["metal"])
    assert int(storage.get("crystal") or 0) == int(expected["crystal"])
    assert int(storage.get("fuel_cells") or 0) == int(expected["fuel_cells"])
    # Flat resource amounts remain numbers (no nested {current,capacity} break).
    assert isinstance(body.get("resources", {}).get("metal"), (int, float))
    # Nested capacity alias may exist; if present must match top-level storage.
    nested = (body.get("resources") or {}).get("storage")
    if isinstance(nested, dict):
        assert int(nested.get("metal") or 0) == int(storage["metal"])


def test_resource_bar_template_shows_visible_capacity_line():
    html = (Path("templates") / "base.html").read_text(encoding="utf-8")
    css = (Path("static") / "style.css").read_text(encoding="utf-8")
    metal = html.split("hud-res-metal")[1].split("hud-res-crystal")[0]
    crystal = html.split("hud-res-crystal")[1].split("hud-res-fuel-cells")[0]
    fuel = html.split("hud-res-fuel-cells")[1].split("hud-res-timekeeper")[0]
    for block in (metal, crystal, fuel):
        assert "hud-res-cap-line" in block
        assert "hud-res-cap-line--sr" not in block
        assert "res-cap" in block
    assert "GC-HUD-STORAGE-001" in html or "Lagerkapazität" in html
    # Narrow viewports keep numeric /cap (bar may hide).
    assert "keep numeric /cap on narrow" in css or "GC-HUD-STORAGE-001: keep numeric" in css


def test_overflow_amount_not_clamped_to_capacity_in_game_state(game_client):
    client, uid = game_client
    planet = get_homeworld(player_id=int(uid))
    pid = int(planet["id"])
    save_planet_buildings(pid, {"metal_storage": 0, "solar_plant": 2})
    caps = EffectResolver(
        get_planet_buildings(pid), get_research_levels(int(uid))
    ).get_storage_capacity()
    overflow = int(caps["metal"]) + 50_000
    conn = db()
    try:
        conn.execute("UPDATE planets SET metal = ? WHERE id = ?;", (overflow, pid))
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/game-state").get_json()
    assert body.get("ok") is True
    metal = float((body.get("resources") or {}).get("metal") or 0)
    cap = int((body.get("storage") or {}).get("metal") or 0)
    assert cap > 0
    assert metal > cap


def test_planet_switch_updates_storage_capacity(game_client):
    from conftest import unlock_colony_slots

    client, uid = game_client
    uid = int(uid)
    home = get_homeworld(player_id=uid)
    home_id = int(home["id"])
    save_planet_buildings(
        home_id,
        {
            "metal_mine": 1,
            "crystal_mine": 1,
            "solar_plant": 2,
            "metal_storage": 0,
            "crystal_storage": 0,
            "fuel_storage": 0,
        },
    )

    conn = db()
    try:
        unlock_colony_slots(conn, home_id, slots=1)
        conn.commit()
        ok, reason, extra = colonize_planet(
            uid,
            name=f"Colony_{uuid.uuid4().hex[:4]}",
            galaxy=1,
            system=301,
            position=8,
            conn=conn,
            allow_legacy_coordinates=True,
            source="test",
        )
        assert ok, reason
        colony_id = int(extra["planet_id"])
        conn.commit()
    finally:
        conn.close()

    save_planet_buildings(
        colony_id,
        {
            "metal_mine": 1,
            "crystal_mine": 1,
            "solar_plant": 2,
            "metal_storage": 12,
            "crystal_storage": 0,
            "fuel_storage": 0,
        },
    )

    home_cap = int(
        EffectResolver(
            get_planet_buildings(home_id), get_research_levels(uid)
        ).get_storage_capacity()["metal"]
    )
    colony_cap = int(
        EffectResolver(
            get_planet_buildings(colony_id), get_research_levels(uid)
        ).get_storage_capacity()["metal"]
    )
    assert colony_cap > home_cap

    r_home = client.post("/api/planets/active", json={"planet_id": home_id}).get_json()
    assert r_home.get("ok") is True
    home_state = r_home.get("state") or {}
    if home_state.get("storage"):
        assert int(home_state["storage"].get("metal") or 0) == home_cap
    else:
        body = client.get("/api/game-state").get_json()
        assert int((body.get("storage") or {}).get("metal") or 0) == home_cap

    r_colony = client.post("/api/planets/active", json={"planet_id": colony_id}).get_json()
    assert r_colony.get("ok") is True
    colony_state = r_colony.get("state") or {}
    if colony_state.get("storage"):
        assert int(colony_state["storage"].get("metal") or 0) == colony_cap
    else:
        body = client.get("/api/game-state").get_json()
        assert int((body.get("storage") or {}).get("metal") or 0) == colony_cap


def test_main_js_storage_warn_threshold_and_cap_source():
    js = (Path("static") / "main.js").read_text(encoding="utf-8")
    warn_fn = js.split("function patchHudStorageWarnings")[1].split(
        "function syncHeaderVacationBanner"
    )[0]
    assert "STORAGE_WARN_RATIO = 0.9" in warn_fn
    assert "resources.storage" in js
    assert 'bar.querySelectorAll(".res-cap.metal")' in js
    # Current amount must not be Math.min'd against storage when painting.
    paint = js.split("function patchShellHudFromState")[1].split(
        "function patchShellHudLiveResources"
    )[0]
    assert "Math.min(metal" not in paint
    assert "Math.min(fuelCells" not in paint
