#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_all_checked(path: Path, old: str, new: str, expected: int, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    count = src.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    path.write_text(src.replace(old, new), encoding="utf-8")


def main() -> int:
    records = ROOT / "game" / "records.py"
    # PostgreSQL requires every selected non-aggregate column to be grouped.
    replace_all_checked(records, "GROUP BY p.player_id\n        ORDER BY value DESC", "GROUP BY p.player_id, pl.name\n        ORDER BY value DESC", 1, "colonies group by")
    replace_all_checked(records, "GROUP BY ps.player_id\n            HAVING", "GROUP BY ps.player_id, pl.name\n            HAVING", 1, "fleet group by")
    replace_all_checked(records, "GROUP BY p.player_id\n            HAVING", "GROUP BY p.player_id, pl.name\n            HAVING", 2, "defense/troops group by")
    replace_all_checked(records, "GROUP BY c.player_id\n        HAVING", "GROUP BY c.player_id, pl.name\n        HAVING", 1, "titans group by")

    buildings = ROOT / "game" / "buildings.py"
    src = buildings.read_text(encoding="utf-8")
    old = '''    from .options import vacation_blocks_outbound\n\n    ok_vacation, vac_reason = vacation_blocks_outbound(user_id, conn=db())\n    if not ok_vacation:\n        return False, vac_reason, {}\n\n    want_max = str(queue_mode or "single").strip().lower() == "max"\n\n    conn = db()\n'''
    new = '''    from .options import vacation_blocks_outbound\n\n    want_max = str(queue_mode or "single").strip().lower() == "max"\n\n    # P0 PG: the vacation probe must share the mutation-owned checkout.\n    # The old vacation_blocks_outbound(user_id, conn=db()) orphaned a pooled\n    # connection before every build enqueue.\n    conn = db()\n    ok_vacation, vac_reason = vacation_blocks_outbound(user_id, conn=conn)\n    if not ok_vacation:\n        conn.close()\n        return False, vac_reason, {}\n'''
    if src.count(old) != 1:
        raise SystemExit(f"building vacation checkout: expected 1, found {src.count(old)}")
    buildings.write_text(src.replace(old, new, 1), encoding="utf-8")

    app = ROOT / "app.py"
    src = app.read_text(encoding="utf-8")
    old = '''    planets = None\n    if ok:\n        from game.galaxy import sync_galaxy_view_session_for_planet\n        from game.planet_evolution.repository import get_context_planet\n\n        sync_galaxy_view_session_for_planet(session, get_context_planet(user_id))\n        from game.planet_evolution.service import list_player_planets_for_switcher\n        from game.planet_visuals import apply_herocard_urls_to_switcher_planets\n\n        planets = apply_herocard_urls_to_switcher_planets(\n            list_player_planets_for_switcher(user_id),\n            versioned_static_url,\n        )\n    return jsonify({"ok": ok, "reason": reason, "state": state, "planets": planets})\n'''
    new = '''    planets = None\n    if ok:\n        from game.galaxy import sync_galaxy_view_session_for_planet\n        from game.planet_evolution.repository import get_context_planet\n        from game.planet_evolution.service import list_player_planets_for_switcher\n        from game.planet_visuals import apply_herocard_urls_to_switcher_planets\n\n        # Keep post-switch context + switcher reads on one short checkout.\n        # Previously these two helpers each opened a separate pool connection.\n        switch_conn = db()\n        try:\n            context_planet = get_context_planet(user_id, conn=switch_conn)\n            sync_galaxy_view_session_for_planet(session, context_planet)\n            planets = apply_herocard_urls_to_switcher_planets(\n                list_player_planets_for_switcher(user_id, conn=switch_conn),\n                versioned_static_url,\n            )\n        finally:\n            switch_conn.close()\n    return jsonify({"ok": ok, "reason": reason, "state": state, "planets": planets})\n'''
    if src.count(old) != 1:
        raise SystemExit(f"planet switch response tail: expected 1, found {src.count(old)}")
    app.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
