import json
import os
import random
import time
from pathlib import Path
from typing import Any, Tuple, Dict

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    jsonify,
    flash,
    session,
)

# --------------------------------------------------------------------------
# GAME INTERNALS (DB / MODELS)
# --------------------------------------------------------------------------
from game.models import (
    init_db,
    db,
    load_player,
    get_game_settings,
    verify_user,
    get_player_stats,
    get_user_by_username,
    create_user,
    get_homeworld,
    get_player_rank,
    get_ranking_rows,
)

from game.logic import (
    update_resources,
    get_build_queue_status,
    queue_build,
    get_building_production_per_hour,
    queue_research,
    get_storage_capacity,
    get_research_status,
    get_techtree_data,
)

from game.buildings import get_buildings_panel_rows

from game.auth import (
    login_user,
    logout_user,
    get_current_user,
    require_login,
    require_admin,
)

from game import admin as admin_logic

from game.ranking import (
    get_player_score_cached,
    invalidate_player_score_cache,
)

# --------------------------------------------------------------------------
# APP SETUP
# --------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())

BASE_DIR = Path(__file__).resolve().parent
LOCALES_DIR = BASE_DIR / "locales"

BACKGROUND_CLASSES = ["bg-1", "bg-2", "bg-3", "bg-4"]
GC_LOCALE = "de"

T_DATA: dict[str, Any] = {}
try:
    with open(LOCALES_DIR / "de.json", "r", encoding="utf-8") as f:
        T_DATA = json.load(f)
except Exception:
    T_DATA = {}


def T(key: str, *fmt_args, **fmt_kwargs) -> str:
    txt = T_DATA.get(key, key)
    if not fmt_args and not fmt_kwargs:
        return txt
    try:
        if fmt_kwargs:
            txt = txt % fmt_kwargs
        elif fmt_args:
            txt = txt % fmt_args
    except Exception:
        return txt
    return txt


@app.template_filter("fmt_int")
def fmt_int_filter(value):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", ".")


# --------------------------------------------------------------------------
# BACKGROUND-ROTATION PRO SESSION
# --------------------------------------------------------------------------

@app.before_request
def choose_background():
    if "bg_class" not in session:
        session["bg_class"] = f"bg-{random.randint(1, 4)}"


# --------------------------------------------------------------------------
# CONTEXT / GLOBALS
# --------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    auth_user = None
    auth_admin = False

    settings: dict[str, Any] = {}
    motd_enabled = False
    motd_text = ""

    player_stats: dict[str, int] = {}

    score_total = 0
    score_buildings = 0
    score_research = 0
    rank_text = None
    my_rank = None
    total_players = None

    # current user (safe)
    try:
        auth_user = get_current_user()
        auth_admin = bool(auth_user and auth_user.get("is_admin"))
    except Exception:
        auth_user = None
        auth_admin = False

    # settings (safe)
    try:
        settings = get_game_settings() or {}
    except Exception:
        settings = {}

    # motd (safe)
    try:
        raw_motd_enabled = settings.get("motd_enabled", "0")
        motd_enabled = str(raw_motd_enabled) in ("1", "true", "True", "yes", "on")
        motd_text = (settings.get("motd_text", "") or "").strip()
    except Exception:
        motd_enabled = False
        motd_text = ""

    # stats (safe)
    try:
        player_stats = get_player_stats() or {}
    except Exception:
        player_stats = {}

    # score + rank (header/sidebar) – darf niemals crashen
    try:
        user_id = session.get("user_id")
        if user_id is not None:
            player_id = int(user_id)  # players.id == users.id

            s = get_player_score_cached(player_id) or {}
            score_total = int(s.get("total", 0) or 0)
            score_buildings = int(s.get("buildings", 0) or 0)
            score_research = int(s.get("research", 0) or 0)

            my_rank, total_players = get_player_rank(player_id)
            if my_rank and total_players:
                rank_text = f"#{int(my_rank)}/{int(total_players)}"
    except Exception:
        pass

    return dict(
        T=T,
        T_DATA=T_DATA,
        GC_LOCALE=GC_LOCALE,

        AUTH_USER=auth_user,
        AUTH_ADMIN=auth_admin,

        GAME_SETTINGS=settings,
        motd_enabled=motd_enabled,
        motd_text=motd_text,

        PLAYER_STATS=player_stats,

        score=score_total,
        score_buildings=score_buildings,
        score_research=score_research,
        rank_text=rank_text,
        my_rank=my_rank,
        total_players=total_players,
    )


