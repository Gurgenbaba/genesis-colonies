from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


fleet_path = Path("game/fleet.py")
s = fleet_path.read_text(encoding="utf-8")

helper_marker = "\n\ndef validate_fleet_send(\n"
helper = '''


def _effective_asteroid_recycle_ships(
    mission: str,
    target_info: Mapping[str, Any] | None,
    origin_planet_id: int,
    ships: Mapping[str, int],
    *,
    conn,
) -> Dict[str, int]:
    """Clamp asteroid Harvest Reclaimers to the count that can actually launch.

    This is intentionally asteroid-only. Generic debris recycling and every
    other fleet mission retain their existing all-or-nothing ship semantics.
    Mixed asteroid fleets remain supported; only ``harvest_reclaimer`` is
    clamped because it is the asteroid harvesting ship.
    """
    ships_n = normalize_ships(ships)
    if (
        str(mission or "").strip().lower() != "recycle"
        or str((target_info or {}).get("target_type") or "") != "asteroid"
    ):
        return ships_n

    asteroid = (target_info or {}).get("asteroid") or {}
    requested = max(0, int(ships_n.get("harvest_reclaimer") or 0))
    available = max(
        0,
        int(
            get_planet_ships(int(origin_planet_id), conn=conn).get(
                "harvest_reclaimer", 0
            )
            or 0
        ),
    )
    needed = max(0, int(asteroid.get("recycler_slots_needed") or 0))
    effective = min(requested, available, needed)

    out = dict(ships_n)
    if effective > 0:
        out["harvest_reclaimer"] = int(effective)
    else:
        out.pop("harvest_reclaimer", None)
    return normalize_ships(out)
'''
s = replace_once(s, helper_marker, helper + helper_marker, "insert helper")

validate_anchor = '    if mission in ("attack", "spy") and target_info:\n'
validate_insert = '''    if (
        mission == "recycle"
        and target_info
        and str(target_info.get("target_type") or "") == "asteroid"
    ):
        ships_n = _effective_asteroid_recycle_ships(
            mission,
            target_info,
            int(origin_planet_id),
            ships_n,
            conn=conn,
        )
        if int(ships_n.get("harvest_reclaimer") or 0) <= 0:
            return False, "recycle_requires_reclaimer", {
                "target": target_info,
                "effective_ships": dict(ships_n),
            }

'''
s = replace_once(s, validate_anchor, validate_insert + validate_anchor, "validate clamp")

success_old = '''    out: Dict[str, Any] = {
        "target": target_info,
        "preview": preview,
        "origin_planet": origin_planet,
        "resolved_target": target,
    }
'''
success_new = '''    out: Dict[str, Any] = {
        "target": target_info,
        "preview": preview,
        "origin_planet": origin_planet,
        "resolved_target": target,
        "effective_ships": dict(ships_n),
    }
'''
s = replace_once(s, success_old, success_new, "validate success context")

preview_anchor = '''        if mission_locked:
            mission_ok = False
            mission_reason = "mission_locked"
        origin_galaxy = int(origin_planet.get("galaxy") or 0) or None
'''
preview_new = '''        if mission_locked:
            mission_ok = False
            mission_reason = "mission_locked"
        if (
            mission == "recycle"
            and target_info
            and str(target_info.get("target_type") or "") == "asteroid"
        ):
            ships_n = _effective_asteroid_recycle_ships(
                mission,
                target_info,
                int(origin_planet.get("id") or 0),
                ships_n,
                conn=conn,
            )
        origin_galaxy = int(origin_planet.get("galaxy") or 0) or None
'''
s = replace_once(s, preview_anchor, preview_new, "preview clamp")

payload_old = '''        payload = {
            **flight,
            "target": target_info,
'''
payload_new = '''        payload = {
            **flight,
            "effective_ships": dict(ships_n),
            "target": target_info,
'''
s = replace_once(s, payload_old, payload_new, "preview payload effective ships")

send_anchor = '''        if not ok_send:
            if own:
                rollback(conn)
            extra = send_ctx if isinstance(send_ctx, dict) else None
            return False, send_reason, extra

        origin_planet = send_ctx["origin_planet"]
'''
send_new = '''        if not ok_send:
            if own:
                rollback(conn)
            extra = send_ctx if isinstance(send_ctx, dict) else None
            return False, send_reason, extra

        if isinstance(send_ctx, dict) and "effective_ships" in send_ctx:
            ships_n = normalize_ships(send_ctx.get("effective_ships") or {})
        if not ships_n:
            if own:
                rollback(conn)
            return False, "no_ships", None

        origin_planet = send_ctx["origin_planet"]
'''
s = replace_once(s, send_anchor, send_new, "send authoritative effective ships")

fleet_path.write_text(s, encoding="utf-8")

version = Path("VERSION")
current = version.read_text(encoding="utf-8").strip()
if current != "0.5.9.167":
    raise SystemExit(f"unexpected VERSION before hotfix: {current}")
