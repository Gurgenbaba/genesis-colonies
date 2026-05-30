import json
import logging
import os
import random
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
    get_planet_buildings,
    get_player_rank,
    get_ranking_rows,
    get_idempotent_action,
    save_idempotent_action,
)
from game.db import commit, rollback

logger = logging.getLogger(__name__)

from game.logic import (
    update_resources,
    get_build_queue_status,
    queue_build,
    cancel_build,
    get_building_production_per_hour,
    queue_research,
    cancel_research,
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
    require_login_api,
    require_admin,
    require_admin_api,
)

from game import admin as admin_logic
from game import admin_api as admin_api_logic

from game.ranking import (
    build_ranking_api_payload,
    get_player_score_cached,
    invalidate_player_score_cache,
    recalculate_all_rankings,
)

from game import playercard as playercard_logic
from game import chat as chat_logic
from game import support as support_logic
from game import messages as messages_logic
from game import options as options_logic
from game import account_email as account_email_logic

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
    if key in T_DATA:
        txt = T_DATA[key]
    elif len(fmt_args) == 1 and isinstance(fmt_args[0], str):
        txt = fmt_args[0]
        fmt_args = ()
    else:
        txt = key
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

    raw = str(name or "").strip()
    display = escape(raw or "—")
    lookup_attr = escape(raw)
    classes = ["gc-player-name"]
    if extra_class:
        classes.append(str(extra_class).strip())
    attrs = [
        f'class="{" ".join(classes)}"',
        f'data-player-id="{pid}"',
        f'data-player-name="{lookup_attr}"',
    ]
    if enable_card:
        attrs.append('data-player-card="1"')
        attrs.append(f'title="{escape(T("playercard_open"))}"')
        attrs.append('role="button"')
        attrs.append('tabindex="0"')
    return Markup(f"<span {' '.join(attrs)}>{display}</span>")


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


@app.teardown_request
def _teardown_queue_finish_dedup(_exc=None):
    from game.queue_engine import clear_request_finish_dedup

    clear_request_finish_dedup()


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
    ctx = _load_page_live_context(finish_source="page_load")
    if ctx is None:
        return None, {}, 1.0, 0, 0, {"metal": 0, "crystal": 0}
    return (
        ctx["player_view"],
        ctx["buildings"],
        ctx["ratio"],
        ctx["energy_total"],
        ctx["energy_used"],
        ctx["storage_caps"],
    )


