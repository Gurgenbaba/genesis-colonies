#!/usr/bin/env python3
"""Apply the scoped Shipyard single-request-connection patch."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app.py"


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    old = '''    data_t0 = time.perf_counter()
    player_view, _, planet_row, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        finish_ssr_perf(response_bytes=0)
        return redirect(url_for("login"))

    from game.fleet import fleet_schema_ready
    from game.planet_evolution.repository import get_context_planet
    from game.shipyard import build_shipyard_page_context

    conn = db()
    try:
        from game.live_state import perf_span

        planet = get_context_planet(int(session.get("user_id") or 0), conn=conn)
        with perf_span("page_context.shipyard"):
            shipyard_ctx = (
                build_shipyard_page_context(int(session.get("user_id") or 0), planet, conn=conn)
                if fleet_schema_ready(conn)
                else {"ready": False, "orbital_shipyard_level": 0}
            )
    finally:
        conn.close()

    if ssr is not None:
        ssr.add_live_context_ms((time.perf_counter() - data_t0) * 1000.0)
    tpl_t0 = time.perf_counter()
    resp = render_template(
        "shipyard.html",
        player=player_view,
        planet=planet_row,
        shipyard=shipyard_ctx,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )
'''
    new = '''    data_t0 = time.perf_counter()
    conn = db()
    try:
        ctx = _load_page_live_context(finish_source="shipyard", conn=conn, close_conn=False)
        if ctx is None:
            finish_ssr_perf(response_bytes=0)
            return redirect(url_for("login"))

        from game.fleet import fleet_schema_ready
        from game.live_state import get_request_context_planet, perf_span
        from game.shipyard import build_shipyard_page_context

        player_view = ctx["player_view"]
        planet = ctx.get("planet")
        if not planet:
            planet = get_request_context_planet(int(session.get("user_id") or 0), conn=conn)
        with perf_span("page_context.shipyard"):
            shipyard_ctx = (
                build_shipyard_page_context(int(session.get("user_id") or 0), planet, conn=conn)
                if fleet_schema_ready(conn)
                else {"ready": False, "orbital_shipyard_level": 0}
            )
    finally:
        conn.close()

    if ssr is not None:
        ssr.add_live_context_ms((time.perf_counter() - data_t0) * 1000.0)
    tpl_t0 = time.perf_counter()
    resp = render_template(
        "shipyard.html",
        player=player_view,
        planet=planet,
        shipyard=shipyard_ctx,
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
    )
'''
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one Shipyard block, found {count}")
    TARGET.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
