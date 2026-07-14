"""Galaxy coordinate system — foundation tests."""

from __future__ import annotations

import importlib
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.galaxy import (
    GALAXY_MIN,
    POSITION_MAX,
    SYSTEM_MAX,
    assign_free_coordinates,
    build_galaxy_nav,
    build_minimap_range,
    format_coordinates,
    get_galaxy_max,
    get_planet_coordinates,
    list_system,
    parse_coordinate_query,
    repair_missing_coordinates,
    resolve_view_coordinates,
)
from game.models import create_user, db, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.overview_page import build_planet_meta


@pytest.fixture()
def galaxy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "galaxy_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player() -> int:
    uname = f"gal_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    return int(user["id"])


def test_new_player_gets_coordinates(galaxy_db):
    uid = _create_player()
    planets = get_planets_by_player(uid)
    assert len(planets) >= 1
    hw = next(p for p in planets if int(p.get("is_homeworld") or 0) == 1)
    coords = get_planet_coordinates(hw)
    gmax = get_galaxy_max()
    assert GALAXY_MIN <= coords["galaxy"] <= gmax
    assert 1 <= coords["system"] <= SYSTEM_MAX
    assert 1 <= coords["position"] <= POSITION_MAX
    assert coords["position"] != 16


def test_new_homeworlds_are_not_sequential_cluster(galaxy_db):
    """Random bootstrap must not place every new player in [1:1:2], [1:1:3], …"""
    coords = []
    for _ in range(10):
        uid = _create_player()
        hw = next(p for p in get_planets_by_player(uid) if int(p.get("is_homeworld") or 0) == 1)
        coords.append(
            (int(hw["galaxy"]), int(hw["system"]), int(hw["position"]))
        )
    sequential_cluster = all(
        g == coords[0][0] and s == coords[0][1] and p == idx + 2
        for idx, (g, s, p) in enumerate(coords)
    )
    assert not sequential_cluster


def test_coordinates_are_unique(galaxy_db):
    ids = [_create_player() for _ in range(5)]
    seen = set()
    for uid in ids:
        for p in get_planets_by_player(uid):
            c = get_planet_coordinates(p)
            key = (c["galaxy"], c["system"], c["position"])
            assert key not in seen, key
            seen.add(key)


def test_repair_assigns_missing_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    pid = int(planet["id"])

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE planets SET system = NULL, position = NULL WHERE id = ?;", (pid,))
    conn.commit()
    conn.close()

    repaired = repair_missing_coordinates()
    assert repaired >= 1

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (pid,))
    row = dict(cur.fetchone())
    conn.close()
    coords = get_planet_coordinates(row)
    assert coords["formatted"] == format_coordinates(
        coords["galaxy"], coords["system"], coords["position"]
    )


def test_format_coordinates():
    assert format_coordinates(1, 42, 8) == "[1:42:8]"


def test_galaxy_view_href_full_position():
    from game.galaxy import galaxy_view_href

    assert galaxy_view_href("[1:42:8]") == "/galaxy?q=%5B1%3A42%3A8%5D"
    assert galaxy_view_href("2:100:3") == "/galaxy?q=%5B2%3A100%3A3%5D"
    assert galaxy_view_href("invalid") is None


def test_parse_coordinate_query():
    assert parse_coordinate_query("[1:42:8]") == {"galaxy": 1, "system": 42, "position": 8}
    assert parse_coordinate_query("2:100") == {"galaxy": 2, "system": 100}
    assert parse_coordinate_query("invalid") is None


def test_resolve_view_coordinates_search():
    g, s, pos = resolve_view_coordinates(default_galaxy=1, default_system=1, coord_query="1:77:3")
    assert g == 1 and s == 77 and pos == 3


def test_resolve_url_galaxy_and_system():
    g, s, pos = resolve_view_coordinates(
        default_galaxy=1,
        default_system=1,
        req_galaxy=1,
        req_system=304,
    )
    assert g == 1 and s == 304 and pos is None


