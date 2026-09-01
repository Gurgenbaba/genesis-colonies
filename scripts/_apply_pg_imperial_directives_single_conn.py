#!/usr/bin/env python3
"""Apply scoped Imperial Directives PostgreSQL request-connection fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
GENERATOR = ROOT / "game" / "directives" / "generator.py"


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return src.replace(old, new, 1)


def main() -> int:
    app = APP.read_text(encoding="utf-8")
    old = '''@app.route("/imperial-directives")
@require_login
def imperial_directives_view():
    ctx = _load_page_live_context(finish_source="imperial_directives")
    if ctx is None:
        return redirect(url_for("login"))

    from game.directives.service import get_imperial_directives_state

    imperial_directives = {"ready": False, "directives": []}
    conn = db()
    try:
        imperial_directives = get_imperial_directives_state(
            int(session["user_id"]),
            conn=conn,
        )
    finally:
        conn.close()

    return render_template(
        "imperial_directives.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        imperial_directives=imperial_directives,
    )
'''
    new = '''@app.route("/imperial-directives")
@require_login
def imperial_directives_view():
    from game.directives.service import get_imperial_directives_state

    imperial_directives = {"ready": False, "directives": []}
    conn = db()
    try:
        ctx = _load_page_live_context(
            finish_source="imperial_directives",
            conn=conn,
            close_conn=False,
        )
        if ctx is None:
            return redirect(url_for("login"))

        imperial_directives = get_imperial_directives_state(
            int(session["user_id"]),
            conn=conn,
        )
    finally:
        conn.close()

    return render_template(
        "imperial_directives.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        imperial_directives=imperial_directives,
    )
'''
    app = replace_once(app, old, new, "imperial directives view")
    APP.write_text(app, encoding="utf-8")

    generator = GENERATOR.read_text(encoding="utf-8")
    generator = replace_once(
        generator,
        '        snapshot = get_player_score_cached(int(player_id), read_only=True)\n',
        '        snapshot = get_player_score_cached(int(player_id), read_only=True, conn=conn)\n',
        "directive score connection reuse",
    )
    GENERATOR.write_text(generator, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
