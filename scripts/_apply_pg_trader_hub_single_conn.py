#!/usr/bin/env python3
"""Apply scoped Trader Hub request-connection reuse."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def main() -> int:
    src = APP.read_text(encoding="utf-8")
    old = '''@app.route("/trader-hub")
@require_login
def trader_hub_view():
    ctx = _load_page_live_context(finish_source="trader_hub")
    if ctx is None:
        return redirect(url_for("login"))

    from game.exchange import exchange_schema_ready, get_exchange_status
    from game.planet_evolution.repository import get_context_planet
    from game.scrapyard import scrapyard_status

    exchange = {}
    scrapyard = {}
    conn = db()
    try:
        planet = get_context_planet(int(session["user_id"]), conn=conn)
'''
    new = '''@app.route("/trader-hub")
@require_login
def trader_hub_view():
    from game.exchange import exchange_schema_ready, get_exchange_status
    from game.planet_evolution.repository import get_context_planet
    from game.scrapyard import scrapyard_status

    exchange = {}
    scrapyard = {}
    conn = db()
    try:
        ctx = _load_page_live_context(
            finish_source="trader_hub",
            conn=conn,
            close_conn=False,
        )
        if ctx is None:
            return redirect(url_for("login"))

        planet = ctx.get("planet") or get_context_planet(int(session["user_id"]), conn=conn)
'''
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one Trader Hub block, found {count}")
    APP.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