def test_galaxy_change_preserves_system():
    g, s, _ = resolve_view_coordinates(
        default_galaxy=1,
        default_system=304,
        req_galaxy=2,
        carry_system=304,
    )
    assert g == 2 and s == 304


def test_clamp_respects_bounds(galaxy_db, monkeypatch):
    monkeypatch.setattr(
        "game.galaxy.get_galaxy_max",
        lambda conn=None: 3,
    )
    from game.galaxy import clamp_galaxy, clamp_system

    assert clamp_galaxy(99) == 3
    assert clamp_galaxy(0) == 1
    assert clamp_system(0) == 1
    assert clamp_system(999) == 499


def test_build_minimap_range(galaxy_db):
    cells = build_minimap_range(1, 10, viewer_player_id=1)
    assert len(cells) == 9
    assert any(c["is_current"] for c in cells)


def test_occupied_slot_includes_meta(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    data = list_system(
        coords["galaxy"],
        coords["system"],
        viewer_player_id=uid,
        active_planet_id=int(planet["id"]),
    )
    slot = next(
        s for s in data["slots"] if s["occupied"] and s["planet_id"] == int(planet["id"])
    )
    assert slot["planet_class_label_key"]
    assert slot["temperature_display"]
    assert slot["planet_score"] is not None
    assert slot["is_own_planet"] is True
    assert slot["is_active_planet"] is True


def test_galaxy_page_url_system_304(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"url_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    resp = client.get("/galaxy?view=system&galaxy=1&system=304")
    assert resp.status_code == 200
    assert "304" in resp.get_data(as_text=True)


def test_empty_slot_not_colony_target(galaxy_db):
    data = list_system(1, 499)
    empty = next(s for s in data["slots"] if not s["occupied"])
    assert empty["colony_target"] is False


def test_build_galaxy_nav_multi_galaxy_flag(galaxy_db, monkeypatch):
    monkeypatch.setenv("GC_GAME_SETTINGS", "")
    nav = build_galaxy_nav(1, 5)
    assert "multi_galaxy" in nav
    assert nav["has_prev_galaxy"] is False


def test_get_planet_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    assert coords["formatted"] == format_coordinates(
        coords["galaxy"], coords["system"], coords["position"]
    )


def test_list_system_returns_15_slots(galaxy_db):
    data = list_system(1, 1)
    assert data["galaxy"] == 1
    assert data["system"] == 1
    assert len(data["slots"]) == 15
    positions = [s["position"] for s in data["slots"]]
    assert positions == list(range(1, 16))


def test_occupied_slots_have_data(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    data = list_system(coords["galaxy"], coords["system"])
    slot = next(s for s in data["slots"] if s["occupied"] and s["planet_id"] == int(planet["id"]))
    assert slot["planet_name"]
    assert slot["commander_name"]
    assert slot["player_id"] == uid
    assert slot["coordinates_formatted"] == coords["formatted"]


def test_empty_slots_are_marked_empty(galaxy_db):
    data = list_system(1, 499)
    empty = [s for s in data["slots"] if not s["occupied"]]
    assert len(empty) == 15
    for slot in empty:
        assert slot["planet_id"] is None
        assert slot["player_id"] is None
        assert slot["coordinates_formatted"] == format_coordinates(1, 499, slot["position"])


def test_list_system_shows_debris_field(galaxy_db):
    from game.combat import add_debris_field

    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    conn = db()
    try:
        add_debris_field(
            coords["galaxy"],
            coords["system"],
            coords["position"],
            12_000,
            3400,
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    data = list_system(coords["galaxy"], coords["system"])
    slot = next(s for s in data["slots"] if s["position"] == coords["position"])
    assert slot["has_debris"] is True
    assert slot["debris"]["metal"] == 12_000
    assert slot["debris"]["crystal"] == 3400
    assert slot["debris"]["total"] == 15_400
    assert slot["debris"]["ttl_remaining_seconds"] >= 0
    assert slot["debris"]["ttl_display"]
    assert slot["debris"]["recycler_slots_needed"] >= 1
    assert "mission=recycle" in slot["debris"]["recycle_href"]
    assert f"target_position={coords['position']}" in slot["debris"]["recycle_href"]


def test_overview_uses_real_coordinates(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    meta = build_planet_meta(planet)
    assert meta["coordinates"]["display"] == format_coordinates(
        meta["coordinates"]["galaxy"],
        meta["coordinates"]["system"],
        meta["coordinates"]["position"],
    )
    assert "?" not in meta["coordinates"]["display"]
    assert "Sektor" not in meta["coordinates"]["display"]


def test_galaxy_page_loads(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"page_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    resp = client.get("/galaxy?view=system")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "galaxy-ring-view" in body or "data-galaxy-ring-view" in body
    assert "galaxy-hud-module" in body
    assert "galaxy-hud-header" in body
    assert "galaxy-hud-controls" in body
    assert "data-galaxy-ring-stage" in body
    assert "galaxy-ring-stage--compact" in body
    assert 'data-orbit-band="hot"' in body or 'data-orbit-band=\"hot\"' in body
    assert 'data-orbit-band="temperate"' in body or 'data-orbit-band=\"temperate\"' in body
    assert 'data-orbit-band="cold"' in body or 'data-orbit-band=\"cold\"' in body
    assert 'data-orbit-band="expedition"' in body or 'data-orbit-band=\"expedition\"' in body
    assert "data-galaxy-hud-body" in body
    assert "galaxy-hud-search" not in body
    assert "galaxy-hud-coord-q" not in body
    assert "galaxy-hud-scan-btn" not in body
    assert "galaxy-system-range" not in body
    assert "galaxy-nav-bar" not in body
    assert "galaxy-nav-step" not in body
    assert "data-galaxy-ring-compact" not in body
    assert "galaxy-ring-compact-toggle" not in body
    assert "galaxy-table" not in body.lower()
    assert body.count("galaxy-hud-group") == 2
    assert "data-galaxy-hud-galaxy-input" in body
    assert "data-galaxy-hud-system-input" in body
    assert 'inputmode="numeric"' in body
    assert "galaxy-hud-value--fixed" not in body
    assert "data-player-card" in body
    assert "galaxy-fleet-action" in body
    assert "galaxy-ring-orbit--hot" not in body
    assert "img/expedition/expedition.png" in body
    from pathlib import Path
    ring_css = Path(__file__).resolve().parents[1].joinpath("static", "style.css").read_text(encoding="utf-8")
    assert "galaxy-ring-debris-marker" in ring_css or "galaxy-ring-debris-marker-img" in ring_css
    assert "img/debris/debris.jpg" in ring_css
    assert "galaxy-ring-inspector--card" in body
    assert "galaxy-ring-slot-owner-label" in body
    assert uname in body
    assert "galaxy-ring-inspector--side" not in body
    assert "galaxy-ring-inspector--dock" not in body
    assert "galaxy_slot_empty" in body or "Leer" in body or "Empty" in body


def test_list_system_slot_ring_presentation(galaxy_db):
    from game.planet_visuals import ORBIT_RING_COLD, ORBIT_RING_HOT, ORBIT_RING_TEMPERATE

    data = list_system(1, 1)
    by_pos = {int(s["position"]): s for s in data["slots"]}
    hot = by_pos[1]
    assert hot["orbit_ring"] == ORBIT_RING_HOT
    assert hot["temperature_band"] == ORBIT_RING_HOT
    assert hot["orbit_angle_deg"] == -90.0
    assert hot["orbit_layout_band"] == ORBIT_RING_HOT
    assert hot["orbit_radius_ref"] == 182
    assert hot["visual_effect"] == "volcanic"
    assert hot["planet_image_relpath"].startswith("img/")
    temperate = by_pos[8]
    assert temperate["orbit_ring"] == ORBIT_RING_TEMPERATE
    assert temperate["orbit_angle_deg"] == 90.0
    assert temperate["orbit_layout_band"] == ORBIT_RING_TEMPERATE
    assert temperate["visual_effect"] == "temperate"
    cold = by_pos[15]
    assert cold["orbit_ring"] == ORBIT_RING_COLD
    assert cold["orbit_angle_deg"] == 180.0
    assert cold["orbit_layout_band"] == ORBIT_RING_COLD
    assert cold["visual_effect"] == "ice"
    assert cold["planet_theme"] == "absolute-zero"


def test_list_system_occupied_slot_uses_herocard_image(galaxy_db):
    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    data = list_system(coords["galaxy"], coords["system"], viewer_player_id=uid)
    slot = next(s for s in data["slots"] if s["occupied"])
    assert slot["planet_image_relpath"].startswith("img/herocards/")
    assert slot["herocard_relpath"] == slot["planet_image_relpath"]
    assert slot["landscape_relpath"].startswith("img/landscapes/")


def test_list_system_slot_coordinates_match_position(galaxy_db):
    uid = _create_player()
    conn = db()
    try:
        data = list_system(1, 1, conn=conn, viewer_player_id=uid)
    finally:
        conn.close()
    seen = set()
    for slot in data["slots"]:
        pos = int(slot["position"])
        coords = slot["coordinates"]
        key = (int(coords["galaxy"]), int(coords["system"]), int(coords["position"]))
        assert key not in seen
        seen.add(key)
        assert int(coords["position"]) == pos
        assert format_coordinates(*key) == format_coordinates(
            int(coords["galaxy"]), int(coords["system"]), int(coords["position"])
        )


def test_list_system_exposes_player_status_flags(galaxy_db):
    import time

    from game.db import column_exists

    viewer_id = _create_player()
    foreign_id = _create_player()
    conn = db()
    try:
        viewer_hw = next(
            p for p in get_planets_by_player(viewer_id) if int(p.get("is_homeworld") or 0) == 1
        )
        foreign_hw = next(
            p for p in get_planets_by_player(foreign_id) if int(p.get("is_homeworld") or 0) == 1
        )
        vcoords = get_planet_coordinates(viewer_hw)
        g, s = int(vcoords["galaxy"]), int(vcoords["system"])
        viewer_pos = int(vcoords["position"])
        foreign_pos = next(
            p for p in range(1, 16) if p != viewer_pos
        )
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET galaxy = ?, system = ?, position = ? WHERE id = ?;",
            (g, s, foreign_pos, int(foreign_hw["id"])),
        )
        cur.execute(
            "UPDATE player_scores SET score_total = ? WHERE player_id = ?;",
            (1000, viewer_id),
        )
        cur.execute(
            "UPDATE player_scores SET score_total = ? WHERE player_id = ?;",
            (50000, foreign_id),
        )
        if column_exists(conn, "players", "last_seen"):
            cur.execute(
                "UPDATE players SET last_seen = ? WHERE id = ?;",
                (int(time.time()), foreign_id),
            )
        if column_exists(conn, "players", "vacation_mode_active"):
            cur.execute(
                "UPDATE players SET vacation_mode_active = 1 WHERE id = ?;",
                (foreign_id,),
            )
        conn.commit()

        data = list_system(g, s, conn=conn, viewer_player_id=viewer_id)
        foreign_slot = next(
            s for s in data["slots"] if int(s.get("player_id") or 0) == foreign_id
        )
        assert foreign_slot["attack_strength"] == "too_strong"
        assert foreign_slot["inactive"] is False
        assert foreign_slot["vacation_active"] is True

        if column_exists(conn, "players", "last_seen"):
            cur.execute(
                "UPDATE players SET last_seen = ? WHERE id = ?;",
                (int(time.time()) - 4 * 86400, foreign_id),
            )
            conn.commit()
            data = list_system(g, s, conn=conn, viewer_player_id=viewer_id)
            foreign_slot = next(
                s for s in data["slots"] if int(s.get("player_id") or 0) == foreign_id
            )
            assert foreign_slot["inactive"] is True
            assert foreign_slot["attack_strength"] is None
    finally:
        conn.close()


def _galaxy_client(monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"gal_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    return client, int(user["id"])


def _foreign_planet_in_system(galaxy: int, system: int, *, avoid_position: int | None = None):
    """Second player homeworld in the same galaxy/system as viewer tests."""
    ok, err, user = create_user(f"foreign_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Foreign")
    planet = get_planets_by_player(uid)[0]
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT position FROM planets
        WHERE galaxy = ? AND system = ? AND position BETWEEN 1 AND 15;
        """,
        (int(galaxy), int(system)),
    )
    taken = {int(row["position"]) for row in cur.fetchall()}
    if avoid_position is not None:
        taken.add(int(avoid_position))
    free_pos = next(p for p in range(1, 16) if p not in taken)
    cur.execute(
        "UPDATE planets SET galaxy = ?, system = ?, position = ? WHERE id = ?;",
        (int(galaxy), int(system), int(free_pos), int(planet["id"])),
    )
    conn.commit()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (int(planet["id"]),))
    coords = get_planet_coordinates(dict(cur.fetchone()))
    conn.close()
    return uid, int(planet["id"]), coords


def test_galaxy_own_planet_fleet_shortcuts(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    resp = client.get(
        f"/galaxy?view=system&galaxy={coords['galaxy']}&system={coords['system']}"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    pos = int(coords["position"])
    assert f"target_position={pos}" in body
    assert "mission=transport" in body
    assert "mission=deploy" in body
    assert "galaxy-fleet-action--transport" in body
    assert "galaxy-fleet-action--deploy" in body


def test_galaxy_foreign_planet_fleet_shortcuts(galaxy_db, monkeypatch):
    from game.fleet_defs import EXPEDITION_POSITION

    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    assert int(foreign_coords["position"]) != EXPEDITION_POSITION
    resp = client.get(f"/galaxy?view=system&galaxy={g}&system={s}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    fp = int(foreign_coords["position"])
    assert f"target_position={fp}" in body
    assert "mission=spy" in body
    assert "mission=attack" in body
    assert "data-galaxy-quick-spy" in body
    assert "data-galaxy-quick-attack" in body
    assert f'data-target-galaxy="{g}"' in body
    assert f'data-target-system="{s}"' in body
    assert f'data-target-position="{fp}"' in body
    assert "galaxy-fleet-action--spy" in body
    assert "galaxy-fleet-action--attack" in body
    assert "galaxy-fleet-action--quick-attack" in body


def test_galaxy_empty_slot_shows_colonize_fleet_shortcut(galaxy_db, monkeypatch):
    from game.db import commit
    from game.fleet import add_planet_ships

    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    conn = db()
    try:
        add_planet_ships(int(planet["id"]), uid, {"seed_ark": 1}, conn=conn)
        commit(conn)
    finally:
        conn.close()
    resp = client.get("/galaxy?view=system&galaxy=1&system=499")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "mission=colonize" in body
    assert "galaxy-fleet-action--colonize" in body
    assert "target_galaxy=1" in body
    assert "target_system=499" in body
    assert "galaxy-fleet-expansion-cta" not in body


def test_galaxy_expedition_slot_shortcut(galaxy_db, monkeypatch):
    from game.fleet_defs import EXPEDITION_POSITION

    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    resp = client.get(
        f"/galaxy?view=system&galaxy={coords['galaxy']}&system={coords['system']}"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "galaxy-slot-expedition" in body or "is-expedition" in body
    assert "data-galaxy-ring-fleet-href" in body
    assert f"target_position={EXPEDITION_POSITION}" in body
    assert "mission=expedition" in body
    assert "galaxy-fleet-action--expedition" in body


def test_fleet_page_exposes_expedition_position_dataset(galaxy_db, monkeypatch):
    import app as app_module
    from game.db import commit, db
    from game.fleet import EXPEDITION_POSITION, add_planet_ships
    from game.models import get_homeworld

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, uid = _galaxy_client(monkeypatch)
    planet = get_homeworld(player_id=uid)
    conn = db()
    try:
        add_planet_ships(int(planet["id"]), uid, {"mule_courier": 1}, conn=conn)
        commit(conn)
    finally:
        conn.close()
    resp = client.get(
        f"/fleet?target_galaxy=1&target_system=42&target_position={EXPEDITION_POSITION}&mission=expedition"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="fleet-page"' in body
    assert f'data-expedition-position="{EXPEDITION_POSITION}"' in body
    assert 'name="target_galaxy"' in body
    assert 'data-fleet-mission' in body


def test_orbit_angle_multi_ring_layout(galaxy_db):
    from game.planet_visuals import orbit_angle_for_position, orbit_layout_band_for_position

    assert orbit_layout_band_for_position(1) == "hot"
    assert orbit_layout_band_for_position(5) == "hot"
    assert orbit_layout_band_for_position(6) == "temperate"
    assert orbit_layout_band_for_position(11) == "cold"
    assert orbit_angle_for_position(1) == -90.0
    assert orbit_angle_for_position(5) == 198.0
    assert orbit_angle_for_position(6) == -54.0
    assert orbit_angle_for_position(8) == 90.0
    assert orbit_angle_for_position(11) == -108.0
    assert orbit_angle_for_position(14) == 108.0
    assert orbit_angle_for_position(15) == 180.0


def test_galaxy_ring_layout_main_js_contract(galaxy_db):
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "static" / "main.js").read_text(encoding="utf-8")
    assert "layoutGalaxyRingOrbits" in js
    assert "planetAngleDeg" in js
    assert "ORBIT_RADII_FALLBACK" in js
    assert "is-inspector-open" in js
    assert "dataset.orbitBand" in js
    assert "ResizeObserver" in js


def test_galaxy_ring_compact_stage_css_contract(galaxy_db):
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(encoding="utf-8")
    assert ".galaxy-ring-stage--compact" in css
    assert "min(100%, 620px)" in css
    assert ".galaxy-ring-slot-owner-label" in css
    assert "Orbitron" in css.split(".galaxy-ring-slot-owner-label", 1)[1].split(".galaxy-ring-slot-owner-label--own", 1)[0]
    assert ".galaxy-ring-inspector--card" in css
    assert "position: absolute" in css
    assert "grid-template-columns: minmax(520px, 1fr) minmax(280px, 300px)" not in css


def test_fleet_url_prefill_contract_in_main_js(galaxy_db):
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "static" / "main.js").read_text(encoding="utf-8")
    assert "function applyFleetUrlPrefill(page)" in js
    assert "page.dataset.fleetUrlMission" in js
    assert "data-expedition-position" in js or "dataset.expeditionPosition" in js
    assert "syncMissionAllowlistFromTarget" in js
    assert "enforceFleetUrlMissionLock" in js
    assert "refreshFleetUrlMissionLock" in js
    assert "GC.applyFleetUrlPrefill = applyFleetUrlPrefill" in js
    assert "page.dataset.fleetWorldKey" in js
    assert "world_key" in js
    assert "openWorldInspectorFromNode" in js
    assert "mergeWorldFieldPayload" in js
    assert "/api/worlds/colonize-preview" in js
    sync_expo = js.split("const syncExpeditionMissionTarget = (page) => {", 1)[1].split(
        "const setColonizeRowVisible = (page, mission) => {", 1
    )[0]
    assert 'missionSel.value = "expedition"' not in sync_expo
    assert "const preserveMission = !locked" in js


def test_fleet_url_with_coords_only_does_not_lock_mission(galaxy_db, monkeypatch):
    import importlib

    import app as app_module
    from game.db import commit, db
    from game.fleet import EXPEDITION_POSITION, add_planet_ships
    from game.models import get_homeworld

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, uid = _galaxy_client(monkeypatch)
    planet = get_homeworld(player_id=uid)
    conn = db()
    try:
        add_planet_ships(int(planet["id"]), uid, {"mule_courier": 1}, conn=conn)
        commit(conn)
    finally:
        conn.close()
    resp = client.get(
        f"/fleet?target_galaxy=1&target_system=42&target_position={EXPEDITION_POSITION}"
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'data-fleet-mission' in body
    assert "mission=expedition" not in resp.request.path


def test_api_galaxy_system(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"api_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    resp = client.get("/api/galaxy/system?galaxy=1&system=1")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert len(payload["data"]["slots"]) == 15


def test_galaxy_coordinate_distance_near_vs_far():
    """Fleet flight math must use real galaxy coordinates (GC-532)."""
    from game.fleet_calc import calculate_distance, calculate_flight_seconds

    near = calculate_distance((1, 1, 1), (1, 1, 2))
    far = calculate_distance((1, 1, 1), (1, 450, 12))
    assert near < far
    near_sec = calculate_flight_seconds(near, 5000, 100)
    far_sec = calculate_flight_seconds(far, 5000, 100)
    assert far_sec > near_sec


def test_assign_free_coordinates_never_duplicates(galaxy_db):
    uid = _create_player()
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        a = assign_free_coordinates(conn)
        conn.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, last_update,
                galaxy, system, position
            ) VALUES (?, 'Probe', 0, 0, 0, 0, ?, ?, ?);
            """,
            (uid, *a),
        )
        b = assign_free_coordinates(conn)
        assert a != b
        conn.rollback()
    finally:
        conn.close()


def test_assign_free_coordinates_random_skips_occupied(galaxy_db, monkeypatch):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        occupied_triplet = iter([1, 1, 1, 3, 88, 12])

        def _fake_randint(lo: int, hi: int) -> int:
            return next(occupied_triplet)

        monkeypatch.setattr("game.galaxy.random.randint", _fake_randint)
        result = assign_free_coordinates(conn, strategy="random")
        assert result == (3, 88, 12)
        assert 1 <= result[2] <= POSITION_MAX
        conn.rollback()
    finally:
        conn.close()


def test_assign_free_coordinates_random_fallback_to_sequential(galaxy_db, monkeypatch):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        monkeypatch.setattr("game.galaxy.HOMEWORLD_RANDOM_ATTEMPTS", 2)
        always_occupied = iter([1, 1, 1, 1, 1, 1])

        def _fake_randint(lo: int, hi: int) -> int:
            return next(always_occupied)

        monkeypatch.setattr("game.galaxy.random.randint", _fake_randint)
        result = assign_free_coordinates(conn, strategy="random")
        assert result != (1, 1, 1)
        assert 1 <= result[2] <= POSITION_MAX
        conn.rollback()
    finally:
        conn.close()


def test_assign_free_coordinates_sequential_unchanged_for_colonization(galaxy_db):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        first = assign_free_coordinates(conn, galaxy=1, strategy="sequential")
        assert first == (1, 1, 2)
        conn.rollback()
    finally:
        conn.close()


def test_galaxy_hud_coord_input_js_contract():
    """Galaxy HUD coord inputs navigate via PJAX on Enter/blur."""
    from pathlib import Path

    js = Path("static/main.js").read_text(encoding="utf-8")
    assert "initGalaxyHudCoordInputs" in js
    assert "data-galaxy-hud-galaxy-input" in js
    assert "data-galaxy-hud-system-input" in js
    chunk = js.split("function initGalaxyHudCoordInputs")[1].split("function initGalaxyRingView")[0]
    assert "GC.navigateTo" in chunk
    assert 'ev.key !== "Enter"' in chunk or 'ev.key === "Enter"' in chunk
    assert "clampGalaxy" in chunk
    assert "clampSystem" in chunk
