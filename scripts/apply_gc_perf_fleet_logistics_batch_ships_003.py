"""One-shot GC-PERF-FLEET-LOGISTICS-003 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "game" / "fleet.py"

OLD_HEAD = '''        colonies: List[Dict[str, Any]] = []
        hub_resources = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        for p in get_planets_by_player(player_id, conn=conn):
'''
NEW_HEAD = '''        colonies: List[Dict[str, Any]] = []
        hub_resources = {"metal": 0, "crystal": 0, "fuel_cells": 0}

        # GC-PERF-FLEET-LOGISTICS-003: one hangar read for all colonies instead
        # of get_planet_ships() once per colony (+ once again for the hub).
        ships_by_planet: Dict[int, Dict[str, int]] = {}
        ships_cur = conn.cursor()
        ships_cur.execute(
            """
            SELECT planet_id, ship_key, amount
            FROM planet_ships
            WHERE player_id = ? AND amount > 0;
            """,
            (int(player_id),),
        )
        for ship_row in ships_cur.fetchall():
            ship_pid = int(ship_row["planet_id"])
            ships_by_planet.setdefault(ship_pid, {})[str(ship_row["ship_key"])] = _safe_int(
                ship_row["amount"]
            )

        for p in get_planets_by_player(player_id, conn=conn):
'''
OLD_SHIPS = '''            ships = get_planet_ships(pid, conn=conn)
            cargo_ships = filter_available_cargo_ships(ships)
'''
NEW_SHIPS = '''            ships = dict(ships_by_planet.get(pid) or {})
            cargo_ships = filter_available_cargo_ships(ships)
'''
OLD_RETURN = '''            "ships": get_planet_ships(planet_id, conn=conn),
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
'''
NEW_RETURN = '''            "ships": dict(ships_by_planet.get(int(planet_id)) or {}),
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
'''


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one target, found {count}")
    return src.replace(old, new, 1)


def main() -> int:
    src = FLEET.read_text(encoding="utf-8")
    if "GC-PERF-FLEET-LOGISTICS-003" in src:
        print("already applied")
        return 0
    src = replace_once(src, OLD_HEAD, NEW_HEAD, "head")
    src = replace_once(src, OLD_SHIPS, NEW_SHIPS, "per-colony ships")
    src = replace_once(src, OLD_RETURN, NEW_RETURN, "hub ships")
    FLEET.write_text(src, encoding="utf-8")
    print("applied GC-PERF-FLEET-LOGISTICS-003")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
