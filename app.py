import json
import logging
import os
import random
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import (
    Flask,
    abort,
    render_template,
    redirect,
    url_for,
    request,
    jsonify,
    flash,
    session,
    g,
    Response,
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
from game.db import begin_write_transaction, commit, rollback

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
    get_techtree_page_context,
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
from game import discord_auth as discord_auth_logic

from game.bootstrap import bootstrap_application
from game.config import get_secret_key, is_debug_enabled, is_production
from game.security import (
    apply_security_headers,
    check_login_rate_limit,
    check_register_rate_limit,
    client_ip,
    generate_csrf_token,
    session_cookie_secure_override,
    validate_csrf_request,
)

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

# GC-861B — moderate cache for unversioned raster static assets (7 days)
GC_STATIC_IMAGE_CACHE_MAX_AGE = 604800
GC_STATIC_IMAGE_SUFFIXES = frozenset({".webp", ".png", ".jpg", ".jpeg", ".gif", ".svg"})


def _is_static_image_path(path: str) -> bool:
    if not path.startswith("/static/"):
        return False
    lower = path.lower().split("?", 1)[0]
    return any(lower.endswith(ext) for ext in GC_STATIC_IMAGE_SUFFIXES)


def apply_static_image_cache_headers(response: Response) -> Response:
    """Set Cache-Control on raster files under /static/ (no query-version bust yet)."""
    if response.status_code not in (200, 304):
        return response
    if not _is_static_image_path(request.path or ""):
        return response
    response.headers["Cache-Control"] = f"public, max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}"
    return response


BACKGROUND_CLASSES = ["bg-1", "bg-2", "bg-3", "bg-4"]
GC_LOCALE = "de"

from game.i18n import (
    DEFAULT_LOCALE,
    current_locale,
    format_i18n,
    get_locale_dict,
    get_player_locale,
    normalize_locale,
    set_player_locale,
    set_request_locale,
)


def _load_t_data(locale: str | None = None) -> dict[str, Any]:
    return get_locale_dict(locale)


T_DATA: dict[str, Any] = _load_t_data(GC_LOCALE)


def T(key: str, *fmt_args, **fmt_kwargs) -> str:
    data = get_locale_dict(current_locale())
    if key in data:
        txt = data[key]
    elif len(fmt_args) == 1 and isinstance(fmt_args[0], str):
        txt = fmt_args[0]
        fmt_args = ()
    else:
        txt = key
    if not fmt_args and not fmt_kwargs:
        return txt
    if fmt_kwargs:
        return format_i18n(txt, **fmt_kwargs)
    positional = {str(i): arg for i, arg in enumerate(fmt_args)}
    return format_i18n(txt, **positional)


from game.number_format import fmt_int as _fmt_int_canonical, fmt_int_compact as _fmt_int_compact_canonical


@app.template_filter("fmt_int")
def fmt_int_filter(value):
    return _fmt_int_canonical(value)


@app.template_filter("fmt_int_compact")
def fmt_int_compact_filter(value):
    return _fmt_int_compact_canonical(value)


@app.template_filter("webp_static")
def webp_static_filter(url: str) -> str:
    """GC-555 — sibling WebP URL for a static raster asset URL."""
    text = str(url or "").strip()
    if not text or "." not in text:
        return text
    base, dot, ext = text.rpartition(".")
    if ext.lower() not in ("png", "jpg", "jpeg"):
        return text
    return f"{base}.webp"


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


@app.template_global()
def galaxy_coord_link(
    coords,
    text=None,
    extra_class: str = "gc-galaxy-coord-link gc-mono",
) -> Markup:
    """Clickable coordinate link to the galaxy view (highlights position when given)."""
    from game.galaxy import galaxy_view_href

    raw = str(coords or "").strip()
    if not raw or raw == "—":
        return Markup(escape(text if text is not None else "—"))
    href = galaxy_view_href(raw)
    display = escape(text if text is not None else raw)
    if not href:
        return Markup(display)
    classes = escape(str(extra_class or "gc-galaxy-coord-link gc-mono").strip())
    title = escape(T("galaxy_coord_link_title", "View in galaxy"))
    return Markup(
        f'<a href="{escape(href)}" class="{classes}" title="{title}">{display}</a>'
    )


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
    try:
        uid = session.get("user_id")
        if uid:
            locale = get_player_locale(int(uid))
        else:
            locale = normalize_locale(request.cookies.get("gc_locale"))
        set_request_locale(locale)
    except Exception:
        set_request_locale(DEFAULT_LOCALE)


# --------------------------------------------------------------------------
# CONTEXT / GLOBALS
# --------------------------------------------------------------------------

_SIMPLE_LAYOUT_ENDPOINTS = frozenset(
    {
        "landing",
        "login",
        "register",
        "forgot_password",
        "reset_password",
        "verify_email",
        "logout",
        "auth_discord_start",
        "auth_discord_callback",
        "discord_welcome",
    }
)


def _is_pjax_request() -> bool:
    from flask import request

    return str(request.headers.get("X-PJAX", "")).strip().lower() in ("1", "true", "yes")


def _is_simple_layout_request() -> bool:
    from flask import request

    return str(request.endpoint or "") in _SIMPLE_LAYOUT_ENDPOINTS


def _is_lightweight_layout_request() -> bool:
    """Auth/landing pages and PJAX fragment fetches — shell globals are unused client-side."""
    return _is_simple_layout_request() or _is_pjax_request()


@app.context_processor
def inject_globals():
    auth_user = None
    auth_admin = False

    settings: dict[str, Any] = {}
    motd_enabled = False
    motd_text = ""
    motd_banner: dict[str, Any] | None = None

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

    # motd / universe news (safe) — skip on auth/simple pages and PJAX (GC-741, GC-745)
    simple_layout = _is_lightweight_layout_request()
    try:
        if not simple_layout:
            raw_motd_enabled = settings.get("motd_enabled", "0")
            motd_enabled = str(raw_motd_enabled) in ("1", "true", "True", "yes", "on")
            from game.universe_news import get_banner_entry

            motd_banner = get_banner_entry()
            if motd_banner:
                motd_text = motd_banner.get("body") or ""
            else:
                motd_text = (settings.get("motd_text", "") or "").strip()
    except Exception:
        motd_enabled = False
        motd_text = ""
        motd_banner = None

    sidebar_release = {"label": "Genesis", "url": "/news", "href": "/news", "anchor_id": "", "has_dev_stream": False}
    try:
        if not simple_layout:
            from game.universe_news import sidebar_release_nav

            sidebar_release = sidebar_release_nav()
    except Exception:
        pass

    # stats (safe) — global counts not needed on login/register
    try:
        if not simple_layout:
            player_stats = get_player_stats() or {}
    except Exception:
        player_stats = {}

    # score + rank (header/sidebar) – darf niemals crashen
    try:
        user_id = session.get("user_id")
        if user_id is not None:
            player_id = int(user_id)  # players.id == users.id

            s = get_player_score_cached(player_id, read_only=True) or {}
            score_total = int(s.get("total", 0) or 0)
            score_buildings = int(s.get("buildings", 0) or 0)
            score_research = int(s.get("research", 0) or 0)

            my_rank, total_players = get_player_rank(player_id)
            if my_rank and total_players:
                rank_text = f"#{int(my_rank)}/{int(total_players)}"
    except Exception:
        pass

    header_planets: list[dict[str, Any]] = []
    header_active_planet: dict[str, Any] | None = None
    try:
        user_id = session.get("user_id")
        if user_id is not None:
            from game.planet_evolution.service import list_player_planets_for_switcher

            header_planets = list_player_planets_for_switcher(int(user_id))
            for row in header_planets:
                if row.get("is_active"):
                    header_active_planet = row
                    break
            if header_active_planet is None and header_planets:
                header_active_planet = header_planets[0]
    except Exception:
        header_planets = []
        header_active_planet = None

    current_planet_landscape_url = None
    current_planet_landscape_webp_url = None
    try:
        user_id = session.get("user_id")
        if user_id is not None:
            from game.planet_visuals import landscape_filename_for_planet, raster_webp_relpath

            landscape_fn = landscape_filename_for_planet(header_active_planet)
            landscape_rel = f"img/landscapes/{landscape_fn}"
            current_planet_landscape_url = url_for("static", filename=landscape_rel)
            current_planet_landscape_webp_url = url_for(
                "static", filename=raster_webp_relpath(landscape_rel)
            )
    except Exception:
        current_planet_landscape_url = None
        current_planet_landscape_webp_url = None

    from game.config import get_client_runtime_config, is_command_map_dev_mode
    from game.planet_evolution.sidebar_nav import (
        ADMINISTRATION_MODULES,
        client_sidebar_nav_config,
        mobile_bottom_modules,
        mobile_drawer_shows_module,
        module_display_section,
        module_in_section,
        nav_link_visible,
        nav_module_tier,
        resolve_sidebar_nav,
        secondary_overflow_modules,
        sidebar_section_visible,
        visible_sidebar_modules,
    )

    sidebar_nav = {"full_nav": True, "modules": {}, "empire_role_key": "general"}
    try:
        sidebar_nav = resolve_sidebar_nav(
            empire_role_key=str((header_active_planet or {}).get("empire_role_key") or "general"),
            is_homeworld=bool((header_active_planet or {}).get("is_homeworld")),
        )
    except Exception:
        pass

    active_locale = current_locale()
    auth_discord_linked = False
    discord_oauth_enabled = False
    discord_invite_url = ""
    try:
        discord_oauth_enabled = discord_auth_logic.discord_oauth_configured()
        discord_invite_url = discord_auth_logic.discord_invite_url()
    except Exception:
        pass
    try:
        if auth_user and auth_user.get("id") and not simple_layout:
            snap = discord_auth_logic.discord_link_snapshot(int(auth_user["id"]))
            auth_discord_linked = bool(snap.get("discord_linked"))
    except Exception:
        auth_discord_linked = False

    return dict(
        T=T,
        T_DATA=get_locale_dict(active_locale),
        GC_LOCALE=active_locale,
        GC_ASSET_VERSION=GC_ASSET_VERSION,
        GC_CLIENT_CONFIG=get_client_runtime_config(),
        player_name_link=player_name_link,
        CURRENT_PLAYER_ID=_current_player_id(),

        AUTH_USER=auth_user,
        AUTH_ADMIN=auth_admin,
        GC_DEBUG_ENABLED=is_debug_enabled(),
        COMMAND_MAP_DEV_MODE=is_command_map_dev_mode(),

        GAME_SETTINGS=settings,
        motd_enabled=motd_enabled,
        motd_text=motd_text,
        motd_banner=motd_banner,
        SIDEBAR_RELEASE=sidebar_release,

        PLAYER_STATS=player_stats,

        score=score_total,
        score_buildings=score_buildings,
        score_research=score_research,
        rank_text=rank_text,
        my_rank=my_rank,
        total_players=total_players,

        HEADER_PLANETS=header_planets,
        HEADER_ACTIVE_PLANET=header_active_planet,
        SIDEBAR_NAV=sidebar_nav,
        SIDEBAR_NAV_CLIENT=client_sidebar_nav_config(),
        ADMINISTRATION_MODULES=sorted(ADMINISTRATION_MODULES),
        MOBILE_BOTTOM_MODULES=mobile_bottom_modules(sidebar_nav),
        nav_module_tier=nav_module_tier,
        nav_link_visible=nav_link_visible,
        module_in_section=module_in_section,
        module_display_section=module_display_section,
        secondary_overflow_modules=secondary_overflow_modules,
        visible_sidebar_modules=visible_sidebar_modules,
        sidebar_section_visible=sidebar_section_visible,
        mobile_drawer_shows_module=mobile_drawer_shows_module,
        current_planet_landscape_url=current_planet_landscape_url,
        current_planet_landscape_webp_url=current_planet_landscape_webp_url,
        SERVER_TIME=int(time.time()),
        DISCORD_OAUTH_ENABLED=discord_oauth_enabled,
        DISCORD_INVITE_URL=discord_invite_url,
        AUTH_DISCORD_LINKED=auth_discord_linked,
    )


# --------------------------------------------------------------------------
# BOOTSTRAP (config, DB, migration guard)
# --------------------------------------------------------------------------

_skip_mig = os.environ.get("GC_SKIP_MIGRATION_CHECK", "0").strip().lower() in ("1", "true", "yes")
bootstrap_application(skip_migration_check=_skip_mig)
app.secret_key = get_secret_key() or os.urandom(32).hex()

_cookie_secure = session_cookie_secure_override()
if _cookie_secure is None:
    _cookie_secure = is_production()

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_cookie_secure,
)


@app.template_global()
def csrf_input() -> Markup:
    """Hidden input for HTML form CSRF (GC-SEC-P0)."""
    token = escape(generate_csrf_token())
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


def _session_cookie_secure() -> bool:
    return bool(app.config.get("SESSION_COOKIE_SECURE"))


@app.after_request
def _gc_security_headers(response):
    secure = _session_cookie_secure() or bool(request.is_secure)
    response = apply_security_headers(response, secure=secure)
    return apply_static_image_cache_headers(response)


def _auth_form_error_key() -> Optional[str]:
    """Validate CSRF for public auth HTML forms. Returns locale error key or None."""
    if not validate_csrf_request(request, testing=bool(app.config.get("TESTING"))):
        return "msg_csrf_invalid"
    return None


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


