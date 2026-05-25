import json
import os
import random
import sys
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
    g,
)
from markupsafe import Markup, escape

# --------------------------------------------------------------------------
# GAME INTERNALS (DB / MODELS)
# --------------------------------------------------------------------------
from game.models import (
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
    get_idempotent_action,
    save_idempotent_action,
)
from game.db import commit, rollback

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
    require_admin_api,
)

from game import admin as admin_logic
from game import admin_api as admin_api_logic

from game.ranking import (
    get_player_score_cached,
    invalidate_player_score_cache,
)

from game import playercard as playercard_logic

from game.bootstrap import bootstrap_application
from game.config import get_secret_key, is_debug_enabled, is_production

# --------------------------------------------------------------------------
# APP SETUP
# --------------------------------------------------------------------------

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LOCALES_DIR = BASE_DIR / "locales"
VERSION_FILE = BASE_DIR / "VERSION"


def get_asset_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "dev"
    except Exception:
        return "dev"


GC_ASSET_VERSION = get_asset_version()

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


@app.template_global()
def player_name_link(
    player_id,
    name=None,
    extra_class: str = "",
    enable_card: bool = True,
) -> Markup:
    """
    Standard clickable player name for PlayerCard (PJAX-safe markup).

    Usage: {{ player_name_link(row.player_id, row.nickname) }}
    """
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return Markup(escape(name or "—"))
    if pid <= 0:
        return Markup(escape(name or "—"))

    label = escape(str(name or "Commander"))
    classes = ["gc-player-name"]
    if extra_class:
        classes.append(str(extra_class).strip())
    attrs = [
        f'class="{" ".join(classes)}"',
        f'data-player-id="{pid}"',
        f'data-player-name="{label}"',
    ]
    if enable_card:
        attrs.append('data-player-card="1"')
        attrs.append(f'title="{escape(T("playercard_open"))}"')
        attrs.append('role="button"')
        attrs.append('tabindex="0"')
    return Markup(f"<span {' '.join(attrs)}>{label}</span>")


def _current_player_id() -> int | None:
    try:
        uid = session.get("user_id")
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


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
        GC_ASSET_VERSION=GC_ASSET_VERSION,
        player_name_link=player_name_link,
        CURRENT_PLAYER_ID=_current_player_id(),

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
# BOOTSTRAP (config, DB, migration guard)
# --------------------------------------------------------------------------

_skip_mig = os.environ.get("GC_SKIP_MIGRATION_CHECK", "0").strip().lower() in ("1", "true", "yes")
bootstrap_application(skip_migration_check=_skip_mig)
app.secret_key = get_secret_key() or os.urandom(32).hex()


# --------------------------------------------------------------------------
# HEALTH
# --------------------------------------------------------------------------