def _load_page_live_context(
    *,
    finish_source: str = "page_load",
    include_panel: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    One finish + derived sync + read-only queue/research per page/API request.
    """
    from game.logic import refresh_player_live_state

    user_id = session.get("user_id")
    if user_id is None:
        return None

    user_id = int(user_id)
    if not load_player(user_id):
        return None

    conn = db()
    src = str(finish_source or "page_load")
    try:
        try:
            if src == "game_state":
                from game.logic import read_player_live_state_for_poll

                player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
                    read_player_live_state_for_poll(user_id, conn=conn)
                )
            else:
                player_view, buildings, ratio, energy_total, energy_used, storage_caps = refresh_player_live_state(
                    user_id,
                    conn=conn,
                    finish_source=src,
                )
            build_queue = get_build_queue_status(user_id=user_id, skip_finish=True, conn=conn)
            research = get_research_status(
                user_id=user_id,
                buildings=buildings,
                skip_finish=True,
                conn=conn,
            )
            prod_per_hour = get_building_production_per_hour(
                buildings=buildings,
                ratio=ratio,
                user_id=user_id,
            )
            if src != "game_state":
                conn.commit()
        except sqlite3.OperationalError:
            rollback(conn)
            if src != "game_state":
                raise
            logger.warning(
                "game_state live context locked, using read-only fallback user_id=%s",
                user_id,
                exc_info=True,
            )
            from game.logic import _read_player_live_state_no_writes

            player = load_player(user_id, conn=conn)
            if not player:
                return None
            from game.planet_evolution.repository import get_context_planet

            planet = get_context_planet(user_id, conn=conn)
            player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
                _read_player_live_state_no_writes(user_id, conn, player, planet)
            )
            build_queue = get_build_queue_status(user_id=user_id, skip_finish=True, conn=conn)
            research = get_research_status(
                user_id=user_id,
                buildings=buildings,
                skip_finish=True,
                conn=conn,
            )
            prod_per_hour = get_building_production_per_hour(
                buildings=buildings,
                ratio=ratio,
                user_id=user_id,
            )
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return {
        "player_view": player_view,
        "buildings": buildings,
        "ratio": ratio,
        "energy_total": energy_total,
        "energy_used": energy_used,
        "storage_caps": storage_caps,
        "build_queue": build_queue,
        "research": research,
        "prod_per_hour": prod_per_hour,
        "include_panel": include_panel,
    }


# --------------------------------------------------------------------------
# AUTH ROUTES
# --------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        # Login uses username only; resolve_login_username() prepared for GC_LOGIN_ALLOW_EMAIL=1
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
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if not username or not password or not email:
            error = T("msg_register_need_user_pass_email") or T("msg_register_need_user_pass")
        elif password != password2:
            error = T("msg_register_pw_mismatch") or "Die Passwörter stimmen nicht überein."
        elif len(username) < 3:
            error = T("msg_register_username_short") or "Benutzername muss mindestens 3 Zeichen lang sein."
        elif len(password) < 4:
            error = T("msg_register_password_short") or "Passwort muss mindestens 4 Zeichen lang sein."
        else:
            ok, err, user = account_email_logic.register_user_with_email(username, password, email)
            if not ok:
                error = T(err) if err and T(err) != err else (err or T("msg_register_failed"))
            else:
                login_user(user)
                flash(T("msg_register_success_verify") or T("msg_register_success"), "success")
                return redirect(url_for("overview"))

    return render_template("register.html", error=error)


@app.route("/verify-email/<token>")
def verify_email(token: str):
    ok, err = account_email_logic.verify_email_token(token)
    state = "success" if ok else ("warning" if err == "account_already_verified" else "error")
    if ok:
        title = T("verify_email_success_title")
        message = T(err) if T(err) != err else err
    elif err == "account_already_verified":
        title = T("verify_email_already_title")
        message = T(err) if T(err) != err else err
    else:
        title = T("verify_email_failed_title")
        message = T(err) if T(err) != err else err
    return render_template(
        "auth_result.html",
        page_title=title,
        badge=T("verify_email_badge"),
        state=state,
        title=title,
        message=message,
        primary_href=url_for("overview") if get_current_user() else url_for("login"),
        primary_label=T("verify_email_continue") if get_current_user() else T("login_btn"),
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    error = None
    sent = False
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        meta = _options_request_meta()
        account_email_logic.request_password_reset(email, ip=meta["ip"])
        sent = True
    return render_template(
        "forgot_password.html",
        error=error,
        sent=sent,
        success_message=T("account_reset_generic"),
    )


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    error = None
    success = False
    if request.method == "POST":
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        ok, err = account_email_logic.reset_password_with_token(token, password, password2)
        if ok:
            success = True
        else:
            error = T(err) if err and T(err) != err else err
    return render_template(
        "reset_password.html",
        error=error,
        success=success,
        token=token,
        success_message=T("account_password_reset_ok"),
    )


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
    ctx = _load_page_live_context(finish_source="overview")
    if ctx is None:
        return redirect(url_for("login"))

    from game.planet_evolution.teaser import get_overview_planet_teaser

    planet_teaser = {"visible": False}
    conn = db()
    try:
        planet_teaser = get_overview_planet_teaser(
            int(session["user_id"]),
            metal=float(ctx["player_view"]["metal"]),
            crystal=float(ctx["player_view"]["crystal"]),
            conn=conn,
        )
    finally:
        conn.close()

    from game.overview_page import build_overview_page_context
    from game.planet_evolution.repository import get_context_planet

    planet = get_context_planet(int(session["user_id"]))
    overview_status = build_overview_page_context(int(session["user_id"]), ctx, planet=planet)

    return render_template(
        "overview.html",
        player=ctx["player_view"],
        ratio=ctx["ratio"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        prod_per_hour=ctx["prod_per_hour"],
        planet_teaser=planet_teaser,
        overview_status=overview_status,
    )


@app.route("/trader-hub")
@require_login
def trader_hub_view():
    ctx = _load_page_live_context(finish_source="trader_hub")
    if ctx is None:
        return redirect(url_for("login"))

    from game.exchange import exchange_schema_ready, get_exchange_status
    from game.planet_evolution.repository import get_context_planet

    exchange = {}
    conn = db()
    try:
        planet = get_context_planet(int(session["user_id"]), conn=conn)
        if exchange_schema_ready(conn):
            exchange = get_exchange_status(
                player_id=int(session["user_id"]),
                planet_id=int(planet["id"]),
                metal=float(ctx["player_view"]["metal"]),
                crystal=float(ctx["player_view"]["crystal"]),
                conn=conn,
            )
    finally:
        conn.close()

    return render_template(
        "trader_hub.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        exchange=exchange,
    )


# --------------------------------------------------------------------------
# BUILDINGS
# --------------------------------------------------------------------------

@app.route("/buildings")
@require_login
def buildings_view():
    active_tab = request.args.get("tab") or "resources"

    ctx = _load_page_live_context(finish_source="buildings")
    if ctx is None:
        return redirect(url_for("login"))

    from game.planet_evolution.repository import get_context_planet

    planet = get_context_planet(int(ctx["player_view"]["id"]))
    rows_by_tab = get_buildings_panel_rows(
        planet,
        ctx["buildings"],
        build_queue=ctx["build_queue"],
    )

    return render_template(
        "buildings.html",
        player=ctx["player_view"],
        active_planet_id=int(planet["id"]),
        active_planet_name=str(planet.get("name") or ""),
        rows_by_tab=rows_by_tab,
        active_tab=active_tab,
        build_queue=ctx["build_queue"],
        prod_per_hour=ctx["prod_per_hour"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        ratio=ctx["ratio"],
        storage_caps=ctx["storage_caps"],
        build_status=ctx["build_queue"],
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
    ctx = _load_page_live_context(finish_source="research")
    if ctx is None:
        return redirect(url_for("login"))

    from game.planet_evolution.repository import get_context_planet

    planet = get_context_planet(int(session["user_id"]))

    return render_template(
        "research.html",
        player=ctx["player_view"],
        buildings=ctx["buildings"],
        research_status=ctx["research"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        active_planet_name=str(planet.get("name") or ""),
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
            if isinstance(payload, dict):
                need_m = int(payload.get("metal", 0))
                need_c = int(payload.get("crystal", 0))
            else:
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
    ctx = _load_page_live_context(finish_source="techtree")
    if ctx is None:
        return redirect(url_for("login"))

    user_id = int(ctx["player_view"]["id"])
    research_status = ctx["research"]
    buildings = ctx["buildings"]
    techs = research_status.get("techs", []) or []
    research_levels = {t.get("key"): int(t.get("level", 0) or 0) for t in techs}

    building_nodes, research_nodes = get_techtree_data(
        buildings=buildings,
        research=research_levels,
        user_id=user_id,
    )

    return render_template(
        "techtree.html",
        player=ctx["player_view"],
        buildings=buildings,
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
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

    from game.galaxy import (
        GALAXY_MAX,
        GALAXY_MIN,
        SYSTEM_MAX,
        SYSTEM_MIN,
        get_planet_coordinates,
        list_system,
    )
    from game.planet_evolution.repository import get_context_planet

    galaxy = GALAXY_MIN
    system = SYSTEM_MIN
    try:
        planet = get_context_planet(int(session["user_id"]))
        coords = get_planet_coordinates(planet)
        galaxy = int(coords["galaxy"])
        system = int(coords["system"])
    except Exception:
        pass

    req_system = request.args.get("system", type=int)
    if req_system is not None:
        system = max(SYSTEM_MIN, min(SYSTEM_MAX, int(req_system)))

    system_data = list_system(galaxy, system)

    return render_template(
        "galaxy.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        galaxy_nav={
            "galaxy": galaxy,
            "system": system,
            "galaxy_min": GALAXY_MIN,
            "galaxy_max": GALAXY_MAX,
            "system_min": SYSTEM_MIN,
            "system_max": SYSTEM_MAX,
            "prev_system": max(SYSTEM_MIN, system - 1),
            "next_system": min(SYSTEM_MAX, system + 1),
            "has_prev": system > SYSTEM_MIN,
            "has_next": system < SYSTEM_MAX,
        },
        system_data=system_data,
    )


@app.route("/api/galaxy/system")
@require_login_api
def api_galaxy_system():
    from game.galaxy import GALAXY_MIN, SYSTEM_MAX, SYSTEM_MIN, list_system

    galaxy = request.args.get("galaxy", default=GALAXY_MIN, type=int)
    system = request.args.get("system", type=int)
    if system is None:
        return jsonify({"ok": False, "error": "system_required"}), 400
    system = max(SYSTEM_MIN, min(SYSTEM_MAX, int(system)))
    try:
        data = list_system(int(galaxy), system)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        logger.exception("api_galaxy_system failed")
        return jsonify({"ok": False, "error": str(e)}), 500


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
    ranking_payload = build_ranking_api_payload(player_id, limit=100, refresh=False)

    return render_template(
        "ranking.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        ranking_payload=ranking_payload,
    )


@app.route("/api/ranking")
@require_login
def api_ranking():
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        payload = build_ranking_api_payload(int(player_id), limit=100, refresh=False)
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "ranking_unavailable"}), 500


@app.route("/api/admin/rankings/recalculate", methods=["POST"])
@require_admin_api
def api_admin_recalculate_rankings():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    try:
        result = recalculate_all_rankings(refresh_scores=True)
        if admin_id:
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "recalculate_rankings",
                    target_type="system",
                    payload={
                        "players_updated": result.get("players_updated"),
                        "duration_ms": result.get("duration_ms"),
                    },
                )
            except Exception:
                pass
        status = 200 if result.get("ok") else 500
        return jsonify(result), status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/admin/balance", methods=["GET"])
@require_admin_api
def api_admin_balance_get():
    return _admin_json(admin_api_logic.api_get_balance_settings())


@app.route("/api/admin/balance", methods=["POST"])
@require_admin_api
def api_admin_balance_save():
    return _admin_json(admin_api_logic.api_save_balance_settings(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/balance/preset-b", methods=["POST"])
@require_admin_api
def api_admin_balance_preset_b():
    return _admin_json(admin_api_logic.api_apply_balance_preset_b(_admin_actor_id()))


# --------------------------------------------------------------------------
# PLAYER CARD (global profile popup)
# --------------------------------------------------------------------------

def _playercard_viewer_id() -> int | None:
    return _current_player_id()


@app.route("/api/player-card/<int:player_id>")
@require_login
def api_player_card_view(player_id: int):
    viewer_id = _playercard_viewer_id()
    wants_json = request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json"
    try:
        card, err = playercard_logic.build_public_card(player_id, viewer_id=viewer_id)
    except sqlite3.OperationalError:
        logger.warning("player-card view locked player_id=%s", player_id, exc_info=True)
        if wants_json:
            return jsonify({"ok": False, "error": "database_locked"}), 503
        return (
            render_template(
                "partials/player_card_error.html",
                error_key="playercard_load_error",
            ),
            200,
        )
    except Exception:
        logger.exception("player-card view failed player_id=%s", player_id)
        if wants_json:
            return jsonify({"ok": False, "error": "internal_error"}), 500
        return (
            render_template(
                "partials/player_card_error.html",
                error_key="playercard_load_error",
            ),
            200,
        )
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
    sync = {
        "player_id": int(viewer_id),
        "avatar_url": card.get("avatar_url_client") or "",
        "avatar_version": int(card.get("avatar_version") or 0),
        "show_avatar": bool(card.get("avatar_url_client")),
        "theme": card.get("theme") or "cyan",
        "avatar_initial": (card.get("commander_name_raw") or "?")[:1],
    }
    return jsonify({"ok": True, "reason": reason, "html": html, "card": sync})


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
# CHAT API (Genesis TChat)
# --------------------------------------------------------------------------

def _chat_player_id() -> int | None:
    return _current_player_id()


def _chat_json(result: dict, default_status: int = 200):
    if not isinstance(result, dict):
        return jsonify({"ok": False, "error": "internal", "data": None}), 500
    if result.get("ok"):
        return jsonify(result), default_status
    err = str(result.get("error") or "error")
    status = {
        "no_permission": 403,
        "chat_banned": 403,
        "owner_cannot_leave_room": 403,
        "room_not_found": 404,
        "player_not_found": 404,
        "not_found": 404,
        "rate_limited": 429,
        "muted": 403,
        "chat_not_ready": 503,
    }.get(err, 400)
    return jsonify(result), status


@app.route("/api/chat/bootstrap")
@require_login
def api_chat_bootstrap():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    return _chat_json(chat_logic.chat_bootstrap(int(pid)))


@app.route("/api/chat/rooms")
@require_login
def api_chat_rooms():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    rooms = chat_logic.list_rooms_for_player(int(pid))
    return jsonify({"ok": True, "error": None, "data": {"rooms": rooms}})


@app.route("/api/chat/messages")
@require_login
def api_chat_messages():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    try:
        room_id = int(request.args.get("room_id", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_room", "data": None}), 400
    try:
        after_id = int(request.args.get("after_id", 0) or 0)
    except (TypeError, ValueError):
        after_id = 0
    messages, err = chat_logic.fetch_messages(int(pid), room_id, after_id=after_id)
    if err:
        return _chat_json({"ok": False, "error": err, "data": None})
    return jsonify({"ok": True, "error": None, "data": {"messages": messages}})


@app.route("/api/chat/send", methods=["POST"])
@require_login
def api_chat_send():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    body = data.get("body") or request.form.get("body") or ""
    room_id = data.get("room_id")
    if room_id is not None:
        try:
            room_id = int(room_id)
        except (TypeError, ValueError):
            room_id = None
    return _chat_json(
        chat_logic.send_chat_message(
            int(pid),
            str(body),
            room_id=room_id,
            command=data.get("command"),
        )
    )


@app.route("/api/chat/read", methods=["POST"])
@require_login
def api_chat_read():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        room_id = int(data.get("room_id"))
        last_id = int(data.get("last_read_message_id", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    err = chat_logic.mark_room_read(int(pid), room_id, last_id)
    if err:
        return _chat_json({"ok": False, "error": err, "data": None})
    return jsonify({"ok": True, "error": None, "data": {}})


@app.route("/api/chat/state", methods=["POST"])
@require_login
def api_chat_state():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    allowed = ("is_open", "is_minimized", "active_room_id", "width", "height", "pos_x", "pos_y")
    payload = {}
    for k in allowed:
        if k in data:
            payload[k] = data[k]
    state = chat_logic.save_user_state(int(pid), payload)
    return jsonify({"ok": True, "error": None, "data": {"ui_state": state}})


@app.route("/api/chat/players")
@require_login
def api_chat_players():
    q = request.args.get("q", "")
    players = chat_logic.search_players_for_autocomplete(q)
    return jsonify({"ok": True, "error": None, "data": {"players": players}})


@app.route("/api/chat/open-dm", methods=["POST"])
@require_login
def api_chat_open_dm():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("target_player_id") or data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.open_dm_room(int(pid), target_id))


@app.route("/api/chat/rooms/create", methods=["POST"])
@require_login
def api_chat_create_room():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "")
    return _chat_json(chat_logic.create_player_custom_room(int(pid), title))


@app.route("/api/chat/rooms/invite", methods=["POST"])
@require_login
def api_chat_invite_room_member():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        room_id = int(data.get("room_id"))
        target_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.invite_player_to_custom_room(int(pid), room_id, target_id))


@app.route("/api/chat/rooms/remove", methods=["POST"])
@require_login
def api_chat_remove_room_member():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        room_id = int(data.get("room_id"))
        target_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.remove_player_from_custom_room(int(pid), room_id, target_id))


@app.route("/api/chat/rooms/delete", methods=["POST"])
@require_login
def api_chat_delete_room():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        room_id = int(data.get("room_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.delete_custom_room(int(pid), room_id))


@app.route("/api/chat/rooms/leave", methods=["POST"])
@require_login
def api_chat_leave_room():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        room_id = int(data.get("room_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.leave_custom_room(int(pid), room_id))


@app.route("/api/chat/rooms/members")
@require_login
def api_chat_room_members():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    try:
        room_id = int(request.args.get("room_id", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_room", "data": None}), 400
    return _chat_json(chat_logic.list_custom_room_members(int(pid), room_id))


# --------------------------------------------------------------------------
# SUPPORT API (simple ticket module)
# --------------------------------------------------------------------------

def _support_json(result: dict, default_status: int = 200):
    if not isinstance(result, dict):
        return jsonify({"ok": False, "error": "internal", "data": None}), 500
    if result.get("ok"):
        return jsonify(result), default_status
    err = str(result.get("error") or "error")
    status = {
        "not_logged_in": 401,
        "forbidden": 403,
        "not_found": 404,
        "support_not_ready": 503,
    }.get(err, 400)
    return jsonify(result), status


@app.route("/api/support/tickets")
@require_login
def api_support_tickets():
    pid = _current_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    return _support_json(support_logic.list_tickets(int(pid)))


@app.route("/api/support/tickets", methods=["POST"])
@require_login
def api_support_ticket_create():
    pid = _current_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    payload = request.get_json(silent=True) or {}
    return _support_json(support_logic.create_ticket(int(pid), payload))


@app.route("/api/support/tickets/<int:ticket_id>/reply", methods=["POST"])
@require_login
def api_support_ticket_reply(ticket_id: int):
    pid = _current_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    payload = request.get_json(silent=True) or {}
    return _support_json(
        support_logic.reply_ticket(
            int(pid),
            int(ticket_id),
            payload.get("message") or "",
        )
    )


@app.route("/api/support/tickets/<int:ticket_id>/status", methods=["POST"])
@require_login
def api_support_ticket_status(ticket_id: int):
    pid = _current_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    payload = request.get_json(silent=True) or {}
    return _support_json(
        support_logic.change_ticket_status(
            int(pid),
            int(ticket_id),
            payload.get("status") or "",
        )
    )


@app.route("/api/admin/support/tickets", methods=["GET"])
@require_admin_api
def api_admin_support_tickets():
    status = request.args.get("status")
    return _support_json(
        support_logic.list_all_tickets(_admin_actor_id(), status=status)
    )


@app.route("/api/admin/support/tickets/<int:ticket_id>/reply", methods=["POST"])
@require_admin_api
def api_admin_support_ticket_reply(ticket_id: int):
    payload = request.get_json(silent=True) or {}
    return _support_json(
        support_logic.admin_reply_ticket(
            _admin_actor_id(),
            int(ticket_id),
            payload.get("message") or "",
        )
    )


@app.route("/api/admin/support/tickets/<int:ticket_id>/status", methods=["POST"])
@require_admin_api
def api_admin_support_ticket_status(ticket_id: int):
    payload = request.get_json(silent=True) or {}
    return _support_json(
        support_logic.change_ticket_status(
            _admin_actor_id(),
            int(ticket_id),
            payload.get("status") or "",
        )
    )


# --------------------------------------------------------------------------
# MESSAGES API (player inbox)
# --------------------------------------------------------------------------

def _messages_json(result: dict, default_status: int = 200):
    if not isinstance(result, dict):
        return jsonify({"ok": False, "error": "internal", "data": None}), 500
    if result.get("ok"):
        return jsonify(result), default_status
    err = str(result.get("error") or "error")
    status = {
        "not_logged_in": 401,
        "forbidden": 403,
        "not_found": 404,
        "messages_not_ready": 503,
        "cooldown": 429,
        "rate_limited": 429,
        "recipient_not_found": 404,
        "recipient_ambiguous": 400,
        "validation": 400,
    }.get(err, 400)
    return jsonify(result), status


@app.route("/api/admin/messages")
@require_admin_api
def api_admin_messages_list():
    player_id = request.args.get("player_id")
    category = request.args.get("category")
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    pid = None
    if player_id not in (None, ""):
        try:
            pid = int(player_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "validation", "data": None}), 400
    return _messages_json(
        messages_logic.admin_list_messages(
            player_id=pid,
            category=category,
            limit=limit,
            offset=offset,
        )
    )


@app.route("/api/admin/messages/<int:message_id>")
@require_admin_api
def api_admin_messages_get(message_id: int):
    return _messages_json(messages_logic.admin_get_message(int(message_id)))


@app.route("/api/admin/messages/send", methods=["POST"])
@require_admin_api
def api_admin_messages_send():
    payload = request.get_json(silent=True) or {}
    recipient = payload.get("recipient_id") or payload.get("recipient") or payload.get("player_id")
    return _messages_json(
        messages_logic.admin_send_message(
            recipient,
            payload.get("subject") or "",
            payload.get("body") or "",
            category=str(payload.get("category") or "admin"),
            sender_name=payload.get("sender_name"),
        )
    )


def _options_request_meta() -> Dict[str, Optional[str]]:
    return {
        "ip": (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64] or None,
        "user_agent": (request.headers.get("User-Agent") or "")[:256] or None,
    }


def _options_api_response(ok: bool, error: Optional[str] = None, data: Any = None, status: int = 200):
    body: Dict[str, Any] = {"ok": bool(ok), "error": error, "data": data}
    if ok and error:
        body["message"] = error
    return jsonify(body), status


@app.route("/options")
@require_login
def options_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    pid = _current_player_id()
    options_data = options_logic.get_options_snapshot(int(pid)) if pid else {}

    return render_template(
        "options.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        options_data=options_data,
    )


@app.route("/api/options/player-name", methods=["POST"])
@require_login_api
def api_options_player_name():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    name = payload.get("player_name") or payload.get("name") or ""
    meta = _options_request_meta()
    ok, err, data = options_logic.update_player_name(
        int(pid), name, ip=meta["ip"], user_agent=meta["user_agent"]
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/options/planet-name", methods=["POST"])
@require_login_api
def api_options_planet_name():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    name = payload.get("planet_name") or payload.get("name") or ""
    meta = _options_request_meta()
    ok, err, data = options_logic.update_homeworld_name(
        int(pid), name, ip=meta["ip"], user_agent=meta["user_agent"]
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/planet/delete", methods=["POST"])
@require_login_api
def api_planet_delete():
    pid = _current_player_id()
    assert pid is not None
    meta = _options_request_meta()
    ok, err, data = options_logic.delete_active_planet(
        int(pid), ip=meta["ip"], user_agent=meta["user_agent"]
    )
    if not ok:
        status = 400
        if err == "planet_error_not_found":
            status = 404
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/options/email", methods=["POST"])
@require_login_api
def api_options_email():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    email = payload.get("email") or ""
    meta = _options_request_meta()
    ok, err, data = options_logic.update_email(
        int(pid), email, ip=meta["ip"], user_agent=meta["user_agent"]
    )
    if not ok:
        status = 429 if err == "options_error_rate_limited" else 400
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/options/password", methods=["POST"])
@require_login_api
def api_options_password():
    pid = _current_player_id()
    assert pid is not None
    user = get_current_user()
    if not user:
        return _options_api_response(False, "not_logged_in", None, 401)

    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    ok, err, data = options_logic.update_password(
        int(pid),
        str(user.get("username") or ""),
        str(payload.get("current_password") or ""),
        str(payload.get("new_password") or ""),
        str(payload.get("confirm_password") or payload.get("password_confirm") or ""),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        status = 429 if err == "options_error_rate_limited" else 400
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/options/resend-verification", methods=["POST"])
@require_login_api
def api_options_resend_verification():
    pid = _current_player_id()
    assert pid is not None
    ok, err = account_email_logic.resend_verification_email(int(pid))
    if not ok:
        status = 429 if err == "options_error_verify_resend_rate" else 400
        return _options_api_response(False, err, None, status)
    return _options_api_response(True, err, {"email_verified": False})


@app.route("/messages")
@require_login
def messages_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))
    return render_template(
        "messages.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )


@app.route("/api/messages")
@require_login_api
def api_messages_list():
    pid = _current_player_id()
    assert pid is not None
    category = request.args.get("category")
    include_archived = str(request.args.get("include_archived", "")).lower() in ("1", "true", "yes")
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return _messages_json(
        messages_logic.list_messages(
            int(pid),
            category=category,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    )


@app.route("/api/messages/<int:message_id>")
@require_login_api
def api_messages_get(message_id: int):
    pid = _current_player_id()
    assert pid is not None
    return _messages_json(messages_logic.get_message(int(pid), int(message_id)))


@app.route("/api/messages/<int:message_id>/read", methods=["POST"])
@require_login_api
def api_messages_read(message_id: int):
    pid = _current_player_id()
    assert pid is not None
    return _messages_json(messages_logic.mark_message_read(int(pid), int(message_id)))


@app.route("/api/messages/read-all", methods=["POST"])
@require_login_api
def api_messages_read_all():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    return _messages_json(
        messages_logic.mark_all_messages_read(
            int(pid),
            category=payload.get("category"),
        )
    )


@app.route("/api/messages/<int:message_id>/archive", methods=["POST"])
@require_login_api
def api_messages_archive(message_id: int):
    pid = _current_player_id()
    assert pid is not None
    return _messages_json(messages_logic.archive_message(int(pid), int(message_id)))


@app.route("/api/messages/<int:message_id>/delete", methods=["POST"])
@require_login_api
def api_messages_delete(message_id: int):
    pid = _current_player_id()
    assert pid is not None
    return _messages_json(messages_logic.delete_message(int(pid), int(message_id)))


@app.route("/api/messages/send", methods=["POST"])
@require_login_api
def api_messages_send():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    return _messages_json(
        messages_logic.send_player_message(
            int(pid),
            payload.get("recipient") or payload.get("recipient_name") or "",
            payload.get("subject") or "",
            payload.get("body") or "",
        )
    )


@app.route("/api/chat/admin/search")
@require_login
def api_chat_admin_search():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    q = request.args.get("q", "")
    limit = request.args.get("limit", 50)
    try:
        limit_i = int(limit)
    except (TypeError, ValueError):
        limit_i = 50
    return _chat_json(chat_logic.admin_search_messages(int(pid), q, limit=limit_i))


@app.route("/api/chat/admin/delete-message", methods=["POST"])
@require_login
def api_chat_admin_delete_message():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.admin_delete_message(int(pid), message_id))


@app.route("/api/chat/admin/mute", methods=["POST"])
@require_login
def api_chat_admin_mute():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("player_id"))
        muted_until = int(data.get("muted_until"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    scope = str(data.get("scope") or "global")
    room_id = data.get("room_id")
    if room_id is not None:
        try:
            room_id = int(room_id)
        except (TypeError, ValueError):
            room_id = None
    return _chat_json(
        chat_logic.admin_mute_player(
            int(pid),
            target_id,
            scope,
            muted_until,
            room_id=room_id,
            reason=data.get("reason"),
        )
    )


@app.route("/api/chat/admin/system-notice", methods=["POST"])
@require_login
def api_chat_admin_system_notice():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    body = str(data.get("body") or "")
    return _chat_json(chat_logic.admin_system_notice(int(pid), body))


@app.route("/api/chat/admin/ban", methods=["POST"])
@require_login
def api_chat_admin_ban():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.admin_chat_ban_player(int(pid), target_id, reason=data.get("reason")))


@app.route("/api/chat/admin/unban", methods=["POST"])
@require_login
def api_chat_admin_unban():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    return _chat_json(chat_logic.admin_chat_unban_player(int(pid), target_id))


@app.route("/api/chat/admin/unmute", methods=["POST"])
@require_login
def api_chat_admin_unmute():
    pid = _chat_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401
    data = request.get_json(silent=True) or {}
    try:
        target_id = int(data.get("player_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_payload", "data": None}), 400
    scope = data.get("scope")
    scope_val = str(scope) if scope else None
    return _chat_json(chat_logic.admin_unmute_player(int(pid), target_id, scope=scope_val))


# --------------------------------------------------------------------------
# API (AJAX / main.js)
# --------------------------------------------------------------------------

def _payload_from_live_context(
    ctx: Dict[str, Any],
    *,
    user_id: int,
    include_panel: bool = True,
) -> Dict[str, Any]:
    """Build JSON payload from an already-refreshed live context."""
    from game.logic import get_research_modifiers

    player_view = ctx["player_view"]
    buildings = ctx["buildings"]
    ratio = ctx["ratio"]
    energy_total = ctx["energy_total"]
    energy_used = ctx["energy_used"]
    storage_caps = ctx["storage_caps"]
    build_queue = ctx["build_queue"]
    research = ctx["research"]
    prod_per_hour = ctx["prod_per_hour"]

    energy_efficiency_pct = int(round(float(ratio) * 100))
    mods = get_research_modifiers(user_id)

    payload: Dict[str, Any] = {
        "ok": True,
        "server_time": time.time(),
        "energy_ratio": float(ratio),
        "energy_efficiency_pct": energy_efficiency_pct,
        "player": {
            "name": player_view["name"],
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
            "energy_ratio": float(ratio),
            "energy_efficiency_pct": energy_efficiency_pct,
        },
        "resources": {
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
            "energy_ratio": float(ratio),
            "energy_efficiency_pct": energy_efficiency_pct,
            "storage": storage_caps,
        },
        "buildings": buildings,
        "build_queue": build_queue,
        "building_queue": build_queue,
        "production_per_hour": prod_per_hour,
        "research": research,
        "research_queue": research.get("queue", []),
        "storage": storage_caps,
        "energy": {
            "total": int(energy_total),
            "used": int(energy_used),
            "ratio": float(ratio),
            "efficiency_pct": energy_efficiency_pct,
            "mine_energy_factor": float(mods.get("mine_energy_factor", 1.0) or 1.0),
        },
        "overview": {
            "rows": [
                {
                    "key": key,
                    "level": int(buildings.get(key, 0) or 0),
                    "production_per_hour": int(prod_per_hour.get(key, 0) or 0),
                }
                for key in ("metal_mine", "crystal_mine", "solar_plant")
            ],
            "energy_hint": (
                "zero"
                if int(energy_total) <= 0
                else ("ok" if float(ratio) >= 1.0 else "low")
            ),
        },
    }

    from game.overview_page import build_overview_status
    from game.planet_evolution.repository import get_active_planet_id, get_context_planet

    planet = get_context_planet(user_id)
    payload["overview"]["status"] = build_overview_status(
        user_id=user_id,
        player_view=player_view,
        ratio=float(ratio),
        energy_total=int(energy_total),
        energy_used=int(energy_used),
        storage_caps=storage_caps,
        prod_per_hour=prod_per_hour,
        build_queue=build_queue,
        research=research,
        planet=planet,
        include_log=False,
    )

    active_planet_id = get_active_planet_id(user_id)
    payload["active_planet_id"] = int(active_planet_id)

    if include_panel:
        planet = get_context_planet(user_id)
        payload["buildings_panel"] = get_buildings_panel_rows(
            planet,
            buildings,
            build_queue=build_queue,
        )

    score = get_player_score_cached(user_id, read_only=True) or {
        "total": 0,
        "buildings": 0,
        "research": 0,
    }
    rank, total_players = get_player_rank(user_id)

    payload["score"] = {
        "total": int(score.get("total", 0) or 0),
        "buildings": int(score.get("buildings", 0) or 0),
        "research": int(score.get("research", 0) or 0),
        "rank": int(rank) if rank else None,
        "total_players": int(total_players) if total_players else None,
    }

    try:
        payload["unread_messages_count"] = messages_logic.unread_count(user_id)
    except Exception:
        payload["unread_messages_count"] = 0

    try:
        from game.exchange import exchange_schema_ready, get_exchange_status

        conn_ex = db()
        try:
            if exchange_schema_ready(conn_ex):
                planet = get_context_planet(user_id, conn=conn_ex)
                payload["exchange"] = get_exchange_status(
                    player_id=user_id,
                    planet_id=int(planet["id"]),
                    metal=float(player_view["metal"]),
                    crystal=float(player_view["crystal"]),
                    conn=conn_ex,
                )
        finally:
            conn_ex.close()
    except Exception:
        pass

    try:
        from game.planet_evolution.teaser import get_overview_planet_teaser

        payload["planet_teaser"] = get_overview_planet_teaser(
            user_id,
            metal=float(player_view["metal"]),
            crystal=float(player_view["crystal"]),
        )
    except Exception:
        payload["planet_teaser"] = {"visible": False}

    return payload


def _build_game_state_payload(
    include_panel: bool = True,
    *,
    finish_source: str = "game_state",
) -> Tuple[dict, int]:
    """
    Zentraler Spielzustand für Polling + AJAX-Refresh (kein Page-Reload).
    Returns (payload, player_id).
    """
    user = get_current_user()
    if not user:
        return {"ok": False, "error": "not_logged_in"}, 0

    user_id = int(user["id"])
    ctx = _load_page_live_context(
        finish_source=str(finish_source or "game_state"),
        include_panel=include_panel,
    )
    if ctx is None:
        return {"ok": False, "error": "not_logged_in"}, 0

    return _payload_from_live_context(ctx, user_id=user_id, include_panel=include_panel), user_id


def _player_context_for_action() -> Optional[Tuple[Any, Dict[str, int]]]:
    """Lightweight player + buildings for mutations (no full live refresh)."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    user_id = int(user_id)
    player_view = load_player(user_id)
    if not player_view:
        return None
    from game.planet_evolution.repository import get_context_planet

    planet = get_context_planet(user_id)
    buildings = get_planet_buildings(int(planet["id"]))
    return player_view, buildings


def _extract_request_id(data: Dict[str, Any]) -> str:
    rid = (data.get("request_id") or request.headers.get("X-Request-Id") or "").strip()
    return rid


def _action_json_response(
    ok: bool,
    reason: str,
    payload: Any = None,
    job: Any = None,
    *,
    finish_source: str = "action",
) -> Any:
    """Immer frischen Spielzustand liefern – auch bei Fehlern (ein Refresh nach Mutation)."""
    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
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
    """Alias von /api/game-state (gleiches Schema)."""
    return api_game_state()


@app.route("/api/game-state")
@require_login
def api_game_state():
    payload, _player_id = _build_game_state_payload(include_panel=True, finish_source="game_state")
    if not payload.get("ok"):
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    return jsonify(payload)


@app.route("/api/exchange/rates")
@require_login
def api_exchange_rates():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.exchange import exchange_schema_ready, get_exchange_status
    from game.planet_evolution.repository import get_context_planet
    from game.logic import refresh_player_live_state

    conn = db()
    try:
        if not exchange_schema_ready(conn):
            return jsonify({"ok": False, "reason": "exchange_unavailable"}), 503
        player_view, _, _, _, _, _ = refresh_player_live_state(user_id, conn=conn, finish_source="exchange_rates")
        planet = get_context_planet(user_id, conn=conn)
        status = get_exchange_status(
            player_id=user_id,
            planet_id=int(planet["id"]),
            metal=float(player_view["metal"]),
            crystal=float(player_view["crystal"]),
            conn=conn,
        )
        conn.commit()
        return jsonify({"ok": True, "exchange": status})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


@app.route("/api/exchange", methods=["POST"])
@require_login
def api_exchange():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    from_resource = (data.get("from") or data.get("from_resource") or "").strip().lower()
    direction = (data.get("direction") or "").strip().lower()
    if direction == "metal_to_crystal":
        from_resource = "metal"
    elif direction == "crystal_to_metal":
        from_resource = "crystal"

    try:
        amount = int(data.get("amount") or 0)
    except (TypeError, ValueError):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_exchange")
        return jsonify({"ok": False, "reason": "invalid_amount", "state": state}), 400

    from game.exchange import execute_exchange, exchange_schema_ready
    from game.planet_evolution.repository import get_context_planet

    if not exchange_schema_ready(db()):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_exchange")
        return jsonify({"ok": False, "reason": "exchange_unavailable", "state": state}), 503

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        ok, reason, result = execute_exchange(
            player_id=user_id,
            planet_id=int(planet["id"]),
            from_resource=from_resource,
            amount=amount,
            conn=conn,
        )
    finally:
        conn.close()

    return _action_json_response(
        ok,
        reason,
        payload=result if not ok else None,
        job=result if ok else None,
        finish_source="api_exchange",
    )


@app.route("/api/buildings/upgrade", methods=["POST"])
@require_login
def api_buildings_upgrade():
    data = request.get_json(silent=True) or {}
    building_type = (data.get("building_type") or request.form.get("building_type") or "").strip()
    if not building_type:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_building_type", "state": state}), 400

    ctx = _player_context_for_action()
    if ctx is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    player_view, buildings = ctx

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
        finish_source="api_buildings_upgrade",
    )
    response_obj = resp.get_json()

    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)

    return resp


