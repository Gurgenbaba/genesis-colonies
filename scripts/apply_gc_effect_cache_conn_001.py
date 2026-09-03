"""One-shot GC-EFFECT-CACHE-CONN-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "game" / "effects" / "effect_resolver.py"
src = path.read_text(encoding="utf-8")

call_old = """            planet_position,\n            skip_boosters,\n        )"""
call_new = """            planet_position,\n            skip_boosters,\n            conn,\n        )"""
if src.count(call_old) != 2:
    raise SystemExit(f"expected 2 resolver cache call sites, got {src.count(call_old)}")
src = src.replace(call_old, call_new)

sig_old = """    planet_position: Optional[int],\n    skip_inventory_boosters: bool,\n) -> tuple:\n    return ("""
sig_new = """    planet_position: Optional[int],\n    skip_inventory_boosters: bool,\n    conn,\n) -> tuple:\n    return ("""
if src.count(sig_old) != 1:
    raise SystemExit("resolver cache signature anchor mismatch")
src = src.replace(sig_old, sig_new)

key_old = """        int(planet_position) if planet_position is not None else None,\n        bool(skip_inventory_boosters),\n    )"""
key_new = """        int(planet_position) if planet_position is not None else None,\n        bool(skip_inventory_boosters),\n        # GC-EFFECT-CACHE-CONN-001: a resolver may retain its DB handle for\n        # optional modifier probes. Never reuse it across DB checkouts; a\n        # closed/returned connection must not leak into the next request/tick.\n        id(conn) if conn is not None else None,\n    )"""
if src.count(key_old) != 1:
    raise SystemExit("resolver cache tuple anchor mismatch")
src = src.replace(key_old, key_new)

path.write_text(src, encoding="utf-8")
