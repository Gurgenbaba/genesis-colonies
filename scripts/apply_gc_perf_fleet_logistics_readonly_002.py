"""One-shot GC-PERF-FLEET-LOGISTICS-002 patch helper.

Turns the read-only Logistics page-context resource refresh into a non-persisting
calculation. Fleet actions keep their existing transactional/persisting paths.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "game" / "fleet.py"

OLD = """            planet_live, *_rest = update_planet_resources(\n                dict(p),\n                conn=conn,\n                skip_queue_finish=True,\n            )\n            stock = planet_resource_stock(planet_live)\n"""

NEW = """            # GC-PERF-FLEET-LOGISTICS-002: SSR is a read path. Compute live\n            # resource stock for the card, but do not write every colony merely\n            # because /fleet was opened. Actions revalidate/persist authoritatively.\n            planet_live, *_rest = update_planet_resources(\n                dict(p),\n                conn=conn,\n                skip_queue_finish=True,\n                persist=False,\n            )\n            stock = planet_resource_stock(planet_live)\n"""


def main() -> int:
    src = FLEET.read_text(encoding="utf-8")
    if NEW in src:
        print("GC-PERF-FLEET-LOGISTICS-002 already applied")
        return 0
    count = src.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one Logistics page-context target, found {count}")
    FLEET.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print("applied GC-PERF-FLEET-LOGISTICS-002")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