@app.route("/api/buildings/cancel", methods=["POST"])
@require_login
def api_buildings_cancel():
    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or request.form.get("job_id") or 0)
    except (TypeError, ValueError):
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_job_id", "state": state}), 400
    if job_id <= 0:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_job_id", "state": state}), 400

    ctx = _player_context_for_action()
    if ctx is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    player_view, _buildings = ctx

    ok, reason, extra = cancel_build(player_view, job_id)
    return _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_buildings_cancel",
    )


@app.route("/api/research/start", methods=["POST"])
@require_login
def api_research_start():
    data = request.get_json(silent=True) or {}
    tech_key = (data.get("tech_key") or request.form.get("tech_key") or "").strip()
    if not tech_key:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_tech_key", "state": state}), 400

    ctx = _player_context_for_action()
    if ctx is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    player_view, _buildings = ctx

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
        finish_source="api_research_start",
    )
    response_obj = resp.get_json()

    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)

    return resp


@app.route("/api/research/cancel", methods=["POST"])
@require_login
def api_research_cancel():
    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or request.form.get("job_id") or 0)
    except (TypeError, ValueError):
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_job_id", "state": state}), 400
    if job_id <= 0:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_job_id", "state": state}), 400

    ctx = _player_context_for_action()
    if ctx is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    player_view, _buildings = ctx

    ok, reason, extra = cancel_research(player_view, job_id)
    return _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_research_cancel",
    )