# --------------------------------------------------------------------------
# DB INIT
# --------------------------------------------------------------------------

init_db()
# init_db() macht create_default_admin() bereits intern -> hier NICHT doppelt.


# --------------------------------------------------------------------------
# HELPER: Spieler-View + Ressourcen laden (conn-safe)
# --------------------------------------------------------------------------

def _load_player_view_with_resources() -> Tuple[Any, Dict[str, int], float, int, int, Dict[str, int]]:
    """
    Return:
      (player_view | None, buildings, ratio, energy_total, energy_used, storage_caps)
    """
    user_id = session.get("user_id")
    if user_id is None:
        return None, {}, 1.0, 0, 0, {"metal": 0, "crystal": 0}

    user_id = int(user_id)
    player = load_player(user_id)
    if not player:
        return None, {}, 1.0, 0, 0, {"metal": 0, "crystal": 0}

    conn = db()
    try:
        # ✅ Ressourcen-Tick & Finisher laufen conn-safe (aber brauchen commit)
        player_view, buildings, ratio, energy_total, energy_used = update_resources(player, conn=conn)

        # ✅ Storage conn-safe
        storage_caps = get_storage_capacity(buildings, user_id=user_id, conn=conn)

        conn.commit()  # ✅ WICHTIG: sonst werden save_planet/finisher zurückgerollt
        return player_view, buildings, ratio, energy_total, energy_used, storage_caps

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# AUTH ROUTES
# --------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = verify_user(username, password)
        if user:
            login_user(user)
            flash(T("msg_login_success"), "success")
            return redirect(url_for("overview"))

        error = T("msg_login_failed") or "Ungültiger Benutzername oder falsches Passwort."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    logout_user()
    flash(T("msg_logout_success") or "Erfolgreich abgemeldet.", "success")
    return redirect(url_for("landing"))


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if not username or not password:
            error = T("msg_register_need_user_pass") or "Bitte Benutzername und Passwort angeben."
        elif password != password2:
            error = T("msg_register_pw_mismatch") or "Die Passwörter stimmen nicht überein."
        elif len(username) < 3:
            error = T("msg_register_username_short") or "Benutzername muss mindestens 3 Zeichen lang sein."
        elif len(password) < 4:
            error = T("msg_register_password_short") or "Passwort muss mindestens 4 Zeichen lang sein."
        else:
            existing = get_user_by_username(username)
            if existing:
                error = T("msg_register_username_taken") or "Benutzername ist bereits vergeben."
            else:
                ok, msg, user = create_user(username, password)
                if not ok:
                    error = msg or (T("msg_register_failed") or "Account konnte nicht erstellt werden.")
                else:
                    login_user(user)
                    flash(T("msg_register_success") or "Willkommen im Genesis-Universum, Commander!", "success")
                    return redirect(url_for("overview"))

    return render_template("register.html", error=error)


# --------------------------------------------------------------------------
# LANDING / MAIN
# --------------------------------------------------------------------------

@app.route("/")
def landing():
    user = get_current_user()
    if user and user.get("id"):
        return redirect(url_for("overview"))
    return render_template("landing.html")


# --------------------------------------------------------------------------
# OVERVIEW
# --------------------------------------------------------------------------

@app.route("/overview")
@require_login
def overview():
    (
        player_view,
        buildings,
        ratio,
        energy_total,
        energy_used,
        storage_caps,
    ) = _load_player_view_with_resources()

    if player_view is None:
        return redirect(url_for("login"))

    user = get_current_user()
    user_id = int(user["id"])

    prod_per_hour = get_building_production_per_hour(
        buildings=buildings,
        ratio=ratio,
        user_id=user_id,
    )

    build_queue = get_build_queue_status(user_id=user_id)

    research_status = get_research_status(
        user_id=user_id,
        buildings=buildings,
    )

    return render_template(
        "overview.html",
        player=player_view,
        buildings=buildings,
        ratio=ratio,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        prod_per_hour=prod_per_hour,
        build_queue=build_queue,
        research_status=research_status,
        build_status=build_queue,
    )


# --------------------------------------------------------------------------
# BUILDINGS
# --------------------------------------------------------------------------