@app.route("/api/internal/cron/ranking", methods=["POST"])
def api_internal_cron_ranking():
    """Token-gated ranking recompute — same DB as web (Railway SQLite cron)."""
    from game.internal_cron import handle_internal_cron_ranking

    payload, status = handle_internal_cron_ranking(request)
    return jsonify(payload), status


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
    conn=None,
    close_conn: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    One finish + derived sync + read-only queue/research per page/API request.
    """
    from game.logic import refresh_player_live_state

    user_id = session.get("user_id")
    if user_id is None:
        return None

    user_id = int(user_id)
    own_conn = conn is None
    if own_conn:
        conn = db()
    src = str(finish_source or "page_load")
    use_poll_live_path = src == "game_state" or _is_pjax_request()
    try:
        try:
            if use_poll_live_path:
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
                commit(conn)
            from game.live_state import get_request_context_planet
            from game.buildings import get_build_queue_status_for_planet

            planet = get_request_context_planet(user_id, conn=conn)
            build_queue = get_build_queue_status_for_planet(
                int(planet["id"]),
                conn=conn,
                skip_finish=True,
            )
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
        except RuntimeError:
            return None
        except sqlite3.OperationalError:
            rollback(conn)
            if not use_poll_live_path:
                raise
            logger.warning(
                "page live context locked, using read-only fallback user_id=%s source=%s",
                user_id,
                src,
                exc_info=True,
            )
            from game.logic import _read_player_live_state_no_writes
            from game.live_state import get_request_context_planet
            from game.buildings import get_build_queue_status_for_planet

            player = load_player(user_id, conn=conn)
            if not player:
                return None
            planet = get_request_context_planet(user_id, conn=conn)
            player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
                _read_player_live_state_no_writes(user_id, conn, player, planet)
            )
            build_queue = get_build_queue_status_for_planet(
                int(planet["id"]),
                conn=conn,
                skip_finish=True,
            )
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
        if own_conn or close_conn:
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
        "planet": planet,
    }


def _is_game_state_poll_source(finish_source: str) -> bool:
    """Lightweight poll path (throttled persist). Panel polls use game_state_panel."""
    return str(finish_source or "") == "game_state"


# --------------------------------------------------------------------------
# AUTH ROUTES
# --------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        csrf_key = _auth_form_error_key()
        if csrf_key:
            error = T(csrf_key) if T(csrf_key) != csrf_key else csrf_key
        elif not check_login_rate_limit(client_ip(request)):
            error = T("msg_auth_rate_limited") if T("msg_auth_rate_limited") != "msg_auth_rate_limited" else (
                "Zu viele Login-Versuche – bitte später erneut versuchen."
            )
        else:
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


@app.route("/auth/discord")
def auth_discord_start():
    if not discord_auth_logic.discord_oauth_configured():
        flash(T("discord_oauth_unavailable"), "error")
        return redirect(url_for("login"))

    state = discord_auth_logic.start_oauth_session(session, link=False)
    return redirect(discord_auth_logic.build_authorize_url(state))


@app.route("/auth/discord/link")
@require_login
def auth_discord_link_start():
    if not discord_auth_logic.discord_oauth_configured():
        flash(T("discord_oauth_unavailable"), "error")
        return redirect(url_for("options_view"))

    state = discord_auth_logic.start_oauth_session(session, link=True)
    return redirect(discord_auth_logic.build_authorize_url(state))


def _discord_callback_redirect_on_error(is_link: bool):
    if is_link and session.get("user_id"):
        return redirect(url_for("options_view"))
    return redirect(url_for("login"))


@app.route("/auth/discord/callback")
def auth_discord_callback():
    if not discord_auth_logic.discord_oauth_configured():
        flash(T("discord_oauth_unavailable"), "error")
        return redirect(url_for("login"))

    received_state = str(request.args.get("state") or "")
    valid, is_link = discord_auth_logic.consume_oauth_session(session, received_state)
    if not valid:
        flash(T("discord_oauth_state_invalid"), "error")
        return _discord_callback_redirect_on_error(is_link)

    oauth_error = str(request.args.get("error") or "").strip()
    if oauth_error:
        flash(T("discord_oauth_denied"), "error")
        return _discord_callback_redirect_on_error(is_link)

    code = str(request.args.get("code") or "").strip()
    if not code:
        flash(T("discord_oauth_failed"), "error")
        return _discord_callback_redirect_on_error(is_link)

    if is_link:
        user_id = session.get("user_id")
        if not user_id:
            flash(T("discord_link_requires_login"), "error")
            return redirect(url_for("login"))

        ok, err_key, _data = discord_auth_logic.complete_discord_link(code, int(user_id))
        if not ok:
            msg = T(err_key) if err_key and T(err_key) != err_key else T("discord_link_failed")
            flash(msg, "error")
            return redirect(url_for("options_view"))

        if err_key == "discord_already_linked":
            flash(T("discord_already_linked"), "info")
        else:
            flash(T("msg_discord_link_success"), "success")
        return redirect(url_for("options_view"))

    ok, err_key, user = discord_auth_logic.complete_discord_callback(code)
    if not ok or not user:
        msg = T(err_key) if err_key and T(err_key) != err_key else T("discord_oauth_failed")
        flash(msg, "error")
        return redirect(url_for("login"))

    login_user(user)
    if err_key == "discord_register_ok":
        flash(T("msg_discord_register_success"), "success")
        return redirect(url_for("discord_welcome"))
    flash(T("msg_discord_login_success"), "success")
    return redirect(url_for("overview"))


@app.route("/welcome/discord")
@require_login
def discord_welcome():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))

    discord_row = discord_auth_logic.get_user_discord_row(int(user["id"]))
    if not discord_row or not discord_row.get("discord_id"):
        return redirect(url_for("overview"))

    commander_name = str(user.get("name") or user.get("username") or "Commander")
    return render_template(
        "discord_welcome.html",
        commander_name=commander_name,
        discord_display=discord_auth_logic.discord_display_name(discord_row),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        csrf_key = _auth_form_error_key()
        if csrf_key:
            error = T(csrf_key) if T(csrf_key) != csrf_key else csrf_key
        elif not check_register_rate_limit(client_ip(request)):
            error = T("msg_auth_rate_limited") if T("msg_auth_rate_limited") != "msg_auth_rate_limited" else (
                "Zu viele Registrierungsversuche – bitte später erneut versuchen."
            )
        else:
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
            elif len(username) > 40:
                error = T("err_username_long") or "Benutzername ist zu lang."
            elif len(password) < 4:
                error = T("msg_register_password_short") or "Passwort muss mindestens 4 Zeichen lang sein."
            else:
                referral_code = (request.form.get("referral_code") or "").strip()
                ok, err, user = account_email_logic.register_user_with_email(username, password, email)
                if not ok:
                    error = T(err) if err and T(err) != err else (err or T("msg_register_failed"))
                else:
                    uid = int(user["id"])
                    reg_ip = client_ip(request)
                    conn = db()
                    try:
                        from game.referrals import (
                            apply_referral_code,
                            referrals_schema_ready,
                            set_user_registration_meta,
                        )

                        begin_write_transaction(conn)
                        set_user_registration_meta(uid, registration_ip=reg_ip, conn=conn)
                        if referral_code and referrals_schema_ready(conn):
                            apply_referral_code(uid, referral_code, reg_ip, conn=conn)
                        commit(conn)
                    except Exception:
                        rollback(conn)
                        logger.exception("referral apply on register failed user_id=%s", uid)
                    finally:
                        conn.close()
                    login_user(user)
                    flash(T("msg_register_success_verify") or T("msg_register_success"), "success")
                    return redirect(url_for("overview"))

    prefilled_referral = (request.args.get("ref") or "").strip()
    return render_template("register.html", error=error, prefilled_referral=prefilled_referral)


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
        csrf_key = _auth_form_error_key()
        if csrf_key:
            error = T(csrf_key) if T(csrf_key) != csrf_key else csrf_key
        else:
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
        csrf_key = _auth_form_error_key()
        if csrf_key:
            error = T(csrf_key) if T(csrf_key) != csrf_key else csrf_key
        else:
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
    import time

    from game.live_state import current_ssr_perf, finish_ssr_perf, start_ssr_perf

    start_ssr_perf("/overview")
    ssr = current_ssr_perf()

    conn = db()
    try:
        ctx_t0 = time.perf_counter()
        ctx = _load_page_live_context(finish_source="overview", conn=conn, close_conn=False)
        if ctx is None:
            finish_ssr_perf(response_bytes=0)
            return redirect(url_for("login"))

        from game.overview_page import build_overview_page_context

        planet = ctx.get("planet")
        if not planet:
            from game.live_state import get_request_context_planet

            planet = get_request_context_planet(int(session["user_id"]), conn=conn)
        overview_status = build_overview_page_context(
            int(session["user_id"]), ctx, planet=planet, conn=conn
        )
        if ssr is not None:
            ssr.add_live_context_ms((time.perf_counter() - ctx_t0) * 1000.0)
    finally:
        conn.close()

    tpl_t0 = time.perf_counter()
    resp = render_template(
        "overview.html",
        player=ctx["player_view"],
        ratio=ctx["ratio"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        prod_per_hour=ctx["prod_per_hour"],
        overview_status=overview_status,
    )
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


@app.route("/empire")
@require_login
def empire_view():
    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login"))

    from game.empire_page import build_empire_context

    empire = build_empire_context(int(user_id))
    return render_template("empire.html", empire=empire)


@app.route("/trader-hub")
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
        pid = int(planet["id"])
        uid = int(session["user_id"])
        if exchange_schema_ready(conn):
            exchange = get_exchange_status(
                player_id=uid,
                planet_id=pid,
                metal=float(ctx["player_view"]["metal"]),
                crystal=float(ctx["player_view"]["crystal"]),
                fuel_cells=float(ctx["player_view"].get("fuel_cells") or 0),
                conn=conn,
            )
        scrapyard = scrapyard_status(uid, pid, conn=conn)
    finally:
        conn.close()

    return render_template(
        "trader_hub.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        exchange=exchange,
        scrapyard=scrapyard,
    )


# --------------------------------------------------------------------------
# BUILDINGS
# --------------------------------------------------------------------------

@app.route("/buildings")
@require_login
def buildings_view():
    import time

    from game.live_state import current_ssr_perf, finish_ssr_perf, start_ssr_perf

    active_tab = request.args.get("tab") or "resources"
    if active_tab not in ("resources", "research", "military", "infrastructure"):
        active_tab = "resources"

    start_ssr_perf("/buildings", tab=active_tab)
    ssr = current_ssr_perf()

    conn = db()
    try:
        ctx_t0 = time.perf_counter()
        ctx = _load_page_live_context(finish_source="buildings", conn=conn, close_conn=False)
        if ssr is not None:
            ssr.add_live_context_ms((time.perf_counter() - ctx_t0) * 1000.0)
        if ctx is None:
            finish_ssr_perf(response_bytes=0)
            return redirect(url_for("login"))

        planet = ctx.get("planet")
        if not planet:
            from game.live_state import get_request_context_planet

            planet = get_request_context_planet(int(session["user_id"]), conn=conn)
        rows_by_tab = get_buildings_panel_rows(
            planet,
            ctx["buildings"],
            build_queue=ctx["build_queue"],
            active_tab=active_tab,
        )
    finally:
        conn.close()

    tpl_t0 = time.perf_counter()
    resp = render_template(
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
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


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

    planet = ctx.get("planet")
    if not planet:
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
        active_planet_id=int(planet["id"]),
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
        # Queue update is visible in the UI — no success flash needed.
        pass

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

    techtree_ctx = get_techtree_page_context(
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
        techtree_sections=techtree_ctx.get("sections") or [],
        building_nodes=techtree_ctx.get("building_nodes") or [],
        research_nodes=techtree_ctx.get("research_nodes") or [],
        defense_ready=techtree_ctx.get("defense_ready", True),
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
        build_galaxy_nav,
        build_minimap_range,
        get_planet_coordinates,
        list_system,
        resolve_view_coordinates,
    )
    from game.fleet import build_expedition_slot, _hold_mission_enabled
    from game.planet_evolution.repository import get_active_planet_id, get_context_planet

    user_id = int(session["user_id"])
    view = (request.args.get("view") or "command_map").strip().lower()
    if view == "imperium":
        view = "command_map"
    if view not in ("system", "command_map"):
        view = "command_map"

    galaxy = 1
    system = 1
    active_planet_id: int | None = None
    hold_mission_enabled = False
    has_url_view = (
        request.args.get("galaxy", type=int) is not None
        or request.args.get("system", type=int) is not None
        or bool(request.args.get("q") or request.args.get("coord"))
    )
    try:
        active_planet_id = get_active_planet_id(user_id) or None
        if not has_url_view:
            planet = get_context_planet(user_id)
            coords = get_planet_coordinates(planet)
            galaxy = int(coords["galaxy"])
            system = int(coords["system"])
    except Exception:
        active_planet_id = None

    carry_system = None
    try:
        if request.args.get("galaxy", type=int) is not None and request.args.get("system", type=int) is None:
            carry_system = int(session.get("galaxy_view_system") or 0) or None
    except (TypeError, ValueError):
        carry_system = None

    galaxy, system, highlight_pos = resolve_view_coordinates(
        default_galaxy=galaxy,
        default_system=system,
        req_galaxy=request.args.get("galaxy", type=int),
        req_system=request.args.get("system", type=int),
        coord_query=request.args.get("q") or request.args.get("coord"),
        carry_system=carry_system,
    )
    session["galaxy_view_galaxy"] = int(galaxy)
    session["galaxy_view_system"] = int(system)

    conn = db()
    command_map: dict[str, Any] = {"nodes": [], "edges": []}
    galactic_directive_banner: dict[str, Any] = {"visible": False}
    galactic_diplomacy_banner: dict[str, Any] = {"visible": False}
    try:
        hold_mission_enabled = _hold_mission_enabled(conn=conn)
        if view == "command_map":
            from game.planet_evolution.command_map import build_command_map_payload

            command_map = build_command_map_payload(user_id, conn=conn)
        from game.galactic_directives.banner import build_galactic_directive_banner
        from game.galactic_diplomacy.banner import build_galactic_diplomacy_banner

        galactic_directive_banner = build_galactic_directive_banner(galaxy, conn=conn)
        galactic_diplomacy_banner = build_galactic_diplomacy_banner(galaxy, conn=conn)
    finally:
        conn.close()

    if view == "command_map":
        galaxy_nav = build_galaxy_nav(galaxy, system)
        system_data = {"galaxy": galaxy, "system": system, "slots": []}
        minimap = []
    else:
        galaxy_nav = build_galaxy_nav(galaxy, system)
        system_data = list_system(
            galaxy,
            system,
            viewer_player_id=user_id,
            active_planet_id=active_planet_id,
            highlight_position=highlight_pos,
        )
        minimap = build_minimap_range(
            galaxy,
            system,
            viewer_player_id=user_id,
        )

    return render_template(
        "galaxy.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        galaxy_nav=galaxy_nav,
        system_data=system_data,
        minimap=minimap,
        viewer_player_id=user_id,
        expedition_slot=build_expedition_slot(galaxy, system) if view != "command_map" else None,
        hold_mission_enabled=hold_mission_enabled,
        galaxy_view=view,
        command_map=command_map,
        galactic_directive_banner=galactic_directive_banner,
        galactic_diplomacy_banner=galactic_diplomacy_banner,
    )


@app.route("/api/galaxy/system")
@require_login_api
def api_galaxy_system():
    from game.galaxy import (
        GalaxyCoordinateError,
        clamp_galaxy,
        clamp_system,
        get_universe_config,
        list_system,
        resolve_view_coordinates,
    )

    user_id = int(session["user_id"])
    cfg = get_universe_config()
    system_raw = request.args.get("system", type=int)
    req_galaxy = request.args.get("galaxy", type=int)
    if system_raw is None and req_galaxy is None:
        return jsonify({"ok": False, "error": "system_required"}), 400

    carry_system = None
    if req_galaxy is not None and system_raw is None:
        try:
            carry_system = int(session.get("galaxy_view_system") or 0) or None
        except (TypeError, ValueError):
            carry_system = None

    try:
        galaxy, system, _ = resolve_view_coordinates(
            default_galaxy=1,
            default_system=1,
            req_galaxy=request.args.get("galaxy", type=int),
            req_system=system_raw,
            coord_query=request.args.get("q") or request.args.get("coord"),
            carry_system=carry_system,
        )
    except GalaxyCoordinateError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    try:
        from game.planet_evolution.repository import get_active_planet_id

        active_pid = get_active_planet_id(user_id)
        data = list_system(
            galaxy,
            system,
            viewer_player_id=user_id,
            active_planet_id=active_pid,
        )
        session["galaxy_view_galaxy"] = int(galaxy)
        session["galaxy_view_system"] = int(system)
        return jsonify(
            {
                "ok": True,
                "data": data,
                "bounds": cfg,
            }
        )
    except Exception as e:
        logger.exception("api_galaxy_system failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/command-map/sectors")
@require_login_api
def api_command_map_sectors():
    """Viewport-aware sector chunk payload for Command Map (GC-580B)."""
    from game.planet_evolution.sector_grid import (
        DEFAULT_SECTOR_SEED,
        SectorBoundsTooLargeError,
        build_sector_chunks_for_request,
        normalize_world_bounds,
    )

    min_wx = request.args.get("min_wx", type=float)
    min_wy = request.args.get("min_wy", type=float)
    max_wx = request.args.get("max_wx", type=float)
    max_wy = request.args.get("max_wy", type=float)
    if None in (min_wx, min_wy, max_wx, max_wy):
        return jsonify({"ok": False, "error": "bounds_required"}), 400

    seed = request.args.get("seed", type=int) or DEFAULT_SECTOR_SEED
    try:
        bounds = normalize_world_bounds(min_wx, min_wy, max_wx, max_wy)
        chunks = build_sector_chunks_for_request(*bounds, seed=int(seed))
    except SectorBoundsTooLargeError:
        return jsonify({"ok": False, "error": "bounds_too_large"}), 400
    except Exception as e:
        logger.exception("api_command_map_sectors failed")
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify(
        {
            "ok": True,
            "sector_chunks": chunks,
            "bounds": {
                "min_wx": bounds[0],
                "min_wy": bounds[1],
                "max_wx": bounds[2],
                "max_wy": bounds[3],
            },
            "seed": int(seed),
        }
    )


_COMMAND_MAP_TELEMETRY_EVENTS = frozenset({
    "map_open",
    "node_click",
    "inspector_open",
})


@app.route("/api/command-map/telemetry", methods=["POST"])
@require_login_api
def api_command_map_telemetry():
    """Lightweight Command Map usage log for closed alpha (GC-597D)."""
    from game.config import is_command_map_dev_mode

    if not is_command_map_dev_mode():
        return jsonify({"ok": True, "skipped": True})

    pid = _current_player_id()
    if pid is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    payload = request.get_json(silent=True) or {}
    event = str(payload.get("event") or "").strip().lower()[:64]
    if event not in _COMMAND_MAP_TELEMETRY_EVENTS:
        return jsonify({"ok": False, "error": "invalid_event"}), 400

    node_kind = str(payload.get("node_kind") or "").strip()[:32]
    logger.info(
        "command_map_telemetry player_id=%s event=%s node_kind=%s",
        int(pid),
        event,
        node_kind or "-",
    )
    return jsonify({"ok": True})


@app.route("/api/worlds/colonize-preview", methods=["GET"])
@require_login_api
def api_worlds_colonize_preview():
    """Presentation-only strategic world colonize preview (GC-582C)."""
    from game.planet_evolution.world_colonization import build_world_colonize_preview

    user_id = int(session.get("user_id") or 0)
    world_key = str(request.args.get("world_key") or "").strip()
    if not world_key:
        return jsonify({"ok": False, "error": "invalid_world_key"}), 400

    conn = db()
    try:
        preview = build_world_colonize_preview(user_id, world_key, conn=conn)
    finally:
        conn.close()

    if not preview.get("presentation"):
        return jsonify({"ok": False, "error": preview.get("block_reason") or "invalid_world_key"}), 400

    return jsonify({"ok": True, "data": preview})


@app.route("/api/worlds/expedition-preview", methods=["GET"])
@require_login_api
def api_worlds_expedition_preview():
    """Presentation-only strategic world expedition preview (GC-583A)."""
    from game.planet_evolution.world_colonization import build_world_expedition_preview

    user_id = int(session.get("user_id") or 0)
    world_key = str(request.args.get("world_key") or "").strip()
    if not world_key:
        return jsonify({"ok": False, "error": "invalid_world_key"}), 400

    conn = db()
    try:
        preview = build_world_expedition_preview(user_id, world_key, conn=conn)
    finally:
        conn.close()

    if not preview.get("presentation"):
        return jsonify({"ok": False, "error": preview.get("block_reason") or "invalid_world_key"}), 400

    return jsonify({"ok": True, "data": preview})


@app.route("/api/worlds/salvage-preview", methods=["GET"])
@require_login_api
def api_worlds_salvage_preview():
    """Presentation-only strategic wreckage/salvage preview (GC-584)."""
    from game.planet_evolution.world_colonization import build_world_salvage_preview

    user_id = int(session.get("user_id") or 0)
    world_key = str(request.args.get("world_key") or "").strip()
    if not world_key:
        return jsonify({"ok": False, "error": "invalid_world_key"}), 400

    conn = db()
    try:
        preview = build_world_salvage_preview(user_id, world_key, conn=conn)
    finally:
        conn.close()

    if not preview.get("presentation"):
        return jsonify({"ok": False, "error": preview.get("block_reason") or "invalid_world_key"}), 400

    return jsonify({"ok": True, "data": preview})


@app.route("/shipyard")
@require_login
def shipyard_view():
    import time

    from game.live_state import current_ssr_perf, finish_ssr_perf, start_ssr_perf

    start_ssr_perf("/shipyard")
    ssr = current_ssr_perf()

    data_t0 = time.perf_counter()
    player_view, _, planet_row, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        finish_ssr_perf(response_bytes=0)
        return redirect(url_for("login"))

    from game.fleet import fleet_schema_ready
    from game.planet_evolution.repository import get_context_planet
    from game.shipyard import build_shipyard_page_context

    conn = db()
    try:
        planet = get_context_planet(int(session.get("user_id") or 0), conn=conn)
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
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


@app.route("/defense")
@require_login
def defense_view():
    import time

    from game.live_state import current_ssr_perf, finish_ssr_perf, start_ssr_perf

    start_ssr_perf("/defense")
    ssr = current_ssr_perf()

    data_t0 = time.perf_counter()
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        finish_ssr_perf(response_bytes=0)
        return redirect(url_for("login"))

    from game.defense_page import build_defense_page_context
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        planet = get_context_planet(int(session.get("user_id") or 0), conn=conn)
        defense_ctx = build_defense_page_context(
            int(session.get("user_id") or 0),
            planet,
            conn=conn,
        )
    finally:
        conn.close()

    if ssr is not None:
        ssr.add_live_context_ms((time.perf_counter() - data_t0) * 1000.0)

    tpl_t0 = time.perf_counter()
    resp = render_template(
        "defense.html",
        player=player_view,
        defense=defense_ctx,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
    )
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


@app.route("/logistics")
@require_login
def logistics_view():
    if _load_player_view_with_resources()[0] is None:
        return redirect(url_for("login"))

    mode = (request.args.get("mode") or "collect").strip().lower()
    if mode not in ("collect", "distribute"):
        mode = "collect"
    return redirect(f"{url_for('fleet_view')}?mode={mode}")


@app.route("/fleet")
@require_login
def fleet_view():
    import time

    from game.live_state import current_ssr_perf, finish_ssr_perf, start_ssr_perf

    start_ssr_perf("/fleet")
    ssr = current_ssr_perf()

    conn = db()
    try:
        ctx_t0 = time.perf_counter()
        ctx = _load_page_live_context(finish_source="fleet", conn=conn, close_conn=False)
        if ssr is not None:
            ssr.add_live_context_ms((time.perf_counter() - ctx_t0) * 1000.0)
        if ctx is None:
            finish_ssr_perf(response_bytes=0)
            return redirect(url_for("login"))

        from game.fleet import build_fleet_page_context, build_logistics_page_context, fleet_schema_ready

        player_view = ctx["player_view"]
        planet = ctx.get("planet")
        if not planet:
            from game.live_state import get_request_context_planet

            planet = get_request_context_planet(int(player_view["id"]), conn=conn)

        fleet_ctx: Dict[str, Any] = {"ready": False}
        logistics_ctx: Dict[str, Any] = {"ready": False}
        if fleet_schema_ready(conn):
            planet_dict = dict(planet)
            fleet_ctx = build_fleet_page_context(
                player_id=int(player_view["id"]),
                planet_id=int(planet["id"]),
                planet=planet_dict,
                conn=conn,
            )
            logistics_ctx = build_logistics_page_context(
                player_id=int(player_view["id"]),
                planet_id=int(planet["id"]),
                planet=planet_dict,
                conn=conn,
            )
    finally:
        conn.close()

    tpl_t0 = time.perf_counter()
    resp = render_template(
        "fleet.html",
        player=player_view,
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        fleet=fleet_ctx,
        logistics=logistics_ctx,
    )
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


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


def _render_placeholder_module(module_key: str):
    from game.placeholder_pages import get_placeholder_module

    module = get_placeholder_module(module_key)
    if not module:
        abort(404)
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))
    ctx = dict(module)
    ctx["key"] = module_key
    return render_template(
        "placeholder_module.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        module=ctx,
    )


_INVENTORY_ACTION_MESSAGES = {
    "inventory_unavailable": "Inventar ist derzeit nicht verfügbar.",
    "inventory_action_failed": "Inventar-Aktion konnte nicht abgeschlossen werden.",
    "invalid_item": "Unbekanntes Item.",
    "item_not_usable": "Dieses Item kann nicht benutzt werden.",
    "insufficient_items": "Nicht genug Items im Inventar.",
    "insufficient_materials": "Nicht genug Material im Inventar.",
    "invalid_recipe": "Unbekanntes Rezept.",
    "no_build_queue": "Keine Bauaufträge in der Warteschlange.",
    "no_research_queue": "Keine Forschung in der Warteschlange.",
    "no_shipyard_queue": "Keine Schiffsbauaufträge in der Warteschlange.",
    "no_matching_research": "Keine passende aktive Forschung für diesen Datenkern.",
    "no_effect_target": "Kein gültiges Ziel für dieses Item.",
    "container_cooldown": "Container ist noch im Cooldown.",
    "insufficient_containers": "Nicht genug Container im Inventar.",
}


def _inventory_action_message(reason: str) -> str:
    key = str(reason or "inventory_action_failed")
    return _INVENTORY_ACTION_MESSAGES.get(key, "Aktion konnte nicht abgeschlossen werden.")


def _inventory_action_context(user_id: int, finish_source: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build fresh game state + inventory after mutation connection is closed."""
    from game.inventory import build_inventory_state

    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
    conn = db()
    try:
        inventory = build_inventory_state(int(user_id), conn=conn)
    finally:
        conn.close()
    return state, inventory