version.write_text("0.5.9.168\n", encoding="utf-8")

test_path = Path("tests/test_asteroids.py")
tests = test_path.read_text(encoding="utf-8")
import_old = '''from game.fleet import (
    add_planet_ships,
    evaluate_fleet_mission_target,
    process_fleet_tick,
    resolve_fleet_target,
    send_fleet,
)
'''
import_new = '''from game.fleet import (
    add_planet_ships,
    build_fleet_send_preview,
    evaluate_fleet_mission_target,
    get_planet_ships,
    preview_fleet_flight,
    process_fleet_tick,
    resolve_fleet_target,
    send_fleet,
)
'''
if tests.count(import_old) != 1:
    raise SystemExit("asteroid test import block changed")
tests = tests.replace(import_old, import_new, 1)

regression = '''


def test_asteroid_send_clamps_to_available_reclaimers_and_exact_fuel(ast_db):
    uid = _player("FuelClamp")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            rng=random.Random(818),
        )
        assert ins["ok"]
        conn.execute(
            "UPDATE asteroid_fields SET metal = 50000000, crystal = 50000000, fuel_cells = 50000000 WHERE id = ?;",
            (int(ins["asteroid"]["id"]),),
        )
        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000, last_update = ? WHERE id = ?;",
            (time.time() + 60, home_id),
        )
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 7}, conn=conn)
        commit(conn)

        origin = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (home_id,)).fetchone())
        expected = preview_fleet_flight(
            origin_planet=origin,
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 7},
            resources={},
            speed_percent=100,
            player_id=uid,
            mission_type="recycle",
            conn=conn,
        )
        expected_fuel = int(expected["fuel_cost"])

        begin_write_transaction(conn)
        ok, err, result = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 100},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok, err
        fleet_id = int(result["fleet"]["id"])
        commit(conn)

        row = conn.execute(
            "SELECT ships_json, fuel_cost FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert json.loads(row["ships_json"] or "{}") == {"harvest_reclaimer": 7}
        assert int(row["fuel_cost"]) == expected_fuel
        assert int(result["fuel_cost"]) == expected_fuel
        assert int(get_planet_ships(home_id, conn=conn).get("harvest_reclaimer") or 0) == 0
        fuel_after = int(float(conn.execute(
            "SELECT fuel_cells FROM planets WHERE id = ?;", (home_id,)
        ).fetchone()["fuel_cells"]))
        assert fuel_after == 500000 - expected_fuel
    finally:
        conn.close()


def test_asteroid_send_clamps_to_current_asteroid_need(ast_db):
    uid = _player("NeedClamp")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="ferronite_rock",
            rng=random.Random(919),
        )
        assert ins["ok"]
        conn.execute(
            "UPDATE asteroid_fields SET metal = 1, crystal = 0, fuel_cells = 0 WHERE id = ?;",
            (int(ins["asteroid"]["id"]),),
        )
        conn.execute(
            "UPDATE planets SET fuel_cells = 500000, last_update = ? WHERE id = ?;",
            (time.time() + 60, home_id),
        )
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 20}, conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, err, result = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 20},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok, err
        fleet_id = int(result["fleet"]["id"])
        commit(conn)

        row = conn.execute(
            "SELECT ships_json FROM fleet_movements WHERE id = ?;", (fleet_id,)
        ).fetchone()
        assert json.loads(row["ships_json"] or "{}") == {"harvest_reclaimer": 1}
        assert int(get_planet_ships(home_id, conn=conn).get("harvest_reclaimer") or 0) == 19
    finally:
        conn.close()


def test_asteroid_preview_uses_effective_ship_map_and_fuel(ast_db):
    uid = _player("PreviewClamp")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            rng=random.Random(1010),
        )
        assert ins["ok"]
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 7}, conn=conn)
        conn.execute(
            "UPDATE planets SET fuel_cells = 500000, last_update = ? WHERE id = ?;",
            (time.time() + 60, home_id),
        )
        commit(conn)

        origin = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (home_id,)).fetchone())
        expected = preview_fleet_flight(
            origin_planet=origin,
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 7},
            resources={},
            speed_percent=100,
            player_id=uid,
            mission_type="recycle",
            conn=conn,
        )
        preview = build_fleet_send_preview(
            player_id=uid,
            origin_planet=origin,
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            mission_type="recycle",
            ships={"harvest_reclaimer": 100},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert preview["effective_ships"] == {"harvest_reclaimer": 7}
        assert int(preview["fuel_cost"]) == int(expected["fuel_cost"])
        assert preview["can_send"] is True
    finally:
        conn.close()
'''
if "test_asteroid_send_clamps_to_available_reclaimers_and_exact_fuel" in tests:
    raise SystemExit("regression tests already present unexpectedly")
tests += regression
test_path.write_text(tests, encoding="utf-8")