@app.route("/buildings")
@require_login
def buildings_view():
    active_tab = request.args.get("tab") or "resources"

    player_view, buildings, ratio, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    planet = get_homeworld(player_id=int(player_view["id"]))

    rows_by_tab = get_buildings_panel_rows(
        planet,
        buildings,
    )

    user = get_current_user()
    user_id = int(user["id"])

    build_queue = get_build_queue_status(user_id=user_id)

    prod_per_hour = get_building_production_per_hour(
        buildings,
        ratio,
        user_id=user_id,
    )

    return render_template(
        "buildings.html",
        player=player_view,
        rows_by_tab=rows_by_tab,
        active_tab=active_tab,
        build_queue=build_queue,
        prod_per_hour=prod_per_hour,
        energy_total=energy_total,
        energy_used=energy_used,
        ratio=ratio,
        storage_caps=storage_caps,
        build_status=build_queue,
    )


@app.route("/upgrade/<building_type>")
@require_login
def upgrade(building_type):
    src = request.args.get("src", "overview")
    tab = request.args.get("tab") or None

    player_view, buildings, _, _, _, _ = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    ok, reason, payload = queue_build(player_view, buildings, building_type)

    if not ok:
        if reason == "not_enough_resources":
            need_m, need_c = payload
            flash(T("msg_upgrade_fail_resources", metal=need_m, crystal=need_c), "error")
        elif reason == "queue_full":
            flash(T("msg_build_queue_full"), "error")
        elif reason == "requirements":
            flash(T("msg_build_requirements"), "error")
        else:
            flash(T("msg_upgrade_unknown"), "error")
    else:
        # Score steigt bei dir erst beim FINISH. Cache-Flush hier ist optional.
        # Für stabilere Live-UI: eher AUS lassen.
        # invalidate_player_score_cache(int(player_view["id"]))
        pass

    if src == "buildings":
        if tab:
            return redirect(url_for("buildings_view", tab=tab))
        return redirect(url_for("buildings_view"))

    return redirect(url_for("overview"))


# --------------------------------------------------------------------------
# RESEARCH
# --------------------------------------------------------------------------

@app.route("/research")
@require_login
def research_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    user = get_current_user()
    user_id = int(user["id"])

    research_status = get_research_status(
        user_id=user_id,
        buildings=buildings,
    )

    return render_template(
        "research.html",
        player=player_view,
        buildings=buildings,
        research_status=research_status,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/research_start/<tech_key>")
@require_login
def research_start(tech_key):
    player_view, buildings, _, _, _, _ = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))
    try:
        ok, reason, payload = queue_research(player_view, buildings, tech_key)
    except TypeError:
        ok, reason, payload = queue_research(player_view, tech_key)
    
    if not ok:
        if reason == "no_research_lab":
            flash(T("research_msg_no_lab"), "error")
        elif reason == "research_active":
            flash(T("research_msg_active"), "error")
        elif reason == "not_enough_resources":
            need_m, need_c = payload
            flash(T("research_msg_not_enough", metal=need_m, crystal=need_c), "error")
        elif reason == "unknown_tech":
            flash(T("research_msg_unknown"), "error")
        elif reason == "requirements":
            flash(T("research_msg_requirements"), "error")
        else:
            flash(T("research_msg_error"), "error")
    else:
        info = payload or {}
        lvl = info.get("level", 0)
        secs = info.get("seconds", 0)
        flash(T("research_msg_started", level=lvl, seconds=secs), "success")

        # Score steigt bei FINISH. Cache-Flush hier optional.
        # invalidate_player_score_cache(int(player_view["id"]))

    return redirect(url_for("research_view"))


# --------------------------------------------------------------------------
# TECH-TREE
# --------------------------------------------------------------------------

@app.route("/techtree")
@require_login
def techtree_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    user = get_current_user()
    user_id = int(user["id"])

    research_status = get_research_status(
        user_id=user_id,
        buildings=buildings,
    )
    techs = research_status.get("techs", []) or []
    research_levels = {t.get("key"): int(t.get("level", 0) or 0) for t in techs}

    building_nodes, research_nodes = get_techtree_data(
        buildings=buildings,
        research=research_levels,
        user_id=user_id,
    )

    return render_template(
        "techtree.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        building_nodes=building_nodes,
        research_nodes=research_nodes,
    )


# --------------------------------------------------------------------------
# PLACEHOLDER PAGES
# --------------------------------------------------------------------------

@app.route("/galaxy")
@require_login
def galaxy_view():
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    return render_template(
        "galaxy.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/shipyard")
@require_login
def shipyard_view():
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    return render_template(
        "shipyard.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/defense")
@require_login
def defense_view():
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    return render_template(
        "defense.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/fleet")
@require_login
def fleet_view():
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    return render_template(
        "fleet.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/alliance")