def _inventory_action_error_response(
    user_id: int,
    reason: str,
    finish_source: str,
    *,
    status: int = 400,
    extra: Optional[Dict[str, Any]] = None,
):
    state, inventory = _inventory_action_context(user_id, finish_source)
    resp: Dict[str, Any] = {
        "ok": False,
        "reason": str(reason or "inventory_action_failed"),
        "message": _inventory_action_message(reason),
        "state": state,
        "inventory": inventory,
    }
    if extra:
        resp.update(extra)
    return jsonify(resp), status


def _inventory_action_ok_response(
    user_id: int,
    reason: str,
    finish_source: str,
    payload: Dict[str, Any],
    *,
    request_id: str = "",
):
    state, inventory = _inventory_action_context(user_id, finish_source)
    resp: Dict[str, Any] = {
        "ok": True,
        "reason": reason,
        "state": state,
        "inventory": inventory,
    }
    resp.update(payload)
    if request_id:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/inventory")
@require_login
def inventory_view():
    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login"))

    from game.inventory import build_inventory_state, inventory_schema_ready
    from game.planet_evolution.repository import get_context_planet

    ctx = _load_page_live_context(finish_source="inventory")
    if ctx is None:
        return redirect(url_for("login"))

    inventory = {"ready": False, "containers": [], "other_items": []}
    conn = db()
    try:
        if inventory_schema_ready(conn):
            inventory = build_inventory_state(int(user_id), conn=conn)
            planet = get_context_planet(int(user_id), conn=conn)
            inventory["planet_id"] = int(planet["id"])
            inventory["planet_name"] = str(planet.get("name") or "").strip()
    finally:
        conn.close()

    return render_template(
        "inventory.html",
        player=ctx["player_view"],
        buildings=ctx["buildings"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        inventory=inventory,
    )


@app.route("/api/inventory/state", methods=["GET"])
@require_login
def api_inventory_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.inventory import build_inventory_state, inventory_schema_ready

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return jsonify({"ok": False, "reason": "inventory_unavailable"}), 503
        inventory = build_inventory_state(user_id, conn=conn)
    finally:
        conn.close()

    return jsonify({"ok": True, "inventory": inventory})


@app.route("/api/inventory/open-container", methods=["POST"])
@require_login
def api_inventory_open_container():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    item_key = str(data.get("item_key") or "").strip()
    try:
        amount = int(data.get("amount") or 1)
    except (TypeError, ValueError):
        amount = 0

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.inventory import inventory_schema_ready, open_containers, run_inventory_mutation
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "inventory_unavailable", "inventory_open", status=503
            )
        planet = get_context_planet(user_id, conn=conn)
        planet_id = int(planet["id"])
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda conn: open_containers(user_id, planet_id, item_key, amount, conn=conn)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "inventory_open", status=500
        )

    if not ok:
        extra = {}
        if isinstance(result, dict):
            if result.get("cooldown_seconds") is not None:
                extra["cooldown_seconds"] = int(result["cooldown_seconds"])
            if result.get("next_open_at") is not None:
                extra["next_open_at"] = float(result["next_open_at"])
        return _inventory_action_error_response(user_id, reason, "inventory_open", extra=extra or None)

    result = result or {}
    return _inventory_action_ok_response(
        user_id,
        "container_open_ok",
        "inventory_open",
        {
            "rewards": result.get("rewards") or [],
            "roll_preview": result.get("roll_preview") or [],
            "winning_index": int(result.get("winning_index") or 0),
            "winning_reward": result.get("winning_reward") or {},
            "opened": result.get("opened") or 0,
            "container_key": result.get("container_key") or item_key,
            "container_name_key": result.get("container_name_key") or "",
            "container_rarity": result.get("container_rarity") or "common",
            "container_image": result.get("container_image") or "",
        },
        request_id=request_id,
    )


@app.route("/api/inventory/use-item", methods=["POST"])
@require_login
def api_inventory_use_item():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    item_key = str(data.get("item_key") or "").strip()
    try:
        amount = int(data.get("amount") or 1)
    except (TypeError, ValueError):
        amount = 0

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.inventory import inventory_schema_ready, run_inventory_mutation
    from game.inventory_use import use_inventory_item
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "inventory_unavailable", "inventory_use", status=503
            )
        planet = get_context_planet(user_id, conn=conn)
        planet_id = int(planet["id"])
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda conn: use_inventory_item(user_id, planet_id, item_key, amount, conn=conn)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "inventory_use", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "inventory_use")

    result = result or {}
    return _inventory_action_ok_response(
        user_id,
        reason,
        "inventory_use",
        {
            "effect": result.get("effect") or {},
            "effects": result.get("effects") or [],
            "consumed": result.get("consumed") or 0,
            "item_key": result.get("item_key") or item_key,
        },
        request_id=request_id,
    )


@app.route("/api/inventory/craft", methods=["POST"])
@require_login
def api_inventory_craft():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    recipe_key = str(data.get("recipe_key") or data.get("item_key") or "").strip()
    try:
        amount = int(data.get("amount") or 1)
    except (TypeError, ValueError):
        amount = 0

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.inventory import inventory_schema_ready, run_inventory_mutation
    from game.inventory_use import craft_inventory_item

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "inventory_unavailable", "inventory_craft", status=503
            )
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda conn: craft_inventory_item(user_id, recipe_key, amount, conn=conn)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "inventory_craft", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "inventory_craft")

    result = result or {}
    return _inventory_action_ok_response(
        user_id,
        reason,
        "inventory_craft",
        {
            "effect": result.get("effect") or {},
            "crafted": result.get("crafted") or 0,
            "output_key": result.get("output_key") or recipe_key,
            "output_amount": result.get("output_amount") or 0,
        },
        request_id=request_id,
    )


@app.route("/api/inventory/exchange", methods=["POST"])
@require_login
def api_inventory_exchange():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    recipe_key = str(data.get("recipe_key") or "").strip()
    try:
        amount = int(data.get("amount") or 1)
    except (TypeError, ValueError):
        amount = 0

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.inventory import inventory_schema_ready, run_inventory_mutation
    from game.inventory_use import exchange_inventory_item

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "inventory_unavailable", "inventory_exchange", status=503
            )
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda conn: exchange_inventory_item(user_id, recipe_key, amount, conn=conn)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "inventory_exchange", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "inventory_exchange")

    result = result or {}
    return _inventory_action_ok_response(
        user_id,
        reason,
        "inventory_exchange",
        {
            "effect": result.get("effect") or {},
            "exchanged": result.get("exchanged") or 0,
            "exchange": result.get("exchange") or {},
        },
        request_id=request_id,
    )


@app.route("/auction-house")
@require_login
def auction_house_view():
    ctx = _load_page_live_context(finish_source="auction_house")
    if ctx is None:
        return redirect(url_for("login"))

    from game.auction_house import build_auction_house_state
    from game.planet_evolution.repository import get_context_planet

    auction_house = {"ready": False, "auctions": []}
    conn = db()
    try:
        planet = get_context_planet(int(session["user_id"]), conn=conn)
        pid = int(planet["id"])
        uid = int(session["user_id"])
        auction_house = build_auction_house_state(
            uid,
            pid,
            metal=float(ctx["player_view"]["metal"]),
            crystal=float(ctx["player_view"]["crystal"]),
            fuel_cells=float(ctx["player_view"].get("fuel_cells") or 0),
            conn=conn,
        )
    finally:
        conn.close()

    return render_template(
        "auction_house.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        auction_house=auction_house,
    )


@app.route("/api/auction-house/state")
@require_login
def api_auction_house_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.auction_house import build_auction_house_state
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        player_view, _, _, _, _, _ = refresh_player_live_state(
            user_id, conn=conn, finish_source="api_auction_house_state", close_conn=False
        )
        payload = build_auction_house_state(
            user_id,
            int(planet["id"]),
            metal=float(player_view["metal"]),
            crystal=float(player_view["crystal"]),
            fuel_cells=float(player_view.get("fuel_cells") or 0),
            conn=conn,
        )
        commit(conn)
        return jsonify({"ok": True, "auction_house": payload})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


@app.route("/api/auction-house/bid", methods=["POST"])
@require_login
def api_auction_house_bid():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        listing_id = int(data.get("listing_id") or 0)
    except (TypeError, ValueError):
        listing_id = 0
    try:
        amount = int(data.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    currency = str(data.get("currency") or "").strip().lower()

    from game.auction_house import auction_schema_ready, build_auction_house_state, place_bid
    from game.planet_evolution.repository import get_context_planet

    if not auction_schema_ready(db()):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_auction_house_bid")
        return jsonify({"ok": False, "reason": "auction_unavailable", "state": state}), 503

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        planet_id = int(planet["id"])
        ok, reason, result = place_bid(
            player_id=user_id,
            planet_id=planet_id,
            listing_id=listing_id,
            amount=amount,
            currency=currency,
            conn=conn,
        )
    except Exception:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_auction_house_bid")
        return jsonify({"ok": False, "reason": "auction_action_failed", "state": state}), 500
    finally:
        conn.close()

    state: Dict[str, Any] = {"ok": True, "server_time": time.time()}
    auction_house: Dict[str, Any] = {}
    try:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_auction_house_bid")
        auction_house = dict(state.get("auction_house") or {})
    except Exception:
        logger.exception("auction-house bid: game-state build failed user_id=%s", user_id)
        try:
            from game.auction_house import build_auction_house_state
            from game.planet_evolution.repository import get_context_planet as _gcp

            conn2 = db()
            try:
                planet2 = _gcp(user_id, conn=conn2)
                player_view, _, _, _, _, _ = refresh_player_live_state(
                    user_id, conn=conn2, finish_source="api_auction_house_bid_fallback", close_conn=False
                )
                auction_house = build_auction_house_state(
                    user_id,
                    int(planet2["id"]),
                    metal=float(player_view["metal"]),
                    crystal=float(player_view["crystal"]),
                    fuel_cells=float(player_view.get("fuel_cells") or 0),
                    conn=conn2,
                )
                state = {"ok": True, "server_time": time.time(), "auction_house": auction_house}
            finally:
                conn2.close()
        except Exception:
            logger.exception("auction-house bid: fallback state failed user_id=%s", user_id)

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "auction_house": auction_house,
    }
    if ok and result:
        resp["bid"] = result
    if not ok and isinstance(result, dict):
        resp.update(result)
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/vote-center")
@require_login
def vote_center_view():
    ctx = _load_page_live_context(finish_source="vote_center")
    if ctx is None:
        return redirect(url_for("login"))

    from game.vote_rewards import get_vote_center_state

    vote_center = {"ready": False, "pending_rewards": []}
    conn = db()
    try:
        vote_center = get_vote_center_state(int(session["user_id"]), conn=conn)
    finally:
        conn.close()

    return render_template(
        "vote_center.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        vote_center=vote_center,
    )


