"""One-shot GC-PERF-FLEET-SHARED-004 patch helper."""
# Trigger commit after the branch-local apply workflow exists.
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "game" / "fleet.py"
APP = ROOT / "app.py"


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one target, found {count}")
    return src.replace(old, new, 1)


def patch_fleet() -> None:
    src = FLEET.read_text(encoding="utf-8")
    if "GC-PERF-FLEET-SHARED-004" in src:
        print("fleet patch already applied")
        return

    src = replace_once(
        src,
        '''def build_logistics_page_context(\n    *,\n    player_id: int,\n    planet_id: int,\n    planet: Dict[str, Any],\n    conn=None,\n) -> Dict[str, Any]:\n''',
        '''def build_logistics_page_context(\n    *,\n    player_id: int,\n    planet_id: int,\n    planet: Dict[str, Any],\n    conn=None,\n    planet_rows: Sequence[Mapping[str, Any]] | None = None,\n    maintenance_prepared: bool = False,\n    fleet_slots: Mapping[str, Any] | None = None,\n    mission_locks: Mapping[str, Any] | None = None,\n) -> Dict[str, Any]:\n''',
        "logistics signature",
    )
    src = replace_once(
        src,
        '''        _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))\n        process_fleet_tick(player_id=int(player_id), conn=conn)\n\n        from .fleet_calc import cargo_ship_count, filter_available_cargo_ships, planet_resource_stock\n''',
        '''        # GC-PERF-FLEET-SHARED-004: /fleet already ran these once in the\n        # canonical Send context. Standalone callers keep the historical behavior.\n        if not maintenance_prepared:\n            _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))\n            process_fleet_tick(player_id=int(player_id), conn=conn)\n\n        from .fleet_calc import cargo_ship_count, filter_available_cargo_ships, planet_resource_stock\n''',
        "logistics maintenance",
    )
    src = replace_once(
        src,
        '''        for p in get_planets_by_player(player_id, conn=conn):\n            pid = int(p["id"])\n''',
        '''        shared_planet_rows = planet_rows if planet_rows is not None else get_planets_by_player(\n            player_id, conn=conn\n        )\n        for p in shared_planet_rows:\n            pid = int(p["id"])\n''',
        "logistics planets",
    )
    src = replace_once(
        src,
        '''            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),\n            "server_time": time.time(),\n            "mission_locks": _fleet_mission_locks_for_client(conn=conn),\n''',
        '''            "fleet_slots": (\n                dict(fleet_slots)\n                if fleet_slots is not None\n                else get_fleet_slot_status(player_id, conn=conn)\n            ),\n            "server_time": time.time(),\n            "mission_locks": (\n                dict(mission_locks)\n                if mission_locks is not None\n                else _fleet_mission_locks_for_client(conn=conn)\n            ),\n''',
        "logistics shared slots locks",
    )
    src = replace_once(
        src,
        '''def build_fleet_page_context(\n    *,\n    player_id: int,\n    planet_id: int,\n    planet: Dict[str, Any],\n    conn=None,\n    can_seed_test_ships: bool = False,\n) -> Dict[str, Any]:\n''',
        '''def build_fleet_page_context(\n    *,\n    player_id: int,\n    planet_id: int,\n    planet: Dict[str, Any],\n    conn=None,\n    can_seed_test_ships: bool = False,\n    planet_rows: Sequence[Mapping[str, Any]] | None = None,\n) -> Dict[str, Any]:\n''',
        "fleet signature",
    )
    src = replace_once(
        src,
        '''        coords = get_planet_coordinates(planet)\n        colonies: List[Dict[str, Any]] = []\n        for p in get_planets_by_player(player_id, conn=conn):\n''',
        '''        coords = get_planet_coordinates(planet)\n        colonies: List[Dict[str, Any]] = []\n        shared_planet_rows = planet_rows if planet_rows is not None else get_planets_by_player(\n            player_id, conn=conn\n        )\n        for p in shared_planet_rows:\n''',
        "fleet planets",
    )
    FLEET.write_text(src, encoding="utf-8")


def patch_app() -> None:
    src = APP.read_text(encoding="utf-8")
    if "GC-PERF-FLEET-SHARED-004" in src:
        print("app patch already applied")
        return
    old = '''            planet_dict = dict(planet)\n            with perf_span("page_context.fleet"):\n                fleet_ctx = build_fleet_page_context(\n                    player_id=int(player_view["id"]),\n                    planet_id=int(planet["id"]),\n                    planet=planet_dict,\n                    conn=conn,\n                )\n                logistics_ctx = build_logistics_page_context(\n                    player_id=int(player_view["id"]),\n                    planet_id=int(planet["id"]),\n                    planet=planet_dict,\n                    conn=conn,\n                )\n'''
    new = '''            planet_dict = dict(planet)\n            player_id = int(player_view["id"])\n            # GC-PERF-FLEET-SHARED-004: both Fleet panels belong to one SSR\n            # request. Reuse its planet list + canonical maintenance results.\n            from game.models import get_planets_by_player\n\n            page_planets = [dict(p) for p in get_planets_by_player(player_id, conn=conn)]\n            with perf_span("page_context.fleet"):\n                fleet_ctx = build_fleet_page_context(\n                    player_id=player_id,\n                    planet_id=int(planet["id"]),\n                    planet=planet_dict,\n                    conn=conn,\n                    planet_rows=page_planets,\n                )\n                logistics_ctx = build_logistics_page_context(\n                    player_id=player_id,\n                    planet_id=int(planet["id"]),\n                    planet=planet_dict,\n                    conn=conn,\n                    planet_rows=page_planets,\n                    maintenance_prepared=True,\n                    fleet_slots=fleet_ctx.get("fleet_slots"),\n                    mission_locks=fleet_ctx.get("mission_locks"),\n                )\n'''
    src = replace_once(src, old, new, "fleet route")
    APP.write_text(src, encoding="utf-8")


def main() -> int:
    patch_fleet()
    patch_app()
    print("applied GC-PERF-FLEET-SHARED-004")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
