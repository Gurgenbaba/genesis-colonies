#!/usr/bin/env python3
"""Apply the scoped World Boss SSR single-request-connection patch."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app.py"


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    old = '''def world_boss_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "world_boss"
    )
    if player_view is None:
        return redirect(url_for("login"))

    from game.world_boss import build_world_boss_payload

    player_id = _current_player_id()
    conn = db()
    wb_payload = None
    try:
        # PostgreSQL GET hotpath: payload composition is read-only. Auto attacks
        # are server-owned by the fleet worker / explicit POST mutations.
        wb_payload = build_world_boss_payload(player_id, conn=conn)
    finally:
        conn.close()

    return render_template(
        "world_boss.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        world_boss_payload=wb_payload,
    )
'''
    new = '''def world_boss_view():
    from game.world_boss import build_world_boss_payload

    player_id = _current_player_id()
    conn = db()
    wb_payload = None
    try:
        ctx = _load_page_live_context(finish_source="world_boss", conn=conn, close_conn=False)
        if ctx is None:
            return redirect(url_for("login"))

        # PostgreSQL GET hotpath: one request-owned connection. Payload composition
        # stays read-only; auto attacks remain worker / explicit POST mutations.
        wb_payload = build_world_boss_payload(player_id, conn=conn)
    finally:
        conn.close()

    return render_template(
        "world_boss.html",
        player=ctx["player_view"],
        buildings=ctx["buildings"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        world_boss_payload=wb_payload,
    )
'''
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one World Boss view block, found {count}")
    TARGET.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
