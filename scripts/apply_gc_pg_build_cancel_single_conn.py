#!/usr/bin/env python3
from pathlib import Path

path = Path("game/buildings.py")
src = path.read_text(encoding="utf-8")
old = '''        owner_id = get_planet_owner_id(planet_id)
        if not owner_id:
            rollback(conn)
            return False, "not_found", {"msg": "Planet owner not found"}
'''
new = '''        owner_row = conn.execute(
            "SELECT player_id FROM planets WHERE id = ? LIMIT 1;",
            (planet_id,),
        ).fetchone()
        owner_id = int(owner_row["player_id"]) if owner_row else None
        if not owner_id:
            rollback(conn)
            return False, "not_found", {"msg": "Planet owner not found"}
'''
marker = "def cancel_build_job_for_planet("
head, sep, tail = src.partition(marker)
if not sep:
    raise SystemExit("cancel function not found")
if old not in tail:
    raise SystemExit("cancel owner lookup target not found")
tail = tail.replace(old, new, 1)
path.write_text(head + sep + tail, encoding="utf-8")