@app.route("/health")
def health():
    from game.health import build_health_report

    report = build_health_report()
    code = 200 if report.get("status") == "ok" else 503
    return jsonify(report), code


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
        rollback(conn)
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

    user = get_current_user()
    user_id = int(user["id"])

    build_queue = get_build_queue_status(user_id=user_id)

    rows_by_tab = get_buildings_panel_rows(
        planet,
        buildings,
        build_queue=build_queue,
    )

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
    ok, reason, payload = queue_research(player_view, tech_key)
    if not ok:
        if reason == "no_research_lab":
            flash(T("research_msg_no_lab"), "error")
        elif reason == "research_active":
            flash(T("research_msg_active"), "error")
        elif reason == "research_queue_full":
            flash(T("research_msg_queue_full"), "error")
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

    sector_commanders = []
    try:
        for row in get_ranking_rows(limit=6, offset=0):
            sector_commanders.append(
                {
                    "player_id": row["player_id"],
                    "nickname": row["nickname"],
                    "score_total": row["score_total"],
                }
            )
    except Exception:
        sector_commanders = []

    return render_template(
        "galaxy.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        sector_commanders=sector_commanders,
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

    alliance_members = []
    try:
        for row in get_ranking_rows(limit=8, offset=0):
            alliance_members.append(
                {
                    "player_id": row["player_id"],
                    "nickname": row["nickname"],
                }
            )
    except Exception:
        alliance_members = []

    return render_template(
        "alliance.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        alliance_members=alliance_members,
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
# PLAYER CARD (global profile popup)
# --------------------------------------------------------------------------

def _playercard_viewer_id() -> int | None:
    return _current_player_id()


@app.route("/api/player-card/<int:player_id>")
@require_login
def api_player_card_view(player_id: int):
    viewer_id = _playercard_viewer_id()
    card, err = playercard_logic.build_public_card(player_id, viewer_id=viewer_id)
    if err:
        return (
            render_template(
                "partials/player_card_error.html",
                error_key=err,
            ),
            404,
        )
    if card is None:
        return (
            render_template(
                "partials/player_card_error.html",
                error_key="playercard_not_found",
            ),
            404,
        )
    return render_template("partials/player_card_view.html", card=card)


@app.route("/api/player-card/<int:player_id>/edit")
@require_login
def api_player_card_edit(player_id: int):
    viewer_id = _playercard_viewer_id()
    if viewer_id is None or int(viewer_id) != int(player_id):
        return (
            render_template(
                "partials/player_card_error.html",
                error_key="playercard_forbidden",
            ),
            403,
        )
    card, err = playercard_logic.build_edit_card(player_id)
    if err:
        status = 403 if err == "playercard_forbidden" else 404
        return render_template("partials/player_card_error.html", error_key=err), status
    if card is None:
        return (
            render_template(
                "partials/player_card_error.html",
                error_key="playercard_not_found",
            ),
            404,
        )
    return render_template("partials/player_card_edit.html", card=card)


@app.route("/api/player-card/me", methods=["POST"])
@require_login
def api_player_card_save():
    viewer_id = _playercard_viewer_id()
    if viewer_id is None:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    ok, reason, card = playercard_logic.save_own_card(int(viewer_id), data)
    if not ok:
        status = 429 if reason == "playercard_rate_limited" else 400
        return jsonify({"ok": False, "reason": reason}), status

    html = render_template("partials/player_card_view.html", card=card)
    return jsonify({"ok": True, "reason": reason, "html": html})


@app.route("/player/<int:player_id>")
@require_login
def player_card_fallback_page(player_id: int):
    """Optional full-page fallback when JS is unavailable."""
    viewer_id = _playercard_viewer_id()
    card, err = playercard_logic.build_public_card(player_id, viewer_id=viewer_id)
    if err or card is None:
        flash(T(err or "playercard_not_found"), "error")
        return redirect(url_for("ranking_view"))

    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    return render_template(
        "player_card_page.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        card=card,
        card_player_id=player_id,
    )


# --------------------------------------------------------------------------
# API (AJAX / main.js)
# --------------------------------------------------------------------------

def _build_game_state_payload(include_panel: bool = True) -> Tuple[dict, int]:
    """
    Zentraler Spielzustand für Polling + AJAX-Refresh (kein Page-Reload).
    Returns (payload, player_id) or raises via caller checking player_view.
    """
    player_view, buildings, ratio, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return {"ok": False, "error": "not_logged_in"}, 0

    user = get_current_user()
    user_id = int(user["id"])
    player_id = int(player_view["id"])

    build_queue = get_build_queue_status(user_id=user_id)
    research = get_research_status(user_id=user_id, buildings=buildings)

    payload: Dict[str, Any] = {
        "ok": True,
        "server_time": int(time.time()),
        "player": {
            "name": player_view["name"],
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
        },
        "resources": {
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
            "storage": storage_caps,
        },
        "buildings": buildings,
        "build_queue": build_queue,
        "building_queue": build_queue,
        "production_per_hour": get_building_production_per_hour(
            buildings=buildings,
            ratio=ratio,
            user_id=user_id,
        ),
        "research": research,
        "research_queue": research.get("queue", []),
        "storage": storage_caps,
    }

    if include_panel:
        planet = get_homeworld(player_id=player_id)
        payload["buildings_panel"] = get_buildings_panel_rows(
            planet,
            buildings,
            build_queue=build_queue,
        )

    score = get_player_score_cached(player_id) or {"total": 0, "buildings": 0, "research": 0}
    rank, total_players = get_player_rank(player_id)

    payload["score"] = {
        "total": int(score.get("total", 0) or 0),
        "buildings": int(score.get("buildings", 0) or 0),
        "research": int(score.get("research", 0) or 0),
        "rank": int(rank) if rank else None,
        "total_players": int(total_players) if total_players else None,
    }

    return payload, player_id


def _extract_request_id(data: Dict[str, Any]) -> str:
    rid = (data.get("request_id") or request.headers.get("X-Request-Id") or "").strip()
    return rid


def _action_json_response(
    ok: bool,
    reason: str,
    payload: Any = None,
    job: Any = None,
) -> Any:
    """Immer frischen Spielzustand liefern – auch bei Fehlern."""
    state, _ = _build_game_state_payload(include_panel=True)
    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
    }
    if not ok and payload is not None:
        resp["payload"] = payload
    if ok and job is not None:
        resp["job"] = job
    return jsonify(resp)


@app.route("/api/status")
@require_login
def api_status():
    payload, player_id = _build_game_state_payload(include_panel=True)
    if not payload.get("ok"):
        return jsonify({"error": "not_logged_in"}), 401
    return jsonify(payload)


@app.route("/api/game-state")
@require_login
def api_game_state():
    payload, player_id = _build_game_state_payload(include_panel=True)
    if not payload.get("ok"):
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    return jsonify(payload)


@app.route("/api/buildings/upgrade", methods=["POST"])
@require_login
def api_buildings_upgrade():
    data = request.get_json(silent=True) or {}
    building_type = (data.get("building_type") or request.form.get("building_type") or "").strip()
    if not building_type:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_building_type", "state": state}), 400

    player_view, buildings, _, _, _, _ = _load_player_view_with_resources()
    if player_view is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = int(player_view["id"])
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    ok, reason, extra = queue_build(player_view, buildings, building_type)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
    )
    response_obj = resp.get_json()

    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)

    return resp


