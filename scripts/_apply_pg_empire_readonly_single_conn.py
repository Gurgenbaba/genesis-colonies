#!/usr/bin/env python3
"""Apply scoped PostgreSQL Empire GET pressure fixes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
EMPIRE = ROOT / "game" / "empire_page.py"


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return src.replace(old, new, 1)


def main() -> int:
    app = APP.read_text(encoding="utf-8")
    old_route = '''@app.route("/empire")
@require_login
def empire_view():
    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login"))

    from game.empire_page import build_empire_context
    from game.initiation.progress import record_page_visit

    uid = int(user_id)
    conn = db()
    try:
        try:
            record_page_visit(uid, "empire", conn=conn)
            commit(conn)
        except Exception:
            rollback(conn)
            logger.exception("initiation empire visit failed user_id=%s", uid)
    finally:
        conn.close()

    empire = build_empire_context(uid)
    return render_template("empire.html", empire=empire)
'''
    new_route = '''@app.route("/empire")
@require_login
def empire_view():
    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login"))

    from game.empire_page import build_empire_context
    from game.initiation.progress import record_page_visit

    uid = int(user_id)
    conn = db()
    try:
        # One request-owned connection. Refresh only the active live context;
        # Empire aggregation below must not persist every colony on a GET.
        ctx = _load_page_live_context(finish_source="empire", conn=conn, close_conn=False)
        if ctx is None:
            return redirect(url_for("login"))

        try:
            record_page_visit(uid, "empire", conn=conn)
            commit(conn)
        except Exception:
            rollback(conn)
            logger.exception("initiation empire visit failed user_id=%s", uid)

        empire = build_empire_context(uid, conn=conn, sync_resources=False)
    finally:
        conn.close()

    return render_template("empire.html", empire=empire)
'''
    app = replace_once(app, old_route, new_route, "empire route")
    APP.write_text(app, encoding="utf-8")

    empire = EMPIRE.read_text(encoding="utf-8")
    empire = replace_once(
        empire,
        'def build_empire_context(player_id: int, *, conn=None) -> Dict[str, Any]:',
        'def build_empire_context(\n    player_id: int,\n    *,\n    conn=None,\n    sync_resources: bool = True,\n) -> Dict[str, Any]:',
        "empire context signature",
    )
    empire = replace_once(
        empire,
        '    Resource balances are ticked for every owned planet before aggregation.\n',
        '    Resource balances are ticked for every owned planet only when ``sync_resources`` is true.\n    Read-only SSR callers should refresh their active live context separately and pass false.\n',
        "empire context doc",
    )
    empire = replace_once(
        empire,
        '        sync_player_planet_resources(uid, conn=conn, finish_queue_first=True, skip_fresh_sec=2.0)\n\n        player = load_player(uid, conn=conn) or {}',
        '        if sync_resources:\n            sync_player_planet_resources(\n                uid,\n                conn=conn,\n                finish_queue_first=True,\n                skip_fresh_sec=2.0,\n            )\n\n        player = load_player(uid, conn=conn) or {}',
        "empire all-colony sync guard",
    )
    empire = replace_once(
        empire,
        '        scores = get_player_score_cached(uid, read_only=True)\n',
        '        scores = get_player_score_cached(uid, read_only=True, conn=conn)\n',
        "empire score connection reuse",
    )
    EMPIRE.write_text(empire, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