# --------------------------------------------------------------------------
# PLANET EVOLUTION
# --------------------------------------------------------------------------

@app.route("/planet-evolution")
@require_login
def planet_evolution_view():
    ctx = _load_page_live_context(finish_source="planet_evolution")
    if ctx is None:
        return redirect(url_for("login"))

    user_id = int(ctx["player_view"]["id"])
    from game.planet_evolution.service import get_planet_state_payload, list_player_planets
    from game.planet_evolution.repository import get_active_planet_id

    conn = db()
    try:
        active_id = get_active_planet_id(user_id, conn=conn)
        planet_state = get_planet_state_payload(active_id, player_id=user_id, conn=conn)
        planets = list_player_planets(user_id, conn=conn)
        conn.commit()
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return render_template(
        "planet_evolution.html",
        player=ctx["player_view"],
        planet_state=planet_state,
        planets=planets,
        build_queue=ctx["build_queue"],
        research_status=ctx["research"],
    )


@app.route("/api/planets")
@require_login
def api_planets_list():
    user_id = int(session["user_id"])
    from game.planet_evolution.service import list_player_planets

    return jsonify({"ok": True, "planets": list_player_planets(user_id)})


@app.route("/api/planets/active", methods=["POST"])
@require_login
def api_planets_set_active():
    data = request.get_json(silent=True) or {}
    try:
        planet_id = int(data.get("planet_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_planet_id"}), 400
    from game.planet_evolution.service import set_active_planet

    ok, reason = set_active_planet(int(session["user_id"]), planet_id)
    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_planets_active")
    return jsonify({"ok": ok, "reason": reason, "state": state})