@app.route("/api/research/start", methods=["POST"])
@require_login
def api_research_start():
    data = request.get_json(silent=True) or {}
    tech_key = (data.get("tech_key") or request.form.get("tech_key") or "").strip()
    if not tech_key:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_tech_key", "state": state}), 400

    player_view, _, _, _, _, _ = _load_player_view_with_resources()
    if player_view is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    user_id = int(player_view["id"])
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    ok, reason, extra = queue_research(player_view, tech_key)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
    )
    response_obj = resp.get_json()

    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)

    return resp


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


def _admin_json(result: Dict[str, Any], default_status: int = 200):
    if not isinstance(result, dict):
        return jsonify({"ok": False, "error": "internal"}), 500
    if result.get("ok"):
        return jsonify(result), default_status
    err = str(result.get("error") or "error")
    status = {
        "not_found": 404,
        "forbidden": 403,
        "confirm_required": 400,
        "invalid_building": 400,
        "invalid_type": 400,
        "migration_failed": 500,
    }.get(err, 400)
    return jsonify(result), status


def _admin_body() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _admin_actor_id() -> int:
    user = getattr(g, "admin_user", None) or get_current_user() or {}
    return int(user.get("id") or session.get("user_id") or 0)


# --------------------------------------------------------------------------
# ADMIN JSON API (Production Control Center)
# --------------------------------------------------------------------------

@app.route("/api/admin/health", methods=["GET"])
@require_admin_api
def api_admin_health():
    return _admin_json(admin_api_logic.api_health())


@app.route("/api/admin/migrations", methods=["GET"])
@require_admin_api
def api_admin_migrations():
    return _admin_json(admin_api_logic.api_migrations())


