#!/usr/bin/env python3
from pathlib import Path

MODELS = Path("game/models.py")
TESTS = Path("tests/test_gc622_integer_overflow.py")

old = '''            (
                planet["metal"],
                planet["crystal"],
                planet.get("fuel_cells", 0),
                planet.get("last_update", time.time()),
                int(planet.get("energy_total", 0)),
                int(planet.get("energy_used", 0)),
                int(planet["id"]),
            ),
'''
new = '''            (
                # Resource columns use SQLite REAL. Bind explicitly as float so
                # Python's sqlite3 adapter does not try to coerce late-game
                # balances above signed INT64 into SQLite INTEGER first.
                # Do not clamp: existing overflow balances remain intact.
                float(planet["metal"]),
                float(planet["crystal"]),
                float(planet.get("fuel_cells", 0)),
                float(planet.get("last_update", time.time())),
                int(planet.get("energy_total", 0)),
                int(planet.get("energy_used", 0)),
                int(planet["id"]),
            ),
'''
text = MODELS.read_text(encoding="utf-8")
if old not in text:
    raise SystemExit("save_planet binding block not found exactly; refusing blind patch")
MODELS.write_text(text.replace(old, new, 1), encoding="utf-8")

test_name = "test_resource_save_above_sqlite_int64_binds_as_real"
test_text = TESTS.read_text(encoding="utf-8")
if test_name not in test_text:
    test_text += '''\n\n# GC-INT64-RESOURCE-BIND-001 — Python sqlite3 binds Python int as SQLite\n# INTEGER before column affinity is considered. Resource columns are REAL, so\n# balances above signed INT64 must be bound as float rather than clamped.\ndef test_resource_save_above_sqlite_int64_binds_as_real(gc622_db):\n    amount = 10**20  # safely above SQLite signed INT64 max (~9.22e18)\n    conn = db()\n    uid = _player(conn=conn)\n    planet = dict(get_homeworld(player_id=uid, conn=conn))\n    pid = int(planet["id"])\n\n    # Reproduce the failing late-game shape: gameplay math can turn a REAL\n    # balance into a Python int before save_planet writes the row back.\n    planet["metal"] = amount\n    planet["crystal"] = amount // 2\n    planet["fuel_cells"] = amount // 4\n\n    save_planet(planet, conn=conn)\n    conn.commit()\n    row = conn.execute(\n        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",\n        (pid,),\n    ).fetchone()\n    conn.close()\n\n    assert float(row["metal"]) == pytest.approx(float(amount))\n    assert float(row["crystal"]) == pytest.approx(float(amount // 2))\n    assert float(row["fuel_cells"]) == pytest.approx(float(amount // 4))\n'''
    TESTS.write_text(test_text, encoding="utf-8")

print("GC-INT64-RESOURCE-BIND-001 patch applied")