@app.route("/api/planets/<int:planet_id>/state")
@require_login
def api_planet_state(planet_id: int):
    from game.planet_evolution.service import get_planet_state_payload

    payload = get_planet_state_payload(planet_id, player_id=int(session["user_id"]))
    if payload.get("error"):
        return jsonify({"ok": False, "reason": payload["error"]}), 403
    return jsonify({"ok": True, "planet": payload})


@app.route("/api/planets/<int:planet_id>/research")
@require_login
def api_planet_research_status(planet_id: int):
    from game.planet_evolution.planet_research import get_planet_research_status
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    return jsonify({"ok": True, "research": get_planet_research_status(planet_id)})


@app.route("/api/planets/<int:planet_id>/research/start", methods=["POST"])
@require_login
def api_planet_research_start(planet_id: int):
    data = request.get_json(silent=True) or {}
    tech_key = (data.get("tech_key") or "").strip()
    if not tech_key:
        return jsonify({"ok": False, "reason": "missing_tech_key"}), 400
    from game.planet_evolution.planet_research import queue_planet_research
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    request_id = _extract_request_id(data)
    user_id = int(session["user_id"])
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)
    ok, reason, extra = queue_planet_research(
        planet_id,
        tech_key,
        player_id=user_id,
        request_id=request_id or None,
    )
    resp = _action_json_response(ok, reason, payload=extra if not ok else None, job=extra if ok else None, finish_source="api_planet_research_start")
    if request_id:
        save_idempotent_action(user_id, request_id, resp.get_json())
    return resp