def _vote_postback_response(provider_key: str) -> Any:
    from game.vote_rewards import handle_provider_postback

    remote_addr = request.remote_addr
    xff = request.headers.get("X-Forwarded-For")
    p_resp = request.args.get("p_resp")
    vote_ip = request.args.get("ip")
    debug_payload = {
        "provider": provider_key,
        "remote_addr": remote_addr,
        "x_forwarded_for": xff,
        "p_resp": p_resp,
        "ip": vote_ip,
    }
    logger.info("vote postback received %s", debug_payload)

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, created, reason = handle_provider_postback(
            provider_key,
            query_params=request.args,
            form_params=request.form,
            remote_addr=remote_addr,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("vote postback failed provider=%s", provider_key)
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    if reason == "forbidden":
        return jsonify({"ok": False, "reason": reason}), 403
    if reason in ("invalid_user_id", "missing_user_id"):
        status = 400 if reason == "invalid_user_id" else 400
        return jsonify({"ok": False, "reason": reason}), status
    if reason in ("provider_disabled", "postback_disabled", "vote_not_valid"):
        return jsonify({"ok": True, "created": False, "reason": reason})
    if not ok:
        return jsonify({"ok": False, "reason": reason}), 503
    return jsonify({"ok": True, "created": bool(created)})


@app.route("/api/vote/postback/<provider_key>", methods=["GET", "POST"])
def api_vote_provider_postback(provider_key: str):
    return _vote_postback_response(str(provider_key or "").strip().lower())


@app.route("/api/vote/topg/postback", methods=["GET"])
def api_vote_topg_postback():
    return _vote_postback_response("topg")


def _gametoor_ivn_response() -> Any:
    from game.vote_rewards import handle_gametoor_ivn

    remote_addr = request.remote_addr
    xff = request.headers.get("X-Forwarded-For")
    json_data = request.get_json(silent=True)
    form_data = dict(request.form) if request.form else None
    logger.info(
        "gametoor ivn received remote_addr=%s x_forwarded_for=%s has_json=%s has_form=%s",
        remote_addr,
        xff,
        bool(json_data),
        bool(form_data),
    )

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, created_count, reason = handle_gametoor_ivn(
            json_data if isinstance(json_data, dict) else None,
            form_data,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("gametoor ivn failed")
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    if reason == "forbidden":
        return jsonify({"ok": False, "reason": reason}), 403
    if reason == "key_missing":
        return jsonify({"ok": False, "reason": reason}), 503
    if not ok:
        return jsonify({"ok": False, "reason": reason}), 503
    return jsonify({"ok": True, "created": int(created_count), "reason": reason}), 200


@app.route("/api/vote/gametoor/ivn", methods=["POST"])
def api_vote_gametoor_ivn():
    return _gametoor_ivn_response()


@app.route("/api/vote/gametoor/postback", methods=["GET", "POST"])
def api_vote_gametoor_postback():
    return _gametoor_ivn_response()


@app.route("/api/vote/arena-top100/postback", methods=["POST"])
def api_vote_arena_top100_postback():
    from game.vote_rewards import handle_arena_top100_postback

    remote_addr = request.remote_addr
    xff = request.headers.get("X-Forwarded-For")
    json_data = request.get_json(silent=True)
    form_data = dict(request.form) if request.form else None
    logger.info(
        "arena_top100 postback received remote_addr=%s x_forwarded_for=%s has_json=%s has_form=%s",
        remote_addr,
        xff,
        bool(json_data),
        bool(form_data),
    )

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, created_count, reason = handle_arena_top100_postback(
            json_data if isinstance(json_data, dict) else None,
            form_data,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("arena_top100 postback failed")
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    if reason == "forbidden":
        return jsonify({"ok": False, "reason": reason}), 403
    if reason == "secret_missing":
        return jsonify({"ok": False, "reason": reason}), 503
    if not ok:
        return jsonify({"ok": False, "reason": reason}), 503
    return jsonify({"ok": True, "created": int(created_count), "reason": reason}), 200


@app.route("/api/vote/gtop100/pingback", methods=["POST"])
def api_vote_gtop100_pingback():
    from game.vote_rewards import handle_gtop100_pingback

    remote_addr = request.remote_addr
    xff = request.headers.get("X-Forwarded-For")
    json_data = request.get_json(silent=True)
    form_data = dict(request.form) if request.form else None
    logger.info(
        "gtop100 pingback received remote_addr=%s x_forwarded_for=%s has_json=%s has_form=%s",
        remote_addr,
        xff,
        bool(json_data),
        bool(form_data),
    )

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, created_count, reason = handle_gtop100_pingback(
            json_data if isinstance(json_data, dict) else None,
            form_data,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("gtop100 pingback failed")
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    if reason == "forbidden":
        return jsonify({"ok": False, "reason": reason}), 403
    if reason == "invalid_site_id":
        return jsonify({"ok": False, "reason": reason}), 400
    if reason == "pingback_key_missing":
        return jsonify({"ok": False, "reason": reason}), 503
    if not ok:
        return jsonify({"ok": False, "reason": reason}), 503
    return jsonify({"ok": True, "created": int(created_count), "reason": reason}), 200


@app.route("/api/dev/topg/postback-test", methods=["POST"])
@require_login
def api_dev_topg_postback_test():
    """Dev/admin only: simulate TopG postback and create pending vote reward."""
    from game.config import is_debug_enabled
    from game.models import load_player
    from game.vote_rewards import get_vote_center_state, record_topg_vote, roll_vote_reward

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    player = load_player(user_id)
    allow = is_debug_enabled() or bool(player and player.get("is_admin"))
    if not allow:
        return jsonify({"ok": False, "reason": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    try:
        target_user_id = int(data.get("user_id") or user_id)
    except (TypeError, ValueError):
        target_user_id = user_id

    reward_payload = data.get("reward_payload")
    if reward_payload is not None and not isinstance(reward_payload, dict):
        reward_payload = None
    if reward_payload is None and data.get("reward_type"):
        reward_payload = dict(data)

    conn = db()
    try:
        begin_write_transaction(conn)
        processed, created = record_topg_vote(
            target_user_id,
            str(data.get("ip") or "127.0.0.1"),
            conn=conn,
            reward_payload=reward_payload or roll_vote_reward(),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        logger.exception("dev topg postback-test failed user_id=%s", target_user_id)
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    vote_center: Dict[str, Any] = {}
    conn2 = db()
    try:
        vote_center = get_vote_center_state(target_user_id, conn=conn2)
    finally:
        conn2.close()

    return jsonify({
        "ok": bool(processed),
        "created": bool(created),
        "user_id": target_user_id,
        "vote_center": vote_center,
    })


@app.route("/api/vote/center-state", methods=["GET"])
@require_login
def api_vote_center_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.vote_rewards import get_vote_center_state

    conn = db()
    try:
        vote_center = get_vote_center_state(user_id, conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, "vote_center": vote_center})


@app.route("/api/vote/visit", methods=["POST"])
@require_login
def api_vote_visit():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    provider_key = str(data.get("provider_key") or "").strip().lower()
    if not provider_key:
        return jsonify({"ok": False, "reason": "missing_provider_key"}), 400

    from game.vote_rewards import get_vote_center_state, handle_vote_visit

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, created, reason, cooldown_remaining_sec = handle_vote_visit(
            user_id, provider_key, conn=conn
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("vote visit failed user_id=%s provider=%s", user_id, provider_key)
        return jsonify({"ok": False, "reason": "server_error"}), 500
    finally:
        conn.close()

    vote_center: Dict[str, Any] = {}
    conn2 = db()
    try:
        vote_center = get_vote_center_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "created": bool(created),
        "reason": reason,
        "cooldown_remaining_sec": int(cooldown_remaining_sec),
        "vote_center": vote_center,
    }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    status = 200 if ok else 400
    if reason == "provider_disabled":
        status = 404
    return jsonify(resp), status


@app.route("/api/vote/rewards/claim", methods=["POST"])
@require_login
def api_vote_rewards_claim():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        reward_id = int(data.get("reward_id") or 0)
    except (TypeError, ValueError):
        reward_id = 0

    from game.vote_rewards import claim_vote_reward, get_vote_center_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_vote_reward(user_id, reward_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("vote reward claim failed user_id=%s reward_id=%s", user_id, reward_id)
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_vote_rewards_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_vote_rewards_claim")
    vote_center: Dict[str, Any] = {}
    conn2 = db()
    try:
        vote_center = get_vote_center_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "vote_center": vote_center,
    }
    if ok and claim_result:
        resp["claim"] = claim_result
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/api/vote/rewards/claim-all", methods=["POST"])
@require_login
def api_vote_rewards_claim_all():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.vote_rewards import claim_all_vote_rewards, get_vote_center_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_all_vote_rewards(user_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("vote reward claim-all failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_vote_rewards_claim_all")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_vote_rewards_claim_all")
    vote_center: Dict[str, Any] = {}
    conn2 = db()
    try:
        vote_center = get_vote_center_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "vote_center": vote_center,
    }
    if claim_result:
        resp["claim_all"] = claim_result
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/galactic-politics")
@require_login
def galactic_politics_view():
    ctx = _load_page_live_context(finish_source="galactic_politics")
    if ctx is None:
        return redirect(url_for("login"))

    from game.galactic_directives import get_galactic_politics_state

    politics_state = {"ready": False, "galaxies": []}
    conn = db()
    try:
        politics_state = get_galactic_politics_state(int(session["user_id"]), conn=conn)
    finally:
        conn.close()

    return render_template(
        "galactic_politics.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        politics_state=politics_state,
    )


@app.route("/api/galactic-politics/state", methods=["GET"])
@require_login
def api_galactic_politics_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.galactic_directives import get_galactic_politics_state

    conn = db()
    try:
        politics = get_galactic_politics_state(user_id, conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, "galactic_politics": politics})


@app.route("/api/galactic-politics/vote", methods=["POST"])
@require_login
def api_galactic_politics_vote():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached:
            return jsonify(cached)

    galaxy = data.get("galaxy")
    directive_key = str(data.get("directive_key") or data.get("directive") or "").strip()
    from game.galactic_directives import get_galactic_politics_state, submit_directive_vote

    conn = db()
    try:
        result = submit_directive_vote(user_id, galaxy, directive_key, conn=conn)
        conn.commit()
    except Exception:
        logger.exception("galactic directive vote failed user_id=%s galaxy=%s", user_id, galaxy)
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_galactic_politics_vote")
        return jsonify({"ok": False, "reason": "vote_failed", "state": state}), 500
    finally:
        conn.close()

    ok = bool(result.get("ok"))
    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_galactic_politics_vote")
    conn2 = db()
    try:
        politics = get_galactic_politics_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": ok,
        "reason": result.get("reason"),
        "state": state,
        "galactic_politics": politics,
    }
    if ok:
        resp["vote"] = {
            "galaxy": result.get("galaxy"),
            "directive": result.get("directive"),
            "cycle_id": result.get("cycle_id"),
        }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    status = 200 if ok else 400
    return jsonify(resp), status


@app.route("/skilltree")
@require_login
def skilltree_view():
    return _render_placeholder_module("skilltree")


@app.route("/premium")
@require_login
def premium_view():
    return _render_placeholder_module("premium")


# --------------------------------------------------------------------------
# REFERRALS (GC-703)
# --------------------------------------------------------------------------

@app.route("/referrals")
@require_login
def referrals_view():
    ctx = _load_page_live_context(finish_source="referrals")
    if ctx is None:
        return redirect(url_for("login"))

    from game.referrals import get_referral_state

    referral_state = {"ready": False}
    conn = db()
    try:
        base = request.url_root.rstrip("/") + url_for("register")
        referral_state = get_referral_state(
            int(session["user_id"]),
            conn=conn,
            referral_link_base=base,
        )
    finally:
        conn.close()

    return render_template(
        "referrals.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        referral_state=referral_state,
    )


@app.route("/api/referrals/state", methods=["GET"])
@require_login
def api_referrals_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.referrals import get_referral_state

    conn = db()
    try:
        base = request.url_root.rstrip("/") + url_for("register")
        referral_state = get_referral_state(user_id, conn=conn, referral_link_base=base)
    finally:
        conn.close()
    return jsonify({"ok": True, "referrals": referral_state})


@app.route("/api/referrals/apply", methods=["POST"])
@require_login
def api_referrals_apply():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    code = str(data.get("referral_code") or data.get("code") or "").strip()
    from game.referrals import apply_referral_code, get_referral_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason = apply_referral_code(
            user_id,
            code,
            client_ip(request),
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("referral apply failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_referrals_apply")
        return jsonify({"ok": False, "reason": "server_error", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_referrals_apply")
    base = request.url_root.rstrip("/") + url_for("register")
    conn2 = db()
    try:
        referrals = get_referral_state(user_id, conn=conn2, referral_link_base=base)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "referrals": referrals,
    }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/api/referrals/claim", methods=["POST"])
@require_login
def api_referrals_claim():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    reward_scope = str(data.get("reward_scope") or "").strip().lower()
    reward_key = str(data.get("reward_key") or "").strip()
    from game.referrals import claim_referral_reward, get_referral_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_referral_reward(
            user_id,
            reward_scope,
            reward_key,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception(
            "referral claim failed user_id=%s scope=%s key=%s",
            user_id,
            reward_scope,
            reward_key,
        )
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_referrals_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_referrals_claim")
    base = request.url_root.rstrip("/") + url_for("register")
    conn2 = db()
    try:
        referrals = get_referral_state(user_id, conn=conn2, referral_link_base=base)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "referrals": referrals,
    }
    if ok and claim_result:
        resp["claim"] = claim_result
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


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


@app.route("/records")
@require_login
def records_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    from game.records import build_records_payload

    conn = db()
    try:
        records_payload = build_records_payload(conn=conn)
    finally:
        conn.close()

    return render_template(
        "records.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        records_payload=records_payload,
    )


@app.route("/news")
@require_login
def news_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    from game.universe_news import news_page_payload
    from game.i18n import current_locale

    news_payload = news_page_payload(locale=current_locale())

    return render_template(
        "news.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        news_payload=news_payload,
    )


@app.route("/devlog")
@require_login
def devlog_view():
    user = get_current_user()
    if not user or not int(user.get("is_admin") or 0):
        return redirect(url_for("news_view"))

    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    from game.universe_news import devlog_page_payload

    return render_template(
        "devlog.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        devlog_payload=devlog_page_payload(),
    )


@app.route("/api/news")
@require_login
def api_news():
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.universe_news import news_page_payload

        return jsonify(news_page_payload())
    except Exception:
        return jsonify({"ok": False, "error": "news_unavailable"}), 500


@app.route("/api/records")
@require_login
def api_records():
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.records import build_records_payload

        conn = db()
        try:
            payload = build_records_payload(conn=conn)
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "records_unavailable"}), 500


@app.route("/hall-of-fame")
@require_login
def hall_of_fame_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    from game.combat_hof import build_hof_api_payload

    sort = request.args.get("sort", "destroyed")
    player_id = _current_player_id()
    conn = db()
    try:
        hof_payload = build_hof_api_payload(sort=sort, player_id=player_id, limit=100, conn=conn)
    finally:
        conn.close()

    return render_template(
        "hall_of_fame.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        hof_payload=hof_payload,
        hof_sort=hof_payload.get("sort") or "destroyed",
    )


@app.route("/api/hall-of-fame")
@require_login
def api_hall_of_fame():
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.combat_hof import build_hof_api_payload

        sort = request.args.get("sort", "destroyed")
        player_id = _current_player_id()
        conn = db()
        try:
            payload = build_hof_api_payload(sort=sort, player_id=player_id, limit=100, conn=conn)
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "hall_of_fame_unavailable"}), 500


@app.route("/chronicles")
@require_login
def chronicles_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources()
    if player_view is None:
        return redirect(url_for("login"))

    from game.chronicles import build_chronicles_api_payload

    section = request.args.get("section", "pvp")
    tab = request.args.get("tab", "overview")
    player_id = _current_player_id()
    conn = db()
    try:
        chronicles_payload = build_chronicles_api_payload(
            player_id=int(player_id),
            section=section,
            tab=tab,
            conn=conn,
        )
    finally:
        conn.close()

    return render_template(
        "chronicles.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        chronicles_payload=chronicles_payload,
        chronicles_section=chronicles_payload.get("section") or "pvp",
        chronicles_tab=chronicles_payload.get("tab") or "overview",
    )


@app.route("/api/chronicles")
@require_login
def api_chronicles():
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.chronicles import build_chronicles_api_payload

        section = request.args.get("section", "pvp")
        tab = request.args.get("tab", "overview")
        player_id = _current_player_id()
        conn = db()
        try:
            payload = build_chronicles_api_payload(
                player_id=int(player_id),
                section=section,
                tab=tab,
                conn=conn,
            )
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "chronicles_unavailable"}), 500


@app.route("/pvp")
@require_login
def pvp_view_redirect():
    tab = request.args.get("tab", "overview")
    return redirect(url_for("chronicles_view", section="pvp", tab=tab))


@app.route("/api/pvp")
@require_login
def api_pvp_legacy():
    """Legacy alias — prefer ``/api/chronicles?section=pvp``."""
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.chronicles import build_chronicles_api_payload

        tab = request.args.get("tab", "overview")
        player_id = _current_player_id()
        conn = db()
        try:
            payload = build_chronicles_api_payload(
                player_id=int(player_id),
                section="pvp",
                tab=tab,
                conn=conn,
            )
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "chronicles_unavailable"}), 500


@app.route("/api/admin/combat-hof/backfill", methods=["POST"])
@require_admin_api
def api_admin_backfill_combat_hof():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    body = request.get_json(silent=True) or {}
    raw_limit = body.get("limit")
    limit = None
    if raw_limit is not None and str(raw_limit).strip() != "":
        try:
            limit = max(1, int(raw_limit))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_limit"}), 400
    try:
        from game.combat_hof import backfill_combat_hof

        conn = db()
        try:
            result = backfill_combat_hof(limit=limit, conn=conn)
            conn.commit()
        finally:
            conn.close()
        if admin_id and result.get("ok"):
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "backfill_combat_hof",
                    target_type="system",
                    payload={
                        "inserted": result.get("inserted"),
                        "skipped_existing": result.get("skipped_existing"),
                        "skipped_invalid": result.get("skipped_invalid"),
                        "pruned": result.get("pruned"),
                        "limit": limit,
                    },
                )
            except Exception:
                pass
        status = 200 if result.get("ok") else 500
        return jsonify(result), status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/admin/rankings/recalculate", methods=["POST"])
@require_admin_api
def api_admin_recalculate_rankings():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    try:
        from game.db import count_table_rows, db, gather_score_stats

        result = recalculate_all_rankings(refresh_scores=True)
        conn = db()
        try:
            result["players_seen"] = count_table_rows(conn, "players")
            result["scores_updated"] = int(result.get("players_updated") or 0)
            stats = gather_score_stats(conn)
            result["top_score"] = stats["top_score"]
        finally:
            conn.close()
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


@app.route("/api/admin/ranking/recompute", methods=["POST"])
@require_admin_api
def api_admin_ranking_recompute():
    """Alias for /api/admin/rankings/recalculate (GC-P0 ranking worker debug)."""
    return api_admin_recalculate_rankings()


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


@app.route("/api/admin/server", methods=["GET"])
@require_admin_api
def api_admin_server_get():
    return _admin_json(admin_api_logic.api_get_server_settings())