@require_login
def alliance_view():
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    return render_template(
        "alliance.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


# --------------------------------------------------------------------------
# RANKING PAGE
# --------------------------------------------------------------------------

@app.route("/ranking")
@require_login
def ranking_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    player_id = int(player_view["id"])

    rows = get_ranking_rows(limit=100, offset=0)
    my_score = get_player_score_cached(player_id)
    my_rank, total_players = get_player_rank(player_id)

    ranking = []
    for idx, row in enumerate(rows, start=1):
        ranking.append(
            {
                "rank": idx,
                "player_id": row["player_id"],
                "nickname": row["nickname"],
                "score_total": row["score_total"],
                "score_buildings": row["score_buildings"],
                "score_research": row["score_research"],
            }
        )

    return render_template(
        "ranking.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        ranking=ranking,
        my_score=my_score,
        my_rank=my_rank,
        total_players=total_players,
    )


# --------------------------------------------------------------------------
# API (AJAX / main.js)
# --------------------------------------------------------------------------

@app.route("/api/status")
@require_login
def api_status():
    player_view, buildings, ratio, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return jsonify({"error": "not_logged_in"}), 401

    user = get_current_user()
    user_id = int(user["id"])
    player_id = int(player_view["id"])

    payload = {
        "server_time": int(time.time()),  # ✅ für Live-Counter / Drift-Korrektur
        "player": {
            "name": player_view["name"],
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
        },
        "buildings": buildings,
        "build_queue": get_build_queue_status(user_id=user_id),
        "production_per_hour": get_building_production_per_hour(
            buildings=buildings,
            ratio=ratio,
            user_id=user_id,
        ),
        "research": get_research_status(
            user_id=user_id,
            buildings=buildings,
        ),
        "storage": storage_caps,
    }

    score = get_player_score_cached(player_id) or {"total": 0, "buildings": 0, "research": 0}
    rank, total_players = get_player_rank(player_id)

    payload["score"] = {
        "total": int(score.get("total", 0) or 0),
        "buildings": int(score.get("buildings", 0) or 0),
        "research": int(score.get("research", 0) or 0),
        "rank": int(rank) if rank else None,
        "total_players": int(total_players) if total_players else None,
    }

    return jsonify(payload)


# --------------------------------------------------------------------------
# ADMIN PANEL
# --------------------------------------------------------------------------

@app.route("/admin", methods=["GET"])
@require_login
@require_admin
def admin_panel():
    player_view, buildings, ratio, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    settings = admin_logic.get_admin_settings()
    banned_players = admin_logic.get_ban_list()

    # ✅ FIX: player_stats wirklich setzen
    player_stats = get_player_stats()

    return render_template(
        "admin_panel.html",
        player=player_view,
        buildings=buildings,
        ratio=ratio,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        settings=settings,
        banned_players=banned_players,
        player_stats=player_stats,
    )



@app.route("/admin/update", methods=["POST"])
@require_login
@require_admin
def admin_update():
    admin_logic.update_admin_settings(request.form)
    flash(T("msg_settings_saved") or "Einstellungen gespeichert.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/resources", methods=["POST"])
@require_login
@require_admin
def admin_resources():
    current_user_id = session.get("user_id")
    admin_logic.handle_resource_tools(
        request.form,
        current_user_id=int(current_user_id) if current_user_id is not None else None,
    )
    flash(T("msg_admin_resources_updated") or "Ressourcen angepasst.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/wipe", methods=["POST"])
@require_login
@require_admin
def admin_wipe_universe():
    admin_logic.wipe_universe(request.form)
    flash(T("msg_admin_wipe") or "Universum wurde zurückgesetzt.", "success")

    # Wipe kann Score/Ranking massiv ändern -> Cache leeren (sicher)
    try:
        uid = session.get("user_id")
        if uid is not None:
            invalidate_player_score_cache(int(uid))
    except Exception:
        pass

    return redirect(url_for("admin_panel"))


@app.route("/admin/ban", methods=["POST"])
@require_login
@require_admin
def admin_ban_user():
    admin_logic.ban_player(request.form)
    flash(T("msg_admin_ban") or "Spieler wurde gebannt.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/unban", methods=["POST"])
@require_login
@require_admin
def admin_unban_user():
    admin_logic.unban_player(request.form)
    flash(T("msg_admin_unban") or "Bann wurde aufgehoben.", "success")
    return redirect(url_for("admin_panel"))


# --------------------------------------------------------------------------
# RUN
# --------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