@app.route("/api/planets/<int:planet_id>/research/choose", methods=["POST"])
@require_login
def api_planet_research_choose(planet_id: int):
    data = request.get_json(silent=True) or {}
    choice_group = (data.get("choice_group") or "").strip()
    choice_key = (data.get("choice_key") or "").strip()
    if not choice_group or not choice_key:
        return jsonify({"ok": False, "reason": "missing_choice"}), 400
    from game.planet_evolution.service import make_locked_choice
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason = make_locked_choice(planet_id, choice_group, choice_key, int(session["user_id"]))
    return _action_json_response(ok, reason, finish_source="api_planet_research_choose")


@app.route("/api/planets/<int:planet_id>/specialization/pick", methods=["POST"])
@require_login
def api_planet_spec_pick(planet_id: int):
    data = request.get_json(silent=True) or {}
    spec_key = (data.get("spec_key") or "").strip()
    if not spec_key:
        return jsonify({"ok": False, "reason": "missing_spec_key"}), 400
    from game.planet_evolution.service import pick_specialization
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason, extra = pick_specialization(planet_id, spec_key, int(session["user_id"]))
    return _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_planet_spec_pick",
    )


@app.route("/api/planets/<int:planet_id>/specialization/upgrade", methods=["POST"])
@require_login
def api_planet_spec_upgrade(planet_id: int):
    from game.planet_evolution.service import upgrade_specialization_tier
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason, extra = upgrade_specialization_tier(planet_id, int(session["user_id"]))
    return _action_json_response(ok, reason, payload=extra if not ok else None, job=extra if ok else None, finish_source="api_planet_spec_upgrade")