@app.route("/api/admin/server", methods=["POST"])
@require_admin_api
def api_admin_server_save():
    return _admin_json(admin_api_logic.api_save_server_settings(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/universe-news", methods=["GET"])
@require_admin_api
def api_admin_universe_news_list():
    return _admin_json(admin_api_logic.api_get_universe_news())


@app.route("/api/admin/universe-news", methods=["POST"])
@require_admin_api
def api_admin_universe_news_create():
    return _admin_json(admin_api_logic.api_create_universe_news(_admin_actor_id(), _admin_body()))


@app.route("/api/news/whats-new")
@require_login
def api_news_whats_new():
    if _current_player_id() is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.universe_news import whats_new_payload

        return jsonify(whats_new_payload())
    except Exception:
        return jsonify({"ok": False, "error": "news_unavailable"}), 500


@app.route("/api/admin/universe-news/import-changelog", methods=["POST"])
@require_admin_api
def api_admin_universe_news_import_changelog():
    return _admin_json(admin_api_logic.api_import_changelog(_admin_actor_id()))


@app.route("/api/admin/universe-news/import-git-history", methods=["POST"])
@require_admin_api
def api_admin_universe_news_import_git_history():
    return _admin_json(admin_api_logic.api_import_git_history(_admin_actor_id()))


@app.route("/api/admin/universe-news/import-full-history", methods=["POST"])
@require_admin_api
def api_admin_universe_news_import_full_history():
    return _admin_json(admin_api_logic.api_import_full_history(_admin_actor_id()))


@app.route("/api/admin/universe-news/reclassify-audience", methods=["POST"])
@require_admin_api
def api_admin_universe_news_reclassify_audience():
    return _admin_json(admin_api_logic.api_reclassify_news_audience(_admin_actor_id()))


@app.route("/api/admin/universe-news/repository-audit", methods=["GET"])
@require_admin_api
def api_admin_universe_news_repository_audit():
    return _admin_json(admin_api_logic.api_repository_history_audit(_admin_actor_id()))


@app.route("/api/admin/universe-news/<int:news_id>", methods=["PATCH"])
@require_admin_api
def api_admin_universe_news_update(news_id: int):
    return _admin_json(admin_api_logic.api_update_universe_news(_admin_actor_id(), news_id, _admin_body()))


@app.route("/api/admin/universe-news/<int:news_id>/banner", methods=["POST"])
@require_admin_api
def api_admin_universe_news_banner(news_id: int):
    return _admin_json(admin_api_logic.api_set_universe_news_banner(_admin_actor_id(), news_id))


@app.route("/api/admin/universe-news/<int:news_id>/delete", methods=["POST"])
@require_admin_api
def api_admin_universe_news_delete_post(news_id: int):
    return _admin_json(admin_api_logic.api_delete_universe_news(_admin_actor_id(), news_id))


@app.route("/api/admin/universe-news/<int:news_id>", methods=["DELETE"])
@require_admin_api
def api_admin_universe_news_delete(news_id: int):
    return _admin_json(admin_api_logic.api_delete_universe_news(_admin_actor_id(), news_id))


@app.route("/api/admin/resources", methods=["POST"])
@require_admin_api
def api_admin_resources_apply():
    return _admin_json(
        admin_api_logic.api_apply_resource_tools(_admin_actor_id(), _admin_body(), _admin_actor_id())
    )


@app.route("/api/admin/wipe", methods=["POST"])
@require_admin_api
def api_admin_wipe():
    return _admin_json(admin_api_logic.api_wipe_universe(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/universe-reset", methods=["POST"])
@require_admin_api
def api_admin_universe_reset():
    return _admin_json(
        admin_api_logic.api_universe_reset_keep_inventory(_admin_actor_id(), _admin_body())
    )


@app.route("/api/admin/bans", methods=["GET"])
@require_admin_api
def api_admin_bans_list():
    return _admin_json(admin_api_logic.api_get_bans())


# --------------------------------------------------------------------------
# PLAYER CARD (global profile popup)
# --------------------------------------------------------------------------

def _playercard_viewer_id() -> int | None:
    return _current_player_id()


@app.route("/api/player-avatar/<int:player_id>")
def api_player_avatar(player_id: int):
    viewer_id = _playercard_viewer_id()
    if not playercard_logic.can_serve_player_avatar(player_id, viewer_id=viewer_id):
        abort(404)

    row = playercard_logic.get_player_avatar_row(player_id)
    if not row:
        abort(404)

    blob = row.get("image_blob")
    if not blob:
        abort(404)

    updated_at = int(row.get("updated_at") or 0)
    mime = str(row.get("mime_type") or "image/webp").split(";")[0].strip().lower()
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        mime = "image/webp"

    etag = f'W/"pa-{int(player_id)}-{updated_at}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag, "Cache-Control": "private, max-age=3600"})

    resp = Response(blob, mimetype=mime)
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, max-age=3600"
    if updated_at > 0:
        resp.headers["Last-Modified"] = time.strftime(
            "%a, %d %b %Y %H:%M:%S GMT",
            time.gmtime(updated_at),
        )
    return resp


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


@app.route("/api/player-card/me/avatar", methods=["POST"])
@require_login
def api_player_card_avatar_upload():
    viewer_id = _playercard_viewer_id()
    if viewer_id is None:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    file_storage = request.files.get("avatar")
    try:
        ok, reason, card = playercard_logic.upload_own_avatar(int(viewer_id), file_storage)
    except Exception:
        logger.exception("player-card avatar upload failed viewer_id=%s", viewer_id)
        return jsonify({"ok": False, "reason": "playercard_avatar_save_failed"}), 500
    if not ok:
        status = 429 if reason == "playercard_rate_limited" else 400
        return jsonify({"ok": False, "reason": reason}), status

    sync = {
        "player_id": int(viewer_id),
        "avatar_url": card.get("avatar_url_client") or "",
        "avatar_version": int(card.get("avatar_version") or 0),
        "show_avatar": bool(card.get("avatar_url_client")),
        "theme": card.get("theme") or "cyan",
        "avatar_initial": (card.get("commander_name_raw") or "?")[:1],
        "avatar_path": card.get("avatar_url_client") or "",
    }
    return jsonify({"ok": True, "reason": reason, "card": sync})


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


@app.route("/api/admin/messages/broadcast", methods=["POST"])
@require_admin_api
def api_admin_messages_broadcast():
    return _admin_json(
        admin_api_logic.api_broadcast_system_messages(_admin_actor_id(), _admin_body())
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
    if pid:
        try:
            options_data.update(discord_auth_logic.discord_link_snapshot(int(pid)))
        except Exception:
            pass

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


@app.route("/api/locale", methods=["POST"])
def api_locale():
    """Guest / pre-login locale — persists display language in gc_locale cookie only."""
    payload = request.get_json(silent=True) or {}
    raw = str(payload.get("locale") or "").strip().lower()
    if raw not in {"de", "en"}:
        return _options_api_response(False, "options_error_invalid_locale", None, 400)
    loc = normalize_locale(raw)
    from flask import make_response

    body, status = _options_api_response(True, None, {"locale": loc})
    resp = make_response(body, status)
    resp.set_cookie("gc_locale", loc, max_age=365 * 24 * 3600, samesite="Lax")
    return resp


@app.route("/api/options/locale", methods=["POST"])
@require_login_api
def api_options_locale():
    pid = session.get("user_id")
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)
    payload = request.get_json(silent=True) or {}
    ok, err, data = options_logic.update_locale(int(pid), payload.get("locale"))
    if not ok:
        return _options_api_response(False, err, data, 400)
    from flask import make_response

    body, status = _options_api_response(True, err, data)
    resp = make_response(body, status)
    resp.set_cookie("gc_locale", (data or {}).get("locale", "de"), max_age=365 * 24 * 3600, samesite="Lax")
    return resp


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


@app.route("/api/options/vacation/enable", methods=["POST"])
@require_login_api
def api_options_vacation_enable():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    ok, err, data = options_logic.enable_vacation_mode(
        int(pid),
        str(payload.get("confirm_text") or ""),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        status = 400
        if err == "options_error_safety_blockers":
            status = 409
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/options/vacation/disable", methods=["POST"])
@require_login_api
def api_options_vacation_disable():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    ok, err, data = options_logic.disable_vacation_mode(
        int(pid),
        str(payload.get("confirm_text") or ""),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/options/account-safety/repair", methods=["POST"])
@require_login_api
def api_options_account_safety_repair():
    pid = _current_player_id()
    assert pid is not None
    meta = _options_request_meta()
    repaired, hud = options_logic.repair_account_safety_state(
        int(pid),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    safety = options_logic.get_account_safety_state(int(pid), self_heal=False)
    state = {
        "ok": True,
        "server_time": time.time(),
        "player_id": int(pid),
        "account_safety": hud,
    }
    return _options_api_response(
        True,
        "options_vacation_repaired",
        {"account_safety": safety, "repaired": repaired, "state": state},
    )


@app.route("/api/options/account-deletion/request", methods=["POST"])
@require_login_api
def api_options_account_deletion_request():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    ok, err, data = options_logic.request_account_deletion(
        int(pid),
        str(payload.get("confirm_text") or ""),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        status = 409 if err == "options_error_safety_blockers" else 400
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/options/account-deletion/cancel", methods=["POST"])
@require_login_api
def api_options_account_deletion_cancel():
    pid = _current_player_id()
    assert pid is not None
    meta = _options_request_meta()
    ok, err, data = options_logic.cancel_account_deletion(
        int(pid),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/options/account-reset", methods=["POST"])
@require_login_api
def api_options_account_reset():
    pid = _current_player_id()
    assert pid is not None
    user = get_current_user()
    if not user:
        return _options_api_response(False, "not_logged_in", None, 401)
    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    ok, err, data = options_logic.execute_account_reset(
        int(pid),
        str(user.get("username") or ""),
        str(payload.get("current_password") or ""),
        str(payload.get("confirm_text") or ""),
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    if not ok:
        status = 409 if err == "options_error_safety_blockers" else 400
        return _options_api_response(False, err, data, status)
    return _options_api_response(True, err, data)


@app.route("/api/account/unlink-discord", methods=["POST"])
@require_login_api
def api_account_unlink_discord():
    pid = _current_player_id()
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)

    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("current_password") or "")

    ok, err, data = discord_auth_logic.unlink_discord_from_user(
        int(pid),
        current_password=current_password or None,
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


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


@app.route("/api/messages/bulk", methods=["POST"])
@require_login_api
def api_messages_bulk():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("ids") or payload.get("message_ids") or []
    if not isinstance(raw_ids, list):
        return _messages_json({"ok": False, "error": "validation", "data": None})
    try:
        ids = [int(i) for i in raw_ids]
    except (TypeError, ValueError):
        return _messages_json({"ok": False, "error": "validation", "data": None})
    return _messages_json(
        messages_logic.bulk_update_messages(
            int(pid),
            ids,
            action=str(payload.get("action") or ""),
        )
    )


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

def _fleet_write_transaction(work):
    """Run fleet DB mutation with BEGIN IMMEDIATE and explicit commit/rollback."""
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, result = work(conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
        return ok, reason, result
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def _payload_from_live_context(
    ctx: Dict[str, Any],
    *,
    user_id: int,
    include_panel: bool = True,
    lightweight: bool = False,
    panel_delta_keys: Optional[List[str]] = None,
    action_slim: bool = False,
    conn=None,
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
    planet = ctx.get("planet")

    own_conn = conn is None
    if own_conn:
        conn = db()

    energy_efficiency_pct = int(round(float(ratio) * 100))
    mods = get_research_modifiers(user_id)

    from game.live_state import get_request_context_planet

    if not isinstance(planet, dict):
        planet = get_request_context_planet(user_id, conn=conn)
    energy_hint = (
        "zero"
        if int(energy_total) <= 0
        else (
            "ok"
            if float(ratio) >= 1.0
            else ("low" if float(ratio) >= 0.5 else "critical")
        )
    )

    payload: Dict[str, Any] = {
        "ok": True,
        "server_time": time.time(),
        "player_id": int(user_id),
        "energy_ratio": float(ratio),
        "energy_efficiency_pct": energy_efficiency_pct,
        "player": {
            "name": player_view["name"],
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "fuel_cells": round(float(player_view.get("fuel_cells") or 0), 2),
            "energy_used": int(energy_used),
            "energy_total": int(energy_total),
            "energy_ratio": float(ratio),
            "energy_efficiency_pct": energy_efficiency_pct,
        },
        "resources": {
            "metal": round(float(player_view["metal"]), 2),
            "crystal": round(float(player_view["crystal"]), 2),
            "fuel_cells": round(float(player_view.get("fuel_cells") or 0), 2),
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
            "energy_hint": energy_hint,
        },
    }

    if include_panel:
        from game.buildings import get_overview_building_rows

        payload["overview"]["rows"] = get_overview_building_rows(
            planet, buildings, build_queue=build_queue
        )

    from game.overview_page import build_overview_status

    if not lightweight:
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
            conn=conn,
        )

    active_planet_id = int(planet.get("id") or 0)
    payload["active_planet_id"] = active_planet_id
    payload["active_planet_name"] = str(planet.get("name") or "")
    try:
        from game.galaxy import get_planet_coordinates
        from game.planet_evolution.dna import effective_planet_class
        from game.planet_evolution.ux_copy import planet_class_label_key

        from game.planet_visuals import (
            get_landscape_for_position,
            get_planet_identity_for_position,
            herocard_static_relpath,
            herocard_webp_srcset_for_position,
            OVERVIEW_HEROCARD_SIZES,
            raster_webp_relpath,
        )

        coords = get_planet_coordinates(planet)
        position = int(coords.get("position") or 0)
        landscape_fn = get_landscape_for_position(position)
        landscape_rel = f"img/landscapes/{landscape_fn}"
        herocard_rel = herocard_static_relpath(position)
        planet_class = effective_planet_class(planet)
        theme = get_planet_identity_for_position(position)
        from game.planet_visuals import climate_economy_display_for_position, temperature_range_for_position

        temp = temperature_range_for_position(position)
        climate = climate_economy_display_for_position(position)
        from game.planet_evolution.empire_identity import empire_identity_for_planet
        from game.planet_evolution.sidebar_nav import resolve_sidebar_nav

        identity = empire_identity_for_planet(planet, conn=conn)
        payload["active_planet"] = {
            "planet_id": int(active_planet_id),
            "name": str(planet.get("name") or ""),
            "coordinates_formatted": coords.get("formatted") or "",
            "planet_class": planet_class,
            "planet_class_label_key": planet_class_label_key(planet_class),
            "is_homeworld": bool(planet.get("is_homeworld")),
            "position": position,
            "landscape_url": url_for("static", filename=landscape_rel),
            "landscape_webp_url": url_for("static", filename=raster_webp_relpath(landscape_rel)),
            "herocard_url": url_for("static", filename=herocard_rel),
            "herocard_webp_url": url_for("static", filename=raster_webp_relpath(herocard_rel)),
            "herocard_webp_srcset": herocard_webp_srcset_for_position(position, url_for),
            "herocard_webp_sizes": OVERVIEW_HEROCARD_SIZES,
            "accent_color": theme["accent_color"],
            "secondary_color": theme["secondary_color"],
            "glow_color": theme["accent_color"],
            "planet_effect": theme["effect"],
            "theme_key": theme["theme_key"],
            "theme_group": theme["theme_group"],
            "slot_label_key": theme["label_key"],
            "temperature_display": temp["display"],
            "climate": climate,
            **identity,
            "sidebar_nav": resolve_sidebar_nav(
                empire_role_key=identity["empire_role_key"],
                is_homeworld=bool(planet.get("is_homeworld")),
            ),
        }
    except Exception:
        from game.planet_visuals import (
            DEFAULT_HEROCARD,
            DEFAULT_LANDSCAPE,
            climate_economy_display_for_position,
            get_planet_identity_for_position,
            herocard_webp_srcset_for_position,
            OVERVIEW_HEROCARD_SIZES,
            raster_webp_relpath,
            temperature_range_for_position,
        )

        fallback_rel = f"img/landscapes/{DEFAULT_LANDSCAPE}"
        fallback_herocard_rel = f"img/herocards/{DEFAULT_HEROCARD}"
        fallback_theme = get_planet_identity_for_position(0)
        fallback_temp = temperature_range_for_position(0)
        fallback_climate = climate_economy_display_for_position(0)
        from game.planet_evolution.empire_identity import empire_identity_for_planet
        from game.planet_evolution.sidebar_nav import resolve_sidebar_nav

        identity = empire_identity_for_planet(planet, conn=conn)
        payload["active_planet"] = {
            "planet_id": int(active_planet_id),
            "name": str(planet.get("name") or ""),
            "coordinates_formatted": "",
            "planet_class": str(planet.get("planet_class") or "terrestrial"),
            "planet_class_label_key": "planet_class_terrestrial",
            "is_homeworld": bool(planet.get("is_homeworld")),
            "position": None,
            "landscape_url": url_for("static", filename=fallback_rel),
            "landscape_webp_url": url_for("static", filename=raster_webp_relpath(fallback_rel)),
            "herocard_url": url_for("static", filename=fallback_herocard_rel),
            "herocard_webp_url": url_for("static", filename=raster_webp_relpath(fallback_herocard_rel)),
            "herocard_webp_srcset": herocard_webp_srcset_for_position(0, url_for),
            "herocard_webp_sizes": OVERVIEW_HEROCARD_SIZES,
            "accent_color": fallback_theme["accent_color"],
            "secondary_color": fallback_theme["secondary_color"],
            "glow_color": fallback_theme["accent_color"],
            "planet_effect": fallback_theme["effect"],
            "theme_key": fallback_theme["theme_key"],
            "theme_group": fallback_theme["theme_group"],
            "slot_label_key": fallback_theme["label_key"],
            "temperature_display": fallback_temp["display"],
            "climate": fallback_climate,
            **identity,
            "sidebar_nav": resolve_sidebar_nav(
                empire_role_key=identity["empire_role_key"],
                is_homeworld=bool(planet.get("is_homeworld")),
            ),
        }

    if panel_delta_keys:
        from game.buildings import get_buildings_panel_delta

        payload["buildings_panel_delta"] = get_buildings_panel_delta(
            planet,
            buildings,
            build_queue=build_queue,
            building_keys=panel_delta_keys,
        )
    elif include_panel:
        from game.buildings import get_buildings_panel_rows

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
        payload["unread_messages_count"] = messages_logic.unread_count(
            user_id,
            conn=conn,
            prepare=not lightweight,
        )
    except Exception:
        payload["unread_messages_count"] = 0

    try:
        from game.live_state import nav_badges_for_game_state

        payload["nav_badges"] = nav_badges_for_game_state(user_id, conn=conn)
    except Exception:
        payload["nav_badges"] = {
            "vote_center": {"active": False, "count": 0, "label": ""},
            "government": {"active": False, "count": 0, "label": ""},
            "referrals": {"active": False, "count": 0, "label": ""},
        }

    try:
        from game.live_state import fleet_hud_for_game_state

        fleet_hud = fleet_hud_for_game_state(user_id, conn=conn)
        if fleet_hud is not None:
            payload["active_fleets"] = fleet_hud.get("active_fleets") or {
                "count": 0,
                "visible_limit": 5,
                "next_remaining_seconds": 0,
                "items": [],
            }
            payload["fleet_slots"] = fleet_hud.get("fleet_slots") or {}
        else:
            payload["active_fleets"] = {
                "count": 0,
                "visible_limit": 5,
                "next_remaining_seconds": 0,
                "items": [],
            }
            payload["fleet_slots"] = {"active": 0, "max": 0, "free": 0}
    except Exception:
        payload["active_fleets"] = {
            "count": 0,
            "visible_limit": 5,
            "next_remaining_seconds": 0,
            "items": [],
        }
        payload["fleet_slots"] = {"active": 0, "max": 0, "free": 0}

    try:
        from game.live_state import account_safety_hud_for_game_state

        payload["account_safety"] = account_safety_hud_for_game_state(user_id, conn=conn)
    except Exception:
        payload["account_safety"] = {
            "vacation_active": False,
            "vacation_locked_until": None,
            "vacation_can_disable": False,
            "deletion_pending": False,
            "deletion_due_at": None,
            "deletion_seconds_remaining": 0,
        }

    if include_panel:
        try:
            from game.live_state import global_queue_hud_for_game_state

            payload["global_queue_hud"] = global_queue_hud_for_game_state(
                user_id,
                buildings=buildings,
                conn=conn,
                planet=planet,
                build_queue=build_queue,
                research=research,
            )
        except Exception:
            payload["global_queue_hud"] = {
                "jobs": [],
                "planet_id": int(payload.get("active_planet_id") or 0),
                "planet_name": str(payload.get("active_planet_name") or ""),
            }

    try:
        from game.models import get_player_stats

        ps = get_player_stats() or {}
        payload["player_stats"] = {
            "online_now": int(ps.get("online_now") or 0),
            "total_players": int(ps.get("total_players") or 0),
        }
    except Exception:
        payload["player_stats"] = {"online_now": 0, "total_players": 0}

    try:
        from game.planet_evolution.service import list_player_planets_for_switcher

        payload["planets"] = list_player_planets_for_switcher(user_id, conn=conn)
    except Exception:
        payload["planets"] = []

    try:
        from game.logic import get_planet_limit_block

        payload["planet_limit"] = get_planet_limit_block(user_id, conn=conn)
    except Exception:
        payload["planet_limit"] = {
            "current": len(payload.get("planets") or []) or 1,
            "max": 9,
        }

    if include_panel:
        try:
            from game.exchange import exchange_schema_ready, get_exchange_status

            if exchange_schema_ready(conn):
                payload["exchange"] = get_exchange_status(
                    player_id=user_id,
                    planet_id=int(planet["id"]),
                    metal=float(player_view["metal"]),
                    crystal=float(player_view["crystal"]),
                    fuel_cells=float(player_view.get("fuel_cells") or 0),
                    conn=conn,
                )
        except Exception:
            pass

        try:
            from game.scrapyard import scrapyard_status

            pid_tr = int(planet["id"])
            payload["scrapyard"] = scrapyard_status(user_id, pid_tr, conn=conn)
        except Exception:
            pass

        try:
            from game.auction_house import auction_schema_ready, build_auction_house_state

            if auction_schema_ready(conn):
                payload["auction_house"] = build_auction_house_state(
                    user_id,
                    int(planet["id"]),
                    metal=float(player_view["metal"]),
                    crystal=float(player_view["crystal"]),
                    fuel_cells=float(player_view.get("fuel_cells") or 0),
                    conn=conn,
                )
        except Exception:
            pass

        try:
            from game.live_state import defense_panel_for_game_state

            defense_panel = defense_panel_for_game_state(user_id, conn=conn)
            if defense_panel is not None:
                payload["defense"] = defense_panel
        except Exception:
            pass

        try:
            from game.live_state import shipyard_panel_for_game_state

            shipyard_panel = shipyard_panel_for_game_state(user_id, conn=conn)
            if shipyard_panel is not None:
                payload["shipyard"] = shipyard_panel
                payload["shipyard_queue"] = shipyard_panel.get("queue")
        except Exception:
            pass

    if not lightweight:
        try:
            from game.planet_evolution.teaser import get_overview_planet_teaser

            payload["planet_teaser"] = get_overview_planet_teaser(
                user_id,
                metal=float(player_view["metal"]),
                crystal=float(player_view["crystal"]),
                conn=conn,
            )
        except sqlite3.OperationalError:
            logger.warning(
                "game-state planet teaser skipped (database locked) user_id=%s",
                user_id,
                exc_info=True,
            )
            payload["planet_teaser"] = {"visible": False}
        except Exception:
            payload["planet_teaser"] = {"visible": False}

    if own_conn and conn is not None:
        conn.close()

    if lightweight:
        from game.live_state import apply_lightweight_game_state_diet

        payload = apply_lightweight_game_state_diet(payload)
    elif action_slim:
        from game.live_state import apply_action_state_diet

        payload = apply_action_state_diet(payload)

    from game.logic import attach_canonical_server_time

    return attach_canonical_server_time(payload)


def _build_game_state_payload(
    include_panel: bool = True,
    *,
    finish_source: str = "game_state",
    force_include_panel: bool = False,
    panel_delta_keys: Optional[List[str]] = None,
    action_slim: bool = False,
) -> Tuple[dict, int]:
    """
    Zentraler Spielzustand für Polling + AJAX-Refresh (kein Page-Reload).
    Returns (payload, player_id).
    """
    user = get_current_user()
    if not user:
        return {"ok": False, "error": "not_logged_in"}, 0

    user_id = int(user["id"])
    lightweight = _is_game_state_poll_source(finish_source)
    if lightweight and not force_include_panel:
        include_panel = False

    conn = db()
    try:
        ctx_t0 = time.perf_counter()
        ctx = _load_page_live_context(
            finish_source=str(finish_source or "game_state"),
            include_panel=include_panel,
            conn=conn,
            close_conn=False,
        )
        if ctx is None:
            return {"ok": False, "error": "not_logged_in"}, 0

        payload_t0 = time.perf_counter()
        payload = _payload_from_live_context(
            ctx,
            user_id=user_id,
            include_panel=include_panel,
            lightweight=lightweight,
            panel_delta_keys=panel_delta_keys,
            action_slim=action_slim,
            conn=conn,
        )
        from game.live_state import current_action_perf

        perf = current_action_perf()
        if perf is not None:
            perf.add_payload_ms((time.perf_counter() - payload_t0) * 1000.0)
            # live_state refresh happens inside _load_page_live_context (refresh_player_live_state)
            _ = ctx_t0  # finish/resource_sync/live_state tracked in refresh_player_live_state
        return payload, user_id
    finally:
        conn.close()


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


def _queue_mode(data: Dict[str, Any]) -> str:
    raw = (data.get("queue_mode") or data.get("mode") or "single").strip().lower()
    return "max" if raw == "max" else "single"


def _uses_action_state_diet(finish_source: str) -> bool:
    return str(finish_source or "") in (
        "api_buildings_upgrade",
        "api_buildings_cancel",
        "game_state_buildings_finish",
        "api_planets_active",
    )


def _is_buildings_queue_action_source(finish_source: str) -> bool:
    return str(finish_source or "") in (
        "api_buildings_upgrade",
        "api_buildings_cancel",
        "game_state_buildings_finish",
    )


def _parse_panel_delta_buildings_param() -> Optional[List[str]]:
    raw = (request.args.get("panel_delta_buildings") or "").strip()
    if not raw:
        return None
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return keys or None


def _action_json_response(
    ok: bool,
    reason: str,
    payload: Any = None,
    job: Any = None,
    *,
    finish_source: str = "action",
    include_panel: bool = True,
    panel_delta_keys: Optional[List[str]] = None,
) -> Any:
    """Immer frischen Spielzustand liefern – auch bei Fehlern (ein Refresh nach Mutation)."""
    use_panel_delta = bool(panel_delta_keys)
    use_slim = (not include_panel) and (
        use_panel_delta or _uses_action_state_diet(finish_source)
    )
    state, _ = _build_game_state_payload(
        include_panel=include_panel and not use_panel_delta,
        finish_source=finish_source,
        panel_delta_keys=panel_delta_keys if use_panel_delta else None,
        action_slim=use_slim,
    )
    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
    }
    if not ok and payload is not None:
        resp["payload"] = payload
    if ok and job is not None:
        resp["job"] = job
    from game.live_state import finish_action_perf, is_action_perf_debug_enabled

    out = jsonify(resp)
    if is_action_perf_debug_enabled():
        perf_data = finish_action_perf(response_bytes=len(out.get_data() or b""))
        if perf_data is not None:
            resp["_action_perf"] = perf_data
            out = jsonify(resp)
    return out


def _defense_json_response(
    ok: bool,
    reason: str = "",
    *,
    queue: Any = None,
    defenses: Any = None,
    finish_source: str = "api_defense",
    status: int = 200,
) -> Any:
    """Canonical defense envelope: { ok, state, queue, defenses }."""
    from game.defense_api import defense_err, defense_ok, empty_defense_slices

    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
    if queue is None or defenses is None:
        empty_q, empty_d = empty_defense_slices()
        queue = empty_q if queue is None else queue
        defenses = empty_d if defenses is None else defenses
    body = (
        defense_ok(state=state, queue=queue, defenses=defenses, reason=reason)
        if ok
        else defense_err(reason or "generic", state=state, queue=queue, defenses=defenses)
    )
    return jsonify(body), status if not ok else 200


@app.route("/api/status")
@require_login
def api_status():
    """Alias von /api/game-state (gleiches Schema)."""
    return api_game_state()


@app.route("/api/game-state")
@require_login
def api_game_state():
    want_panel = request.args.get("include_panel", "").lower() in ("1", "true", "yes")
    delta_keys = _parse_panel_delta_buildings_param()
    if delta_keys:
        payload, _player_id = _build_game_state_payload(
            include_panel=False,
            finish_source="game_state_buildings_finish",
            panel_delta_keys=delta_keys,
            action_slim=True,
        )
    elif want_panel:
        # Panel polls need full live refresh so resources + buildings_panel stay in sync (GC-801).
        finish_source = "game_state_panel"
        payload, _player_id = _build_game_state_payload(
            include_panel=True,
            finish_source=finish_source,
            force_include_panel=True,
        )
    else:
        payload, _player_id = _build_game_state_payload(
            include_panel=False,
            finish_source="game_state",
        )
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
            fuel_cells=float(player_view.get("fuel_cells") or 0),
            conn=conn,
        )
        commit(conn)
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
    to_resource = (data.get("to") or data.get("to_resource") or "").strip().lower()
    direction = (data.get("direction") or "").strip().lower()

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
            to_resource=to_resource or None,
            direction=direction,
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


@app.route("/api/trader/scrapyard", methods=["POST"])
@require_login
def api_scrapyard_recycle():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    from game.planet_evolution.repository import get_context_planet
    from game.scrapyard import recycle_ships

    try:
        amount = int(data.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    ship_key = str(data.get("ship_key") or "").strip()

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        ok, reason, result = recycle_ships(
            player_id=user_id,
            planet_id=int(planet["id"]),
            ship_key=ship_key,
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
        finish_source="api_scrapyard",
    )


@app.route("/api/trader/fuel-exchange", methods=["POST"])
@require_login
def api_fuel_exchange_buy():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    from game.fuel_exchange import buy_fuel_cells, fuel_exchange_schema_ready
    from game.planet_evolution.repository import get_context_planet

    if not fuel_exchange_schema_ready(db()):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fuel_exchange")
        return jsonify({"ok": False, "reason": "fuel_exchange_unavailable", "state": state}), 503

    try:
        units = int(data.get("units") or data.get("amount") or 0)
    except (TypeError, ValueError):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fuel_exchange")
        return jsonify({"ok": False, "reason": "invalid_amount", "state": state}), 400

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        ok, reason, result = buy_fuel_cells(
            player_id=user_id,
            planet_id=int(planet["id"]),
            units=units,
            conn=conn,
        )
    finally:
        conn.close()

    return _action_json_response(
        ok,
        reason,
        payload=result if not ok else None,
        job=result if ok else None,
        finish_source="api_fuel_exchange",
    )


@app.route("/api/fleet/preview", methods=["POST"])
@require_login
def api_fleet_preview():
    from game.fleet import build_fleet_send_preview, fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_calc import normalize_ships
    from game.fleet_origin import resolve_fleet_origin_planet_id
    from game.fleet_target import parse_fleet_target_request

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    conn = db()
    try:
        dom_raw = request.headers.get("X-GC-Dom-Planet-Id") or data.get("dom_planet_id")
        dom_planet_id = int(dom_raw) if dom_raw not in (None, "") else None
        origin_id, _origin_audit = resolve_fleet_origin_planet_id(
            user_id,
            data.get("origin_planet_id"),
            conn=conn,
            dom_planet_id=dom_planet_id,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (origin_id, user_id),
        )
        origin_row = cur.fetchone()
        if not origin_row:
            return jsonify(fleet_err("origin_not_found")), 400
        origin_planet = dict(origin_row)

        ships = normalize_ships(data.get("ships") or {})
        if not ships and data.get("ships"):
            return jsonify(fleet_err("unknown_ship")), 400

        try:
            speed_percent = int(data.get("speed_percent") or 100)
        except (TypeError, ValueError):
            speed_percent = 100

        mission_type = str(data.get("mission_type") or "transport")
        target_req = parse_fleet_target_request(data)
        preview = build_fleet_send_preview(
            player_id=user_id,
            origin_planet=origin_planet,
            target_galaxy=int(data.get("target_galaxy") or origin_planet.get("galaxy") or 1),
            target_system=int(data.get("target_system") or origin_planet.get("system") or 1),
            target_position=int(data.get("target_position") or 1),
            mission_type=mission_type,
            ships=ships,
            resources=data.get("resources") or {},
            speed_percent=speed_percent,
            conn=conn,
            world_key=target_req.get("world_key"),
            target_type=target_req.get("target_type"),
            target_planet_id=target_req.get("target_planet_id"),
            target_world_x=target_req.get("target_world_x"),
            target_world_y=target_req.get("target_world_y"),
            expedition_hours=int(data["expedition_hours"]) if data.get("expedition_hours") not in (None, "") else None,
        )
        return jsonify(fleet_ok({"preview": preview}, message_key="fleet_preview_ok"))
    finally:
        conn.close()


@app.route("/api/fleet/resolve-target", methods=["GET", "POST"])
@require_login
def api_fleet_resolve_target():
    from game.fleet import (
        evaluate_fleet_mission_target,
        fleet_schema_ready,
        resolve_fleet_target,
    )
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_target import attach_world_target, parse_fleet_target_request
    from game.planet_evolution.world_colonization import (
        validate_world_colonize_target,
        validate_world_expedition_target,
        validate_world_salvage_target,
    )

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = request.args

    target_req = parse_fleet_target_request(data)
    mission = str(data.get("mission_type") or data.get("mission") or "transport").strip().lower()
    world_key = target_req.get("world_key")

    conn = db()
    try:
        if world_key:
            if mission == "colonize":
                ok, reason, target = validate_world_colonize_target(world_key, conn=conn)
            elif mission == "expedition":
                ok, reason, target = validate_world_expedition_target(world_key, conn=conn)
                if not ok:
                    ok, reason, target = validate_world_salvage_target(world_key, conn=conn)
            else:
                ok, reason, target = True, "", {}
                try:
                    from game.planet_evolution.world_colonization import parse_world_key
                    from game.planet_evolution.strategic_worlds import build_strategic_world_presentation

                    parsed = parse_world_key(world_key)
                    target = {
                        "target_type": "strategic_world",
                        "world_key": world_key,
                        "world_x": parsed["world_x"],
                        "world_y": parsed["world_y"],
                        "planet_role": parsed["planet_role"],
                        "coords": world_key,
                        "strategic_world": build_strategic_world_presentation(
                            parsed["world_x"],
                            parsed["world_y"],
                            world_type=parsed["world_type"],
                        ),
                    }
                except Exception:
                    ok, reason, target = False, "invalid_world_key", {}
            if not ok:
                return jsonify(fleet_err(reason or "invalid_target")), 400
            attach_world_target(
                target,
                player_id=user_id,
                conn=conn,
                explicit_native_type=target_req.get("target_type"),
            )
            return jsonify(fleet_ok({"target": target}, message_key="fleet_target_ok"))

        try:
            galaxy = int(data.get("galaxy") or data.get("target_galaxy") or 1)
            system = int(data.get("system") or data.get("target_system") or 1)
            position = int(data.get("position") or data.get("target_position") or 1)
        except (TypeError, ValueError):
            return jsonify(fleet_err("invalid_target")), 400

        target = resolve_fleet_target(user_id, galaxy, system, position, conn=conn)
        attach_world_target(
            target,
            player_id=user_id,
            conn=conn,
            explicit_native_type=target_req.get("target_type"),
            legacy_coords={"galaxy": galaxy, "system": system, "position": position},
        )
        if mission:
            ok, reason, _ = evaluate_fleet_mission_target(
                user_id, mission, galaxy, system, position, conn=conn
            )
            if not ok:
                target["mission_block_reason"] = reason
    finally:
        conn.close()

    return jsonify(fleet_ok({"target": target}, message_key="fleet_target_ok"))


@app.route("/api/fleet/state", methods=["GET"])
@require_login
def api_fleet_state():
    from game.fleet import fleet_schema_ready, get_fleet_live_state
    from game.fleet_api import fleet_err, fleet_ok
    from game.planet_evolution.repository import get_context_planet

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    conn = db()
    try:
        from game.db import begin_write_transaction, commit, rollback
        from game.shipyard import resolve_owned_planet_id

        begin_write_transaction(conn)
        raw_pid = request.args.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            return jsonify(fleet_err(err)), 404
        state = get_fleet_live_state(player_id=user_id, planet_id=int(planet_id), conn=conn)
        if not state.get("ready"):
            rollback(conn)
            return jsonify(fleet_err(str(state.get("error") or "fleet_unavailable"))), 400
        commit(conn)
        return jsonify(fleet_ok(state, message_key="fleet_state_ok"))
    except Exception:
        from game.db import rollback

        rollback(conn)
        raise
    finally:
        conn.close()


@app.route("/api/fleet/send", methods=["POST"])
@require_login
def api_fleet_send():
    from game.fleet import fleet_schema_ready, send_fleet
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_calc import normalize_ships
    from game.fleet_origin import resolve_fleet_origin_planet_id
    from game.fleet_target import parse_fleet_target_request

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_send")
        body = fleet_err("fleet_unavailable", data={"state": state})
        return jsonify(body), 503

    data = request.get_json(silent=True) or {}
    ships = normalize_ships(data.get("ships") or {})
    if not ships and data.get("ships"):
        return jsonify(fleet_err("unknown_ship")), 400
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100

    def _send(conn):
        dom_raw = request.headers.get("X-GC-Dom-Planet-Id") or data.get("dom_planet_id")
        dom_planet_id = int(dom_raw) if dom_raw not in (None, "") else None
        origin_id, _origin_audit = resolve_fleet_origin_planet_id(
            user_id,
            data.get("origin_planet_id"),
            conn=conn,
            dom_planet_id=dom_planet_id,
        )
        target_req = parse_fleet_target_request(data)
        return send_fleet(
            player_id=user_id,
            origin_planet_id=origin_id,
            target_galaxy=int(data.get("target_galaxy") or 0),
            target_system=int(data.get("target_system") or 0),
            target_position=int(data.get("target_position") or 0),
            mission_type=str(data.get("mission_type") or ""),
            ships=ships,
            resources=data.get("resources") or {},
            speed_percent=speed_percent,
            preset_id=int(data["preset_id"]) if data.get("preset_id") else None,
            batch_id=int(data["batch_id"]) if data.get("batch_id") else None,
            colony_name=str(data.get("colony_name") or "").strip() or None,
            world_key=target_req.get("world_key"),
            target_type=target_req.get("target_type"),
            target_planet_id=target_req.get("target_planet_id"),
            target_world_x=target_req.get("target_world_x"),
            target_world_y=target_req.get("target_world_y"),
            expedition_hours=int(data["expedition_hours"]) if data.get("expedition_hours") not in (None, "") else None,
            conn=conn,
        )

    ok, reason, result = _fleet_write_transaction(_send)

    if ok and result:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_send")
        live = {
            "fleet": result.get("fleet"),
            "updated_ships": result.get("updated_ships"),
            "updated_resources": result.get("updated_resources"),
            "active_slots": result.get("active_slots"),
            "fuel_cost": result.get("fuel_cost"),
        }
        body = fleet_ok(live, message_key="fleet_send_success")
        body["state"] = state
        return jsonify(body)

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_send")
    return jsonify(fleet_err(reason or "generic", data={"state": state})), 400


@app.route("/api/fleet/recall", methods=["POST"])
@require_login
def api_fleet_recall():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok, fleet_recall_movement

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_recall")
        return jsonify(fleet_err("fleet_unavailable", data={"state": state})), 503

    data = request.get_json(silent=True) or {}
    try:
        movement_id = int(data.get("movement_id") or 0)
    except (TypeError, ValueError):
        movement_id = 0
    if movement_id <= 0:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_recall")
        body = fleet_err("fleet_not_found", data={"state": state})
        body["state"] = state
        return jsonify(body), 400

    def _recall(conn):
        return fleet_recall_movement(user_id, movement_id, conn=conn)

    ok, reason, result = _fleet_write_transaction(_recall)
    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_fleet_recall")
    if ok:
        body = fleet_ok(result or {}, message_key="fleet_recall_success")
        body["state"] = state
        return jsonify(body)
    body = fleet_err(reason or "fleet_recall_failed", data={"state": state})
    body["state"] = state
    return jsonify(body), 400


@app.route("/api/fleet/presets", methods=["GET"])
@require_login
def api_fleet_presets_list():
    from game.fleet import fleet_schema_ready, list_presets
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503
    return jsonify(fleet_ok({"presets": list_presets(user_id)}, message_key="fleet_presets_ok"))


@app.route("/api/fleet/presets", methods=["POST"])
@require_login
def api_fleet_presets_create():
    from game.fleet import create_preset, fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    ok, reason, preset = create_preset(
        user_id,
        name=str(data.get("name") or ""),
        preset_type=str(data.get("preset_type") or "custom"),
        ships_json=data.get("ships_json") or data.get("ships") or {},
        resources_json=data.get("resources_json") or data.get("resources"),
        speed_percent=int(data.get("speed_percent") or 100),
        mission_type=data.get("mission_type"),
        target_galaxy=data.get("target_galaxy"),
        target_system=data.get("target_system"),
        target_position=data.get("target_position"),
    )
    if ok:
        return jsonify(fleet_ok({"preset": preset}, message_key="fleet_preset_saved"))
    return jsonify(fleet_err(reason)), 400


@app.route("/api/fleet/presets/<int:preset_id>", methods=["PUT", "PATCH"])
@require_login
def api_fleet_presets_update(preset_id: int):
    from game.fleet import fleet_schema_ready, update_preset
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    fields = dict(data)
    if "ships" in fields and "ships_json" not in fields:
        fields["ships_json"] = fields.pop("ships")
    if "resources" in fields and "resources_json" not in fields:
        fields["resources_json"] = fields.pop("resources")

    ok, reason, preset = update_preset(preset_id, user_id, fields)
    if ok:
        return jsonify(fleet_ok({"preset": preset}, message_key="fleet_preset_updated"))
    return jsonify(fleet_err(reason)), 400


@app.route("/api/fleet/presets/<int:preset_id>", methods=["DELETE"])
@require_login
def api_fleet_presets_delete(preset_id: int):
    from game.fleet import delete_preset, fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    ok, reason = delete_preset(preset_id, user_id)
    if ok:
        return jsonify(fleet_ok({"preset_id": preset_id}, message_key="fleet_preset_deleted"))
    return jsonify(fleet_err(reason)), 404


@app.route("/api/fleet/dev/seed-ships", methods=["POST"])
@require_login
def api_fleet_dev_seed_ships():
    """Dev/admin only: stack test ships on active planet (no shipyard required)."""
    from game.config import is_debug_enabled
    from game.fleet import fleet_schema_ready, seed_planet_ships_stack
    from game.fleet_api import fleet_err, fleet_ok
    from game.models import load_player
    from game.planet_evolution.repository import get_context_planet

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    player = load_player(user_id)
    allow = is_debug_enabled() or bool(player and player.get("is_admin"))
    if not allow:
        return jsonify(fleet_err("forbidden")), 403
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    seeded_planet_id = {"id": 0}

    def _seed(conn):
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(user_id, conn=conn)
        seeded_planet_id["id"] = int(data.get("planet_id") or planet["id"])
        return seed_planet_ships_stack(
            seeded_planet_id["id"],
            user_id,
            ships=data.get("ships"),
            replace=bool(data.get("replace")),
            conn=conn,
        )

    ok, reason, ships = _fleet_write_transaction(_seed)
    planet_id = int(seeded_planet_id["id"])

    if ok:
        return jsonify(fleet_ok({"ships": ships, "planet_id": planet_id}, message_key="fleet_dev_seed_ok"))
    return jsonify(fleet_err(reason)), 400


@app.route("/api/dev/fleet/seed-ships", methods=["POST"])
@require_login
def api_dev_fleet_seed_ships():
    """Alias for dev/admin test ship seed."""
    return api_fleet_dev_seed_ships()


@app.route("/api/dev/combat/simulate-spy", methods=["POST"])
@require_login
def api_dev_combat_simulate_spy():
    """DEV/admin: combat simulator from spy report metadata (no fleet dispatch)."""
    from game.combat import simulate_combat_preview_from_spy
    from game.config import is_debug_enabled
    from game.fleet_api import fleet_err, fleet_ok
    from game.messages import get_message
    from game.models import load_player

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    player = load_player(user_id)
    allow = is_debug_enabled() or bool(player and player.get("is_admin"))
    if not allow:
        return jsonify(fleet_err("forbidden")), 403

    data = request.get_json(silent=True) or {}
    message_id = int(data.get("message_id") or 0)
    spy_meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else None

    if message_id > 0:
        msg_row = get_message(user_id, message_id, mark_read=False)
        if not msg_row.get("ok"):
            return jsonify(fleet_err("message_not_found")), 404
        msg = (msg_row.get("data") or {}).get("message")
        if not msg:
            return jsonify(fleet_err("message_not_found")), 404
        if str(msg.get("category") or "") != "espionage":
            return jsonify(fleet_err("invalid_message")), 400
        spy_meta = dict(msg.get("metadata") or {})

    if not spy_meta or int(spy_meta.get("report_version") or 0) < 2:
        return jsonify(fleet_err("invalid_spy_report")), 400

    try:
        metadata = simulate_combat_preview_from_spy(
            player_id=user_id,
            spy_metadata=spy_meta,
        )
    except Exception:
        current_app.logger.exception("dev combat simulate-spy failed user_id=%s", user_id)
        return jsonify(fleet_err("combat_sim_failed")), 500

    return jsonify(fleet_ok({"metadata": metadata, "simulated": True}))


@app.route("/api/ships/<ship_key>")
@require_login
def api_ship_detail(ship_key: str):
    from game.models import get_planet_buildings, get_research_levels
    from game.planet_evolution.repository import get_context_planet
    from game.ship_detail import build_ship_detail_card

    buildings = None
    research = None
    user_id = int(session.get("user_id") or 0)
    if user_id:
        conn = db()
        try:
            planet = get_context_planet(user_id, conn=conn)
            buildings = get_planet_buildings(int(planet["id"]), conn=conn)
            research = get_research_levels(user_id=user_id, conn=conn)
        finally:
            conn.close()

    card, err = build_ship_detail_card(ship_key, buildings=buildings, research=research)
    if err:
        return (
            render_template(
                "partials/ship_detail_error.html",
                error_key=err,
            ),
            404,
        )
    return render_template("partials/ship_detail_view.html", card=card)


@app.route("/api/defense-units/<defense_key>")
@require_login
def api_defense_detail(defense_key: str):
    from game.defense_detail import build_defense_detail_card
    from game.models import get_planet_buildings, get_research_levels
    from game.planet_evolution.repository import get_context_planet

    buildings = None
    research = None
    user_id = int(session.get("user_id") or 0)
    if user_id:
        conn = db()
        try:
            planet = get_context_planet(user_id, conn=conn)
            buildings = get_planet_buildings(int(planet["id"]), conn=conn)
            research = get_research_levels(user_id=user_id, conn=conn)
        finally:
            conn.close()

    card, err = build_defense_detail_card(
        defense_key, buildings=buildings, research=research
    )
    if err:
        return (
            render_template(
                "partials/ship_detail_error.html",
                error_key=err,
            ),
            404,
        )
    return render_template("partials/defense_detail_view.html", card=card)


@app.route("/api/shipyard", methods=["GET"])
@require_login
def api_shipyard_state():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.shipyard import build_shipyard_api_payload, resolve_owned_planet_id

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    raw_pid = request.args.get("planet_id")
    req_pid = int(raw_pid) if raw_pid not in (None, "") else None

    conn = db()
    try:
        begin_write_transaction(conn)
        if not fleet_schema_ready(conn):
            rollback(conn)
            return jsonify(fleet_err("fleet_unavailable")), 503
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            return jsonify(fleet_err(err)), 404
        payload = build_shipyard_api_payload(user_id, int(planet_id), conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return jsonify(fleet_ok(payload))


@app.route("/api/defense/state", methods=["GET"])
@require_login
def api_defense_state_canonical():
    from game.defense_api import (
        defense_schema_available,
        fetch_defense_slices,
        resolve_context_planet_id,
    )
    from game.fleet_api import fleet_err

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    raw_pid = request.args.get("planet_id")
    req_pid = int(raw_pid) if raw_pid not in (None, "") else None

    conn = db()
    try:
        begin_write_transaction(conn)
        if not defense_schema_available(conn):
            rollback(conn)
            return _defense_json_response(False, "defense_unavailable", finish_source="api_defense_state", status=503)
        planet_id, err = resolve_context_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            return _defense_json_response(False, err, finish_source="api_defense_state", status=404)
        queue, defenses = fetch_defense_slices(user_id, int(planet_id), conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return _defense_json_response(True, finish_source="api_defense_state", queue=queue, defenses=defenses)


@app.route("/api/defense/overview", methods=["GET"])
@require_login
def api_defense_overview():
    from game.defense_api import (
        build_overview_slice,
        defense_err,
        defense_ok,
        defense_schema_available,
        empty_defense_slices,
        fetch_defense_slices,
        resolve_context_planet_id,
    )
    from game.fleet_api import fleet_err

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    raw_pid = request.args.get("planet_id")
    req_pid = int(raw_pid) if raw_pid not in (None, "") else None

    conn = db()
    try:
        begin_write_transaction(conn)
        if not defense_schema_available(conn):
            rollback(conn)
            state, _ = _build_game_state_payload(include_panel=True, finish_source="api_defense_overview")
            empty_q, empty_d = empty_defense_slices()
            return jsonify(defense_err("defense_unavailable", state=state, queue=empty_q, defenses=empty_d)), 503
        planet_id, err = resolve_context_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            state, _ = _build_game_state_payload(include_panel=True, finish_source="api_defense_overview")
            empty_q, empty_d = empty_defense_slices()
            return jsonify(defense_err(err, state=state, queue=empty_q, defenses=empty_d)), 404
        overview = build_overview_slice(user_id, int(planet_id), conn=conn)
        queue, defenses = fetch_defense_slices(user_id, int(planet_id), conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_defense_overview")
    body = defense_ok(state=state, queue=queue, defenses={**defenses, "overview": overview})
    return jsonify(body)


@app.route("/api/defense", methods=["GET"])
@require_login
def api_defense_state():
    from game.defense import build_defense_api_payload, defense_queue_table_ready
    from game.defense_page import build_defense_page_context
    from game.fleet_api import fleet_err, fleet_ok
    from game.models import defense_schema_ready
    from game.shipyard import resolve_owned_planet_id

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    raw_pid = request.args.get("planet_id")
    req_pid = int(raw_pid) if raw_pid not in (None, "") else None

    conn = db()
    try:
        begin_write_transaction(conn)
        if not defense_schema_ready(conn) or not defense_queue_table_ready(conn):
            rollback(conn)
            return jsonify(fleet_err("defense_unavailable")), 503
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            rollback(conn)
            return jsonify(fleet_err(err)), 404
        cur = conn.cursor()
        cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return jsonify(fleet_err("planet_not_found")), 404
        payload = build_defense_page_context(user_id, dict(row), conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return jsonify(fleet_ok(payload))


@app.route("/api/defense/build", methods=["POST"])
@require_login
def api_defense_build():
    from game.defense import build_defense
    from game.defense_api import (
        defense_schema_available,
        fetch_defense_slices,
        resolve_context_planet_id,
    )
    from game.live_state import defense_finish_source

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    defense_key = str(data.get("defense_key") or "").strip()
    from game.number_format import parse_int_number

    amount = parse_int_number(data.get("amount") or 1, default=0)
    if amount <= 0:
        return _defense_json_response(
            False,
            "invalid_amount",
            finish_source=defense_finish_source("build"),
            status=400,
        )

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    finish_source = defense_finish_source("build")
    conn = db()
    try:
        if not defense_schema_available(conn):
            return _defense_json_response(
                False,
                "defense_unavailable",
                finish_source=finish_source,
                status=503,
            )
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_context_planet_id(user_id, req_pid, conn=conn)
        if err:
            return _defense_json_response(False, err, finish_source=finish_source, status=404)
        ok, reason, _result = build_defense(
            player_id=user_id,
            planet_id=int(planet_id),
            defense_key=defense_key,
            amount=amount,
            conn=conn,
        )
        if not ok:
            return _defense_json_response(False, reason or "generic", finish_source=finish_source, status=400)
        queue, defenses = fetch_defense_slices(user_id, int(planet_id), conn=conn)
    finally:
        conn.close()

    resp = _defense_json_response(
        True,
        reason="defense_build_ok",
        queue=queue,
        defenses=defenses,
        finish_source=finish_source,
    )
    response_obj = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
    return resp


@app.route("/api/defense/cancel", methods=["POST"])
@require_login
def api_defense_cancel():
    from game.defense_api import (
        cancel_defense_job,
        defense_schema_available,
        fetch_defense_slices,
        resolve_context_planet_id,
    )
    from game.live_state import defense_finish_source

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or 0)
    except (TypeError, ValueError):
        job_id = 0

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    finish_source = defense_finish_source("cancel")
    if job_id <= 0:
        return _defense_json_response(False, "invalid_job", finish_source=finish_source, status=400)

    conn = db()
    try:
        if not defense_schema_available(conn):
            return _defense_json_response(
                False,
                "defense_unavailable",
                finish_source=finish_source,
                status=503,
            )
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_context_planet_id(user_id, req_pid, conn=conn)
        if err:
            return _defense_json_response(False, err, finish_source=finish_source, status=404)
        ok, reason = cancel_defense_job(
            player_id=user_id,
            planet_id=int(planet_id),
            job_id=job_id,
            conn=conn,
        )
        if not ok:
            return _defense_json_response(False, reason or "generic", finish_source=finish_source, status=400)
        queue, defenses = fetch_defense_slices(user_id, int(planet_id), conn=conn)
    finally:
        conn.close()

    resp = _defense_json_response(
        True,
        reason="defense_cancel_ok",
        queue=queue,
        defenses=defenses,
        finish_source=finish_source,
    )
    response_obj = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
    return resp


@app.route("/api/shipyard/build", methods=["POST"])
@require_login
def api_shipyard_build():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.planet_evolution.repository import get_context_planet
    from game.shipyard import build_ship

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    ship_key = str(data.get("ship_key") or "").strip()
    from game.number_format import parse_int_number

    amount = parse_int_number(data.get("amount") or 1, default=0)

    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return jsonify(fleet_err("fleet_unavailable")), 503
        from game.shipyard import resolve_owned_planet_id

        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason, result = build_ship(
            player_id=user_id,
            planet_id=int(planet_id),
            ship_key=ship_key,
            amount=amount,
            conn=conn,
        )
    finally:
        conn.close()

    if ok:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_shipyard_build")
        body = fleet_ok(result, message_key="shipyard_build_ok")
        body["state"] = state
        return jsonify(body)
    return jsonify(fleet_err(reason)), 400


@app.route("/api/shipyard/queue/cancel", methods=["POST"])
@require_login
def api_shipyard_queue_cancel():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.shipyard import cancel_shipyard_job, resolve_owned_planet_id

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or 0)
    except (TypeError, ValueError):
        job_id = 0
    if job_id <= 0:
        return jsonify(fleet_err("invalid_job")), 400

    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return jsonify(fleet_err("fleet_unavailable")), 503
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason, payload = cancel_shipyard_job(
            player_id=user_id,
            planet_id=int(planet_id),
            job_id=job_id,
            conn=conn,
        )
    finally:
        conn.close()

    if ok:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_shipyard_queue_cancel")
        body = fleet_ok(payload, message_key="shipyard_cancel_ok")
        body["state"] = state
        return jsonify(body)
    return jsonify(fleet_err(reason)), 400


@app.route("/api/shipyard/queue/move", methods=["POST"])
@require_login
def api_shipyard_queue_move():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.shipyard import move_shipyard_job, resolve_owned_planet_id

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or 0)
    except (TypeError, ValueError):
        job_id = 0
    direction = str(data.get("direction") or "").strip().lower()
    if job_id <= 0 or direction not in ("up", "down"):
        return jsonify(fleet_err("invalid_request")), 400

    conn = db()
    try:
        if not fleet_schema_ready(conn):
            return jsonify(fleet_err("fleet_unavailable")), 503
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason, payload = move_shipyard_job(
            player_id=user_id,
            planet_id=int(planet_id),
            job_id=job_id,
            direction=direction,
            conn=conn,
        )
    finally:
        conn.close()

    if ok:
        return jsonify(fleet_ok(payload, message_key="shipyard_move_ok"))
    return jsonify(fleet_err(reason)), 400


def _logistics_planet_rows(conn, planet_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    ids = sorted({int(x) for x in planet_ids if int(x) > 0})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM planets WHERE id IN ({placeholders});",
        ids,
    )
    return {int(row["id"]): dict(row) for row in cur.fetchall()}


def _build_logistics_preview(
    *,
    user_id: int,
    data: Mapping[str, Any],
    conn,
) -> Dict[str, Any]:
    """Server-side logistics plan preview (collect / distribute legs)."""
    from game.fleet import (
        build_collect_route,
        build_distribute_route,
        build_fleet_send_preview,
        get_fleet_slot_status,
    )
    from game.fleet_calc import (
        calculate_loaded_resources,
        calculate_total_cargo,
        loaded_resource_total,
        normalize_ships,
    )
    from game.galaxy import format_coordinates
    from game.planet_evolution.repository import get_context_planet

    mode = str(data.get("mode") or "collect").strip().lower()
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100

    ships = normalize_ships(data.get("ships") or {})
    slots = get_fleet_slot_status(int(user_id), conn=conn)
    base: Dict[str, Any] = {
        "mode": mode,
        "can_launch": False,
        "block_reason": "",
        "fleet_slots": slots,
        "slots_needed": 0,
        "max_flight_seconds": 0,
        "total_fuel_cost": 0,
        "cargo_total": 0,
        "cargo_used": 0,
        "cargo_free": 0,
        "legs": [],
        "delivered_total": None,
    }

    if not ships:
        base["block_reason"] = "no_ships"
        return base

    planet = get_context_planet(int(user_id), conn=conn)
    origin_id = int(
        data.get("origin_planet_id")
        or data.get("target_planet_id")
        or planet["id"]
    )

    legs: List[Dict[str, Any]] = []
    delivered_total: Optional[Dict[str, int]] = None
    route_ok = False
    route_reason = ""

    if mode == "collect":
        hub_id = int(data.get("target_planet_id") or origin_id)
        source_ids = [int(x) for x in (data.get("source_planet_ids") or [])]
        planet_rows = _logistics_planet_rows(conn, [hub_id, *source_ids])
        route_ok, route_reason, route_legs = build_collect_route(
            origin_planet_id=hub_id,
            source_planet_ids=source_ids,
            planet_rows_by_id=planet_rows,
            ships=ships,
            free_fleet_slots=int(slots["free"]),
            player_id=int(user_id),
        )
        if route_ok and route_legs:
            origin_row = planet_rows.get(hub_id) or dict(planet)
            for leg in route_legs:
                leg_previews = build_fleet_send_preview(
                    player_id=int(user_id),
                    origin_planet=origin_row,
                    target_galaxy=int(leg["galaxy"]),
                    target_system=int(leg["system"]),
                    target_position=int(leg["position"]),
                    mission_type="collect",
                    ships=leg["ships"],
                    resources={},
                    speed_percent=speed_percent,
                    conn=conn,
                )
                prow = planet_rows.get(int(leg["planet_id"])) or {}
                legs.append(
                    {
                        "planet_id": int(leg["planet_id"]),
                        "name": str(prow.get("name") or ""),
                        "coordinates": format_coordinates(
                            int(leg["galaxy"]),
                            int(leg["system"]),
                            int(leg["position"]),
                        ),
                        "flight_seconds": int(leg_previews.get("flight_seconds") or 0),
                        "cargo_total": int(leg_previews.get("cargo_total") or 0),
                        "cargo_used": int(leg_previews.get("cargo_used") or 0),
                        "cargo_free": int(leg_previews.get("cargo_free") or 0),
                        "fuel_cost": int(leg_previews.get("fuel_cost") or 0),
                        "can_send": bool(leg_previews.get("can_send")),
                        "block_reason": str(leg_previews.get("block_reason") or ""),
                        "resources": None,
                    }
                )
    elif mode == "distribute":
        target_ids = [int(x) for x in (data.get("target_planet_ids") or [])]
        resources_mode = str(data.get("resources_mode") or "equal").strip().lower()
        planet_rows = _logistics_planet_rows(conn, [origin_id, *target_ids])
        route_ok, route_reason, route_legs, delivered_total = build_distribute_route(
            origin_planet_id=origin_id,
            target_planet_ids=target_ids,
            planet_rows_by_id=planet_rows,
            ships=ships,
            resources=data.get("resources"),
            resources_mode=resources_mode,
            target_resources=data.get("target_resources"),
            free_fleet_slots=int(slots["free"]),
            player_id=int(user_id),
            conn=conn,
        )
        if route_ok and route_legs:
            origin_row = planet_rows.get(origin_id) or dict(planet)
            for leg in route_legs:
                cargo = calculate_loaded_resources(leg.get("resources"))
                leg_previews = build_fleet_send_preview(
                    player_id=int(user_id),
                    origin_planet=origin_row,
                    target_galaxy=int(leg["galaxy"]),
                    target_system=int(leg["system"]),
                    target_position=int(leg["position"]),
                    mission_type="transport",
                    ships=leg["ships"],
                    resources=cargo,
                    speed_percent=speed_percent,
                    conn=conn,
                )
                prow = planet_rows.get(int(leg["planet_id"])) or {}
                legs.append(
                    {
                        "planet_id": int(leg["planet_id"]),
                        "name": str(prow.get("name") or ""),
                        "coordinates": format_coordinates(
                            int(leg["galaxy"]),
                            int(leg["system"]),
                            int(leg["position"]),
                        ),
                        "flight_seconds": int(leg_previews.get("flight_seconds") or 0),
                        "cargo_total": int(leg_previews.get("cargo_total") or 0),
                        "cargo_used": int(leg_previews.get("cargo_used") or 0),
                        "cargo_free": int(leg_previews.get("cargo_free") or 0),
                        "fuel_cost": int(leg_previews.get("fuel_cost") or 0),
                        "can_send": bool(leg_previews.get("can_send")),
                        "block_reason": str(leg_previews.get("block_reason") or ""),
                        "resources": cargo,
                    }
                )
    else:
        base["block_reason"] = "invalid_logistics_mode"
        return base

    if not route_ok or not legs:
        base["block_reason"] = route_reason or "no_deliverable_resources"
        return base

    targets_selected = 0
    if mode == "collect":
        targets_selected = len([int(x) for x in (data.get("source_planet_ids") or [])])
    elif mode == "distribute":
        targets_selected = len([int(x) for x in (data.get("target_planet_ids") or [])])
    targets_launching = len(legs)
    targets_skipped = max(0, int(targets_selected) - int(targets_launching))

    max_flight = max(int(x.get("flight_seconds") or 0) for x in legs)
    total_fuel = sum(int(x.get("fuel_cost") or 0) for x in legs)
    cargo_total = sum(int(x.get("cargo_total") or 0) for x in legs)
    cargo_used = sum(int(x.get("cargo_used") or 0) for x in legs)
    slots_needed = len(legs)
    block_reason = route_reason or ""
    can_launch = int(slots.get("free") or 0) > 0 and slots_needed > 0
    for leg in legs:
        if not leg.get("can_send"):
            can_launch = False
            if not block_reason:
                block_reason = str(leg.get("block_reason") or "generic")
    if int(slots.get("free") or 0) <= 0:
        can_launch = False
        if not block_reason:
            block_reason = "fleet_slots_full"

    base.update(
        {
            "can_launch": can_launch,
            "block_reason": block_reason,
            "slots_needed": slots_needed,
            "targets_selected": targets_selected,
            "targets_launching": targets_launching,
            "targets_skipped": targets_skipped,
            "slots_capped": targets_skipped > 0,
            "max_flight_seconds": max_flight,
            "total_fuel_cost": total_fuel,
            "cargo_total": cargo_total,
            "cargo_used": cargo_used,
            "cargo_free": max(0, cargo_total - cargo_used),
            "legs": legs,
            "delivered_total": delivered_total,
        }
    )
    return base


@app.route("/api/fleet/logistics/preview", methods=["POST"])
@require_login
def api_fleet_logistics_preview():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    conn = db()
    try:
        preview = _build_logistics_preview(user_id=user_id, data=data, conn=conn)
        return jsonify(fleet_ok({"preview": preview}, message_key="fleet_logistics_preview_ok"))
    finally:
        conn.close()


@app.route("/api/fleet/logistics/collect", methods=["POST"])
@require_login
def api_fleet_logistics_collect():
    from game.fleet import collect_resources, fleet_schema_ready
    from game.fleet_calc import normalize_ships

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "state": {}}), 401
    if not fleet_schema_ready(db()):
        return _action_json_response(
            False, "fleet_unavailable", finish_source="api_fleet_logistics_collect"
        ), 503

    data = request.get_json(silent=True) or {}
    ships = normalize_ships(data.get("ships") or {})
    if not ships and data.get("ships"):
        return _action_json_response(
            False, "unknown_ship", finish_source="api_fleet_logistics_collect"
        ), 400
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    def _collect(conn):
        return collect_resources(
            player_id=user_id,
            target_planet_id=int(data.get("target_planet_id") or 0),
            source_planet_ids=[int(x) for x in (data.get("source_planet_ids") or [])],
            ships=ships,
            resources_mode=str(data.get("resources_mode") or "all"),
            resources=data.get("resources"),
            ships_selection_mode=str(data.get("ships_selection_mode") or "manual"),
            preset_id=int(data["preset_id"]) if data.get("preset_id") else None,
            speed_percent=speed_percent,
            conn=conn,
        )

    ok, reason, result = _fleet_write_transaction(_collect)
    resp = _action_json_response(
        ok,
        reason or ("fleet_logistics_collect_ok" if ok else "generic"),
        payload=result if not ok else None,
        job=result if ok else None,
        finish_source="api_fleet_logistics_collect",
    )
    body = resp.get_json()
    if isinstance(body, dict):
        if ok and result is not None:
            body["data"] = result
        elif not ok and result is not None:
            body["data"] = result
    out = jsonify(body)
    if request_id and isinstance(body, dict):
        save_idempotent_action(user_id, request_id, body)
    if not ok:
        return out, 400
    return out


@app.route("/api/fleet/logistics/distribute", methods=["POST"])
@require_login
def api_fleet_logistics_distribute():
    from game.fleet import distribute_resources, fleet_schema_ready
    from game.fleet_calc import normalize_ships

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "state": {}}), 401
    if not fleet_schema_ready(db()):
        return _action_json_response(
            False, "fleet_unavailable", finish_source="api_fleet_logistics_distribute"
        ), 503

    data = request.get_json(silent=True) or {}
    ships = normalize_ships(data.get("ships") or {})
    if not ships and data.get("ships"):
        return _action_json_response(
            False, "unknown_ship", finish_source="api_fleet_logistics_distribute"
        ), 400
    try:
        speed_percent = int(data.get("speed_percent") or 100)
    except (TypeError, ValueError):
        speed_percent = 100

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    def _distribute(conn):
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(user_id, conn=conn)
        origin_id = int(data.get("origin_planet_id") or planet["id"])
        return distribute_resources(
            player_id=user_id,
            origin_planet_id=origin_id,
            target_planet_ids=[int(x) for x in (data.get("target_planet_ids") or [])],
            ships=ships,
            resources_mode=str(data.get("resources_mode") or "equal"),
            resources=data.get("resources"),
            target_resources=data.get("target_resources"),
            ships_selection_mode=str(data.get("ships_selection_mode") or "manual"),
            preset_id=int(data["preset_id"]) if data.get("preset_id") else None,
            speed_percent=speed_percent,
            conn=conn,
        )

    ok, reason, result = _fleet_write_transaction(_distribute)
    resp = _action_json_response(
        ok,
        reason or ("fleet_logistics_distribute_ok" if ok else "generic"),
        payload=result if not ok else None,
        job=result if ok else None,
        finish_source="api_fleet_logistics_distribute",
    )
    body = resp.get_json()
    if isinstance(body, dict):
        if ok and result is not None:
            body["data"] = result
        elif not ok and result is not None:
            body["data"] = result
    out = jsonify(body)
    if request_id and isinstance(body, dict):
        save_idempotent_action(user_id, request_id, body)
    if not ok:
        return out, 400
    return out


@app.route("/api/fleet/mass-expedition", methods=["POST"])
@require_login
def api_fleet_mass_expedition():
    from game.fleet import fleet_schema_ready, mass_expedition
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}

    def _mass_expo(conn):
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(user_id, conn=conn)
        origin_id = int(data.get("origin_planet_id") or planet["id"])
        return mass_expedition(
            player_id=user_id,
            origin_planet_id=origin_id,
            preset_id=int(data.get("preset_id") or 0),
            waves=int(data.get("waves") or 1),
            target_slots=int(data["target_slots"]) if data.get("target_slots") is not None else None,
            speed_percent=int(data["speed_percent"]) if data.get("speed_percent") is not None else None,
            conn=conn,
        )

    ok, reason, result = _fleet_write_transaction(_mass_expo)

    if ok and result:
        return jsonify(fleet_ok(result, message_key="fleet_mass_expo_success"))
    return jsonify(fleet_err(reason)), 400


@app.route("/api/admin/planet/<int:planet_id>/ships", methods=["POST"])
@require_admin_api
def api_admin_planet_ships(planet_id: int):
    from game.fleet import fleet_schema_ready, seed_planet_ships_stack
    from game.fleet_api import fleet_err, fleet_ok

    if not fleet_schema_ready(db()):
        return _admin_json(fleet_err("fleet_unavailable"))

    data = _admin_body()

    def _seed(conn):
        cur = conn.cursor()
        cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            return False, "planet_not_found", None
        owner_id = int(row["player_id"])
        return seed_planet_ships_stack(
            int(planet_id),
            owner_id,
            ships=data.get("ships"),
            replace=bool(data.get("replace")),
            conn=conn,
        )

    ok, reason, ships = _fleet_write_transaction(_seed)

    if ok:
        return _admin_json(fleet_ok({"ships": ships, "planet_id": planet_id}, message_key="fleet_dev_seed_ok"))
    return _admin_json(fleet_err(reason))


@app.route("/api/buildings/<building_type>/technical-data")
@require_login
def api_building_technical_data(building_type: str):
    from game.buildings import build_building_technical_data

    user_id = int(session.get("user_id") or 0)
    conn = db()
    try:
        data, err = build_building_technical_data(building_type, user_id=user_id, conn=conn)
    finally:
        conn.close()
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": data})


@app.route("/api/research/<tech_key>/technical-data")
@require_login
def api_research_technical_data(tech_key: str):
    from game.research import build_research_technical_data

    user_id = int(session.get("user_id") or 0)
    conn = db()
    try:
        data, err = build_research_technical_data(tech_key, user_id=user_id, conn=conn)
    finally:
        conn.close()
    if err:
        return jsonify({"ok": False, "error": err}), 404
    return jsonify({"ok": True, "data": data})


@app.route("/api/buildings/upgrade", methods=["POST"])
@require_login
def api_buildings_upgrade():
    from game.live_state import start_action_perf

    perf = start_action_perf("/api/buildings/upgrade")
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
            if perf is not None:
                from game.live_state import finish_action_perf, is_action_perf_debug_enabled

                if is_action_perf_debug_enabled():
                    import json as _json

                    cached = dict(cached)
                    perf_data = finish_action_perf(
                        response_bytes=len(_json.dumps(cached, separators=(",", ":")).encode("utf-8"))
                    )
                    if perf_data is not None:
                        cached["_action_perf"] = {**perf_data, "cached": True}
            return jsonify(cached)

    ok, reason, extra = queue_build(player_view, buildings, building_type, queue_mode=_queue_mode(data))
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_buildings_upgrade",
        include_panel=False,
        panel_delta_keys=[building_type] if building_type else None,
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
    delta_keys: Optional[List[str]] = None
    if isinstance(extra, dict):
        bt = str(extra.get("building_type") or "").strip()
        if bt:
            delta_keys = [bt]
    return _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_buildings_cancel",
        include_panel=False,
        panel_delta_keys=delta_keys,
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

    ok, reason, extra = queue_research(player_view, tech_key, queue_mode=_queue_mode(data))
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
    from game.planet_evolution.service import get_planet_state_payload
    from game.planet_evolution.repository import get_active_planet_id

    conn = db()
    planet_state: Dict[str, Any] = {"ok": False, "error": "unavailable"}
    try:
        try:
            active_id = get_active_planet_id(user_id, conn=conn)
            planet_state = get_planet_state_payload(active_id, player_id=user_id, conn=conn)
            commit(conn)
        except sqlite3.OperationalError:
            rollback(conn)
            logger.warning(
                "planet evolution state skipped (database locked) user_id=%s",
                user_id,
                exc_info=True,
            )
            planet_state = {"ok": False, "error": "database_locked", "locked": True}
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return render_template(
        "planet_evolution.html",
        player=ctx["player_view"],
        planet_state=planet_state,
        build_queue=ctx["build_queue"],
        research_status=ctx["research"],
    )


@app.route("/api/planets")
@require_login
def api_planets_list():
    user_id = int(session["user_id"])
    from game.planet_evolution.service import list_player_planets_for_switcher

    return jsonify({"ok": True, "planets": list_player_planets_for_switcher(user_id)})


@app.route("/api/planets/active", methods=["POST"])
@require_login
def api_planets_set_active():
    data = request.get_json(silent=True) or {}
    try:
        planet_id = int(data.get("planet_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_planet_id"}), 400
    from game.planet_evolution.service import set_active_planet

    user_id = int(session["user_id"])
    ok, reason = set_active_planet(user_id, planet_id)
    state, _ = _build_game_state_payload(
        include_panel=False,
        finish_source="api_planets_active",
        action_slim=True,
    )
    planets = None
    if ok:
        from game.galaxy import sync_galaxy_view_session_for_planet
        from game.planet_evolution.repository import get_context_planet

        sync_galaxy_view_session_for_planet(session, get_context_planet(user_id))
        from game.planet_evolution.service import list_player_planets_for_switcher

        planets = list_player_planets_for_switcher(user_id)
    return jsonify({"ok": ok, "reason": reason, "state": state, "planets": planets})


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
    if is_production():
        flash(
            T("admin_wipe_deprecated")
            or "Legacy-Wipe ist in Production deaktiviert. Nutze „Universum resetten“ im Admin Panel.",
            "error",
        )
        return redirect(url_for("admin_panel"))
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


@app.route("/api/admin/player/<int:player_id>/delete", methods=["POST"])
@require_admin_api
def api_admin_player_delete(player_id: int):
    return _admin_json(admin_api_logic.delete_player_api(_admin_actor_id(), player_id, _admin_body()))


@app.route("/api/admin/player/<int:player_id>/resources", methods=["POST"])
@require_admin_api
def api_admin_player_resources(player_id: int):
    return _admin_json(admin_api_logic.set_player_resources(_admin_actor_id(), player_id, _admin_body()))


@app.route("/api/admin/player/<int:player_id>/repair-homeworld", methods=["POST"])
@require_admin_api
def api_admin_player_repair_homeworld(player_id: int):
    return _admin_json(admin_api_logic.repair_homeworld(_admin_actor_id(), player_id))


@app.route("/api/admin/inventory/catalog", methods=["GET"])
@require_admin_api
def api_admin_inventory_catalog():
    return _admin_json(admin_api_logic.inventory_admin_catalog())


@app.route("/api/admin/player/<int:player_id>/inventory-grant", methods=["POST"])
@require_admin_api
def api_admin_player_inventory_grant(player_id: int):
    return _admin_json(
        admin_api_logic.grant_player_inventory(_admin_actor_id(), player_id, _admin_body())
    )


@app.route("/api/admin/inventory/grant-all", methods=["POST"])
@require_admin_api
def api_admin_inventory_grant_all():
    return _admin_json(
        admin_api_logic.grant_inventory_all_players(_admin_actor_id(), _admin_body())
    )


@app.route("/api/admin/lootboxes/state", methods=["GET"])
@require_admin_api
def api_admin_lootboxes_state():
    return _admin_json(admin_api_logic.lootboxes_admin_state())


@app.route("/api/admin/lootboxes/pools/save", methods=["POST"])
@require_admin_api
def api_admin_lootboxes_pools_save():
    return _admin_json(admin_api_logic.save_lootbox_pool(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/lootboxes/pools/reset", methods=["POST"])
@require_admin_api
def api_admin_lootboxes_pools_reset():
    return _admin_json(admin_api_logic.reset_lootbox_pool(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/lootboxes/grant-all", methods=["POST"])
@require_admin_api
def api_admin_lootboxes_grant_all():
    return _admin_json(
        admin_api_logic.grant_inventory_all_players(_admin_actor_id(), _admin_body())
    )


@app.route("/api/admin/lootboxes/grant-player", methods=["POST"])
@require_admin_api
def api_admin_lootboxes_grant_player():
    body = _admin_body()
    try:
        player_id = int(body.get("player_id") or 0)
    except (TypeError, ValueError):
        player_id = 0
    return _admin_json(
        admin_api_logic.grant_player_inventory(_admin_actor_id(), player_id, body)
    )


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


@app.route("/api/admin/fleets", methods=["GET"])
@require_admin_api
def api_admin_fleets():
    filters = {
        "player_id": request.args.get("player_id"),
        "status": request.args.get("status", "all"),
        "limit": request.args.get("limit", 100),
    }
    return _admin_json(admin_api_logic.get_admin_fleets(filters))


@app.route("/api/admin/fleet/<int:movement_id>/advance", methods=["POST"])
@require_admin_api
def api_admin_fleet_advance(movement_id: int):
    return _admin_json(
        admin_api_logic.advance_admin_fleet(_admin_actor_id(), movement_id, _admin_body())
    )


@app.route("/api/admin/galactic-diplomacy/<int:galaxy>", methods=["GET"])
@require_admin_api
def api_admin_galactic_diplomacy_get(galaxy: int):
    return _admin_json(admin_api_logic.api_get_galactic_diplomacy_state(galaxy))


@app.route("/api/admin/galactic-diplomacy/<int:galaxy>/personality", methods=["POST"])
@require_admin_api
def api_admin_galactic_diplomacy_personality(galaxy: int):
    return _admin_json(
        admin_api_logic.api_set_galactic_diplomacy_personality(
            _admin_actor_id(),
            galaxy,
            _admin_body(),
        )
    )


@app.route("/api/admin/galactic-diplomacy/<int:galaxy>/resolution", methods=["POST"])
@require_admin_api
def api_admin_galactic_diplomacy_resolution(galaxy: int):
    return _admin_json(
        admin_api_logic.api_set_galactic_diplomacy_resolution(
            _admin_actor_id(),
            galaxy,
            _admin_body(),
        )
    )


@app.route("/api/admin/galactic-diplomacy/<int:galaxy>/emergency", methods=["POST"])
@require_admin_api
def api_admin_galactic_diplomacy_emergency(galaxy: int):
    return _admin_json(
        admin_api_logic.api_set_galactic_diplomacy_emergency(
            _admin_actor_id(),
            galaxy,
            _admin_body(),
        )
    )


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
    threaded_raw = os.environ.get("GC_FLASK_THREADED", "1" if not is_production() else "0").strip().lower()
    threaded = threaded_raw in ("1", "true", "yes", "on")
    app.run(host=host, port=port, debug=is_debug_enabled(), threaded=threaded)