@app.route("/api/admin/migrations/run", methods=["POST"])
@require_admin_api
def api_admin_migrations_run():
    return _admin_json(admin_api_logic.api_run_migrations(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/runtime", methods=["GET"])
@require_admin_api
def api_admin_runtime():
    return _admin_json(admin_api_logic.api_runtime())


@app.route("/api/admin/players", methods=["GET"])
@require_admin_api
def api_admin_players_search():
    return _admin_json(admin_api_logic.search_players(request.args.get("q", "")))


@app.route("/api/admin/player/<int:player_id>", methods=["GET"])
@require_admin_api
def api_admin_player_detail(player_id: int):
    return _admin_json(admin_api_logic.get_player_detail(player_id))


@app.route("/api/admin/player/<int:player_id>/set-admin", methods=["POST"])
@require_admin_api
def api_admin_player_set_admin(player_id: int):
    return _admin_json(admin_api_logic.set_player_admin(_admin_actor_id(), player_id, _admin_body()))


@app.route("/api/admin/player/<int:player_id>/ban", methods=["POST"])
@require_admin_api
def api_admin_player_ban(player_id: int):
    return _admin_json(admin_api_logic.ban_player_api(_admin_actor_id(), player_id, _admin_body()))


@app.route("/api/admin/player/<int:player_id>/unban", methods=["POST"])
@require_admin_api
def api_admin_player_unban(player_id: int):
    return _admin_json(admin_api_logic.unban_player_api(_admin_actor_id(), player_id))


@app.route("/api/admin/player/<int:player_id>/resources", methods=["POST"])
@require_admin_api
def api_admin_player_resources(player_id: int):
    return _admin_json(admin_api_logic.set_player_resources(_admin_actor_id(), player_id, _admin_body()))


@app.route("/api/admin/player/<int:player_id>/repair-homeworld", methods=["POST"])
@require_admin_api
def api_admin_player_repair_homeworld(player_id: int):
    return _admin_json(admin_api_logic.repair_homeworld(_admin_actor_id(), player_id))


@app.route("/api/admin/planets", methods=["GET"])
@require_admin_api
def api_admin_planets_search():
    return _admin_json(admin_api_logic.search_planets(request.args.get("q", "")))


@app.route("/api/admin/planet/<int:planet_id>", methods=["GET"])
@require_admin_api
def api_admin_planet_detail(planet_id: int):
    return _admin_json(admin_api_logic.get_planet_detail(planet_id))


@app.route("/api/admin/planet/<int:planet_id>/resources", methods=["POST"])
@require_admin_api
def api_admin_planet_resources(planet_id: int):
    return _admin_json(admin_api_logic.set_planet_resources(_admin_actor_id(), planet_id, _admin_body()))


@app.route("/api/admin/planet/<int:planet_id>/building", methods=["POST"])
@require_admin_api
def api_admin_planet_building(planet_id: int):
    return _admin_json(admin_api_logic.set_planet_building(_admin_actor_id(), planet_id, _admin_body()))


@app.route("/api/admin/planet/<int:planet_id>/reset", methods=["POST"])
@require_admin_api
def api_admin_planet_reset(planet_id: int):
    return _admin_json(admin_api_logic.reset_planet(_admin_actor_id(), planet_id, _admin_body()))


@app.route("/api/admin/queues", methods=["GET"])
@require_admin_api
def api_admin_queues():
    filters = {
        "player_id": request.args.get("player_id"),
        "planet_id": request.args.get("planet_id"),
        "status": request.args.get("status", "all"),
    }
    return _admin_json(admin_api_logic.get_queues(filters))


@app.route("/api/admin/queue/<queue_type>/<int:job_id>/cancel", methods=["POST"])
@require_admin_api
def api_admin_queue_cancel(queue_type: str, job_id: int):
    return _admin_json(admin_api_logic.cancel_queue_job(_admin_actor_id(), queue_type, job_id))


@app.route("/api/admin/queues/finish-due", methods=["POST"])
@require_admin_api
def api_admin_queues_finish_due():
    return _admin_json(admin_api_logic.finish_due_queues(_admin_actor_id()))


@app.route("/api/admin/queues/clear", methods=["POST"])
@require_admin_api
def api_admin_queues_clear():
    return _admin_json(admin_api_logic.clear_queues(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/audit-log", methods=["GET"])
@require_admin_api
def api_admin_audit_log():
    filters = {
        "admin_id": request.args.get("admin_id"),
        "action": request.args.get("action"),
        "target_type": request.args.get("target_type"),
        "limit": request.args.get("limit", 100),
        "offset": request.args.get("offset", 0),
    }
    aid = filters.get("admin_id")
    if aid is not None and str(aid).strip().isdigit():
        filters["admin_id"] = int(aid)
    else:
        filters["admin_id"] = None
    return _admin_json(admin_api_logic.get_audit_log(filters))


# --------------------------------------------------------------------------
# RUN
# --------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    if is_production() and is_debug_enabled():
        print("[GC] ERROR: Refusing to run production with FLASK_DEBUG=1", file=sys.stderr)
        raise SystemExit(1)
    app.run(host=host, port=port, debug=is_debug_enabled())
