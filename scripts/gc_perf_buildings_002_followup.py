"""One-shot follow-up for GC-PERF-BUILDINGS-002.

Threads the request connection through production formula external reads and shares
planet-scoped Mine Evolution modifier probes across synthetic target resolvers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    er = ROOT / "game" / "effects" / "effect_resolver.py"
    replace_once(
        er,
        '''            self.player_id,\n            self.galaxy_id,\n            bool(self._skip_inventory_boosters),\n''',
        '''            self.player_id,\n            self.planet_id,\n            self.galaxy_id,\n            bool(self._skip_inventory_boosters),\n''',
    )

    pf = ROOT / "game" / "production_formula.py"
    replace_once(
        pf,
        '''        event_mod = float(active_production_mult() or 1.0)\n''',
        '''        event_mod = float(active_production_mult(conn=getattr(resolver, "_conn", None)) or 1.0)\n''',
    )
    replace_once(
        pf,
        '''                building_mod = float(building_modifier_for(int(pid), mine_key))\n                cache[mine_key] = building_mod\n''',
        '''                probe = getattr(resolver, "_run_optional_conn_probe", None)\n                if callable(probe):\n                    building_mod = float(\n                        probe(\n                            f"mine_evolution:{mine_key}",\n                            lambda: building_modifier_for(\n                                int(pid),\n                                mine_key,\n                                conn=getattr(resolver, "_conn", None),\n                            ),\n                        )\n                    )\n                else:\n                    building_mod = float(\n                        building_modifier_for(\n                            int(pid),\n                            mine_key,\n                            conn=getattr(resolver, "_conn", None),\n                        )\n                    )\n                cache[mine_key] = building_mod\n''',
    )
    print("GC-PERF-BUILDINGS-002 follow-up applied")


if __name__ == "__main__":
    main()