@app.route("/api/planets/<int:planet_id>/policies/activate", methods=["POST"])
@require_login
def api_planet_policy_activate(planet_id: int):
    data = request.get_json(silent=True) or {}
    try:
        slot = int(data.get("slot") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_slot"}), 400
    policy_key = (data.get("policy_key") or "").strip()
    if slot <= 0 or not policy_key:
        return jsonify({"ok": False, "reason": "invalid_payload"}), 400
    from game.planet_evolution.service import activate_policy
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason = activate_policy(planet_id, slot, policy_key, int(session["user_id"]))
    return _action_json_response(ok, reason, finish_source="api_planet_policy_activate")


@app.route("/api/planets/<int:planet_id>/events/resolve", methods=["POST"])
@require_login
def api_planet_event_resolve(planet_id: int):
    data = request.get_json(silent=True) or {}
    try:
        event_id = int(data.get("event_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_event_id"}), 400
    choice_key = (data.get("choice_key") or "").strip()
    if event_id <= 0 or not choice_key:
        return jsonify({"ok": False, "reason": "invalid_payload"}), 400
    from game.planet_evolution.service import resolve_event_choice
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason, extra = resolve_event_choice(planet_id, event_id, choice_key, int(session["user_id"]))
    return _action_json_response(ok, reason, payload=extra if not ok else None, job=extra if ok else None, finish_source="api_planet_event_resolve")


@app.route("/api/planets/colonize", methods=["POST"])
@require_login
def api_planets_colonize():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "reason": "missing_name"}), 400
    from game.planet_evolution.service import colonize_planet

    ok, reason, extra = colonize_planet(
        int(session["user_id"]),
        name=name,
        galaxy=int(data.get("galaxy") or 1),
        system=data.get("system"),
        position=data.get("position"),
    )
    return _action_json_response(ok, reason, payload=extra if not ok else None, job=extra if ok else None, finish_source="api_planets_colonize")


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


@app.route("/api/admin/player/<int:player_id>/effects", methods=["GET"])
@require_admin_api
def api_admin_player_effects(player_id: int):
    return _admin_json(admin_api_logic.get_player_effects_debug(player_id))


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


@app.route("/api/admin/queue-tick", methods=["POST"])
@require_admin_api
def api_admin_queue_tick():
    return _admin_json(admin_api_logic.run_queue_tick_admin(_admin_actor_id()))


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
