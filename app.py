import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import timedelta
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
    expire_browser_session_cookies,
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
from game.universe_search import SEARCH_TYPES, search_universe

from game import playercard as playercard_logic
from game import chat as chat_logic
from game import support as support_logic
from game import messages as messages_logic
from game import options as options_logic
from game import account_email as account_email_logic
from game import discord_auth as discord_auth_logic

from game.bootstrap import bootstrap_application
from game.config import get_secret_key, is_debug_enabled, is_production, session_cookie_domain
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

from flask_sock import Sock

sock = Sock(app)

from game.db import DbPoolTimeout


@app.errorhandler(DbPoolTimeout)
def handle_db_pool_timeout(exc):
    """Pool exhausted — 503, not a fake 'postgres not configured' 500."""
    app.logger.warning("db pool timeout: %s", exc)
    wants_json = (
        str(request.path or "").startswith("/api/")
        or "application/json" in (request.headers.get("Accept") or "")
        or request.is_json
    )
    if wants_json:
        return jsonify({"ok": False, "error": "db_busy", "retry": True}), 503
    return ("Service temporarily busy. Please retry.", 503, {"Content-Type": "text/plain; charset=utf-8"})



def ws_long_lived_safe() -> bool:
    """GC-AST-LIVE: can this process hold a long-lived WS connection open
    without starving every other request?

    Explicit override (set in the local __main__ dev-server block below,
    based on the actual threaded= flag Werkzeug is running with) always
    wins. Otherwise — i.e. under gunicorn — only gevent/eventlet workers
    multiplex connections via greenlets, so only those are safe for galaxy
    live push. Default production worker is gthread (GC-PROD-SQLITE-STALL-001)
    so this returns False and the WS route refuses the socket; the client
    already degrades to existing polling. That beats freezing /healthz when
    sync sqlite3 blocks a single gevent loop.
    """
    override = app.config.get("GC_WS_LONG_LIVED_SAFE")
    if override is not None:
        return bool(override)
    worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread").strip().lower()
    return worker_class in ("gevent", "eventlet")


BASE_DIR = Path(__file__).resolve().parent
LOCALES_DIR = BASE_DIR / "locales"
VERSION_FILE = BASE_DIR / "VERSION"


def get_asset_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "dev"
    except Exception:
        return "dev"


def versioned_static_url(endpoint: str, **values):
    """``url_for`` for static assets with cache-busting ``v=`` (immutable Cache-Control)."""
    if endpoint == "static" and "v" not in values:
        values["v"] = get_asset_version()
    return url_for(endpoint, **values)


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
    """Set Cache-Control on raster files under /static/ (versioned URLs may be immutable)."""
    if response.status_code not in (200, 304):
        return response
    if not _is_static_image_path(request.path or ""):
        return response
    if request.args.get("v"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers["Cache-Control"] = f"public, max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}"
    return response


BACKGROUND_CLASSES = ["bg-1", "bg-2", "bg-3", "bg-4"]
GC_LOCALE = "de"

from game.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LANGUAGES,
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


@app.template_filter("fmt_duration")
def fmt_duration_filter(value, max_parts: int = 3):
    """Human duration: y / mo / w / d / h / min / s (canonical game calendar)."""
    from game.time_format import format_duration_human

    return format_duration_human(value, max_parts=int(max_parts or 3))


@app.template_filter("webp_static")
def webp_static_filter(url: str) -> str:
    """GC-555 — sibling WebP URL for a static raster asset URL.

    Preserves query strings (e.g. ``?v=`` cache bust) after the extension swap.
    """
    text = str(url or "").strip()
    if not text or "." not in text:
        return text
    path, sep, query = text.partition("?")
    base, dot, ext = path.rpartition(".")
    if not dot or ext.lower() not in ("png", "jpg", "jpeg"):
        return text
    out = f"{base}.webp"
    return f"{out}?{query}" if sep else out


@app.template_filter("rules_md")
def rules_md_filter(text: str) -> Markup:
    """Minimal markdown for rules panel bodies (**bold**, paragraphs)."""
    raw = str(text or "").strip()
    if not raw:
        return Markup("")
    parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    html_parts: list[str] = []
    for part in parts:
        s = escape(part)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = s.replace("\n", "<br>")
        html_parts.append(f"<p>{s}</p>")
    return Markup("".join(html_parts))


@app.template_global()
def player_name_link(
    player_id,
    name=None,
    extra_class: str = "",
    enable_card: bool = True,
    name_style=None,
) -> Markup:
    """
    Standard clickable player name for PlayerCard (PJAX-safe markup).

    Usage: {{ player_name_link(row.player_id, row.nickname) }}
    Optional name_style: equipped style key, or None to look up.
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
    style_key = "none"
    try:
        from game.playercard import get_equipped_name_style, validate_name_style

        if name_style is None:
            style_key = get_equipped_name_style(pid)
        else:
            style_key = validate_name_style(name_style)
    except Exception:
        style_key = "none"
    classes = ["gc-player-name"]
    if extra_class:
        classes.append(str(extra_class).strip())
    attrs = [
        f'class="{" ".join(classes)}"',
        f'data-player-id="{pid}"',
        f'data-player-name="{lookup_attr}"',
        f'data-name-style="{escape(style_key)}"',
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
    from game.live_state import start_request_perf

    try:
        start_request_perf(
            method=str(request.method or ""),
            endpoint=str(request.endpoint or ""),
            path=str(request.path or ""),
        )
    except Exception:
        pass
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


_FLEET_TICK_SKIP_ENDPOINTS = frozenset(
    {
        "static",
        "api_game_state",
        "api_notifications_summary",
        # GC-PERF-FLEET-SEND: mutation RTT must not wait on global fleet tick
        "api_fleet_send",
        "api_fleet_bulk_launch_presets",
        "api_fleet_recall",
        "api_fleet_mass_expedition",
        "api_fleet_mass_expedition_preview",
        # GC-PERF-PLANET-SWITCH-003: switch RTT must not wait on global fleet tick
        "api_planets_set_active",
    }
)
_FLEET_TICK_SKIP_PREFIXES = ("api_admin_", "api_chat_")


def _should_run_fleet_tick_before_request() -> bool:
    """Skip high-frequency polls and admin/chat APIs — avoids SQLite writer pile-up on local dev.

    GC-PERF-PROD-003: when the maintenance sidecar owns the bag
    (``GC_MAINTENANCE_WORKER=1``), never piggyback fleet/account-deletion work
    on HTTP — concurrent writers + ``busy_timeout=20000`` freeze navigation.
    """
    try:
        from game.config import is_maintenance_worker_sidecar_enabled

        if is_maintenance_worker_sidecar_enabled():
            return False
    except Exception:
        pass
    endpoint = str(request.endpoint or "")
    if endpoint in _FLEET_TICK_SKIP_ENDPOINTS:
        return False
    if any(endpoint.startswith(prefix) for prefix in _FLEET_TICK_SKIP_PREFIXES):
        return False
    return session.get("user_id") is not None


@app.before_request
def _fleet_tick_before_authenticated_request():
    """Isolated fleet tick before SSR routes open a long-lived page connection.

    Legacy fallback when the maintenance sidecar is off; production docker
    entrypoint keeps this path idle (GC-PERF-PROD-003).
    """
    try:
        if _should_run_fleet_tick_before_request():
            ft0 = time.perf_counter()
            try:
                from game.fleet_worker import maybe_run_global_fleet_tick
                from game.live_state import record_request_perf_phase, set_request_perf_meta

                endpoint = str(request.endpoint or "request")
                set_request_perf_meta("fleet_tick_source", endpoint)
                result = maybe_run_global_fleet_tick(force=False, source=endpoint)
                record_request_perf_phase(
                    "fleet_tick_ms", (time.perf_counter() - ft0) * 1000.0
                )
                if isinstance(result, dict):
                    ran = 0 if result.get("skipped_interval") else 1
                    set_request_perf_meta("fleet_tick_ran", ran)
                ad0 = time.perf_counter()
                from game.options import maybe_run_due_account_deletions

                ad_result = maybe_run_due_account_deletions(force=False, source=endpoint)
                record_request_perf_phase(
                    "account_deletion_worker_ms", (time.perf_counter() - ad0) * 1000.0
                )
                if isinstance(ad_result, dict) and ad_result.get("count"):
                    set_request_perf_meta(
                        "account_deletions_ran", int(ad_result.get("count") or 0)
                    )
            except Exception:
                logger.exception(
                    "before_request fleet tick failed endpoint=%s", request.endpoint
                )
    finally:
        # GC-PERF-PROD-001: wall split before_request → handler (even when tick skipped).
        try:
            from game.live_state import mark_request_perf_enter_handler

            mark_request_perf_enter_handler()
        except Exception:
            pass
    return None


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
    """Auth/landing pages use the simple shell. Legal is simple only for guests —
    logged-in players keep the ingame shell + identity theme."""
    from flask import request, session

    ep = str(request.endpoint or "")
    if ep == "legal_view":
        return not bool(session.get("user_id"))
    return ep in _SIMPLE_LAYOUT_ENDPOINTS


def _is_lightweight_layout_request() -> bool:
    """Auth/landing pages and PJAX fragment fetches — shell globals are unused client-side."""
    return _is_simple_layout_request() or _is_pjax_request()


def _is_landing_request() -> bool:
    from flask import request

    return str(request.endpoint or "") == "landing"


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

    world_boss_active = False
    world_boss_count = 0
    try:
        if not simple_layout:
            # GC-PERF-OVERVIEW-TTFB-001: reuse stash from page live_context when present.
            from flask import g as _flask_g

            _wb_cached_count = getattr(_flask_g, "gc_world_boss_count", None)
            if _wb_cached_count is not None:
                world_boss_count = int(_wb_cached_count or 0)
                world_boss_active = bool(getattr(_flask_g, "gc_world_boss_active", world_boss_count > 0))
            else:
                from game.db import db as _wb_db
                from game.world_boss import list_active_events

                _wb_conn = _wb_db()
                try:
                    _wb_list = list_active_events(conn=_wb_conn, limit=10)
                    world_boss_count = len(_wb_list)
                    world_boss_active = world_boss_count > 0
                finally:
                    _wb_conn.close()
    except Exception:
        world_boss_active = False
        world_boss_count = 0

    sidebar_release = {"label": "Genesis", "url": "/news", "href": "/news", "anchor_id": "", "has_dev_stream": False}
    try:
        if not simple_layout:
            from game.universe_news import sidebar_release_nav

            sidebar_release = sidebar_release_nav()
    except Exception:
        pass

    # stats (safe) — skip on auth pages; landing still shows universe online/total
    try:
        if _is_landing_request() or not simple_layout:
            player_stats = get_player_stats() or {}
    except Exception:
        player_stats = {}

    # score + rank (header/sidebar) – shell only; skip on PJAX/auth (GC-PERF-PJAX-CTX-SHELL-001)
    try:
        user_id = session.get("user_id")
        if user_id is not None and not simple_layout:
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
    header_planet_limit: dict[str, Any] | None = None
    try:
        user_id = session.get("user_id")
        if user_id is not None and not simple_layout:
            from game.planet_evolution.service import list_player_planets_for_switcher
            from game.planet_visuals import apply_herocard_urls_to_switcher_planets

            header_planets = apply_herocard_urls_to_switcher_planets(
                list_player_planets_for_switcher(int(user_id)),
                versioned_static_url,
            )
            for row in header_planets:
                if row.get("is_active"):
                    header_active_planet = row
                    break
            if header_active_planet is None and header_planets:
                header_active_planet = header_planets[0]
            try:
                from game.logic import get_planet_limit_block

                header_planet_limit = get_planet_limit_block(int(user_id))
            except Exception:
                header_planet_limit = None
    except Exception:
        header_planets = []
        header_active_planet = None
        header_planet_limit = None

    current_planet_landscape_url = None
    current_planet_landscape_webp_url = None
    try:
        user_id = session.get("user_id")
        if user_id is not None and not simple_layout:
            from game.planet_visuals import (
                DEFAULT_HEROCARD,
                landscape_static_relpath,
                raster_webp_relpath,
            )

            pos = (header_active_planet or {}).get("position")
            try:
                pos_i = int(pos) if pos is not None and pos != "" else 0
            except (TypeError, ValueError):
                pos_i = 0
            landscape_rel = (
                landscape_static_relpath(pos_i) if pos_i else f"img/herocards/{DEFAULT_HEROCARD}"
            )
            current_planet_landscape_url = versioned_static_url("static", filename=landscape_rel)
            current_planet_landscape_webp_url = versioned_static_url(
                "static", filename=raster_webp_relpath(landscape_rel)
            )
    except Exception:
        current_planet_landscape_url = None
        current_planet_landscape_webp_url = None

    from game.config import get_client_runtime_config, is_command_map_dev_mode
    from game.options import get_notify_sound_settings, get_spy_probe_settings
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

    codex_panel: dict[str, Any] = {"bands": []}
    codex_commander_tip: dict[str, str] | None = None
    codex_primary: str | None = None
    codex_client: dict[str, Any] = {"articles": {}}
    try:
        if auth_user and auth_user.get("id"):
            from flask import request

            from game.codex import build_codex_template_context

            _codex_conn = db()
            try:
                _codex_ctx = build_codex_template_context(
                    int(auth_user["id"]),
                    str(request.endpoint or ""),
                    conn=_codex_conn,
                )
                codex_panel = _codex_ctx["CODEX_PANEL"]
                codex_commander_tip = _codex_ctx["CODEX_COMMANDER_TIP"]
                codex_primary = _codex_ctx["CODEX_PRIMARY"]
                codex_client = _codex_ctx["CODEX_CLIENT"]
                _codex_conn.commit()
            finally:
                _codex_conn.close()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("[GC CODEX] template context failed")

    rules_panel_ctx: dict[str, Any] = {
        "RULES_PANEL_SECTIONS": (),
        "RULES_PANEL_FAQ": (),
        "RULES_PANEL_INTRO_KEY": "rules_panel_intro",
        "RULES_PANEL_FAQ_TITLE_KEY": "rules_panel_faq_title",
        "RULES_PANEL_VERSION_KEY": "rules_panel_version",
        "RULES_PANEL_SUPPORT_CTA_KEY": "rules_panel_support_cta",
    }
    try:
        from game.game_rules_panel import rules_panel_template_context

        rules_panel_ctx = rules_panel_template_context()
    except Exception:
        pass

    legal_panel_ctx: dict[str, Any] = {
        "LEGAL_DOCS": (),
        "LEGAL_TEXT_VERSION": "v1",
        "LEGAL_STAND": "",
        "LEGAL_OPERATOR_NAME": "",
        "LEGAL_OPERATOR_STREET": "",
        "LEGAL_OPERATOR_POSTAL": "",
        "LEGAL_OPERATOR_CITY": "",
        "LEGAL_OPERATOR_COUNTRY": "",
        "LEGAL_OPERATOR_EMAIL": "",
        "LEGAL_OPERATOR_ADDRESS_LINE": "",
    }
    try:
        from game.legal_panel import legal_panel_template_context

        legal_panel_ctx = legal_panel_template_context()
    except Exception:
        pass

    client_runtime_config = {
        **get_client_runtime_config(),
        "asset_version": get_asset_version(),
    }
    try:
        if auth_user and auth_user.get("id"):
            from game.options import get_buildings_ui_settings

            client_runtime_config = {
                **client_runtime_config,
                **get_notify_sound_settings(int(auth_user["id"])),
                **get_spy_probe_settings(int(auth_user["id"])),
                **get_buildings_ui_settings(int(auth_user["id"])),
            }
    except Exception:
        pass

    header_active_boosters: dict[str, Any] = {"ready": False, "active": [], "active_effects": []}
    header_timekeeper: dict[str, Any] = {"ready": False, "balance_sec": 0, "label": "0min"}
    initiation_hud: dict[str, Any] = {
        "ready": False,
        "active": False,
        "completed": False,
        "step_index": 0,
        "step_count": 0,
        "progress": 0,
        "target": 0,
        "route": "",
        "title_key": "",
        "hint_key": "",
        "step_id": "",
        "phase_id": "",
    }
    # GC-INSTANT-UX-001A — slim shell HUD for first paint (fleet + unread); avoids deferred poll gap.
    header_hud_boot: dict[str, Any] = {
        "ok": True,
        "active_fleets": None,
        "fleet_alerts": {
            "incoming_attack_count": 0,
            "next_attack_arrival": None,
            "has_incoming_attack": False,
            "alert_key": "",
            "incoming_attacks": [],
        },
        "fleet_slots": {"active": 0, "max": 0, "free": 0},
        "unread_messages_count": 0,
        "latest_message_id": None,
    }
    try:
        if auth_user and auth_user.get("id") and not simple_layout:
            from game.fleet import FLEET_DRAWER_VISIBLE_LIMIT
            from game.inventory_boosters import build_inventory_boosters_state
            from game.live_state import fleet_hud_for_game_state
            from game import messages as messages_logic
            from game.timekeeper import serialize_for_client

            _boost_conn = db()
            try:
                uid = int(auth_user["id"])
                header_active_boosters = build_inventory_boosters_state(
                    uid,
                    conn=_boost_conn,
                    locale=active_locale,
                )
                header_timekeeper = serialize_for_client(uid, conn=_boost_conn)
                try:
                    from game.initiation.service import get_initiation_summary

                    initiation_hud = get_initiation_summary(uid, conn=_boost_conn, ensure=True)
                except Exception:
                    pass
                try:
                    header_hud_boot["unread_messages_count"] = int(
                        messages_logic.unread_count(uid, conn=_boost_conn, prepare=False) or 0
                    )
                    latest_mid = messages_logic.latest_inbox_message_id(
                        uid, conn=_boost_conn, prepare=False
                    )
                    header_hud_boot["latest_message_id"] = int(latest_mid) if latest_mid else None
                except Exception:
                    pass
                try:
                    from game.overview_page import build_overview_live_events

                    header_hud_boot["live_events"] = build_overview_live_events(
                        conn=_boost_conn,
                        user_id=uid,
                        locale=active_locale,
                    )
                except Exception:
                    header_hud_boot["live_events"] = []
                try:
                    # GC-PERF-OVERVIEW-TTFB-001: fleet HUD stashed on live_context conn.
                    from flask import g as _flask_g

                    fleet_hud = getattr(_flask_g, "gc_fleet_hud", None)
                    if fleet_hud is None:
                        fleet_hud = fleet_hud_for_game_state(uid, conn=_boost_conn)
                    if fleet_hud is not None:
                        header_hud_boot["active_fleets"] = fleet_hud.get("active_fleets") or {
                            "count": 0,
                            "active_fleet_count": 0,
                            "fleets_confirmed_empty": True,
                            "visible_limit": FLEET_DRAWER_VISIBLE_LIMIT,
                            "next_remaining_seconds": 0,
                            "items": [],
                        }
                        header_hud_boot["fleet_slots"] = fleet_hud.get("fleet_slots") or {
                            "active": 0,
                            "max": 0,
                            "free": 0,
                        }
                        header_hud_boot["fleet_alerts"] = fleet_hud.get("fleet_alerts") or header_hud_boot[
                            "fleet_alerts"
                        ]
                    else:
                        header_hud_boot["active_fleets"] = {
                            "count": 0,
                            "active_fleet_count": 0,
                            "fleets_confirmed_empty": True,
                            "visible_limit": FLEET_DRAWER_VISIBLE_LIMIT,
                            "next_remaining_seconds": 0,
                            "items": [],
                        }
                except Exception:
                    header_hud_boot["active_fleets"] = {
                        "count": 0,
                        "active_fleet_count": 0,
                        "fleets_confirmed_empty": True,
                        "visible_limit": FLEET_DRAWER_VISIBLE_LIMIT,
                        "next_remaining_seconds": 0,
                        "items": [],
                    }
            finally:
                _boost_conn.close()
    except Exception:
        pass

    identity_theme = "cyan"
    identity_aura = "none"
    identity_theme_rgb = "70, 229, 255"
    identity_theme_bg = "#040810"
    try:
        user_id = session.get("user_id")
        if user_id is not None and not simple_layout:
            from game.playercard import (
                get_equipped_identity,
                identity_theme_bg as _identity_theme_bg,
                identity_theme_rgb as _identity_theme_rgb,
            )

            identity_theme, identity_aura = get_equipped_identity(int(user_id))
            identity_theme_rgb = _identity_theme_rgb(identity_theme)
            identity_theme_bg = _identity_theme_bg(identity_theme)
    except Exception:
        identity_theme = "cyan"
        identity_aura = "none"
        identity_theme_rgb = "70, 229, 255"
        identity_theme_bg = "#040810"

    header_prod_per_hour = {}
    try:
        from flask import g as _flask_g

        raw_prod = getattr(_flask_g, "gc_prod_per_hour", None)
        if isinstance(raw_prod, dict):
            header_prod_per_hour = raw_prod
    except Exception:
        header_prod_per_hour = {}

    return dict(
        T=T,
        T_DATA=get_locale_dict(active_locale),
        GC_LOCALE=active_locale,
        SUPPORTED_LANGUAGES=SUPPORTED_LANGUAGES,
        GC_ASSET_VERSION=get_asset_version(),
        GC_CLIENT_CONFIG=client_runtime_config,
        player_name_link=player_name_link,
        CURRENT_PLAYER_ID=_current_player_id(),
        IDENTITY_THEME=identity_theme,
        IDENTITY_AURA=identity_aura,
        IDENTITY_THEME_RGB=identity_theme_rgb,
        IDENTITY_THEME_BG=identity_theme_bg,
        HEADER_PROD_PER_HOUR=header_prod_per_hour,

        AUTH_USER=auth_user,
        AUTH_ADMIN=auth_admin,
        GC_DEBUG_ENABLED=is_debug_enabled(),
        COMMAND_MAP_DEV_MODE=is_command_map_dev_mode(),

        GAME_SETTINGS=settings,
        motd_enabled=motd_enabled,
        motd_text=motd_text,
        motd_banner=motd_banner,
        WORLD_BOSS_ACTIVE=world_boss_active,
        WORLD_BOSS_COUNT=world_boss_count,
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
        HEADER_PLANET_LIMIT=header_planet_limit,
        HEADER_ACTIVE_BOOSTERS=header_active_boosters,
        HEADER_HUD_BOOT=header_hud_boot,
        TIMEKEEPER=header_timekeeper,
        initiation_hud=initiation_hud,
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

        CODEX_PANEL=codex_panel,
        CODEX_COMMANDER_TIP=codex_commander_tip,
        CODEX_PRIMARY=codex_primary,
        CODEX_CLIENT=codex_client,

        **rules_panel_ctx,
        **legal_panel_ctx,
    )


# --------------------------------------------------------------------------
# BOOTSTRAP (config, DB, migration guard)
# --------------------------------------------------------------------------

_skip_mig = os.environ.get("GC_SKIP_MIGRATION_CHECK", "0").strip().lower() in ("1", "true", "yes")
bootstrap_application(skip_migration_check=_skip_mig)

from game.player_changelog import register_player_changelog_routes
register_player_changelog_routes(app)

try:
    from game.internal_cron import start_embedded_cron_if_enabled

    start_embedded_cron_if_enabled()
except Exception:
    logger.exception("embedded maintenance cron failed to start")

_secret = get_secret_key()
if not _secret:
    # Dev: persist a stable local secret so Flask sessions survive process restarts.
    _dev_secret_path = Path(__file__).resolve().parent / ".gc_dev_secret"
    try:
        if _dev_secret_path.is_file():
            _secret = _dev_secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        _secret = ""
    if not _secret:
        _secret = (
            os.environ.get("GC_DEV_SECRET_KEY", "").strip()
            or "gc-dev-only-unstable-secret"
        )
        try:
            _dev_secret_path.write_text(_secret, encoding="utf-8")
        except OSError:
            pass
    if is_production():
        raise RuntimeError("SECRET_KEY must be set in production")
app.secret_key = _secret

_cookie_secure = session_cookie_secure_override()
if _cookie_secure is None:
    _cookie_secure = is_production()

_cookie_domain = session_cookie_domain()

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_cookie_secure,
    PERMANENT_SESSION_LIFETIME=timedelta(days=31),
    SESSION_REFRESH_EACH_REQUEST=True,
)
if _cookie_domain:
    app.config["SESSION_COOKIE_DOMAIN"] = _cookie_domain


@app.template_global()
def csrf_input() -> Markup:
    """Hidden input for HTML form CSRF (GC-SEC-P0)."""
    token = escape(generate_csrf_token())
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


def _session_cookie_secure() -> bool:
    return bool(app.config.get("SESSION_COOKIE_SECURE"))


@app.after_request
def _gc_security_headers(response):
    try:
        from game.live_state import mark_request_perf_enter_after

        mark_request_perf_enter_after()
    except Exception:
        pass
    secure = _session_cookie_secure() or bool(request.is_secure)
    response = apply_security_headers(response, secure=secure)
    response = apply_static_image_cache_headers(response)
    try:
        from game.live_state import finish_request_perf_after

        response = finish_request_perf_after(response)
    except Exception:
        pass
    return response


def _auth_form_error_key() -> Optional[str]:
    """Validate CSRF for public auth HTML forms. Returns locale error key or None."""
    if not validate_csrf_request(request, testing=bool(app.config.get("TESTING"))):
        return "msg_csrf_invalid"
    return None


@app.teardown_request
def _teardown_queue_finish_dedup(_exc=None):
    from game.queue_engine import clear_request_finish_dedup

    clear_request_finish_dedup()
    try:
        from game.effects import clear_effect_resolver_cache

        clear_effect_resolver_cache()
    except Exception:
        pass
    try:
        from game.live_state import finish_request_perf_teardown

        finish_request_perf_teardown(_exc)
    except Exception:
        pass


# --------------------------------------------------------------------------
# HEALTH
# --------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    """GC-PERF-PROD-001: cheap liveness — no DB/FS. Docker HEALTHCHECK target."""
    from game.health import build_liveness_report

    return jsonify(build_liveness_report()), 200


@app.route("/health")
def health():
    """Deep readiness (DB + migrations + volume). Railway deploy gate."""
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


@app.route("/api/internal/cron/fleet-tick", methods=["POST"])
def api_internal_cron_fleet_tick():
    """Token-gated global fleet tick — same DB as web (Railway SQLite cron)."""
    from game.internal_cron import handle_internal_cron_fleet_tick

    payload, status = handle_internal_cron_fleet_tick(request)
    return jsonify(payload), status


@app.route("/api/internal/cron/queue-tick", methods=["POST"])
def api_internal_cron_queue_tick():
    """Token-gated global queue finish — GC-PERF-WORKER-001 (same finish_due_work owner)."""
    from game.internal_cron import handle_internal_cron_queue_tick

    payload, status = handle_internal_cron_queue_tick(request)
    return jsonify(payload), status


@app.route("/api/internal/cron/galactic-directives", methods=["POST"])
def api_internal_cron_galactic_directives():
    """Token-gated galactic directive cycle resolve — GC-720I."""
    from game.internal_cron import handle_internal_cron_galactic_directives

    payload, status = handle_internal_cron_galactic_directives(request)
    return jsonify(payload), status


# --------------------------------------------------------------------------
# HELPER: Spieler-View + Ressourcen laden (conn-safe)
# --------------------------------------------------------------------------

def _load_player_view_with_resources(
    finish_source: str = "page_load",
) -> Tuple[Any, Dict[str, int], float, int, int, Dict[str, int]]:
    """
    Return:
      (player_view | None, buildings, ratio, energy_total, energy_used, storage_caps)

    Pass a named finish_source for Command Initiation visit_page credit (works on PJAX).
    """
    ctx = _load_page_live_context(finish_source=str(finish_source or "page_load"))
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


_BUILDINGS_PANEL_TABS = frozenset({"resources", "research", "military", "infrastructure"})

# GC-PERF-PANEL-SCOPE-002: action finish_source → page when client omitted panel_page.
# Unmapped / empty → no heavy catalogs (HUD + lightweight slices only).
_FINISH_SOURCE_PANEL_PAGE: Dict[str, str] = {
    "api_auction_house_bid": "auction_house",
    "api_auction_house_bid_fallback": "auction_house",
    "api_exchange": "trader_hub",
    "api_scrapyard": "trader_hub",
    "api_collector_exchange": "trader_hub",
    "api_fuel_exchange": "trader_hub",
    "api_defense_overview": "defense",
    "api_defense": "defense",
    "api_troops_train": "defense",
    "api_troops_cancel": "defense",
    "api_shipyard_build": "shipyard",
    "api_shipyard_queue_cancel": "shipyard",
    "api_buildings_upgrade": "buildings",
    "api_buildings_cancel": "buildings",
    "api_buildings_mine_evolve": "buildings",
    "api_research_start": "research",
    "api_research_cancel": "research",
    "research": "research",
    "techtree": "techtree",
    "buildings": "buildings",
    "shipyard": "shipyard",
    "defense": "defense",
    "overview": "overview",
    "api_world_boss_companion_mission": "overview",
    "api_world_boss_catch": "overview",
    "auction_house": "auction_house",
    "trader_hub": "trader_hub",
}


def _normalize_panel_page(panel_page: str) -> str:
    """Canonical panel_page token (underscore). ``other`` / empty → no heavy scope."""
    page = str(panel_page or "").strip().lower().replace("-", "_")
    if page in ("", "other"):
        return ""
    return page


def _resolve_effective_panel_page(panel_page: str, finish_source: str = "") -> str:
    """Explicit panel_page wins; else finish_source hint; else unscoped (no heavy)."""
    page = _normalize_panel_page(panel_page)
    if page:
        return page
    src = str(finish_source or "").strip().lower()
    return _normalize_panel_page(_FINISH_SOURCE_PANEL_PAGE.get(src, ""))


def _heavy_panels_for_page(panel_page: str) -> frozenset:
    """Which heavy catalogs to build for a resolved panel_page (SCOPE-002)."""
    page = _normalize_panel_page(panel_page)
    if not page:
        return frozenset()
    if page == "buildings":
        return frozenset({"buildings"})
    if page in ("research", "techtree"):
        return frozenset({"research"})
    if page == "defense":
        return frozenset({"defense"})
    if page == "shipyard":
        return frozenset({"shipyard"})
    if page == "trader_hub":
        return frozenset({"exchange", "scrapyard", "collector_exchange"})
    if page == "auction_house":
        return frozenset({"auction_house"})
    if page == "overview":
        return frozenset({"overview"})
    return frozenset()


def _resolve_game_state_panel_scope() -> Tuple[str, Optional[str]]:
    """Client panel_page / panel_tab for GC-PERF-PANEL-SCOPE (include_panel diet)."""
    page = _normalize_panel_page(
        request.args.get("panel_page") or request.headers.get("X-GC-Page") or ""
    )
    tab = str(request.args.get("panel_tab") or "").strip().lower()
    if tab not in _BUILDINGS_PANEL_TABS:
        tab = ""
    return page, (tab or None)


def _want_research_techs_for_panel(
    include_panel: bool,
    finish_source: str,
    panel_page: str = "",
) -> bool:
    """Full research catalog only on research/techtree (SSR source or scoped panel)."""
    src = str(finish_source or "")
    if src in ("research", "techtree"):
        return True
    if not include_panel:
        return False
    page = _resolve_effective_panel_page(panel_page, finish_source)
    return "research" in _heavy_panels_for_page(page)


def _load_page_live_context(
    *,
    finish_source: str = "page_load",
    include_panel: bool = False,
    panel_page: str = "",
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
    src = str(finish_source or "page_load")
    own_conn = conn is None
    resolved_panel_page = _normalize_panel_page(panel_page)
    try:
        from flask import has_request_context, request as flask_request
        from game.live_state import set_request_perf_meta

        if has_request_context():
            set_request_perf_meta("finish_source", src)
            set_request_perf_meta("route", str(flask_request.path or ""))
            if str(flask_request.headers.get("X-PJAX") or "").strip().lower() in ("1", "true", "yes"):
                set_request_perf_meta("pjax", 1)
            if not resolved_panel_page:
                resolved_panel_page = _normalize_panel_page(
                    flask_request.args.get("panel_page")
                    or flask_request.headers.get("X-GC-Page")
                    or ""
                )
    except Exception:
        pass
    if own_conn:
        conn = db()
    use_poll_live_path = _use_poll_live_path(src)
    use_planet_switch_live_path = src == "api_planets_active"
    try:
        try:
            wrote_live = False
            if use_planet_switch_live_path:
                # GC-PERF-PLANET-SWITCH-003: no empire finish / write TX on switch.
                from game.logic import read_player_live_state_for_planet_switch

                player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
                    read_player_live_state_for_planet_switch(user_id, conn=conn)
                )
            elif use_poll_live_path:
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
                wrote_live = True

            # Command Initiation visit_page must run on full loads AND PJAX HTML
            # navigations. Poll path skips finish_due_work for perf, but visit
            # credit is a small write and was previously dropped on every soft nav.
            from game.initiation.pages import should_record_page_visit
            from game.initiation.progress import maybe_record_page_visit_from_request

            try_visit = (not use_planet_switch_live_path) and should_record_page_visit(src)
            if try_visit:
                visit_recorded = False
                try:
                    from game.db import get_db_backend as _get_db_backend

                    use_sp = _get_db_backend() == "postgres"
                    if use_sp:
                        try:
                            conn.execute("SAVEPOINT gc_initiation_visit")
                        except Exception:
                            # Outer TX already aborted (e.g. lock timeout upstream).
                            try:
                                from game.db import rollback as _rollback_conn

                                _rollback_conn(conn)
                            except Exception:
                                pass
                            try_visit = False
                            wrote_live = False
                            use_sp = False
                    if try_visit:
                        maybe_record_page_visit_from_request(
                            user_id,
                            conn=conn,
                            finish_source=src,
                        )
                        visit_recorded = True
                        if use_sp:
                            try:
                                conn.execute("RELEASE SAVEPOINT gc_initiation_visit")
                            except Exception:
                                pass
                except Exception as visit_exc:
                    is_abort = "InFailedSqlTransaction" in type(visit_exc).__name__ or (
                        "current transaction is aborted" in str(visit_exc).lower()
                    )
                    if is_abort:
                        logger.warning(
                            "initiation page visit skipped (aborted TX) user_id=%s source=%s",
                            user_id,
                            src,
                        )
                    else:
                        logger.exception(
                            "initiation page visit failed user_id=%s source=%s",
                            user_id,
                            src,
                        )
                    try:
                        from game.db import get_db_backend as _get_db_backend2

                        if _get_db_backend2() == "postgres":
                            try:
                                conn.execute(
                                    "ROLLBACK TO SAVEPOINT gc_initiation_visit"
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        from game.db import rollback as _rollback_conn

                        _rollback_conn(conn)
                    except Exception:
                        pass
                    try_visit = False
                    wrote_live = False
                if not visit_recorded:
                    try_visit = False

            from game.live_state import (
                consume_request_poll_safety_net_write,
                get_request_context_planet,
                perf_span as _live_perf_span,
            )

            if wrote_live or try_visit or consume_request_poll_safety_net_write():
                commit(conn)
            from game.buildings import get_build_queue_status_for_planet

            planet = get_request_context_planet(user_id, conn=conn)
            # Full research catalog only for research SSR / scoped research panel.
            include_research_techs = _want_research_techs_for_panel(
                include_panel, src, resolved_panel_page
            )

            from game.models import get_research_levels

            with _live_perf_span("live.hud_reads"):
                with _live_perf_span("hud.build_queue"):
                    build_queue = get_build_queue_status_for_planet(
                        int(planet["id"]),
                        conn=conn,
                        skip_finish=True,
                    )
                # One levels read shared by research HUD + production (GC-PERF-HUD-READS-001).
                research_levels = get_research_levels(user_id, conn=conn)
                with _live_perf_span("hud.research"):
                    research = get_research_status(
                        user_id=user_id,
                        buildings=buildings,
                        skip_finish=True,
                        include_techs=include_research_techs,
                        conn=conn,
                        levels=research_levels,
                    )
                with _live_perf_span("hud.prod"):
                    prod_per_hour = get_building_production_per_hour(
                        buildings=buildings,
                        ratio=ratio,
                        user_id=user_id,
                        research=research_levels,
                        conn=conn,
                    )
            try:
                from flask import g as _flask_g, has_request_context

                if has_request_context():
                    _flask_g.gc_prod_per_hour = prod_per_hour
            except Exception:
                pass
            if not use_poll_live_path and not use_planet_switch_live_path:
                _stash_shell_boot_for_inject(user_id, conn)
        except RuntimeError:
            return None
        except Exception as live_exc:
            # PG LockNotAvailable / deadlock are not sqlite3.OperationalError.
            # Under live lock pressure, SSR/PJAX pages (e.g. /galaxy) must soft-fallback
            # instead of 500 — same path poll/planet_switch already used.
            from game.db import is_db_lock_error

            if not (
                isinstance(live_exc, sqlite3.OperationalError) or is_db_lock_error(live_exc)
            ):
                raise
            rollback(conn)
            logger.warning(
                "page live context locked, using read-only fallback user_id=%s source=%s",
                user_id,
                src,
                exc_info=True,
            )
            from game.logic import _read_player_live_state_no_writes
            from game.live_state import get_request_context_planet, mark_request_live_refreshed
            from game.buildings import get_build_queue_status_for_planet

            # We already gave up on finishing due work this request (lock above);
            # mark refreshed so coerce_skip_finish() honors skip_finish=True below
            # instead of retrying finish_due_work_once and hitting the same lock
            # again (GC-STABILIZE-002; game/live_state.py coerce_skip_finish).
            mark_request_live_refreshed()

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
            include_research_techs = _want_research_techs_for_panel(
                include_panel, src, resolved_panel_page
            )
            from game.models import get_research_levels
            from game.live_state import perf_span as _live_perf_span

            with _live_perf_span("live.hud_reads"):
                with _live_perf_span("hud.build_queue"):
                    build_queue = get_build_queue_status_for_planet(
                        int(planet["id"]),
                        conn=conn,
                        skip_finish=True,
                    )
                research_levels = get_research_levels(user_id, conn=conn)
                with _live_perf_span("hud.research"):
                    research = get_research_status(
                        user_id=user_id,
                        buildings=buildings,
                        skip_finish=True,
                        include_techs=include_research_techs,
                        conn=conn,
                        levels=research_levels,
                    )
                with _live_perf_span("hud.prod"):
                    prod_per_hour = get_building_production_per_hour(
                        buildings=buildings,
                        ratio=ratio,
                        user_id=user_id,
                        research=research_levels,
                        conn=conn,
                    )
            try:
                from flask import g as _flask_g, has_request_context

                if has_request_context():
                    _flask_g.gc_prod_per_hour = prod_per_hour
            except Exception:
                pass
            if not use_poll_live_path and not use_planet_switch_live_path:
                _stash_shell_boot_for_inject(user_id, conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own_conn or close_conn:
            conn.close()

    try:
        from flask import g as _flask_g, has_request_context

        if has_request_context() and prod_per_hour is not None:
            _flask_g.gc_prod_per_hour = prod_per_hour
    except Exception:
        pass

    # GC-PERF-AUTO-007B: do not record page_context_ms here — this function is live
    # refresh (finish+resources), not SSR page builders. True page_context.* spans
    # are recorded in overview/shipyard/fleet views.
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


def _stash_shell_boot_for_inject(user_id: int, conn) -> None:
    """GC-PERF-OVERVIEW-TTFB-001 — request-scoped shell bits for inject_globals (no 2nd DB conn)."""
    try:
        from flask import g as _flask_g, has_request_context

        if not has_request_context() or conn is None:
            return
        uid = int(user_id)
        if getattr(_flask_g, "gc_world_boss_count", None) is None:
            from game.world_boss import list_active_events

            wb_list = list_active_events(conn=conn, limit=10)
            _flask_g.gc_world_boss_count = len(wb_list)
            _flask_g.gc_world_boss_active = bool(wb_list)
        if getattr(_flask_g, "gc_fleet_hud", None) is None:
            from game.live_state import fleet_hud_for_game_state

            _flask_g.gc_fleet_hud = fleet_hud_for_game_state(uid, conn=conn)
    except Exception:
        pass


def _is_game_state_poll_source(finish_source: str) -> bool:
    """Lightweight poll path (throttled persist). Panel polls use game_state_panel."""
    return str(finish_source or "") == "game_state"


_FLEET_MUTATION_LIVE_SOURCES = frozenset(
    {
        "api_fleet_send",
        "api_fleet_bulk_launch_presets",
        "api_fleet_recall",
    }
)


def _use_poll_live_path(finish_source: str) -> bool:
    """Poll path for /api/game-state, PJAX, and fleet mutation responses (no finish_due_work)."""
    src = str(finish_source or "")
    if src in _FLEET_MUTATION_LIVE_SOURCES:
        return True
    return src == "game_state" or _is_pjax_request()


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
    resp = redirect(url_for("landing"))
    return expire_browser_session_cookies(resp)


@app.route("/auth/discord")
def auth_discord_start():
    if not discord_auth_logic.discord_oauth_configured():
        flash(T("discord_oauth_unavailable"), "error")
        return redirect(url_for("login"))

    # New Discord accounts require age + privacy/AGB ack (from register page query).
    allow_register = (
        str(request.args.get("age_ok") or "").strip() == "1"
        and str(request.args.get("legal_ack") or "").strip() == "1"
    )
    session["discord_allow_register"] = bool(allow_register)

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

    ok, err_key, user = discord_auth_logic.complete_discord_callback(
        code,
        allow_register=bool(session.pop("discord_allow_register", False)),
    )
    if not ok or not user:
        msg = T(err_key) if err_key and T(err_key) != err_key else T("discord_oauth_failed")
        flash(msg, "error")
        if err_key == "discord_register_ack_required":
            return redirect(url_for("register"))
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
            elif str(request.form.get("age_ok") or "") != "1":
                error = T("register_age_required") or "Bitte bestätige, dass du mindestens 16 Jahre alt bist."
            elif str(request.form.get("legal_ack") or "") != "1":
                error = T("register_legal_required") or "Bitte akzeptiere Datenschutz und AGB."
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

    prefilled_referral = (
        request.args.get("ref")
        or request.args.get("promo")
        or request.args.get("referral_code")
        or ""
    ).strip()
    if not prefilled_referral:
        sticky = session.get("shop_promo_code")
        if isinstance(sticky, dict):
            code_s = str(sticky.get("code") or "").strip()
            exp = float(sticky.get("expires_at") or 0)
            if code_s and exp >= time.time():
                prefilled_referral = code_s
    if prefilled_referral:
        prefilled_referral = prefilled_referral.upper()
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
    from game.landing_media import resolve_landing_media

    return render_template("landing.html", landing_media=resolve_landing_media())


@app.route("/legal")
@app.route("/legal/<doc>")
def legal_view(doc: str | None = None):
    """Public legal notices (provider ID, privacy, terms, withdrawal) — no login."""
    from flask import request
    from game.legal_panel import resolve_doc_id

    raw = doc or request.args.get("doc")
    return render_template("legal.html", legal_doc=resolve_doc_id(raw))


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
        if ssr is not None:
            ssr.add_live_context_ms((time.perf_counter() - ctx_t0) * 1000.0)

        from game.live_state import perf_span
        from game.overview_page import build_overview_page_context

        planet = ctx.get("planet")
        if not planet:
            from game.live_state import get_request_context_planet

            planet = get_request_context_planet(int(session["user_id"]), conn=conn)
        with perf_span("page_context.overview"):
            overview_status = build_overview_page_context(
                int(session["user_id"]), ctx, planet=planet, conn=conn
            )
            # Persist companion away→ready transitions from overview build.
            from game.db import commit as _commit

            _commit(conn)
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
        from game.collector_exchange import build_collector_exchange_payload, collector_schema_ready

        collector_exchange = (
            build_collector_exchange_payload(uid, conn=conn)
            if collector_schema_ready(conn)
            else {"ready": False, "specialists": []}
        )
    finally:
        conn.close()

    return render_template(
        "trader_hub.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        exchange=exchange,
        scrapyard=scrapyard,
        collector_exchange=collector_exchange,
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
            conn=conn,
        )
        from game.options import get_buildings_ui_settings

        buildings_ui = get_buildings_ui_settings(int(session["user_id"]), conn=conn)
        buildings_ui_mode = buildings_ui.get("buildings_ui_mode") or "stage"
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
        buildings_ui_mode=buildings_ui_mode,
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
    user_id = int(session["user_id"])
    player_view, _, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "galaxy"
    )
    if player_view is None:
        return redirect(url_for("login"))

    from game.galaxy import (
        build_galaxy_nav,
        get_planet_coordinates,
        get_relocation_client_state,
        list_system,
        player_has_seed_ark,
        relocation_schema_ready,
        resolve_view_coordinates,
    )
    from game.fleet import build_expedition_slot, _hold_mission_enabled
    from game.planet_evolution.repository import get_active_planet_id, get_context_planet

    from game.config import is_command_map_accessible

    view = (request.args.get("view") or "system").strip().lower()
    if view == "imperium":
        view = "system"
    if view not in ("system", "command_map"):
        view = "system"
    command_map_available = is_command_map_accessible(
        dev_query=request.args.get("dev"),
    )
    if view == "command_map" and not command_map_available:
        view = "system"

    galaxy = 1
    system = 1
    active_planet_id: int | None = None
    has_url_view = (
        request.args.get("galaxy", type=int) is not None
        or request.args.get("system", type=int) is not None
        or bool(request.args.get("q") or request.args.get("coord"))
    )

    carry_system = None
    try:
        if request.args.get("galaxy", type=int) is not None and request.args.get("system", type=int) is None:
            carry_system = int(session.get("galaxy_view_system") or 0) or None
    except (TypeError, ValueError):
        carry_system = None

    conn = db()
    hold_mission_enabled = False
    has_seed_ark = False
    galaxy_colonize_gate: dict[str, Any] = {"ok": True, "reason": "", "reason_key": ""}
    planet_relocation: dict[str, Any] = {"active": False, "can_start": False}
    command_map: dict[str, Any] = {"nodes": [], "edges": []}
    galactic_directive_banner: dict[str, Any] = {"visible": False}
    galactic_diplomacy_banner: dict[str, Any] = {"visible": False}
    galaxy_nav: dict[str, Any] = {}
    system_data: dict[str, Any] = {"galaxy": galaxy, "system": system, "slots": []}
    expedition_slot = None
    try:
        try:
            active_planet_id = get_active_planet_id(user_id, conn=conn) or None
            if not has_url_view:
                planet = get_context_planet(user_id, conn=conn)
                coords = get_planet_coordinates(planet)
                galaxy = int(coords["galaxy"])
                system = int(coords["system"])
        except Exception:
            active_planet_id = None

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

        hold_mission_enabled = _hold_mission_enabled(conn=conn)
        has_seed_ark = player_has_seed_ark(user_id, conn=conn)
        from game.planet_evolution.expansion_protocol import build_galaxy_colonize_gate

        galaxy_colonize_gate = build_galaxy_colonize_gate(user_id, conn=conn)
        if active_planet_id and relocation_schema_ready(conn):
            planet_relocation = get_relocation_client_state(
                int(active_planet_id), conn=conn, now=time.time()
            )
        if view == "command_map":
            from game.planet_evolution.command_map import build_command_map_payload

            command_map = build_command_map_payload(user_id, conn=conn)
        from game.galactic_directives.banner import build_galactic_directive_banner
        from game.galactic_diplomacy.banner import build_galactic_diplomacy_banner

        galactic_directive_banner = build_galactic_directive_banner(galaxy, conn=conn)
        galactic_diplomacy_banner = build_galactic_diplomacy_banner(galaxy, conn=conn)

        galaxy_nav = build_galaxy_nav(galaxy, system, conn=conn)
        if view != "command_map":
            from game.asteroids import ensure_asteroids_present
            from game.db import commit as db_commit, is_db_lock_error, rollback as db_rollback

            # Deploy bootstrap: first Galaxy open seeds belts if the universe is empty.
            # Best-effort: lock contention must not 500 PJAX/prefetch (aborted TX).
            try:
                ensure_asteroids_present(conn=conn)
                db_commit(conn)
            except Exception as asteroid_exc:
                if is_db_lock_error(asteroid_exc) or isinstance(
                    asteroid_exc, sqlite3.OperationalError
                ):
                    db_rollback(conn)
                    logger.warning(
                        "galaxy asteroid ensure skipped (database locked) user_id=%s",
                        user_id,
                        exc_info=True,
                    )
                else:
                    raise
            system_data = list_system(
                galaxy,
                system,
                conn=conn,
                viewer_player_id=user_id,
                active_planet_id=active_planet_id,
                highlight_position=highlight_pos,
            )
            expedition_slot = build_expedition_slot(galaxy, system, conn=conn)
    finally:
        conn.close()

    from game.planet_visuals import galaxy_ring_orbit_radii_payload

    return render_template(
        "galaxy.html",
        player=player_view,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        galaxy_nav=galaxy_nav,
        system_data=system_data,
        viewer_player_id=user_id,
        # Required for PJAX: inject_globals skips HEADER_ACTIVE_PLANET on X-PJAX.
        active_planet_id=active_planet_id,
        expedition_slot=expedition_slot,
        orbit_radii=galaxy_ring_orbit_radii_payload() if view != "command_map" else None,
        hold_mission_enabled=hold_mission_enabled,
        has_seed_ark=has_seed_ark,
        galaxy_colonize_gate=galaxy_colonize_gate,
        planet_relocation=planet_relocation,
        galaxy_view=view,
        command_map=command_map,
        galactic_directive_banner=galactic_directive_banner,
        galactic_diplomacy_banner=galactic_diplomacy_banner,
        command_map_available=command_map_available,
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


@sock.route("/ws/galaxy/<int:galaxy>/<int:system>")
def ws_galaxy_system(ws, galaxy: int, system: int):
    """Live push for galaxy-system viewers (GC-AST-LIVE).

    Thin invalidation channel only — never touches the DB. Auth reuses the
    standard Flask session cookie (sent automatically on the WS upgrade
    request), same as require_login_api elsewhere.
    """
    from game.ws_hub import (
        WSClient,
        galaxy_topic,
        release_connection_slot,
        subscribe,
        try_acquire_connection_slot,
        unsubscribe_all,
    )

    # GC-AST-LIVE: refuses to hold this connection open on a worker that
    # can't multiplex it (sync/gthread gunicorn, or the non-threaded local
    # Werkzeug dev server) — see ws_long_lived_safe() docstring.
    if not ws_long_lived_safe():
        return

    user_id = session.get("user_id")
    if not user_id:
        return

    if not try_acquire_connection_slot():
        return

    client = WSClient(ws, int(user_id))
    subscribe(client, galaxy_topic(galaxy, system))
    try:
        while True:
            # No inbound protocol — client only pings to keep the connection
            # alive; receive() with a timeout doubles as our heartbeat.
            ws.receive(timeout=30)
    except Exception:
        pass
    finally:
        unsubscribe_all(client)
        release_connection_slot()


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
    conn = db()
    try:
        ctx = _load_page_live_context(finish_source="defense", conn=conn, close_conn=False)
        if ctx is None:
            finish_ssr_perf(response_bytes=0)
            return redirect(url_for("login"))

        from game.defense_page import build_defense_page_context
        from game.live_state import get_request_context_planet

        player_view = ctx["player_view"]
        planet = ctx.get("planet")
        if not planet:
            planet = get_request_context_planet(int(session.get("user_id") or 0), conn=conn)
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
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
    )
    if ssr is not None:
        ssr.add_template_ms((time.perf_counter() - tpl_t0) * 1000.0)
        from flask import make_response

        out = make_response(resp)
        finish_ssr_perf(response_bytes=len(out.get_data() or b""))
        return out
    return resp


@app.route("/combat-simulator")
@require_login
def combat_simulator_view():
    ctx = _load_page_live_context(finish_source="combat_simulator")
    if ctx is None:
        return redirect(url_for("login"))

    from game.combat_simulator import build_combat_simulator_page_context

    user_id = int(ctx["player_view"]["id"])
    is_admin = bool(int(ctx["player_view"].get("is_admin") or 0))
    spy_report_id = None
    try:
        raw_spy = request.args.get("spy_report_id")
        if raw_spy is not None and str(raw_spy).strip():
            spy_report_id = int(raw_spy)
    except (TypeError, ValueError):
        spy_report_id = None
    conn = db()
    try:
        sim_ctx = build_combat_simulator_page_context(
            user_id,
            conn=conn,
            is_admin=is_admin,
            spy_report_id=spy_report_id,
        )
    finally:
        conn.close()

    return render_template(
        "combat_simulator.html",
        player=ctx["player_view"],
        energy_total=ctx["energy_total"],
        energy_used=ctx["energy_used"],
        storage_caps=ctx["storage_caps"],
        combat_simulator=sim_ctx,
    )


@app.route("/logistics")
@require_login
def logistics_view():
    if _load_player_view_with_resources()[0] is None:
        return redirect(url_for("login"))

    mode = (request.args.get("mode") or "collect").strip().lower()
    if mode not in ("collect", "distribute"):
        mode = "collect"

    # GC-FLT-SCOPE-001: preserve the planet-scoped navigation/cache key. The
    # canonical active planet remains server-owned and is not mutated by this GET.
    redirect_args: Dict[str, Any] = {"mode": mode}
    try:
        requested_planet_id = int(request.args.get("planet_id") or 0)
    except (TypeError, ValueError):
        requested_planet_id = 0
    if requested_planet_id > 0:
        redirect_args["planet_id"] = requested_planet_id
    return redirect(url_for("fleet_view", **redirect_args))


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
            from game.live_state import perf_span

            planet_dict = dict(planet)
            with perf_span("page_context.fleet"):
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
    ctx = _load_page_live_context(finish_source="alliance")
    if ctx is None:
        return redirect(url_for("login"))

    from game.alliance import get_alliance_state

    alliance_state = {"ready": False}
    conn = db()
    try:
        alliance_state = get_alliance_state(int(session["user_id"]), conn=conn)
    finally:
        conn.close()

    return render_template(
        "alliance.html",
        player=ctx["player_view"],
        energy_total=ctx.get("energy_total"),
        energy_used=ctx.get("energy_used"),
        storage_caps=ctx["storage_caps"],
        alliance_state=alliance_state,
    )


@app.route("/alliance/<int:alliance_id>")
@require_login
def alliance_visitor_view(alliance_id: int):
    ctx = _load_page_live_context(finish_source="alliance_visitor")
    if ctx is None:
        return redirect(url_for("login"))

    from game.alliance import get_alliance_state, get_alliance_visitor_page

    user_id = int(session["user_id"])
    visitor = None
    alliance_state = {"ready": False}
    conn = db()
    try:
        visitor = get_alliance_visitor_page(user_id, int(alliance_id), conn=conn)
        alliance_state = get_alliance_state(user_id, conn=conn)
    except ValueError as exc:
        err = str(exc)
        if err == "alliance_not_found":
            abort(404)
        alliance_state = {"ready": False, "error": err}
        visitor = None
    finally:
        conn.close()

    return render_template(
        "alliance.html",
        player=ctx["player_view"],
        energy_total=ctx.get("energy_total"),
        energy_used=ctx.get("energy_used"),
        storage_caps=ctx["storage_caps"],
        alliance_state=alliance_state,
        alliance_visitor=visitor,
    )


def _alliance_action_json(user_id: int, alliance_state: Dict[str, Any], finish_source: str):
    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
    return jsonify({"ok": True, "state": state, "alliance": alliance_state})


def _alliance_error_json(
    user_id: int,
    error: str,
    finish_source: str,
    *,
    status: int = 400,
    message: Optional[str] = None,
):
    from game.alliance import get_alliance_state

    conn = db()
    try:
        alliance_state = get_alliance_state(user_id, conn=conn)
    finally:
        conn.close()
    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
    err = str(error or "alliance_action_failed")
    msg = str(message or err)
    return (
        jsonify(
            {
                "ok": False,
                "error": err,
                "reason": err,
                "message": msg,
                "state": state,
                "alliance": alliance_state,
            }
        ),
        status,
    )


def _run_alliance_mutation(user_id: int, finish_source: str, mutate_fn):
    """Execute alliance write logic and commit — uncommitted writes were lost on conn.close()."""
    from game.alliance import get_alliance_state

    conn = db()
    try:
        mutate_fn(conn)
        commit(conn)
        alliance_state = get_alliance_state(user_id, conn=conn)
    except ValueError as exc:
        rollback(conn)
        return _alliance_error_json(user_id, str(exc), finish_source)
    except Exception:
        rollback(conn)
        logger.exception("alliance mutation failed source=%s user=%s", finish_source, user_id)
        return _alliance_error_json(user_id, "alliance_action_failed", finish_source, status=500)
    finally:
        conn.close()
    return _alliance_action_json(user_id, alliance_state, finish_source)


@app.route("/api/alliance/state", methods=["GET"])
@require_login
def api_alliance_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.alliance import get_alliance_state

    conn = db()
    try:
        alliance_state = get_alliance_state(user_id, conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, "alliance": alliance_state})


@app.route("/api/alliance/profile/<int:alliance_id>", methods=["GET"])
@require_login
def api_alliance_profile(alliance_id: int):
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.alliance import get_alliance_public_profile, get_alliance_state

    conn = db()
    try:
        profile = get_alliance_public_profile(alliance_id, conn=conn)
        alliance_state = get_alliance_state(user_id, conn=conn)
    except ValueError as exc:
        return _alliance_error_json(user_id, str(exc), "api_alliance_profile")
    except Exception:
        return _alliance_error_json(user_id, "alliance_action_failed", "api_alliance_profile", status=500)
    finally:
        conn.close()
    return jsonify({"ok": True, "profile": profile, "alliance": alliance_state})


@app.route("/api/alliance/create", methods=["POST"])
@require_login
def api_alliance_create():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import create_alliance

    def mutate(conn):
        create_alliance(
            str(data.get("tag") or ""),
            str(data.get("name") or ""),
            user_id,
            description=str(data.get("description") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_create", mutate)


@app.route("/api/alliance/join", methods=["POST"])
@require_login
def api_alliance_join():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import join_alliance_by_tag

    def mutate(conn):
        join_alliance_by_tag(user_id, str(data.get("tag") or ""), conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_join", mutate)


@app.route("/api/alliance/apply", methods=["POST"])
@require_login
def api_alliance_apply():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import apply_to_alliance

    def mutate(conn):
        apply_to_alliance(
            user_id,
            int(data.get("alliance_id") or 0),
            message=str(data.get("message") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_apply", mutate)


@app.route("/api/alliance/application/withdraw", methods=["POST"])
@require_login
def api_alliance_application_withdraw():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.alliance import withdraw_application

    def mutate(conn):
        withdraw_application(user_id, conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_application_withdraw", mutate)


@app.route("/api/alliance/leave", methods=["POST"])
@require_login
def api_alliance_leave():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.alliance import leave_alliance

    def mutate(conn):
        leave_alliance(user_id, conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_leave", mutate)


@app.route("/api/alliance/description", methods=["POST"])
@require_login
def api_alliance_description():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import update_alliance_description

    def mutate(conn):
        update_alliance_description(user_id, str(data.get("description") or ""), conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_description", mutate)


@app.route("/api/alliance/donate", methods=["POST"])
@require_login
def api_alliance_donate():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import donate_to_alliance

    def mutate(conn):
        donate_to_alliance(
            user_id,
            str(data.get("resource") or ""),
            int(data.get("amount") or 0),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_donate", mutate)


@app.route("/api/alliance-logo/<int:alliance_id>")
def api_alliance_logo(alliance_id: int):
    from game.alliance import can_serve_alliance_logo, get_alliance_logo_row

    if not can_serve_alliance_logo(alliance_id):
        abort(404)

    row = None
    conn = db()
    try:
        row = get_alliance_logo_row(alliance_id, conn=conn)
    finally:
        conn.close()
    if not row:
        abort(404)

    blob = row.get("image_blob")
    if not blob:
        abort(404)

    updated_at = int(row.get("updated_at") or 0)
    mime = str(row.get("mime_type") or "image/webp").split(";")[0].strip().lower()
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        mime = "image/webp"

    etag = f'W/"al-{int(alliance_id)}-{updated_at}"'
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


@app.route("/api/alliance/logo", methods=["POST"])
@require_login
def api_alliance_logo_upload():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    file_storage = request.files.get("logo")
    from game.alliance import upload_alliance_logo

    def mutate(conn):
        upload_alliance_logo(user_id, file_storage, conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_logo_upload", mutate)


@app.route("/api/alliance/project/start", methods=["POST"])
@require_login
def api_alliance_project_start():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import start_alliance_project

    def mutate(conn):
        start_alliance_project(
            user_id,
            str(data.get("kind") or ""),
            str(data.get("key") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_project_start", mutate)


@app.route("/api/alliance/application/respond", methods=["POST"])
@require_login
def api_alliance_application_respond():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import respond_application

    def mutate(conn):
        respond_application(
            user_id,
            int(data.get("application_id") or 0),
            accept=bool(data.get("accept")),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_application_respond", mutate)


@app.route("/api/alliance/diplomacy/send", methods=["POST"])
@require_login
def api_alliance_diplomacy_send():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import send_diplomacy_request

    def mutate(conn):
        send_diplomacy_request(
            user_id,
            str(data.get("tag") or ""),
            str(data.get("request_type") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_diplomacy_send", mutate)


@app.route("/api/alliance/diplomacy/respond", methods=["POST"])
@require_login
def api_alliance_diplomacy_respond():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import respond_diplomacy_request

    def mutate(conn):
        respond_diplomacy_request(
            user_id,
            int(data.get("request_id") or 0),
            accept=bool(data.get("accept")),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_diplomacy_respond", mutate)


@app.route("/api/alliance/recruitment", methods=["POST"])
@require_login
def api_alliance_recruitment():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import get_player_alliance, update_recruitment_mode

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        update_recruitment_mode(
            int(membership["alliance_id"]),
            user_id,
            str(data.get("mode") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_recruitment", mutate)


@app.route("/api/alliance/profile", methods=["POST"])
@require_login
def api_alliance_profile_update():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import get_player_alliance, update_alliance_profile

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        kwargs: Dict[str, Any] = {}
        if "name" in data:
            kwargs["name"] = str(data.get("name") or "")
        if "tag" in data:
            kwargs["tag"] = str(data.get("tag") or "")
        if "description" in data:
            kwargs["description"] = str(data.get("description") or "")
        update_alliance_profile(int(membership["alliance_id"]), user_id, conn=conn, **kwargs)

    return _run_alliance_mutation(user_id, "api_alliance_profile_update", mutate)


@app.route("/api/alliance/member/role", methods=["POST"])
@require_login
def api_alliance_member_role():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import get_player_alliance, set_member_role

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        set_member_role(
            int(membership["alliance_id"]),
            user_id,
            int(data.get("player_id") or 0),
            str(data.get("role") or ""),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_member_role", mutate)


@app.route("/api/alliance/leader/transfer", methods=["POST"])
@require_login
def api_alliance_leader_transfer():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import get_player_alliance, transfer_leadership

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        transfer_leadership(
            int(membership["alliance_id"]),
            user_id,
            int(data.get("player_id") or 0),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_leader_transfer", mutate)


@app.route("/api/alliance/member/kick", methods=["POST"])
@require_login
def api_alliance_member_kick():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import get_player_alliance, kick_member

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        kick_member(
            int(membership["alliance_id"]),
            user_id,
            int(data.get("player_id") or 0),
            conn=conn,
        )

    return _run_alliance_mutation(user_id, "api_alliance_member_kick", mutate)


@app.route("/api/alliance/broadcast", methods=["POST"])
@require_login
def api_alliance_broadcast():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    from game.alliance import send_alliance_broadcast

    sent_holder: Dict[str, int] = {"count": 0}

    def mutate(conn):
        sent_holder["count"] = int(
            send_alliance_broadcast(
                user_id,
                str(data.get("subject") or ""),
                str(data.get("body") or ""),
                conn=conn,
            )
        )

    resp = _run_alliance_mutation(user_id, "api_alliance_broadcast", mutate)
    payload = resp.get_json()
    if payload and payload.get("ok"):
        payload["broadcast_count"] = sent_holder["count"]
        return jsonify(payload)
    return resp


@app.route("/api/alliance/disband", methods=["POST"])
@require_login
def api_alliance_disband():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.alliance import disband_alliance, get_player_alliance

    def mutate(conn):
        membership = get_player_alliance(user_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        disband_alliance(int(membership["alliance_id"]), user_id, conn=conn)

    return _run_alliance_mutation(user_id, "api_alliance_disband", mutate)


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
    "case_battles_unavailable": "Relikt-Arena ist derzeit nicht verfügbar.",
    "invalid_cases": "Ungültige Container-Auswahl.",
    "invalid_case_count": "1–10 Container pro Battle erlaubt.",
    "unknown_container": "Unbekannter Container.",
    "invalid_mode": "Ungültiger Battle-Modus.",
    "invalid_visibility": "Ungültige Sichtbarkeit.",
    "battle_not_found": "Battle nicht gefunden.",
    "battle_not_open": "Battle ist nicht mehr offen.",
    "battle_not_running": "Battle läuft nicht.",
    "battle_full": "Battle ist voll.",
    "already_joined": "Du bist bereits in diesem Battle.",
    "invalid_join_code": "Ungültiger Beitrittscode.",
    "not_creator": "Nur der Ersteller kann das Battle abbrechen.",
    "invalid_player_limit": "Ungültige Spieleranzahl.",
    "not_participant": "Nur Teilnehmer können dieses Battle abschließen.",
    "battle_not_finished": "Battle ist noch nicht beendet.",
}


def _inventory_action_message(reason: str) -> str:
    key = str(reason or "inventory_action_failed")
    return _INVENTORY_ACTION_MESSAGES.get(key, "Aktion konnte nicht abgeschlossen werden.")


def _inventory_action_context(
    user_id: int, finish_source: str
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build fresh game state + inventory + case battles after mutation connection is closed."""
    from game.case_battles import build_case_battles_state
    from game.inventory import build_inventory_state

    state, _ = _build_game_state_payload(include_panel=True, finish_source=finish_source)
    conn = db()
    try:
        inventory = build_inventory_state(int(user_id), conn=conn)
        case_battles = build_case_battles_state(int(user_id), conn=conn)
    finally:
        conn.close()
    return state, inventory, case_battles


def _inventory_action_error_response(
    user_id: int,
    reason: str,
    finish_source: str,
    *,
    status: int = 400,
    extra: Optional[Dict[str, Any]] = None,
):
    state, inventory, case_battles = _inventory_action_context(user_id, finish_source)
    resp: Dict[str, Any] = {
        "ok": False,
        "reason": str(reason or "inventory_action_failed"),
        "message": _inventory_action_message(reason),
        "state": state,
        "inventory": inventory,
        "case_battles": case_battles,
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
    state, inventory, case_battles = _inventory_action_context(user_id, finish_source)
    resp: Dict[str, Any] = {
        "ok": True,
        "reason": reason,
        "state": state,
        "inventory": inventory,
        "case_battles": case_battles,
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

    from game.case_battles import build_case_battles_state
    from game.inventory import build_inventory_state, inventory_schema_ready
    from game.planet_evolution.repository import get_context_planet

    ctx = _load_page_live_context(finish_source="inventory")
    if ctx is None:
        return redirect(url_for("login"))

    inventory = {"ready": False, "containers": [], "other_items": []}
    case_battles = {"ready": False, "lobby": [], "mine": [], "active": None}
    conn = db()
    try:
        if inventory_schema_ready(conn):
            inventory = build_inventory_state(int(user_id), conn=conn)
            planet = get_context_planet(int(user_id), conn=conn)
            inventory["planet_id"] = int(planet["id"])
            inventory["planet_name"] = str(planet.get("name") or "").strip()
        case_battles = build_case_battles_state(int(user_id), conn=conn)
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
        case_battles=case_battles,
    )


@app.route("/api/inventory/state", methods=["GET"])
@require_login
def api_inventory_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.case_battles import build_case_battles_state
    from game.inventory import build_inventory_state, inventory_schema_ready

    conn = db()
    try:
        if not inventory_schema_ready(conn):
            return jsonify({"ok": False, "reason": "inventory_unavailable"}), 503
        inventory = build_inventory_state(user_id, conn=conn)
        case_battles = build_case_battles_state(user_id, conn=conn)
    finally:
        conn.close()

    return jsonify({"ok": True, "inventory": inventory, "case_battles": case_battles})


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


@app.route("/api/inventory/use", methods=["POST"])
@app.route("/api/inventory/use-item", methods=["POST"])
@require_login
def api_inventory_use_item():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    item_key = str(data.get("item_key") or "").strip()
    deposit_domain = str(data.get("deposit_domain") or "").strip().lower()
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
    from game.inventory_use import deposit_timekeeper_domain, use_inventory_item
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
        if deposit_domain:
            ok, reason, result = run_inventory_mutation(
                lambda conn: deposit_timekeeper_domain(user_id, deposit_domain, conn=conn)
            )
        elif not item_key:
            return _inventory_action_error_response(user_id, "missing_item", "inventory_use")
        else:
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


@app.route("/api/timekeeper/apply", methods=["POST"])
@require_login
def api_timekeeper_apply():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    domain = str(data.get("domain") or "").strip().lower()
    mode = str(data.get("mode") or "partial").strip().lower()
    try:
        seconds = int(data.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0
    planet_id_raw = data.get("planet_id")
    planet_id = int(planet_id_raw) if planet_id_raw is not None and str(planet_id_raw).strip() != "" else None

    from game.db import begin_write_transaction, commit, rollback
    from game.planet_evolution.repository import get_context_planet
    from game.timekeeper import apply_timekeeper

    conn = db()
    try:
        if planet_id is None and domain in (
            "build",
            "shipyard",
            "defense",
            "planet_research",
            "ascension",
        ):
            planet = get_context_planet(user_id, conn=conn)
            planet_id = int(planet["id"])
        t_apply0 = time.perf_counter()
        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(
            user_id,
            domain,
            planet_id=planet_id,
            seconds=seconds if mode == "partial" else None,
            mode=mode,
            conn=conn,
        )
        if not ok:
            rollback(conn)
            conn.close()
            conn = None
            state = _timekeeper_apply_game_state(domain)
            body = {"ok": False, "reason": reason, "state": state}
            if result.get("timekeeper"):
                body["timekeeper"] = result["timekeeper"]
            logger.info(
                "timekeeper_apply user_id=%s domain=%s ok=0 reason=%s seconds_applied=0",
                user_id,
                domain,
                reason,
            )
            return jsonify(body), 400
        commit(conn)
        apply_ms = (time.perf_counter() - t_apply0) * 1000.0

        # GC-PERF-TK-002: verify debit persisted (read-only — avoid INSERT OR IGNORE
        # starting a new write TX on this conn that would block state rebuild).
        applied = int(result.get("seconds_applied") or 0)
        tk_slice = result.get("timekeeper") or {}
        expected_bal = int(tk_slice.get("balance_sec") or 0)
        row = conn.execute(
            "SELECT balance_sec FROM timekeeper_balances WHERE player_id = ? LIMIT 1;",
            (user_id,),
        ).fetchone()
        persisted_bal = int(row["balance_sec"] or 0) if row else -1
        if applied > 0 and persisted_bal != expected_bal:
            logger.error(
                "timekeeper_apply not persisted user_id=%s domain=%s applied=%s expected_bal=%s got_bal=%s",
                user_id,
                domain,
                applied,
                expected_bal,
                persisted_bal,
            )
            conn.close()
            conn = None
            state = _timekeeper_apply_game_state(domain)
            if isinstance(state, dict) and tk_slice:
                state["timekeeper"] = tk_slice
            return jsonify(
                {
                    "ok": False,
                    "reason": "apply_not_persisted",
                    "state": state,
                    "timekeeper": tk_slice,
                    "seconds_applied": 0,
                }
            ), 500

        # Release apply conn before state rebuild (separate write TX).
        conn.close()
        conn = None

        t_state0 = time.perf_counter()
        state = _timekeeper_apply_game_state(domain)
        state_ms = (time.perf_counter() - t_state0) * 1000.0
        # Apply ledger wins over rebuild so HUD never keeps a stale balance.
        if isinstance(state, dict) and tk_slice:
            state["timekeeper"] = tk_slice
        jobs_finished = bool(result.get("jobs_finished"))
        # Surfaced on state so applyActionState / panel sync see the finish flag.
        if isinstance(state, dict):
            state["jobs_finished"] = jobs_finished
        logger.info(
            "timekeeper_apply user_id=%s domain=%s ok=1 reason=ok seconds_applied=%s "
            "jobs_finished=%s balance_after=%s apply_ms=%.1f state_ms=%.1f",
            user_id,
            domain,
            applied,
            1 if jobs_finished else 0,
            expected_bal,
            apply_ms,
            state_ms,
        )
        return jsonify(
            {
                "ok": True,
                "reason": "ok",
                "state": state,
                "timekeeper": tk_slice,
                "seconds_applied": applied,
                "jobs_finished": jobs_finished,
            }
        )
    except Exception:
        if conn is not None:
            rollback(conn)
        raise
    finally:
        if conn is not None:
            conn.close()


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


@app.route("/api/case-battles/state", methods=["GET"])
@require_login
def api_case_battles_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.case_battles import build_case_battles_state

    conn = db()
    try:
        case_battles = build_case_battles_state(user_id, conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, "case_battles": case_battles})


@app.route("/api/case-battles/<int:battle_id>", methods=["GET"])
@require_login
def api_case_battles_get(battle_id: int):
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.case_battles import get_battle_payload
    from game.db import begin_write_transaction, commit, rollback

    conn = db()
    try:
        begin_write_transaction(conn)
        battle = get_battle_payload(int(battle_id), conn=conn, viewer_id=user_id, auto_settle=True)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    if not battle:
        return jsonify({"ok": False, "reason": "battle_not_found", "message": _inventory_action_message("battle_not_found")}), 404
    return jsonify({"ok": True, "battle": battle})


@app.route("/api/case-battles/create", methods=["POST"])
@require_login
def api_case_battles_create():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.case_battles import case_battles_schema_ready, create_battle
    from game.inventory import run_inventory_mutation

    conn = db()
    try:
        if not case_battles_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "case_battles_unavailable", "case_battles_create", status=503
            )
    finally:
        conn.close()

    cases = data.get("cases")
    mode = str(data.get("mode") or "standard")
    visibility = str(data.get("visibility") or "public")
    try:
        player_limit = int(data.get("player_limit") or 2)
    except (TypeError, ValueError):
        player_limit = 2

    try:
        ok, reason, result = run_inventory_mutation(
            lambda c: create_battle(
                user_id,
                cases=cases,
                mode=mode,
                visibility=visibility,
                player_limit=player_limit,
                conn=c,
            )
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "case_battles_create", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "case_battles_create")

    return _inventory_action_ok_response(
        user_id,
        reason,
        "case_battles_create",
        {"battle": result},
        request_id=request_id,
    )


@app.route("/api/case-battles/join", methods=["POST"])
@require_login
def api_case_battles_join():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        battle_id = int(data.get("battle_id") or 0)
    except (TypeError, ValueError):
        battle_id = 0
    join_code = data.get("join_code")

    from game.case_battles import case_battles_schema_ready, join_battle, join_battle_by_code
    from game.inventory import run_inventory_mutation

    conn = db()
    try:
        if not case_battles_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "case_battles_unavailable", "case_battles_join", status=503
            )
    finally:
        conn.close()

    try:
        if battle_id <= 0 and join_code:
            ok, reason, result = run_inventory_mutation(
                lambda c: join_battle_by_code(user_id, str(join_code), conn=c)
            )
        else:
            ok, reason, result = run_inventory_mutation(
                lambda c: join_battle(user_id, battle_id, join_code=join_code, conn=c)
            )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "case_battles_join", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "case_battles_join")

    return _inventory_action_ok_response(
        user_id,
        reason,
        "case_battles_join",
        {"battle": result},
        request_id=request_id,
    )


@app.route("/api/case-battles/cancel", methods=["POST"])
@require_login
def api_case_battles_cancel():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        battle_id = int(data.get("battle_id") or 0)
    except (TypeError, ValueError):
        battle_id = 0

    from game.case_battles import cancel_battle, case_battles_schema_ready
    from game.inventory import run_inventory_mutation

    conn = db()
    try:
        if not case_battles_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "case_battles_unavailable", "case_battles_cancel", status=503
            )
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda c: cancel_battle(user_id, battle_id, conn=c)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "case_battles_cancel", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "case_battles_cancel")

    return _inventory_action_ok_response(
        user_id,
        reason,
        "case_battles_cancel",
        {"battle": result},
        request_id=request_id,
    )


@app.route("/api/case-battles/settle", methods=["POST"])
@require_login
def api_case_battles_settle():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "message": "Nicht angemeldet."}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        battle_id = int(data.get("battle_id") or 0)
    except (TypeError, ValueError):
        battle_id = 0

    from game.case_battles import case_battles_schema_ready, get_battle_payload, settle_battle
    from game.inventory import run_inventory_mutation

    conn = db()
    try:
        if not case_battles_schema_ready(conn):
            return _inventory_action_error_response(
                user_id, "case_battles_unavailable", "case_battles_settle", status=503
            )
        preview = get_battle_payload(battle_id, conn=conn, viewer_id=user_id)
        if not preview:
            return _inventory_action_error_response(user_id, "battle_not_found", "case_battles_settle")
        if not preview.get("is_participant"):
            return _inventory_action_error_response(user_id, "not_participant", "case_battles_settle")
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda c: settle_battle(battle_id, conn=c)
        )
    except Exception:
        return _inventory_action_error_response(
            user_id, "inventory_action_failed", "case_battles_settle", status=500
        )

    if not ok:
        return _inventory_action_error_response(user_id, reason, "case_battles_settle")

    return _inventory_action_ok_response(
        user_id,
        reason,
        "case_battles_settle",
        {"battle": result},
        request_id=request_id,
    )


@app.route("/api/case-battles/verify", methods=["POST"])
@require_login
def api_case_battles_verify():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    try:
        battle_id = int(data.get("battle_id") or 0)
    except (TypeError, ValueError):
        battle_id = 0
    try:
        round_index = int(data.get("round_index") or 0)
    except (TypeError, ValueError):
        round_index = -1
    try:
        target_user_id = int(data.get("user_id") or user_id)
    except (TypeError, ValueError):
        target_user_id = user_id

    from game.case_battles import verify_battle_roll

    conn = db()
    try:
        ok, reason, result = verify_battle_roll(
            battle_id,
            round_index=round_index,
            user_id=target_user_id,
            conn=conn,
        )
    finally:
        conn.close()

    if not ok:
        return jsonify({"ok": False, "reason": reason, "message": _inventory_action_message(reason)}), 400
    return jsonify({"ok": True, "reason": reason, "verification": result})


# --- EPIC-28 Space Lottery / Chrono Chamber ---------------------------------

_LOTTERY_REASON_MESSAGES = {
    "lottery_unavailable": "Chrono Chamber ist derzeit nicht verfügbar.",
    "insufficient_timekeeper": "Nicht genug Imperiumszeit.",
    "timekeeper_unavailable": "Timekeeper nicht verfügbar.",
    "bet_too_low": "Einsatz zu niedrig.",
    "bet_too_high": "Einsatz zu hoch.",
    "daily_wager_cap": "Tages-Einsatzlimit erreicht.",
    "round_active": "Es läuft bereits eine Runde.",
    "no_active_round": "Keine aktive Runde.",
    "invalid_ticket_count": "Ungültige Ticket-Anzahl.",
    "week_closed": "Diese Tombola-Woche ist geschlossen.",
    "invalid_mine_count": "Ungültige Minen-Anzahl.",
    "invalid_cell": "Ungültige Zelle.",
    "already_revealed": "Zelle bereits aufgedeckt.",
    "nothing_to_cashout": "Noch nichts zum Auszahlen.",
    "invalid_multiplier": "Ungültiger Multiplikator.",
    "multiplier_too_low": "Multiplikator zu niedrig.",
    "round_not_found": "Runde nicht gefunden.",
    "round_not_settled": "Runde noch nicht abgeschlossen.",
    "seed_mismatch": "Seed stimmt nicht.",
    "mode_disabled": "Dieses Spiel ist derzeit nicht verfügbar.",
}


def _lottery_message(reason: str) -> str:
    return _LOTTERY_REASON_MESSAGES.get(str(reason or ""), str(reason or "error"))


def _lottery_action_response(
    user_id: int,
    *,
    ok: bool,
    reason: str,
    lottery_state: Optional[Dict[str, Any]] = None,
    finish_source: str = "space_lottery",
    status: int = 200,
    extra: Optional[Dict[str, Any]] = None,
):
    from game.timekeeper import serialize_for_client as tk_serialize

    state, _ = _build_game_state_payload(
        include_panel=False,
        finish_source=finish_source,
        action_slim=True,
    )
    tk = None
    conn = db()
    try:
        tk = tk_serialize(user_id, conn=conn)
        if lottery_state is None:
            from game.space_lottery import serialize_state

            lottery_state = serialize_state(user_id, conn=conn)
    finally:
        conn.close()
    # Prefer lottery state's timekeeper if present (post-mutation balance).
    if isinstance(lottery_state, dict) and isinstance(lottery_state.get("timekeeper"), dict):
        tk = lottery_state["timekeeper"]
    if isinstance(state, dict) and tk:
        state = {**state, "timekeeper": tk}
    payload: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": str(reason or ""),
        "message": _lottery_message(reason) if not ok else "",
        "state": state,
        "timekeeper": tk,
        "space_lottery": lottery_state,
    }
    if extra:
        payload.update(extra)
    return jsonify(payload), (status if not ok else 200)


def _run_lottery_mutation(user_id: int, mut_fn, *, finish_source: str):
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, lottery_state = mut_fn(conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return _lottery_action_response(
        user_id,
        ok=ok,
        reason=reason,
        lottery_state=lottery_state,
        finish_source=finish_source,
        status=400 if not ok else 200,
    )


@app.route("/space-lottery")
@require_login
def space_lottery_view():
    ctx = _load_page_live_context(finish_source="space_lottery")
    if ctx is None:
        return redirect(url_for("login"))
    from game.space_lottery import serialize_state

    user_id = int(session["user_id"])
    lottery = {"ready": False}
    conn = db()
    try:
        begin_write_transaction(conn)
        lottery = serialize_state(user_id, conn=conn)
        commit(conn)
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        lottery = {"ready": False}
    finally:
        conn.close()
    return render_template(
        "space_lottery.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        space_lottery=lottery,
    )


@app.route("/api/space-lottery/state", methods=["GET"])
@require_login_api
def api_space_lottery_state():
    user_id = int(session.get("user_id") or 0)
    from game.space_lottery import serialize_state

    conn = db()
    try:
        begin_write_transaction(conn)
        state = serialize_state(user_id, conn=conn)
        commit(conn)
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        state = {"ready": False}
    finally:
        conn.close()
    return jsonify({"ok": True, "space_lottery": state})


@app.route("/api/space-lottery/tombola/buy", methods=["POST"])
@require_login_api
def api_space_lottery_tombola_buy():
    user_id = int(session.get("user_id") or 0)
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    try:
        count = int(data.get("count") or 1)
    except (TypeError, ValueError):
        count = 1

    def _mut(conn):
        from game.space_lottery import buy_tombola_tickets

        return buy_tombola_tickets(user_id, count, conn=conn, request_id=request_id)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_tombola")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/mines/start", methods=["POST"])
@require_login_api
def api_space_lottery_mines_start():
    user_id = int(session.get("user_id") or 0)
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    try:
        bet_sec = int(data.get("bet_sec") or 0)
    except (TypeError, ValueError):
        bet_sec = 0
    try:
        mine_count = int(data.get("mine_count") or 3)
    except (TypeError, ValueError):
        mine_count = 3

    def _mut(conn):
        from game.space_lottery import start_mines

        return start_mines(
            user_id, bet_sec, mine_count=mine_count, conn=conn, request_id=request_id
        )

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_mines")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/mines/reveal", methods=["POST"])
@require_login_api
def api_space_lottery_mines_reveal():
    user_id = int(session.get("user_id") or 0)
    data = request.get_json(silent=True) or {}
    try:
        cell = int(data.get("cell"))
    except (TypeError, ValueError):
        cell = -1

    def _mut(conn):
        from game.space_lottery import reveal_mines_cell

        return reveal_mines_cell(user_id, cell, conn=conn)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_mines")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/mines/cashout", methods=["POST"])
@require_login_api
def api_space_lottery_mines_cashout():
    user_id = int(session.get("user_id") or 0)

    def _mut(conn):
        from game.space_lottery import cashout_mines

        return cashout_mines(user_id, conn=conn)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_mines")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/crash/bet", methods=["POST"])
@require_login_api
def api_space_lottery_crash_bet():
    user_id = int(session.get("user_id") or 0)
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    try:
        bet_sec = int(data.get("bet_sec") or 0)
    except (TypeError, ValueError):
        bet_sec = 0

    def _mut(conn):
        from game.space_lottery import start_crash

        return start_crash(user_id, bet_sec, conn=conn, request_id=request_id)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_crash")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/crash/cashout", methods=["POST"])
@require_login_api
def api_space_lottery_crash_cashout():
    user_id = int(session.get("user_id") or 0)
    data = request.get_json(silent=True) or {}
    try:
        multiplier = float(data.get("multiplier") or 0)
    except (TypeError, ValueError):
        multiplier = 0.0

    def _mut(conn):
        from game.space_lottery import cashout_crash

        return cashout_crash(user_id, multiplier, conn=conn)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_crash")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/crash/bust", methods=["POST"])
@require_login_api
def api_space_lottery_crash_bust():
    user_id = int(session.get("user_id") or 0)

    def _mut(conn):
        from game.space_lottery import bust_crash

        return bust_crash(user_id, conn=conn)

    try:
        return _run_lottery_mutation(user_id, _mut, finish_source="space_lottery_crash")
    except Exception:
        return _lottery_action_response(
            user_id, ok=False, reason="lottery_unavailable", finish_source="space_lottery", status=500
        )


@app.route("/api/space-lottery/verify", methods=["POST"])
@require_login_api
def api_space_lottery_verify():
    data = request.get_json(silent=True) or {}
    try:
        round_id = int(data.get("round_id") or 0)
    except (TypeError, ValueError):
        round_id = 0
    from game.space_lottery import verify_round

    conn = db()
    try:
        ok, reason, result = verify_round(round_id, conn=conn)
    finally:
        conn.close()
    if not ok:
        return jsonify({"ok": False, "reason": reason, "message": _lottery_message(reason), "verification": result}), 400
    return jsonify({"ok": True, "reason": reason, "verification": result})


@app.route("/api/internal/cron/space-lottery-draw", methods=["POST"])
def api_internal_cron_space_lottery_draw():
    from game.internal_cron import verify_internal_cron_request
    from game.space_lottery import maybe_settle_due_weeks

    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        return jsonify({"ok": False, "error": auth_err or "unauthorized"}), 401
    conn = db()
    try:
        begin_write_transaction(conn)
        n = maybe_settle_due_weeks(conn=conn)
        commit(conn)
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()
    return jsonify({"ok": True, "weeks_settled": int(n)})


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
            mark_visited=True,
        )
        commit(conn)
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
            mark_visited=True,
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
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_auction_house_bid",
            panel_page="auction_house",
        )
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
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_auction_house_bid",
            panel_page="auction_house",
        )
        return jsonify({"ok": False, "reason": "auction_action_failed", "state": state}), 500
    finally:
        conn.close()

    state: Dict[str, Any] = {"ok": True, "server_time": time.time()}
    auction_house: Dict[str, Any] = {}
    try:
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_auction_house_bid",
            panel_page="auction_house",
        )
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
        state = _hud_only_game_state("api_vote_rewards_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_vote_rewards_claim")
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
        state = _hud_only_game_state("api_vote_rewards_claim_all")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_vote_rewards_claim_all")
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
        state = _hud_only_game_state("api_galactic_politics_vote")
        return jsonify({"ok": False, "reason": "vote_failed", "state": state}), 500
    finally:
        conn.close()

    ok = bool(result.get("ok"))
    state = _hud_only_game_state("api_galactic_politics_vote")
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


@app.route("/api/galactic-politics/bloc", methods=["POST"])
@require_login
def api_galactic_politics_bloc():
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
    bloc_key = str(data.get("bloc_key") or data.get("bloc") or "").strip()
    from game.galactic_diplomacy import submit_bloc_membership
    from game.galactic_directives import get_galactic_politics_state

    conn = db()
    try:
        result = submit_bloc_membership(user_id, galaxy, bloc_key, conn=conn)
        conn.commit()
    except Exception:
        logger.exception("galactic politics bloc failed user_id=%s galaxy=%s", user_id, galaxy)
        state = _hud_only_game_state("api_galactic_politics_bloc")
        return jsonify({"ok": False, "reason": "bloc_failed", "state": state}), 500
    finally:
        conn.close()

    ok = bool(result.get("ok"))
    state = _hud_only_game_state("api_galactic_politics_bloc")
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
        "bloc_key": result.get("bloc_key"),
    }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp), (200 if ok else 400)


@app.route("/api/galactic-politics/resolution/propose", methods=["POST"])
@require_login
def api_galactic_politics_resolution_propose():
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
    resolution_key = str(data.get("resolution_key") or data.get("resolution") or "").strip()
    from game.galactic_diplomacy import propose_resolution_session
    from game.galactic_directives import get_galactic_politics_state

    conn = db()
    try:
        result = propose_resolution_session(user_id, galaxy, resolution_key, conn=conn)
        conn.commit()
    except Exception:
        logger.exception("galactic resolution propose failed user_id=%s", user_id)
        state = _hud_only_game_state("api_galactic_politics_res_propose")
        return jsonify({"ok": False, "reason": "propose_failed", "state": state}), 500
    finally:
        conn.close()

    ok = bool(result.get("ok"))
    state = _hud_only_game_state("api_galactic_politics_res_propose")
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
        "session": result.get("session"),
    }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp), (200 if ok else 400)


@app.route("/api/galactic-politics/resolution/vote", methods=["POST"])
@require_login
def api_galactic_politics_resolution_vote():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached:
            return jsonify(cached)

    session_id = data.get("session_id") or data.get("session")
    choice = str(data.get("choice") or "").strip()
    from game.galactic_diplomacy import submit_resolution_vote
    from game.galactic_directives import get_galactic_politics_state

    try:
        sid = int(session_id or 0)
    except (TypeError, ValueError):
        sid = 0

    conn = db()
    try:
        result = submit_resolution_vote(user_id, sid, choice, conn=conn)
        conn.commit()
    except Exception:
        logger.exception("galactic resolution vote failed user_id=%s", user_id)
        state = _hud_only_game_state("api_galactic_politics_res_vote")
        return jsonify({"ok": False, "reason": "vote_failed", "state": state}), 500
    finally:
        conn.close()

    ok = bool(result.get("ok"))
    state = _hud_only_game_state("api_galactic_politics_res_vote")
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
        "session": result.get("session"),
    }
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp), (200 if ok else 400)


@app.route("/skilltree")
@require_login
def skilltree_view():
    ctx = _load_page_live_context(finish_source="skilltree")
    if ctx is None:
        return redirect(url_for("login"))

    from game.commander_classes import get_skilltree_page_context
    from game.db import begin_write_transaction, commit, rollback

    commander = {"ready": False}
    conn = db()
    try:
        begin_write_transaction(conn)
        page = get_skilltree_page_context(int(session["user_id"]), conn=conn)
        commander = page.get("commander") or {}
        commit(conn)
    except Exception:
        rollback(conn)
        logger.exception("skilltree page failed user_id=%s", session.get("user_id"))
    finally:
        conn.close()

    return render_template(
        "skilltree.html",
        commander=commander,
        **ctx,
    )


@app.route("/api/commander/class/pick", methods=["POST"])
@require_login_api
def api_commander_class_pick():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    body = request.get_json(silent=True) or {}
    class_key = str(body.get("class_key") or "").strip()
    from game.commander_classes import pick_class
    from game.queue_engine import finish_due_work_once

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id, conn=conn, source="api_commander_pick", manage_transaction=False
        )
        ok, reason, commander = pick_class(user_id, class_key, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("commander pick failed user_id=%s", user_id)
        return jsonify({"ok": False, "reason": "pick_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=False, finish_source="api_commander_pick")
    return jsonify({"ok": ok, "reason": reason, "commander": commander, "state": state}), (
        200 if ok else 400
    )


@app.route("/api/commander/sp/claim", methods=["POST"])
@require_login_api
def api_commander_sp_claim():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    from game.commander_classes import claim_skill_points

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, commander = claim_skill_points(user_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("commander sp claim failed user_id=%s", user_id)
        return jsonify({"ok": False, "reason": "claim_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=False, finish_source="api_commander_sp_claim")
    return jsonify({"ok": ok, "reason": reason, "commander": commander, "state": state}), (
        200 if ok else 400
    )


@app.route("/api/commander/skills/unlock", methods=["POST"])
@require_login_api
def api_commander_skills_unlock():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    body = request.get_json(silent=True) or {}
    skill_key = str(body.get("skill_key") or "").strip()
    planet_raw = body.get("planet_id")
    planet_id = int(planet_raw) if planet_raw not in (None, "") else None
    from game.commander_classes import unlock_skill
    from game.queue_engine import finish_due_work_once

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id,
            conn=conn,
            source="api_commander_unlock",
            manage_transaction=False,
        )
        ok, reason, commander = unlock_skill(
            user_id, skill_key, planet_id=planet_id, conn=conn
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("commander unlock failed user_id=%s", user_id)
        return jsonify({"ok": False, "reason": "unlock_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=False, finish_source="api_commander_unlock")
    return jsonify({"ok": ok, "reason": reason, "commander": commander, "state": state}), (
        200 if ok else 400
    )


@app.route("/api/commander/class/swap", methods=["POST"])
@require_login_api
def api_commander_class_swap():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        return jsonify({"ok": False, "reason": "confirm_required"}), 400
    from game.commander_classes import swap_class
    from game.queue_engine import finish_due_work_once

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id, conn=conn, source="api_commander_swap", manage_transaction=False
        )
        ok, reason, commander = swap_class(user_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("commander swap failed user_id=%s", user_id)
        return jsonify({"ok": False, "reason": "swap_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=False, finish_source="api_commander_swap")
    return jsonify({"ok": ok, "reason": reason, "commander": commander, "state": state}), (
        200 if ok else 400
    )


@app.route("/login-rewards")
@require_login
def login_rewards_view():
    ctx = _load_page_live_context(finish_source="login_rewards")
    if ctx is None:
        return redirect(url_for("login"))

    from game.login_rewards import serialize_for_client

    login_state = {"ready": False}
    conn = db()
    try:
        login_state = serialize_for_client(
            int(session["user_id"]),
            conn=conn,
            include_calendar=True,
        )
    finally:
        conn.close()

    return render_template(
        "login_rewards.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        login_rewards=login_state,
    )


@app.route("/api/login-rewards/claim", methods=["POST"])
@require_login
def api_login_rewards_claim():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.login_rewards import claim_login_reward, serialize_for_client

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_login_reward(user_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("login reward claim failed user_id=%s", user_id)
        state = _hud_only_game_state("api_login_rewards_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_login_rewards_claim")
    conn2 = db()
    try:
        login_rewards = (
            (claim_result or {}).get("login_rewards")
            if ok
            else serialize_for_client(user_id, conn=conn2, include_calendar=True)
        )
    finally:
        conn2.close()

    resp = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "login_rewards": login_rewards,
    }
    if ok and claim_result:
        resp["day"] = claim_result.get("day")
        resp["reward"] = claim_result.get("reward")
        resp["granted"] = claim_result.get("granted")
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/premium")
@require_login
def premium_view():
    ctx = _load_page_live_context(finish_source="premium")
    if ctx is None:
        return redirect(url_for("login"))

    from game.battle_pass import serialize_for_client as bp_serialize
    from game.login_rewards import serialize_for_client as lr_serialize
    from game.shop import serialize_catalog_for_client

    battle_pass = {"ready": False}
    login_teaser = {"ready": False}
    shop_checkout = {"enabled": False, "providers": []}
    conn = db()
    try:
        uid = int(session["user_id"])
        battle_pass = bp_serialize(uid, conn=conn, include_tracks=True)
        login_teaser = lr_serialize(uid, conn=conn, include_calendar=False)
        shop_state = serialize_catalog_for_client(conn=conn, player_id=uid)
        conn.commit()
        shop_checkout = {
            "enabled": bool(shop_state.get("enabled")),
            "providers": list(shop_state.get("providers") or []),
        }
    finally:
        conn.close()

    return render_template(
        "premium.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        battle_pass=battle_pass,
        login_teaser=login_teaser,
        shop_checkout=shop_checkout,
    )


@app.route("/api/battle-pass/claim", methods=["POST"])
@require_login
def api_battle_pass_claim():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    level = int(data.get("level") or 0)
    track = str(data.get("track") or "").strip().lower()
    from game.battle_pass import claim_battle_pass_reward, serialize_for_client

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_battle_pass_reward(
            user_id, level, track, conn=conn
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception(
            "battle pass claim failed user_id=%s level=%s track=%s",
            user_id,
            level,
            track,
        )
        state = _hud_only_game_state("api_battle_pass_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_battle_pass_claim")
    conn2 = db()
    try:
        battle_pass = (
            (claim_result or {}).get("battle_pass")
            if ok
            else serialize_for_client(user_id, conn=conn2, include_tracks=True)
        )
    finally:
        conn2.close()

    resp = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "battle_pass": battle_pass,
    }
    if ok and claim_result:
        resp["level"] = claim_result.get("level")
        resp["track"] = claim_result.get("track")
        resp["reward"] = claim_result.get("reward")
        resp["granted"] = claim_result.get("granted")
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/api/battle-pass/claim-op", methods=["POST"])
@require_login
def api_battle_pass_claim_op():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    op_key = str(data.get("op_key") or "").strip()
    period_key = str(data.get("period_key") or "").strip() or None
    from game.battle_pass import claim_op, serialize_for_client

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_op(
            user_id, op_key, conn=conn, period_key=period_key
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception(
            "battle pass claim-op failed user_id=%s op_key=%s",
            user_id,
            op_key,
        )
        state = _hud_only_game_state("api_battle_pass_claim_op")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_battle_pass_claim_op")
    conn2 = db()
    try:
        battle_pass = (
            (claim_result or {}).get("battle_pass")
            if ok
            else serialize_for_client(user_id, conn=conn2, include_tracks=True)
        )
    finally:
        conn2.close()

    resp = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "battle_pass": battle_pass,
    }
    if ok and claim_result:
        resp["op_key"] = claim_result.get("op_key")
        resp["period_key"] = claim_result.get("period_key")
        resp["xp_reward"] = claim_result.get("xp_reward")
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/api/admin/battle-pass/unlock-premium", methods=["POST"])
@require_admin_api
def api_admin_battle_pass_unlock_premium():
    data = request.get_json(silent=True) or {}
    player_id = int(data.get("player_id") or 0)
    if player_id <= 0:
        return jsonify({"ok": False, "reason": "invalid_player"}), 400

    from game.battle_pass import unlock_premium

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, result = unlock_premium(
            player_id,
            conn=conn,
            source=f"admin:{int(session.get('user_id') or 0)}",
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("admin battle pass unlock failed player_id=%s", player_id)
        return jsonify({"ok": False, "reason": "unlock_failed"}), 500
    finally:
        conn.close()

    return jsonify({"ok": bool(ok), "reason": reason, "result": result})


# --------------------------------------------------------------------------
# SHOP / PAYMENTS (EPIC-23)
# --------------------------------------------------------------------------

def _shop_absolute_url(path: str) -> str:
    """Stripe/PayPal require absolute https/http return URLs.

    Live PayPal: PUBLIC_BASE_URL. Sandbox/local: request host when PUBLIC_BASE_URL
    points at another host (common local .env with prod PUBLIC_BASE_URL).
    """
    from game.config import (
        resolve_shop_checkout_base_url,
        shop_cancel_url,
        shop_success_url,
    )
    from game.payment_providers import paypal_mode

    checkout_base = resolve_shop_checkout_base_url(
        request_url_root=request.url_root.rstrip("/"),
        paypal_live=(paypal_mode() == "live"),
    )
    if path == "success":
        configured = shop_success_url(checkout_base=checkout_base)
    elif path == "cancel":
        configured = shop_cancel_url(checkout_base=checkout_base)
    else:
        configured = path
    if configured.startswith("http://") or configured.startswith("https://"):
        return configured
    base = (checkout_base or request.url_root.rstrip("/")).rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        base = request.url_root.rstrip("/")
    suffix = configured if configured.startswith("/") else f"/{configured}"
    return f"{base}{suffix}"


@app.route("/shop")
@require_login
def shop_view():
    ctx = _load_page_live_context(finish_source="shop")
    if ctx is None:
        return redirect(url_for("login"))

    from game.shop import serialize_catalog_for_client
    from game.story.free_shop import get_free_shop_state

    shop_state = {"ready": False, "enabled": False, "products": [], "providers": []}
    free_shop_state: Dict[str, Any] = {
        "balance": 0,
        "token_key": "story_scrap_token",
        "label": "Ark-Token",
        "offers": [],
    }
    conn = db()
    try:
        uid = int(session["user_id"])
        shop_state = serialize_catalog_for_client(conn=conn, player_id=uid)
        free_shop_state = get_free_shop_state(uid, conn=conn)
        conn.commit()
    finally:
        conn.close()

    promo_q = str(request.args.get("promo") or "").strip()
    if promo_q:
        _set_shop_promo_sticky(promo_q)
    sticky = session.get("shop_promo_code") if isinstance(session.get("shop_promo_code"), dict) else {}
    active_promo = ""
    if sticky:
        code_s = str(sticky.get("code") or "").strip()
        exp = float(sticky.get("expires_at") or 0)
        if code_s and exp >= time.time():
            active_promo = code_s
        elif code_s:
            session.pop("shop_promo_code", None)

    return render_template(
        "shop.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        shop=shop_state,
        free_shop=free_shop_state,
        shop_cancelled=bool(request.args.get("cancelled")),
        active_promo=active_promo,
    )


@app.route("/shop/return")
@require_login
def shop_return_view():
    """Post-checkout return. PayPal: capture+fulfill here if still pending (webhook backup)."""
    order_id = int(request.args.get("order_id") or 0)
    session_id = str(request.args.get("session_id") or "").strip()
    token = str(request.args.get("token") or "").strip()
    user_id = int(session.get("user_id") or 0)
    order = None
    receipt = None
    conn = db()
    try:
        from game.payment_providers import paypal_capture_order, paypal_order_capture_summary
        from game.shop import (
            build_shop_return_payload,
            find_order_by_session,
            get_order,
            process_paid_event,
            recover_paypal_return_for_player,
        )

        # Fall through: wrong/local order_id must not block PayPal token recovery.
        if order_id > 0:
            order = get_order(order_id, conn=conn)
            if order and int(order["player_id"]) != user_id:
                order = None
        if order is None and session_id:
            order = find_order_by_session("stripe", session_id, conn=conn)
            if order is None:
                order = find_order_by_session("paypal", session_id, conn=conn)
            if order and int(order["player_id"]) != user_id:
                order = None
        if order is None and token:
            order = find_order_by_session("paypal", token, conn=conn)
            if order and int(order["player_id"]) != user_id:
                order = None

        # Orphaned live payment: order exists only on another DB (local→prod).
        if order is None and token and user_id > 0:
            begin_write_transaction(conn)
            try:
                rok, rreason, recovered = recover_paypal_return_for_player(
                    user_id, token, conn=conn
                )
                if rok and recovered:
                    commit(conn)
                    order = recovered
                else:
                    rollback(conn)
                    if rreason not in ("paypal_not_paid", "paypal_http_404"):
                        logger.warning(
                            "paypal return recover failed token=%s reason=%s",
                            token,
                            rreason,
                        )
            except Exception:
                rollback(conn)
                logger.exception("paypal return recover crashed token=%s", token)

        # PayPal browser return — capture & fulfill if webhook has not landed yet.
        if (
            order
            and str(order.get("provider") or "") == "paypal"
            and str(order.get("status") or "") in ("pending", "paid")
            and (token or order.get("provider_session_id"))
        ):
            paypal_oid = token or str(order.get("provider_session_id") or "")
            begin_write_transaction(conn)
            try:
                cok, creason, cap = paypal_capture_order(paypal_oid)
                payment_id = paypal_oid
                if isinstance(cap, dict):
                    summary = paypal_order_capture_summary(cap)
                    if summary.get("capture_id"):
                        payment_id = str(summary["capture_id"])
                if cok:
                    process_paid_event(
                        provider="paypal",
                        event_id=f"return_capture:{paypal_oid}:{int(order['id'])}",
                        order_id=int(order["id"]),
                        provider_session_id=paypal_oid,
                        provider_payment_id=payment_id,
                        conn=conn,
                        payload={"source": "shop_return", "capture_ok": True},
                    )
                    commit(conn)
                else:
                    rollback(conn)
                    logger.warning(
                        "paypal return capture failed order_id=%s reason=%s",
                        order.get("id"),
                        creason,
                    )
            except Exception:
                rollback(conn)
                logger.exception(
                    "paypal return fulfill failed order_id=%s", order.get("id")
                )
            order = get_order(int(order["id"]), conn=conn)
        receipt = build_shop_return_payload(order, conn=conn)
    finally:
        conn.close()

    if receipt is None:
        from game.shop import build_shop_return_payload

        receipt = build_shop_return_payload(None, conn=None)

    # Drop session cart after a successful paid/fulfilled return (PayPal path).
    if order and str(order.get("status") or "") in ("paid", "fulfilled"):
        from game.shop import clear_session_cart

        clear_session_cart(session)

    ctx = _load_page_live_context(finish_source="shop_return")
    if ctx is None:
        return redirect(url_for("login"))

    return render_template(
        "shop_return.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        order=order,
        receipt=receipt,
    )


@app.route("/api/shop/catalog", methods=["GET"])
@require_login
def api_shop_catalog():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.shop import serialize_catalog_for_client

    conn = db()
    try:
        shop = serialize_catalog_for_client(conn=conn, player_id=user_id)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "reason": "ok", "shop": shop})


@app.route("/api/shop/cart", methods=["GET"])
@require_login_api
def api_shop_cart_get():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "error": "not_logged_in"}), 401
    from game.shop import get_session_cart, serialize_cart_for_client

    promo_code = str(request.args.get("promo_code") or "").strip()
    if not promo_code:
        sticky = session.get("shop_promo_code") or {}
        if isinstance(sticky, dict):
            code_s = str(sticky.get("code") or "").strip()
            exp = float(sticky.get("expires_at") or 0)
            if code_s and exp >= time.time():
                promo_code = code_s
    conn = db()
    try:
        cart = get_session_cart(session)
        payload = serialize_cart_for_client(
            user_id, cart, conn=conn, promo_code=promo_code or None
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "reason": "ok", "cart": payload})


@app.route("/api/shop/cart/add", methods=["POST"])
@require_login_api
def api_shop_cart_add():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    sku = str(data.get("sku") or "").strip()
    try:
        qty = int(data.get("qty") or 1)
    except (TypeError, ValueError):
        qty = 1
    if not sku:
        return jsonify({"ok": False, "reason": "unknown_sku"}), 400
    from game.shop import (
        MAX_CART_DISTINCT_SKUS,
        add_to_session_cart,
        get_product,
        get_session_cart,
        normalize_cart_lines,
        serialize_cart_for_client,
    )

    conn = db()
    try:
        product = get_product(sku, conn=conn)
        if not product:
            return jsonify({"ok": False, "reason": "unknown_sku"}), 400
        before = get_session_cart(session)
        if (
            not any(r["sku"] == sku for r in before)
            and len(before) >= MAX_CART_DISTINCT_SKUS
        ):
            return jsonify({"ok": False, "reason": "cart_too_large"}), 400
        add_to_session_cart(session, sku, qty)
        # Validate ownership / caps after merge
        ok_n, reason_n, _ = normalize_cart_lines(
            get_session_cart(session),
            conn=conn,
            player_id=user_id,
            allow_owned=False,
        )
        if not ok_n:
            # Roll back add for this sku
            from game.shop import set_session_cart

            set_session_cart(session, before)
            return jsonify({"ok": False, "reason": reason_n}), 400
        promo_code = str(data.get("promo_code") or "").strip() or None
        payload = serialize_cart_for_client(
            user_id, get_session_cart(session), conn=conn, promo_code=promo_code
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "reason": "ok", "cart": payload})


@app.route("/api/shop/cart/update", methods=["POST"])
@require_login_api
def api_shop_cart_update():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    sku = str(data.get("sku") or "").strip()
    try:
        qty = int(data.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    if not sku:
        return jsonify({"ok": False, "reason": "unknown_sku"}), 400
    from game.shop import (
        get_session_cart,
        serialize_cart_for_client,
        update_session_cart,
    )

    update_session_cart(session, sku, qty)
    conn = db()
    try:
        payload = serialize_cart_for_client(
            user_id, get_session_cart(session), conn=conn
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "reason": "ok", "cart": payload})


@app.route("/api/shop/checkout", methods=["POST"])
@require_login_api
def api_shop_checkout():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    sku = str(data.get("sku") or "").strip()
    provider = str(data.get("provider") or "").strip().lower()
    legal_ack = bool(data.get("legal_ack"))
    legal_text_version = str(data.get("legal_text_version") or "").strip() or None
    promo_code = str(data.get("promo_code") or "").strip()
    raw_lines = data.get("lines") if isinstance(data.get("lines"), list) else None
    use_cart = bool(data.get("from_cart")) or (not sku and not raw_lines)
    if not promo_code:
        sticky = session.get("shop_promo_code") or {}
        if isinstance(sticky, dict):
            code_s = str(sticky.get("code") or "").strip()
            exp = float(sticky.get("expires_at") or 0)
            if code_s and exp >= time.time():
                promo_code = code_s
            elif code_s:
                session.pop("shop_promo_code", None)
    from game.shop import clear_session_cart, get_session_cart, start_checkout
    from game.config import (
        canon_shop_host,
        get_canonical_shop_url,
        public_shop_host,
        resolve_shop_checkout_base_url,
    )
    from game.payment_providers import paypal_mode

    checkout_lines = None
    if raw_lines:
        checkout_lines = raw_lines
    elif use_cart:
        checkout_lines = get_session_cart(session)
        if not checkout_lines:
            return jsonify({"ok": False, "reason": "empty_cart"}), 400
    elif not sku:
        return jsonify({"ok": False, "reason": "unknown_sku"}), 400

    paypal_live = provider == "paypal" and paypal_mode() == "live"
    req_host = canon_shop_host(request.host or "")
    pub_host = public_shop_host()
    return_base = resolve_shop_checkout_base_url(
        request_url_root=request.url_root.rstrip("/"),
        paypal_live=paypal_live,
    )

    # Block local→live PayPal: PUBLIC_BASE_URL host must match this request host
    # (www and apex are treated as the same site). Sandbox never hits this gate.
    if paypal_live and pub_host and req_host and pub_host != req_host:
        canonical = get_canonical_shop_url()
        logger.warning(
            "shop checkout host mismatch user_id=%s req_host=%s pub_host=%s mode=live",
            user_id,
            req_host,
            pub_host,
        )
        return jsonify(
            {
                "ok": False,
                "reason": "public_host_mismatch",
                "detail": "Live PayPal nur über die Produktions-URL.",
                "canonical_shop_url": canonical,
            }
        ), 400

    success_url = _shop_absolute_url("success")
    cancel_url = _shop_absolute_url("cancel")
    logger.info(
        "shop checkout start user_id=%s sku=%s provider=%s mode=%s req_host=%s return_base=%s cart=%s",
        user_id,
        sku or "cart",
        provider,
        paypal_mode() if provider == "paypal" else provider,
        req_host,
        return_base,
        bool(use_cart or raw_lines),
    )

    def _checkout_once(promo: Optional[str]):
        begin_write_transaction(conn)
        try:
            ok_i, reason_i, result_i = start_checkout(
                user_id,
                sku if not checkout_lines else "",
                provider,
                conn=conn,
                success_url=success_url,
                cancel_url=cancel_url,
                legal_ack=legal_ack,
                legal_text_version=legal_text_version,
                promo_code=promo or None,
                lines=checkout_lines,
            )
            if ok_i:
                if result_i and result_i.get("order_id") and provider != "stripe":
                    oid = int(result_i["order_id"])
                    result_i = dict(result_i)
                    result_i["return_hint"] = f"/shop/return?order_id={oid}"
                commit(conn)
            else:
                rollback(conn)
            return ok_i, reason_i, result_i
        except Exception:
            rollback(conn)
            raise

    promo_dropped = None
    conn = db()
    try:
        ok, reason, result = _checkout_once(promo_code or None)
        if (not ok) and str(reason or "").startswith("promo_"):
            promo_dropped = str(reason)
            session.pop("shop_promo_code", None)
            logger.warning(
                "shop checkout dropping invalid promo user_id=%s sku=%s reason=%s",
                user_id,
                sku or "cart",
                promo_dropped,
            )
            ok, reason, result = _checkout_once(None)
    except Exception:
        logger.exception(
            "shop checkout failed user_id=%s sku=%s provider=%s",
            user_id,
            sku or "cart",
            provider,
        )
        return jsonify({"ok": False, "reason": "checkout_failed"}), 500
    finally:
        conn.close()

    checkout_url = (result or {}).get("checkout_url") if result else None
    fulfilled = bool((result or {}).get("fulfilled")) if result else False
    if ok and fulfilled and (use_cart or raw_lines):
        # Only clear after immediate fulfill (test provider). PayPal redirect must
        # keep the cart until paid — otherwise a failed/aborted redirect leaves a
        # stale client cart and the next click returns empty_cart.
        clear_session_cart(session)

    if ok and checkout_url and not fulfilled:
        state = {}
    else:
        try:
            state, _ = _build_game_state_payload(
                include_panel=True, finish_source="api_shop_checkout"
            )
        except Exception:
            logger.exception(
                "shop checkout state build failed user_id=%s sku=%s (checkout ok=%s)",
                user_id,
                sku or "cart",
                ok,
            )
            state = {}
    resp = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "order_id": (result or {}).get("order_id") if result else None,
        "checkout_url": checkout_url,
        "fulfilled": fulfilled,
    }
    if promo_dropped:
        resp["promo_dropped"] = promo_dropped
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    status = 200 if ok else 400
    if reason in ("not_logged_in",):
        status = 401
    return jsonify(resp), status


def _set_shop_promo_sticky(code: str) -> None:
    from game.shop_promos import SESSION_PROMO_TTL_SEC, normalize_code

    normalized = normalize_code(code)
    if not normalized:
        return
    session["shop_promo_code"] = {
        "code": normalized,
        "expires_at": time.time() + float(SESSION_PROMO_TTL_SEC),
    }


@app.route("/api/shop/promo/preview", methods=["POST"])
@require_login_api
def api_shop_promo_preview():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in", "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or data.get("promo_code") or "").strip()
    sku = str(data.get("sku") or "").strip() or None
    sticky = bool(data.get("sticky", True))
    from game.shop_promos import preview_pricing, schema_ready

    conn = db()
    try:
        if not schema_ready(conn):
            return jsonify({"ok": False, "reason": "promo_unavailable"}), 400
        ok, reason, payload = preview_pricing(
            code, conn=conn, buyer_player_id=user_id, sku=sku
        )
        if ok and sticky and payload:
            _set_shop_promo_sticky(str(payload.get("code") or code))
            # Keep cart: sticky must not replace the session payload.
            session.modified = True
            conn.commit()
        return jsonify({"ok": ok, "reason": reason, **(payload or {})}), (200 if ok else 400)
    finally:
        conn.close()


@app.route("/r/<code>")
def shop_promo_share_landing(code: str):
    from game.shop_promos import record_click, schema_ready

    conn = db()
    try:
        if schema_ready(conn):
            begin_write_transaction(conn)
            try:
                uid = int(session.get("user_id") or 0) or None
                record_click(code, conn=conn, actor_player_id=uid)
                commit(conn)
            except Exception:
                rollback(conn)
        _set_shop_promo_sticky(code)
    finally:
        conn.close()
    if session.get("user_id"):
        return redirect(url_for("shop_view", promo=str(code or "").strip().upper()))
    return redirect(url_for("register", ref=str(code or "").strip().upper()))


@app.route("/creator")
@require_login
def creator_dashboard_view():
    ctx = _load_page_live_context(finish_source="creator")
    if ctx is None:
        return redirect(url_for("login"))
    from game.shop_promos import creator_overview, schema_ready

    overview = None
    reason = "promo_unavailable"
    conn = db()
    try:
        if schema_ready(conn):
            begin_write_transaction(conn)
            try:
                ok, reason, overview = creator_overview(int(session["user_id"]), conn=conn)
                commit(conn)
            except Exception:
                rollback(conn)
                raise
    finally:
        conn.close()
    return render_template(
        "creator.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        creator_ok=bool(overview),
        creator_reason=reason,
        creator=overview,
    )


@app.route("/api/creator/overview", methods=["GET"])
@require_login
def api_creator_overview():
    from game.shop_promos import creator_overview, schema_ready

    conn = db()
    try:
        if not schema_ready(conn):
            return jsonify({"ok": False, "reason": "promo_unavailable"}), 400
        begin_write_transaction(conn)
        try:
            ok, reason, overview = creator_overview(int(session["user_id"]), conn=conn)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        return jsonify({"ok": ok, "reason": reason, "overview": overview}), (200 if ok else 403)
    finally:
        conn.close()


@app.route("/api/creator/terms-ack", methods=["POST"])
@require_login
def api_creator_terms_ack():
    from game.shop_promos import ack_partner_terms, schema_ready

    conn = db()
    try:
        if not schema_ready(conn):
            return jsonify({"ok": False, "reason": "promo_unavailable"}), 400
        begin_write_transaction(conn)
        try:
            ok, reason = ack_partner_terms(int(session["user_id"]), conn=conn)
            if ok:
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
        return jsonify({"ok": ok, "reason": reason}), (200 if ok else 400)
    finally:
        conn.close()


@app.route("/api/creator/ledger.csv", methods=["GET"])
@require_login
def api_creator_ledger_csv():
    from game.shop_promos import get_creator_by_player, ledger_csv, schema_ready
    from flask import Response

    conn = db()
    try:
        if not schema_ready(conn):
            return jsonify({"ok": False, "reason": "promo_unavailable"}), 400
        creator = get_creator_by_player(int(session["user_id"]), conn=conn)
        if not creator or not creator["active"]:
            return jsonify({"ok": False, "reason": "not_creator"}), 403
        csv_text = ledger_csv(int(creator["id"]), conn=conn)
        return Response(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=creator_ledger.csv"},
        )
    finally:
        conn.close()


@app.route("/api/webhooks/stripe", methods=["POST"])
def api_webhook_stripe():
    from game.payment_providers import (
        stripe_extract_checkout_completed,
        stripe_verify_and_parse_event,
    )
    from game.shop import process_paid_event

    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature") or ""
    ok, reason, event = stripe_verify_and_parse_event(payload, sig)
    if not ok or not event:
        return jsonify({"ok": False, "reason": reason}), 400

    extracted = stripe_extract_checkout_completed(event)
    if not extracted:
        # Acknowledge irrelevant event types.
        return jsonify({"ok": True, "reason": "ignored"}), 200

    conn = db()
    try:
        begin_write_transaction(conn)
        fok, freason, _order = process_paid_event(
            provider="stripe",
            event_id=str(extracted["event_id"]),
            order_id=extracted.get("order_id"),
            provider_session_id=extracted.get("provider_session_id"),
            provider_payment_id=extracted.get("provider_payment_id"),
            conn=conn,
            payload=event if isinstance(event, dict) else {"raw": True},
        )
        if fok or freason == "duplicate":
            commit(conn)
            return jsonify({"ok": True, "reason": freason}), 200
        rollback(conn)
        return jsonify({"ok": False, "reason": freason}), 400
    except Exception:
        rollback(conn)
        logger.exception("stripe webhook fulfill failed")
        return jsonify({"ok": False, "reason": "webhook_failed"}), 500
    finally:
        conn.close()


@app.route("/api/webhooks/paypal", methods=["POST"])
def api_webhook_paypal():
    from game.payment_providers import (
        paypal_capture_order,
        paypal_extract_payment_completed,
        paypal_verify_webhook,
    )
    from game.shop import process_paid_event

    payload = request.get_data()
    headers = {k: v for k, v in request.headers.items()}
    ok, reason, event = paypal_verify_webhook(headers=headers, body=payload)
    if not ok or not event:
        return jsonify({"ok": False, "reason": reason}), 400

    extracted = paypal_extract_payment_completed(event)
    if not extracted:
        return jsonify({"ok": True, "reason": "ignored"}), 200

    if extracted.get("needs_capture") and extracted.get("provider_session_id"):
        cok, creason, _cap = paypal_capture_order(str(extracted["provider_session_id"]))
        if not cok:
            return jsonify({"ok": False, "reason": creason}), 400

    conn = db()
    try:
        begin_write_transaction(conn)
        fok, freason, _order = process_paid_event(
            provider="paypal",
            event_id=str(extracted["event_id"]),
            order_id=extracted.get("order_id"),
            provider_session_id=extracted.get("provider_session_id"),
            provider_payment_id=extracted.get("provider_payment_id"),
            conn=conn,
            payload=event if isinstance(event, dict) else {"raw": True},
        )
        if fok or freason == "duplicate":
            commit(conn)
            return jsonify({"ok": True, "reason": freason}), 200
        rollback(conn)
        return jsonify({"ok": False, "reason": freason}), 400
    except Exception:
        rollback(conn)
        logger.exception("paypal webhook fulfill failed")
        return jsonify({"ok": False, "reason": "webhook_failed"}), 500
    finally:
        conn.close()


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
        state = _hud_only_game_state("api_referrals_apply")
        return jsonify({"ok": False, "reason": "server_error", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_referrals_apply")
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
        state = _hud_only_game_state("api_referrals_claim")
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state = _hud_only_game_state("api_referrals_claim")
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


@app.route("/api/imperial-directives/claim", methods=["POST"])
@require_login
def api_imperial_directives_claim():
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
        directive_id = int(data.get("directive_id") or 0)
    except (TypeError, ValueError):
        directive_id = 0

    from game.directives.rewards import claim_directive_reward
    from game.directives.service import get_imperial_directives_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_directive_reward(
            user_id,
            directive_id,
            conn=conn,
        )
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception(
            "imperial directive claim failed user_id=%s directive_id=%s",
            user_id,
            directive_id,
        )
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_imperial_directives_claim",
        )
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_imperial_directives_claim",
    )
    imperial_directives: Dict[str, Any] = {}
    conn2 = db()
    try:
        imperial_directives = get_imperial_directives_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "imperial_directives": imperial_directives,
    }
    if ok and claim_result:
        resp["claim"] = claim_result
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


@app.route("/api/imperial-directives/claim-all", methods=["POST"])
@require_login
def api_imperial_directives_claim_all():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.directives.rewards import claim_all_directive_rewards
    from game.directives.service import get_imperial_directives_state

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, claim_result = claim_all_directive_rewards(user_id, conn=conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("imperial directive claim-all failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_imperial_directives_claim_all",
        )
        return jsonify({"ok": False, "reason": "claim_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_imperial_directives_claim_all",
    )
    imperial_directives: Dict[str, Any] = {}
    conn2 = db()
    try:
        imperial_directives = get_imperial_directives_state(user_id, conn=conn2)
    finally:
        conn2.close()

    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
        "imperial_directives": imperial_directives,
    }
    if claim_result:
        resp["claim"] = claim_result
    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)
    return jsonify(resp)


# --------------------------------------------------------------------------
# IMPERIAL DIRECTIVES (GC-914B)
# --------------------------------------------------------------------------

@app.route("/api/imperial-directives/state")
@require_login
def api_imperial_directives_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    from game.directives.service import get_imperial_directives_state

    conn = db()
    try:
        imperial_directives = get_imperial_directives_state(user_id, conn=conn)
    finally:
        conn.close()

    return jsonify({"ok": True, "imperial_directives": imperial_directives})


@app.route("/imperial-directives")
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


@app.route("/api/initiation/state")
@require_login
def api_initiation_state():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401
    from game.initiation.service import get_initiation_state

    conn = db()
    try:
        initiation = get_initiation_state(user_id, conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, "initiation": initiation})


@app.route("/initiation")
@require_login
def initiation_view():
    ctx = _load_page_live_context(finish_source="initiation")
    if ctx is None:
        return redirect(url_for("login"))

    from game.initiation.service import get_initiation_state

    initiation = {"ready": False, "steps": [], "phases": [], "current": None}
    conn = db()
    try:
        initiation = get_initiation_state(int(session["user_id"]), conn=conn)
    finally:
        conn.close()

    return render_template(
        "initiation.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        initiation=initiation,
    )


@app.route("/api/story/state")
@require_login
def api_story_state():
    """Read-only story snapshot for UI focus — never ensure (write lock / hang on tab)."""
    user_id = int(session["user_id"])
    from game.story.service import get_story_state

    focus_pack = str(request.args.get("pack_id") or "").strip() or None
    focus_arc = str(request.args.get("arc_id") or "").strip() or None
    conn = db()
    try:
        story = get_story_state(
            user_id,
            conn=conn,
            ensure=False,
            focus_pack_id=focus_pack,
            focus_arc_id=focus_arc,
        )
    finally:
        conn.close()
    return jsonify({"ok": True, "story": story})


@app.route("/api/story/tts", methods=["POST"])
@require_login
def api_story_tts():
    """Neural story voice (edge-tts) — returns audio/mpeg."""
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400

    from game.i18n import current_locale
    from game.story.tts import synthesize_mp3

    audio, mime, err = synthesize_mp3(text, locale=current_locale())
    if err or not audio:
        # Transient Microsoft/edge failures → 503 so clients can retry Killian.
        code = 503 if err in ("edge_tts_missing", "tts_timeout", "empty_audio") or str(
            err or ""
        ).startswith("tts_failed") else 400
        return jsonify({"ok": False, "error": err or "tts_failed"}), code
    return Response(audio, mimetype=mime, headers={"Cache-Control": "private, max-age=3600"})


@app.route("/api/story/advance", methods=["POST"])
@require_login
def api_story_advance():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    body = request.get_json(silent=True) or {}
    pack_id = str(body.get("pack_id") or "").strip()
    arc_id = str(body.get("arc_id") or "").strip()
    if not pack_id or not arc_id:
        return jsonify({"ok": False, "error": "missing_arc"}), 400

    from game.queue_engine import finish_due_work_once
    from game.story.engine import advance_active_beat
    from game.story.service import get_story_state

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id,
            conn=conn,
            source="api_story_advance",
            manage_transaction=False,
        )
        result = advance_active_beat(
            user_id, pack_id=pack_id, arc_id=arc_id, conn=conn
        )
        if result.get("ok"):
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("story advance failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_story_advance",
        )
        return jsonify({"ok": False, "error": "advance_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_story_advance",
    )
    story: Dict[str, Any] = {}
    conn2 = db()
    try:
        # Mutation already ran ensure_player_story — avoid a second write lock.
        story = get_story_state(
            user_id,
            conn=conn2,
            ensure=False,
            focus_pack_id=pack_id,
            focus_arc_id=arc_id,
        )
    finally:
        conn2.close()

    ok = bool(result.get("ok"))
    return jsonify(
        {
            "ok": ok,
            "error": result.get("error"),
            "ark_tokens_gained": int(result.get("ark_tokens_gained") or 0) if ok else 0,
            "story": story,
            "state": state,
        }
    ), (200 if ok else 400)


@app.route("/api/story/free-shop/redeem", methods=["POST"])
@require_login
def api_story_free_shop_redeem():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    body = request.get_json(silent=True) or {}
    offer_id = str(body.get("offer_id") or "").strip()
    request_id = str(body.get("request_id") or request.headers.get("X-Request-Id") or "").strip()
    if not offer_id:
        return jsonify({"ok": False, "error": "missing_offer"}), 400

    from game.queue_engine import finish_due_work_once
    from game.story.free_shop import get_free_shop_state, redeem_free_shop_offer
    from game.story.service import get_story_state

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id,
            conn=conn,
            source="api_story_free_shop_redeem",
            manage_transaction=False,
        )
        result = redeem_free_shop_offer(
            user_id, offer_id=offer_id, conn=conn, request_id=request_id or None
        )
        if result.get("ok"):
            commit(conn)
        else:
            rollback(conn)
        free_shop = get_free_shop_state(user_id, conn=conn)
    except Exception:
        rollback(conn)
        logger.exception("story free shop redeem failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_story_free_shop_redeem",
        )
        return jsonify({"ok": False, "error": "redeem_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_story_free_shop_redeem",
    )
    story: Dict[str, Any] = {}
    conn2 = db()
    try:
        story = get_story_state(user_id, conn=conn2, ensure=False)
    finally:
        conn2.close()

    ok = bool(result.get("ok"))
    return jsonify(
        {
            "ok": ok,
            "error": result.get("error"),
            "free_shop": free_shop,
            "story": story,
            "state": state,
        }
    ), (200 if ok else 400)


@app.route("/api/story/choice", methods=["POST"])
@require_login
def api_story_choice():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    body = request.get_json(silent=True) or {}
    pack_id = str(body.get("pack_id") or "").strip()
    arc_id = str(body.get("arc_id") or "").strip()
    choice_id = str(body.get("choice_id") or "").strip()
    if not pack_id or not arc_id or not choice_id:
        return jsonify({"ok": False, "error": "missing_fields"}), 400

    from game.queue_engine import finish_due_work_once
    from game.story.engine import apply_choice
    from game.story.service import get_story_state

    conn = db()
    try:
        begin_write_transaction(conn)
        finish_due_work_once(
            player_id=user_id,
            conn=conn,
            source="api_story_choice",
            manage_transaction=False,
        )
        result = apply_choice(
            user_id,
            pack_id=pack_id,
            arc_id=arc_id,
            choice_id=choice_id,
            conn=conn,
        )
        if result.get("ok"):
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        logger.exception("story choice failed user_id=%s", user_id)
        state, _ = _build_game_state_payload(
            include_panel=True,
            finish_source="api_story_choice",
        )
        return jsonify({"ok": False, "error": "choice_failed", "state": state}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_story_choice",
    )
    story: Dict[str, Any] = {}
    conn2 = db()
    try:
        story = get_story_state(
            user_id,
            conn=conn2,
            ensure=False,
            focus_pack_id=pack_id,
            focus_arc_id=arc_id,
        )
    finally:
        conn2.close()

    ok = bool(result.get("ok"))
    return jsonify(
        {
            "ok": ok,
            "error": result.get("error"),
            "ark_tokens_gained": int(result.get("ark_tokens_gained") or 0) if ok else 0,
            "story": story,
            "state": state,
        }
    ), (200 if ok else 400)


@app.route("/story")
@require_login
def story_view():
    ctx = _load_page_live_context(finish_source="story")
    if ctx is None:
        return redirect(url_for("login"))

    from game.story.service import get_story_state

    story = {"ready": False, "arcs": [], "focus": None, "lore_fragments": []}
    conn = db()
    try:
        story = get_story_state(int(session["user_id"]), conn=conn)
    finally:
        conn.close()

    return render_template(
        "story.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        story=story,
    )


# RANKING PAGE
# --------------------------------------------------------------------------

@app.route("/ranking")
@require_login
def ranking_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "ranking"
    )
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


# --------------------------------------------------------------------------
# UNIVERSE SEARCH (GC-880)
# --------------------------------------------------------------------------

@app.route("/search")
@require_login
def search_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "search"
    )
    if player_view is None:
        return redirect(url_for("login"))

    q = str(request.args.get("q") or "").strip()
    stype = str(request.args.get("type") or "player").strip().lower()
    if stype not in SEARCH_TYPES:
        stype = "player"
    initial = None
    if q:
        initial = search_universe(q, stype)

    return render_template(
        "search.html",
        player=player_view,
        buildings=buildings,
        energy_total=energy_total,
        energy_used=energy_used,
        storage_caps=storage_caps,
        search_query=q,
        search_type=stype,
        search_payload=initial,
    )


@app.route("/api/search")
@require_login
def api_search():
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in", "results": [], "meta": {}}), 401
    q = str(request.args.get("q") or "").strip()
    stype = str(request.args.get("type") or "player").strip().lower()
    try:
        payload = search_universe(q, stype)
        return jsonify(payload)
    except Exception:
        return jsonify(
            {
                "ok": False,
                "error": "search_unavailable",
                "results": [],
                "meta": {"query": q, "type": stype, "coord_jump": None},
            }
        ), 500


@app.route("/records")
@require_login
def records_view():
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "records"
    )
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


@app.route("/banned-players")
@require_login
def banned_players_view():
    ctx = _load_page_live_context(finish_source="banned_players")
    if ctx is None:
        return redirect(url_for("login"))

    banned_players = admin_logic.get_public_ban_list()
    return render_template(
        "banned_players.html",
        player=ctx["player_view"],
        storage_caps=ctx["storage_caps"],
        banned_players=banned_players,
    )


@app.route("/chat/popout")
@require_login
def chat_popout_view():
    """Standalone chat window (GC-CHAT-POPOUT) — for second-monitor setups.

    Reuses the normal in-game layout/boot so chat.js's existing bootstrap
    (auth, i18n, CSRF, GC.* namespace) works unchanged; base.html hides
    everything except the chat panel via the CHAT_POPOUT body class.
    """
    return render_template("chat_popout.html", CHAT_POPOUT=True)


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
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "hall_of_fame"
    )
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


@app.route("/world-boss")
@require_login
def world_boss_view():
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


@app.route("/api/world-boss")
@require_login_api
def api_world_boss():
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    try:
        from game.world_boss import build_world_boss_payload

        event_id = request.args.get("event_id", type=int)
        conn = db()
        try:
            # GET must never become an attack transaction merely by polling.
            payload = build_world_boss_payload(player_id, conn=conn, event_id=event_id)
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_unavailable"}), 500


@app.route("/api/world-boss/attack", methods=["POST"])
@require_login_api
def api_world_boss_attack():
    """GC-WB-ATTACK-002 — instant World Boss strike (no fleet flight, no ship losses)."""
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(int(player_id), request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        event_id = int(data.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    if event_id <= 0:
        return jsonify({"ok": False, "error": "invalid_event"}), 400

    raw_ships = data.get("ships") if isinstance(data.get("ships"), dict) else {}
    ships: Dict[str, int] = {}
    for key, amount in raw_ships.items():
        try:
            qty = int(amount or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            ships[str(key)] = qty
    auto_select = bool(data.get("auto_select") or data.get("world_boss_auto_attack"))
    try:
        hit_mult = int(data.get("hit_mult") or 1)
    except (TypeError, ValueError):
        hit_mult = 1

    from game.db import begin_write_transaction, commit, rollback
    from game.planet_evolution.repository import get_context_planet
    from game.world_boss import execute_instant_attack

    conn = db()
    result: Dict[str, Any] = {"ok": False, "error": "world_boss_attack_failed"}
    try:
        begin_write_transaction(conn)
        try:
            planet = get_context_planet(int(player_id), conn=conn)
            if not planet:
                rollback(conn)
                return jsonify({"ok": False, "error": "origin_not_found"}), 400
            result = execute_instant_attack(
                int(player_id),
                event_id,
                ships,
                planet_id=int(planet["id"]),
                conn=conn,
                auto_select=auto_select or not ships,
                hit_mult=hit_mult,
            )
            if result.get("ok"):
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_attack_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_world_boss_attack",
    )
    body: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "attack": result.get("attack"),
        "boss": result.get("boss"),
        "player": result.get("player"),
        "state": state,
    }
    if not result.get("ok"):
        body["error"] = result.get("error") or "world_boss_attack_failed"
    status = 200 if result.get("ok") else 400
    if request_id and result.get("ok"):
        save_idempotent_action(int(player_id), request_id, body)
    return jsonify(body), status


@app.route("/api/world-boss/auto-attack", methods=["POST"])
@require_login_api
def api_world_boss_auto_attack():
    """GC-WB-AUTO-004 — toggle server auto-attack; enable may fire an immediate strike."""
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    try:
        event_id = int(data.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    if event_id <= 0:
        return jsonify({"ok": False, "error": "invalid_event"}), 400
    enabled = bool(data.get("enabled"))
    raw_ships = data.get("ships") if isinstance(data.get("ships"), dict) else {}
    ships: Dict[str, int] = {}
    for key, amount in raw_ships.items():
        try:
            qty = int(amount or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            ships[str(key)] = qty

    from game.db import begin_write_transaction, commit, rollback
    from game.planet_evolution.repository import get_context_planet
    from game.world_boss import set_world_boss_auto_attack

    conn = db()
    result: Dict[str, Any] = {"ok": False}
    try:
        begin_write_transaction(conn)
        try:
            planet = get_context_planet(int(player_id), conn=conn)
            if not planet:
                rollback(conn)
                return jsonify({"ok": False, "error": "origin_not_found"}), 400
            result = set_world_boss_auto_attack(
                int(player_id),
                event_id,
                enabled=enabled,
                planet_id=int(planet["id"]),
                ships=ships,
                conn=conn,
                auto_select=bool(data.get("auto_select", True)) or not ships,
            )
            if result.get("ok"):
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_auto_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_world_boss_auto_attack",
    )
    body = {
        "ok": bool(result.get("ok")),
        "auto_attack": result,
        "attack": result.get("attack"),
        "boss": result.get("boss"),
        "player": result.get("player"),
        "state": state,
    }
    if not result.get("ok"):
        body["error"] = result.get("error") or "world_boss_auto_failed"
    return jsonify(body), (200 if result.get("ok") else 400)


@app.route("/api/world-boss/claim", methods=["POST"])
@require_login_api
def api_world_boss_claim():
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    try:
        event_id = int(data.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    if event_id <= 0:
        return jsonify({"ok": False, "error": "invalid_event"}), 400

    from game.db import begin_write_transaction, commit, rollback
    from game.world_boss import claim_world_boss_rewards

    conn = db()
    result: Dict[str, Any] = {"ok": False}
    try:
        begin_write_transaction(conn)
        try:
            result = claim_world_boss_rewards(int(player_id), event_id, conn=conn)
            if result.get("ok"):
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_claim_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source="api_world_boss_claim",
    )
    status = 200 if result.get("ok") else 400
    return jsonify({"ok": bool(result.get("ok")), "claim": result, "state": state}), status


@app.route("/api/world-boss/catch", methods=["POST"])
@require_login_api
def api_world_boss_catch():
    """GC-WB-TAME-01 — Phase-3 tame attempt (10h TK, 10% roll, catch cooldown)."""
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(int(player_id), request_id)
        if cached is not None:
            return jsonify(cached)

    try:
        event_id = int(data.get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    if event_id <= 0:
        return jsonify({"ok": False, "error": "invalid_event"}), 400

    from game.db import begin_write_transaction, commit, rollback
    from game.world_boss_companions import attempt_tame

    conn = db()
    result: Dict[str, Any] = {"ok": False, "error": "world_boss_catch_failed"}
    try:
        begin_write_transaction(conn)
        try:
            result = attempt_tame(int(player_id), event_id, conn=conn)
            if result.get("ok"):
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_catch_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        panel_page="overview",
        finish_source="api_world_boss_catch",
    )
    body: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "catch": result,
        "state": state,
    }
    if not result.get("ok"):
        body["error"] = result.get("error") or "world_boss_catch_failed"
    status = 200 if result.get("ok") else 400
    if request_id and result.get("ok"):
        save_idempotent_action(int(player_id), request_id, body)
    return jsonify(body), status


@app.route("/api/world-boss/companion/mission", methods=["POST"])
@require_login_api
def api_world_boss_companion_mission():
    """GC-WB-TAME-05 — start or claim companion Ark-Token mission."""
    player_id = _current_player_id()
    if player_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(int(player_id), request_id)
        if cached is not None:
            return jsonify(cached)

    boss_key = str(data.get("boss_key") or "").strip()
    action = str(data.get("action") or "start").strip().lower()
    variant_key = str(data.get("variant_key") or "strike").strip().lower()
    if not boss_key:
        return jsonify({"ok": False, "error": "invalid_boss"}), 400
    if action not in ("start", "claim", "sync"):
        return jsonify({"ok": False, "error": "invalid_action"}), 400

    from game.db import begin_write_transaction, commit, rollback
    from game.world_boss_companions import (
        claim_mission_reward,
        start_companion_mission,
        sync_companion_mission,
    )

    conn = db()
    result: Dict[str, Any] = {"ok": False, "error": "companion_mission_failed"}
    try:
        begin_write_transaction(conn)
        try:
            if action == "claim":
                result = claim_mission_reward(int(player_id), boss_key, conn=conn)
            elif action == "sync":
                result = sync_companion_mission(int(player_id), boss_key, conn=conn)
            else:
                result = start_companion_mission(
                    int(player_id),
                    boss_key,
                    conn=conn,
                    variant_key=variant_key,
                    request_id=request_id,
                )
            if result.get("ok"):
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        return jsonify({"ok": False, "error": "companion_mission_failed"}), 500
    finally:
        conn.close()

    state, _ = _build_game_state_payload(
        include_panel=True,
        panel_page="overview",
        finish_source="api_world_boss_companion_mission",
    )
    body: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "mission": result,
        "state": state,
    }
    if not result.get("ok"):
        body["error"] = result.get("error") or "companion_mission_failed"
    status = 200 if result.get("ok") else 400
    if request_id and result.get("ok") and action != "sync":
        save_idempotent_action(int(player_id), request_id, body)
    return jsonify(body), status


@app.route("/api/admin/world-boss", methods=["GET"])
@require_admin_api
def api_admin_world_boss():
    """Admin status + catalog for World Boss LiveOps tab."""
    try:
        from game.world_boss import build_world_boss_payload, list_definitions

        conn = db()
        try:
            payload = build_world_boss_payload(None, conn=conn)
            defs = list_definitions(conn=conn, active_only=True)
        finally:
            conn.close()
        return jsonify(
            {
                "ok": True,
                "ready": bool(payload.get("ready")),
                "event": payload.get("event"),
                "schedule": payload.get("schedule") or {},
                "definitions": defs,
                "server_now": payload.get("server_now"),
            }
        )
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_unavailable"}), 500


@app.route("/api/admin/story/packs", methods=["GET"])
@require_admin_api
def api_admin_story_packs():
    """GC-2505: read-only Story Ops pack preview."""
    try:
        from game.story.service import admin_preview_packs

        return jsonify({"ok": True, **admin_preview_packs()})
    except Exception:
        logger.exception("admin story packs preview failed")
        return jsonify({"ok": False, "error": "story_packs_failed"}), 500


@app.route("/api/admin/world-boss/spawn", methods=["POST"])
@require_admin_api
def api_admin_world_boss_spawn():
    data = request.get_json(silent=True) or {}
    boss_key = str(data.get("boss_key") or "").strip()
    if not boss_key:
        return jsonify({"ok": False, "error": "boss_key_required"}), 400
    from game.db import begin_write_transaction, commit, rollback
    from game.world_boss import spawn_world_boss

    conn = db()
    try:
        begin_write_transaction(conn)
        try:
            g = data.get("galaxy")
            s = data.get("system")
            p = data.get("position")
            result = spawn_world_boss(
                boss_key,
                conn=conn,
                galaxy=int(g) if g is not None and str(g).strip() != "" else None,
                system=int(s) if s is not None and str(s).strip() != "" else None,
                position=int(p) if p is not None and str(p).strip() != "" else None,
                force=bool(data.get("force")),
                announce=bool(data.get("announce", True)),
            )
            if not result.get("ok"):
                rollback(conn)
                return jsonify(result), 400
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        return jsonify(result)
    except Exception:
        return jsonify({"ok": False, "error": "world_boss_spawn_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/pirates", methods=["GET"])
@require_admin_api
def api_admin_pirates():
    """Admin Bot-Log + KPIs + kill-switch status (EPIC-21 / GC-P08)."""
    try:
        from game.pirates.admin import build_admin_pirates_payload

        limit_raw = request.args.get("limit", "80")
        try:
            limit = max(1, min(200, int(limit_raw)))
        except (TypeError, ValueError):
            limit = 80
        conn = db()
        try:
            payload = build_admin_pirates_payload(conn, log_limit=limit)
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "pirates_admin_unavailable"}), 500


@app.route("/api/admin/pirates/ai", methods=["POST"])
@require_admin_api
def api_admin_pirates_ai():
    """Kill-switch: soft on/off, or hard-off (recall pirate outbound fleets)."""
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "soft").strip().lower()
    from game.db import begin_write_transaction, commit, rollback
    from game.pirates.admin import admin_hard_disable_ai, admin_set_ai

    if mode == "hard":
        conn = db()
        try:
            begin_write_transaction(conn)
            try:
                result = admin_hard_disable_ai(conn)
                commit(conn)
            except Exception:
                rollback(conn)
                raise
            return jsonify(result)
        except Exception:
            return jsonify({"ok": False, "error": "pirates_ai_hard_off_failed"}), 500
        finally:
            conn.close()

    if "enabled" not in data:
        return jsonify({"ok": False, "error": "enabled_required"}), 400
    enabled = bool(data.get("enabled"))
    conn = db()
    try:
        begin_write_transaction(conn)
        try:
            result = admin_set_ai(conn, enabled)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        return jsonify(result)
    except Exception:
        return jsonify({"ok": False, "error": "pirates_ai_toggle_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/pirates/force-spawn", methods=["POST"])
@require_admin_api
def api_admin_pirates_force_spawn():
    """LiveOps: force-spawn a pirate base in hottest (or given) galaxy (GC-P19)."""
    data = request.get_json(silent=True) or {}
    galaxy_raw = data.get("galaxy_id")
    galaxy_id = None
    if galaxy_raw is not None and str(galaxy_raw).strip() != "":
        try:
            galaxy_id = int(galaxy_raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid_galaxy_id"}), 400
    from game.db import begin_write_transaction, commit, rollback
    from game.pirates.admin import admin_force_spawn_hottest

    conn = db()
    try:
        begin_write_transaction(conn)
        try:
            result = admin_force_spawn_hottest(conn, galaxy_id=galaxy_id)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception:
        return jsonify({"ok": False, "error": "pirates_force_spawn_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/pirates/force-tick", methods=["POST"])
@require_admin_api
def api_admin_pirates_force_tick():
    """LiveOps: run one bot-play-loop tick now (economy + missions) (GC-2613)."""
    from game.db import begin_write_transaction, commit, rollback
    from game.pirates.admin import admin_force_tick

    conn = db()
    try:
        begin_write_transaction(conn)
        try:
            result = admin_force_tick(conn)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception:
        return jsonify({"ok": False, "error": "pirates_force_tick_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/inactive-autoplay", methods=["GET"])
@require_admin_api
def api_admin_inactive_autoplay():
    """Admin KPIs + kill-switch status for Inactive Autoplay (EPIC-26 / GC-2608)."""
    try:
        from game.inactive_autoplay_admin import build_admin_inactive_autoplay_payload

        conn = db()
        try:
            payload = build_admin_inactive_autoplay_payload(conn)
        finally:
            conn.close()
        return jsonify(payload)
    except Exception:
        return jsonify({"ok": False, "error": "inactive_autoplay_admin_unavailable"}), 500


@app.route("/api/admin/inactive-autoplay/toggle", methods=["POST"])
@require_admin_api
def api_admin_inactive_autoplay_toggle():
    """Kill-switch: Soft-On/Off for Inactive Autoplay (mirrors pirates AI toggle)."""
    data = request.get_json(silent=True) or {}
    if "enabled" not in data:
        return jsonify({"ok": False, "error": "enabled_required"}), 400
    enabled = bool(data.get("enabled"))
    from game.db import begin_write_transaction, commit, rollback
    from game.inactive_autoplay_admin import admin_set_inactive_autoplay

    conn = db()
    try:
        begin_write_transaction(conn)
        try:
            result = admin_set_inactive_autoplay(conn, enabled)
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        return jsonify(result)
    except Exception:
        return jsonify({"ok": False, "error": "inactive_autoplay_toggle_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/inactive-autoplay/force-tick", methods=["POST"])
@require_admin_api
def api_admin_inactive_autoplay_force_tick():
    """LiveOps: wake/tick the sticky roster now, bypassing the wake interval (GC-2613).

    GC-PERF-AUTOPLAY-001: do not wrap the whole tick in one BEGIN IMMEDIATE —
    `run_inactive_autoplay_tick` owns short per-player write transactions.
    """
    from game.inactive_autoplay_admin import admin_force_tick_inactive_autoplay

    conn = db()
    try:
        result = admin_force_tick_inactive_autoplay(conn)
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception:
        return jsonify({"ok": False, "error": "inactive_autoplay_force_tick_failed"}), 500
    finally:
        conn.close()


@app.route("/api/admin/galactic-directives/force", methods=["POST"])
@require_admin_api
def api_admin_galactic_directives_force():
    """LiveOps: force-set galactic directive mandate for a galaxy (GC-720I)."""
    data = request.get_json(silent=True) or {}
    try:
        galaxy_id = int(data.get("galaxy_id") or data.get("galaxy") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_galaxy_id"}), 400
    primary = str(data.get("primary") or data.get("primary_key") or "").strip()
    secondary_raw = data.get("secondary", data.get("secondary_key"))
    secondary = None if secondary_raw in (None, "") else str(secondary_raw).strip()
    from game.galactic_directives import admin_force_directive

    result = admin_force_directive(galaxy_id, primary, secondary)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/admin/galactic-directives/unforce", methods=["POST"])
@require_admin_api
def api_admin_galactic_directives_unforce():
    """LiveOps: re-open galactic directive voting for a galaxy (GC-720I)."""
    data = request.get_json(silent=True) or {}
    try:
        galaxy_id = int(data.get("galaxy_id") or data.get("galaxy") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_galaxy_id"}), 400
    reset_state = bool(data.get("reset_state") or False)
    from game.galactic_directives import admin_unforce_directive

    result = admin_unforce_directive(galaxy_id, reset_state=reset_state)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


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


@app.route("/api/admin/combat-bots/ensure", methods=["POST"])
@require_admin_api
def api_admin_combat_bots_ensure():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    conn = db()
    try:
        from game.db import begin_write_transaction, commit
        from game.combat_balance_bots import ensure_combat_balance_bots

        begin_write_transaction(conn)
        payload = ensure_combat_balance_bots(conn=conn)
        commit(conn)
        if admin_id:
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "combat_bots_ensure",
                    target_type="system",
                    payload={"alpha_id": payload["alpha"]["player_id"], "beta_id": payload["beta"]["player_id"]},
                )
            except Exception:
                pass
        return jsonify(payload)
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/admin/combat-bots/run-scenario", methods=["POST"])
@require_admin_api
def api_admin_combat_bots_run_scenario():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    body = request.get_json(silent=True) or {}
    scenario_key = str(body.get("scenario_key") or "").strip()
    force = bool(body.get("force"))
    if not scenario_key:
        return jsonify({"ok": False, "error": "missing_scenario_key"}), 400
    conn = db()
    try:
        from game.db import begin_write_transaction, commit
        from game.combat_balance_bots import run_combat_balance_scenario

        begin_write_transaction(conn)
        result = run_combat_balance_scenario(
            scenario_key,
            conn=conn,
            force=force,
            skip_cooldown=force,
        )
        if result.get("ok"):
            commit(conn)
        else:
            conn.rollback()
        if admin_id and result.get("ok"):
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "combat_bots_run_scenario",
                    target_type="scenario",
                    target_id=scenario_key,
                    payload={
                        "run_id": result.get("run_id"),
                        "fleet_movement_id": result.get("fleet_movement_id"),
                        "flight_seconds": result.get("flight_seconds"),
                    },
                )
            except Exception:
                pass
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/admin/combat-bots/run-next-scenario", methods=["POST"])
@require_admin_api
def api_admin_combat_bots_run_next_scenario():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    conn = db()
    try:
        from game.db import begin_write_transaction, commit
        from game.combat_balance_bots import advance_scenario_index, resolve_next_scenario_key, run_combat_balance_scenario

        key = resolve_next_scenario_key(conn=conn)
        begin_write_transaction(conn)
        result = run_combat_balance_scenario(
            key,
            conn=conn,
            force=force,
            skip_cooldown=force,
        )
        if result.get("ok"):
            advance_scenario_index(conn=conn)
            commit(conn)
        else:
            conn.rollback()
        if admin_id and result.get("ok"):
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "combat_bots_run_next_scenario",
                    target_type="scenario",
                    target_id=key,
                    payload={"fleet_movement_id": result.get("fleet_movement_id")},
                )
            except Exception:
                pass
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/admin/combat-bots/toggle", methods=["POST"])
@require_admin_api
def api_admin_combat_bots_toggle():
    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify({"ok": False, "error": "missing_enabled"}), 400
    enabled = bool(body.get("enabled"))
    conn = db()
    try:
        from game.db import begin_write_transaction, commit
        from game.combat_balance_bots import (
            LOCAL_BALANCE_TEST_HINT,
            live_combat_balance_bots_allowed,
            set_combat_balance_bots_enabled,
        )

        begin_write_transaction(conn)
        if enabled and not live_combat_balance_bots_allowed():
            conn.rollback()
            return jsonify(
                {
                    "ok": False,
                    "error": "live_bots_disabled",
                    "hint": LOCAL_BALANCE_TEST_HINT,
                }
            ), 403
        if not set_combat_balance_bots_enabled(enabled, conn=conn):
            conn.rollback()
            return jsonify(
                {
                    "ok": False,
                    "error": "live_bots_disabled",
                    "hint": LOCAL_BALANCE_TEST_HINT,
                }
            ), 403
        commit(conn)
        if admin_id:
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "combat_bots_toggle",
                    target_type="system",
                    payload={"enabled": enabled},
                )
            except Exception:
                pass
        return jsonify({"ok": True, "enabled": enabled})
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/admin/combat-bots/results", methods=["GET"])
@require_admin_api
def api_admin_combat_bots_results():
    limit_raw = request.args.get("limit", "20")
    try:
        limit = max(1, min(200, int(limit_raw)))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_limit"}), 400
    conn = db()
    try:
        from game.combat_balance_bots import (
            get_combat_balance_bots_snapshot,
            list_combat_balance_results,
        )

        return jsonify(
            {
                "ok": True,
                "results": list_combat_balance_results(conn=conn, limit=limit),
                "status": {
                    **get_combat_balance_bots_snapshot(conn=conn),
                    "recent_results": list_combat_balance_results(conn=conn, limit=10),
                },
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/admin/rankings/recalculate", methods=["POST"])
@require_admin_api
def api_admin_recalculate_rankings():
    """Legacy alias — prefer POST /api/admin/ranking/recompute."""
    return api_admin_ranking_recompute()


@app.route("/api/admin/ranking/recompute", methods=["POST"])
@require_admin_api
def api_admin_ranking_recompute():
    """Admin manual ranking batch (same job as HTTP cron, force=1, session auth)."""
    from game.internal_cron import handle_admin_ranking_recompute

    admin = get_current_user()
    admin_id = int(admin["id"]) if admin else 0
    try:
        payload, status = handle_admin_ranking_recompute()
        if admin_id and payload.get("ok"):
            try:
                from game.admin_audit import write_admin_audit

                write_admin_audit(
                    admin_id,
                    "admin_ranking_recompute",
                    target_type="system",
                    payload={
                        "players_seen": payload.get("players_seen"),
                        "players_updated": payload.get("players_updated"),
                        "ranks_assigned": payload.get("ranks_assigned"),
                        "duration_ms": payload.get("duration_ms"),
                    },
                )
            except Exception:
                logger.exception("admin ranking recompute audit failed")
        return jsonify(payload), status
    except Exception as exc:
        logger.exception("api_admin_ranking_recompute failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/admin/votes/stats", methods=["GET"])
@require_admin_api
def api_admin_votes_stats():
    from game.db import db
    from game.vote_rewards import build_admin_vote_stats

    conn = db()
    try:
        payload = build_admin_vote_stats(conn=conn)
    finally:
        conn.close()
    return jsonify({"ok": True, **payload})


@app.route("/api/admin/votes/players", methods=["GET"])
@require_admin_api
def api_admin_votes_players():
    from game.db import db
    from game.vote_rewards import search_admin_vote_players

    q = str(request.args.get("q") or "").strip()
    activity = str(request.args.get("activity") or "all").strip().lower()
    try:
        limit = int(request.args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    conn = db()
    try:
        payload = search_admin_vote_players(
            conn=conn,
            q=q,
            activity=activity,
            limit=limit,
            offset=offset,
        )
    finally:
        conn.close()
    return jsonify(payload)


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


@app.route("/api/admin/universe-news/publish-release", methods=["POST"])
@require_admin_api
def api_admin_universe_news_publish_release():
    return _admin_json(
        admin_api_logic.api_publish_universe_news_release(_admin_actor_id(), _admin_body())
    )


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


@app.route("/api/admin/events", methods=["GET"])
@require_admin_api
def api_admin_events_list():
    return _admin_json(admin_api_logic.api_get_server_events())


@app.route("/api/admin/events", methods=["POST"])
@require_admin_api
def api_admin_events_create():
    return _admin_json(admin_api_logic.api_create_server_event(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/events/<int:event_id>", methods=["PATCH"])
@require_admin_api
def api_admin_events_update(event_id: int):
    return _admin_json(
        admin_api_logic.api_update_server_event(_admin_actor_id(), event_id, _admin_body())
    )


@app.route("/api/admin/events/<int:event_id>", methods=["DELETE"])
@require_admin_api
def api_admin_events_delete(event_id: int):
    return _admin_json(admin_api_logic.api_delete_server_event(_admin_actor_id(), event_id))


@app.route("/api/admin/events/<int:event_id>/delete", methods=["POST"])
@require_admin_api
def api_admin_events_delete_post(event_id: int):
    return _admin_json(admin_api_logic.api_delete_server_event(_admin_actor_id(), event_id))


@app.route("/api/admin/events/presets", methods=["GET"])
@require_admin_api
def api_admin_events_presets_list():
    return _admin_json(admin_api_logic.api_list_event_presets())


@app.route("/api/admin/events/presets/<preset_id>/apply", methods=["POST"])
@require_admin_api
def api_admin_events_preset_apply(preset_id: str):
    return _admin_json(
        admin_api_logic.api_apply_event_preset(_admin_actor_id(), preset_id, _admin_body())
    )


@app.route("/api/admin/events/schedules", methods=["GET"])
@require_admin_api
def api_admin_events_schedules_list():
    return _admin_json(admin_api_logic.api_list_event_schedules())


@app.route("/api/admin/events/schedules/<int:schedule_id>", methods=["PATCH"])
@require_admin_api
def api_admin_events_schedule_patch(schedule_id: int):
    return _admin_json(
        admin_api_logic.api_set_event_schedule_enabled(
            _admin_actor_id(), schedule_id, _admin_body()
        )
    )


@app.route("/api/admin/events/schedules/<int:schedule_id>/materialize", methods=["POST"])
@require_admin_api
def api_admin_events_schedule_materialize(schedule_id: int):
    return _admin_json(
        admin_api_logic.api_materialize_event_schedule(
            _admin_actor_id(), schedule_id, _admin_body()
        )
    )


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
        sync_badges = viewer_id is not None and int(viewer_id) == int(player_id)
        card, err = playercard_logic.build_public_card(
            player_id,
            viewer_id=viewer_id,
            sync_badges=sync_badges,
        )
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
        "aura_key": card.get("aura_key") or "none",
        "title_flair": card.get("title_flair") or "none",
        "name_style": card.get("name_style") or "none",
        "title": card.get("title") or "",
        "avatar_initial": (card.get("commander_name_raw") or "?")[:1],
        "badges": card.get("badges") or [],
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


@app.route("/api/planet/relocation/start", methods=["POST"])
@require_login_api
def api_planet_relocation_start():
    pid = _current_player_id()
    assert pid is not None
    payload = request.get_json(silent=True) or {}
    meta = _options_request_meta()
    try:
        galaxy = int(payload.get("galaxy") or payload.get("target_galaxy") or 0)
        system = int(payload.get("system") or payload.get("target_system") or 0)
        position = int(payload.get("position") or payload.get("target_position") or 0)
    except (TypeError, ValueError):
        return _action_json_response(
            False,
            "planet_relocation_invalid_coords",
            None,
            finish_source="api_planet_relocation_start",
        )
    from game.galaxy import start_planet_relocation

    ok, err, data = start_planet_relocation(
        int(pid),
        galaxy,
        system,
        position,
        ip=meta["ip"],
        user_agent=meta["user_agent"],
    )
    return _action_json_response(
        ok,
        err,
        data if ok else data,
        finish_source="api_planet_relocation_start",
    )


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
    if raw not in SUPPORTED_LANGUAGES:
        return _options_api_response(False, "options_error_invalid_locale", None, 400)
    loc = normalize_locale(raw)
    from flask import make_response

    body, status = _options_api_response(True, None, {"locale": loc})
    resp = make_response(body, status)
    resp.set_cookie("gc_locale", loc, max_age=365 * 24 * 3600, samesite="Lax")
    return resp


@app.route("/api/options/notify-sounds", methods=["POST"])
@require_login_api
def api_options_notify_sounds():
    pid = session.get("user_id")
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)
    payload = request.get_json(silent=True) or {}
    ok, err, data = options_logic.update_notify_sounds(
        int(pid),
        notify_attack_sound=payload.get("notify_attack_sound"),
        notify_message_sound=payload.get("notify_message_sound"),
        sfx_ui_sound=payload.get("sfx_ui_sound"),
        sfx_combat_sound=payload.get("sfx_combat_sound"),
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/options/spy-probes", methods=["POST"])
@require_login_api
def api_options_spy_probes():
    pid = session.get("user_id")
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)
    payload = request.get_json(silent=True) or {}
    ok, err, data = options_logic.update_spy_probe_settings(
        int(pid),
        default_spy_probes=payload.get("default_spy_probes"),
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


@app.route("/api/options/buildings-ui", methods=["POST"])
@require_login_api
def api_options_buildings_ui():
    pid = session.get("user_id")
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)
    payload = request.get_json(silent=True) or {}
    mark_done = bool(payload.get("mark_choice_done"))
    ok, err, data = options_logic.update_buildings_ui_settings(
        int(pid),
        buildings_ui_mode=payload.get("buildings_ui_mode"),
        mark_choice_done=mark_done,
    )
    if not ok:
        return _options_api_response(False, err, data, 400)
    return _options_api_response(True, err, data)


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


@app.route("/api/options/data-export", methods=["GET"])
@require_login_api
def api_options_data_export():
    """DSGVO Auskunft — JSON download of personal data."""
    from flask import Response
    import json as _json

    pid = _current_player_id()
    if not pid:
        return _options_api_response(False, "not_logged_in", None, 401)
    if not check_register_rate_limit(client_ip(request)):
        # reuse rate limit bucket loosely; prefer dedicated if available
        pass
    payload = options_logic.export_player_personal_data(int(pid))
    body = _json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="genesis-colonies-data-{int(pid)}.json"'
        },
    )


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
    player_view, buildings, _, energy_total, energy_used, storage_caps = _load_player_view_with_resources(
        "messages"
    )
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
    except Exception as exc:
        rollback(conn)
        from game.db import is_db_lock_error

        if is_db_lock_error(exc):
            app.logger.warning(
                "fleet write lock_busy — soft skip (%s)",
                type(exc).__name__,
            )
            return False, "lock_busy", {"retry": True}
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
    panel_page: str = "",
    panel_tab: Optional[str] = None,
    conn=None,
) -> Dict[str, Any]:
    """Build JSON payload from an already-refreshed live context."""
    from game.logic import get_research_modifiers
    from game.live_state import perf_span

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
    mods = get_research_modifiers(user_id, conn=conn)

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

    # Diet polls strip catalogs in apply_lightweight_game_state_diet (attach-then-strip).
    if lightweight:
        payload.pop("buildings", None)
        payload.pop("building_queue", None)
        payload.pop("research_queue", None)

    try:
        from game.timekeeper import serialize_for_client

        payload["timekeeper"] = serialize_for_client(int(user_id), conn=conn)
    except Exception:
        payload["timekeeper"] = {"ready": False, "balance_sec": 0, "label": "0min"}

    try:
        from game.commander_classes import serialize_for_client as serialize_commander

        payload["commander"] = serialize_commander(int(user_id), conn=conn)
    except Exception:
        payload["commander"] = {"ready": False}

    # GC-PERF-PANEL-SCOPE-002: heavy catalogs only for resolved panel_page (never unscoped all).
    from game.live_state import record_request_perf_phase, set_request_perf_meta

    page = _normalize_panel_page(panel_page)
    heavy = _heavy_panels_for_page(page) if include_panel else frozenset()
    panels_built: List[str] = []
    panel_block_t0 = time.perf_counter()

    with perf_span("payload.panel"):
        if include_panel and "overview" in heavy:
            from game.buildings import get_overview_building_rows
            from game.overview_page import build_overview_status

            with perf_span("panel.overview_rows"):
                payload["overview"]["rows"] = get_overview_building_rows(
                    planet, buildings, build_queue=build_queue
                )
            with perf_span("panel.overview_status"):
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
            panels_built.append("overview")

        if include_panel and "buildings" in heavy:
            from game.buildings import get_buildings_panel_rows

            with perf_span("panel.buildings_rows"):
                payload["buildings_panel"] = get_buildings_panel_rows(
                    planet,
                    buildings,
                    build_queue=build_queue,
                    active_tab=panel_tab if page == "buildings" else None,
                    conn=conn,
                )
            panels_built.append("buildings")

        if panel_delta_keys:
            from game.buildings import get_buildings_panel_delta

            with perf_span("panel.buildings_delta"):
                payload["buildings_panel_delta"] = get_buildings_panel_delta(
                    planet,
                    buildings,
                    build_queue=build_queue,
                    building_keys=panel_delta_keys,
                    conn=conn,
                )
            if "buildings_delta" not in panels_built:
                panels_built.append("buildings_delta")

    active_planet_id = int(planet.get("id") or 0)
    payload["active_planet_id"] = active_planet_id
    payload["active_planet_name"] = str(planet.get("name") or "")
    with perf_span("payload.active_planet"):
        try:
            from game.galaxy import get_planet_coordinates
            from game.planet_evolution.dna import effective_planet_class
            from game.planet_evolution.ux_copy import planet_class_label_key

            from game.planet_visuals import (
                get_planet_identity_for_position,
                herocard_webp_srcset_for_position,
                landscape_static_relpath,
                OVERVIEW_HEROCARD_SIZES,
                raster_webp_relpath,
            )

            coords = get_planet_coordinates(planet)
            position = int(coords.get("position") or 0)
            landscape_rel = landscape_static_relpath(position)
            herocard_rel = landscape_rel
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
                "landscape_url": versioned_static_url("static", filename=landscape_rel),
                "landscape_webp_url": versioned_static_url(
                    "static", filename=raster_webp_relpath(landscape_rel)
                ),
                "herocard_url": versioned_static_url("static", filename=herocard_rel),
                "herocard_webp_url": versioned_static_url(
                    "static", filename=raster_webp_relpath(herocard_rel)
                ),
                "herocard_webp_srcset": herocard_webp_srcset_for_position(
                    position, versioned_static_url
                ),
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
                climate_economy_display_for_position,
                get_planet_identity_for_position,
                herocard_webp_srcset_for_position,
                OVERVIEW_HEROCARD_SIZES,
                raster_webp_relpath,
                temperature_range_for_position,
            )

            fallback_rel = f"img/herocards/{DEFAULT_HEROCARD}"
            fallback_herocard_rel = fallback_rel
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
                "landscape_url": versioned_static_url("static", filename=fallback_rel),
                "landscape_webp_url": versioned_static_url(
                    "static", filename=raster_webp_relpath(fallback_rel)
                ),
                "herocard_url": versioned_static_url("static", filename=fallback_herocard_rel),
                "herocard_webp_url": versioned_static_url(
                    "static", filename=raster_webp_relpath(fallback_herocard_rel)
                ),
                "herocard_webp_srcset": herocard_webp_srcset_for_position(
                    0, versioned_static_url
                ),
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

    with perf_span("payload.score"):
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

    with perf_span("payload.notifications"):
        try:
            payload["unread_messages_count"] = messages_logic.unread_count(
                user_id,
                conn=conn,
                prepare=not lightweight,
            )
            latest_message_id = messages_logic.latest_inbox_message_id(
                user_id,
                conn=conn,
                prepare=not lightweight,
            )
            payload["latest_message_id"] = int(latest_message_id) if latest_message_id else None
            toast_items = []
            if int(payload["unread_messages_count"] or 0) > 0:
                toast_items = messages_logic.notification_toast_items(
                    user_id,
                    limit=16,
                    conn=conn,
                    prepare=False,
                )
            payload["notifications"] = {
                "unread_count": max(0, int(payload["unread_messages_count"] or 0)),
                "newest_id": payload["latest_message_id"],
                "new_items": toast_items,
            }
        except Exception:
            payload["unread_messages_count"] = 0
            payload["latest_message_id"] = None
            payload["notifications"] = {
                "unread_count": 0,
                "newest_id": None,
                "new_items": [],
            }

    try:
        from game.battle_pass import serialize_for_client as bp_serialize

        # Build once per game-state request. The same state feeds the premium payload
        # and the nav claimable badge.
        battle_pass_state = bp_serialize(
            int(user_id), conn=conn, include_tracks=not lightweight
        )
    except Exception:
        battle_pass_state = {"ready": False}

    with perf_span("payload.nav_badges"):
        try:
            from game.live_state import nav_badges_for_game_state

            payload["nav_badges"] = nav_badges_for_game_state(
                user_id, conn=conn, battle_pass=battle_pass_state
            )
        except Exception:
            payload["nav_badges"] = {
                "vote_center": {"active": False, "count": 0, "label": ""},
                "government": {"active": False, "count": 0, "label": ""},
                "referrals": {"active": False, "count": 0, "label": ""},
                "imperial_directives": {"active": False, "count": 0, "label": ""},
                "auction_house": {"active": False, "count": 0, "label": ""},
            }

    try:
        from game.live_state import imperial_directives_for_game_state

        if not lightweight:
            payload["imperial_directives"] = imperial_directives_for_game_state(user_id, conn=conn)
    except Exception:
        if not lightweight:
            payload["imperial_directives"] = {
                "ready": False,
                "daily_completed": 0,
                "daily_total": 0,
                "weekly_completed": 0,
                "weekly_total": 0,
                "claimable_count": 0,
                "daily_reset_at": 0,
                "weekly_reset_at": 0,
            }

    try:
        from game.live_state import initiation_for_game_state

        # Diet-safe: keep on lightweight polls so HUD chip stays live.
        payload["initiation"] = initiation_for_game_state(user_id, conn=conn)
    except Exception:
        payload["initiation"] = {
            "ready": False,
            "active": False,
            "completed": False,
            "step_index": 0,
            "step_count": 0,
            "progress": 0,
            "target": 0,
            "route": "",
            "title_key": "",
            "hint_key": "",
            "step_id": "",
            "phase_id": "",
        }

    with perf_span("payload.liveops"):
        try:
            from game.server_events import serialize_active_events

            payload["server_events"] = serialize_active_events(conn=conn)
        except Exception:
            payload["server_events"] = {
                "events": [],
                "production_mult": 1.0,
                "expedition_hold_mult": 1.0,
                "shop_discount_bps": 0,
                "build_time_speed": 1.0,
                "research_time_speed": 1.0,
                "asteroid_spawn_mult": 1.0,
                "world_boss_spawn_mult": 1.0,
                "inactive_farm_mult": 1.0,
            }

        try:
            from game.overview_page import build_overview_live_events
            from game.i18n import current_locale

            payload["live_events"] = build_overview_live_events(
                conn=conn,
                user_id=user_id,
                locale=current_locale(),
            )
        except Exception:
            payload["live_events"] = []

    with perf_span("payload.fleets_hud"):
        try:
            from game.live_state import fleet_hud_for_game_state

            fleet_hud = fleet_hud_for_game_state(user_id, conn=conn)
            if fleet_hud is not None:
                from game.fleet import FLEET_DRAWER_VISIBLE_LIMIT

                payload["active_fleets"] = fleet_hud.get("active_fleets") or {
                    "count": 0,
                    "active_fleet_count": 0,
                    "fleets_confirmed_empty": True,
                    "visible_limit": FLEET_DRAWER_VISIBLE_LIMIT,
                    "next_remaining_seconds": 0,
                    "items": [],
                }
                payload["fleet_slots"] = fleet_hud.get("fleet_slots") or {}
                payload["fleet_alerts"] = fleet_hud.get("fleet_alerts") or {
                    "incoming_attack_count": 0,
                    "next_attack_arrival": None,
                    "has_incoming_attack": False,
                    "alert_key": "",
                    "incoming_attacks": [],
                }
            else:
                payload["fleet_slots"] = {"active": 0, "max": 0, "free": 0}
                payload["fleet_alerts"] = {
                    "incoming_attack_count": 0,
                    "next_attack_arrival": None,
                    "has_incoming_attack": False,
                    "alert_key": "",
                    "incoming_attacks": [],
                }
        except Exception:
            payload["fleet_slots"] = {"active": 0, "max": 0, "free": 0}
            payload["fleet_alerts"] = {
                "incoming_attack_count": 0,
                "next_attack_arrival": None,
                "has_incoming_attack": False,
                "alert_key": "",
                "incoming_attacks": [],
            }

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

    try:
        from game.inventory_boosters import build_inventory_boosters_state

        player_locale = get_player_locale(user_id, conn=conn)
        payload["active_boosters"] = build_inventory_boosters_state(
            user_id, conn=conn, locale=player_locale
        )
    except Exception:
        payload["active_boosters"] = {"ready": False, "active": [], "active_effects": []}

    try:
        from game.login_rewards import serialize_for_client as lr_serialize

        payload["login_rewards"] = lr_serialize(int(user_id), conn=conn)
    except Exception:
        payload["login_rewards"] = {"ready": False, "available": False}

    payload["battle_pass"] = battle_pass_state

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
        from game.planet_visuals import apply_herocard_urls_to_switcher_planets

        payload["planets"] = apply_herocard_urls_to_switcher_planets(
            list_player_planets_for_switcher(user_id, conn=conn),
            versioned_static_url,
        )
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

    try:
        from game.galaxy import get_relocation_client_state, relocation_schema_ready

        if not lightweight and relocation_schema_ready(conn):
            payload["planet_relocation"] = get_relocation_client_state(
                int(active_planet_id),
                conn=conn,
                now=time.time(),
            )
        elif not lightweight:
            payload["planet_relocation"] = {"active": False, "can_start": False}
    except Exception:
        if not lightweight:
            payload["planet_relocation"] = {"active": False, "can_start": False}

    if not lightweight:
        try:
            from game.galaxy import player_has_seed_ark

            payload["has_seed_ark"] = player_has_seed_ark(user_id, conn=conn)
        except Exception:
            payload["has_seed_ark"] = False

    # Heavy trader / combat catalogs — only when SCOPE-002 page asks for them.
    if include_panel and "exchange" in heavy:
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
                if "exchange" not in panels_built:
                    panels_built.append("exchange")
        except Exception:
            pass

    if include_panel and "scrapyard" in heavy:
        try:
            from game.scrapyard import scrapyard_status

            pid_tr = int(planet["id"])
            payload["scrapyard"] = scrapyard_status(user_id, pid_tr, conn=conn)
            if "scrapyard" not in panels_built:
                panels_built.append("scrapyard")
        except Exception:
            pass

    if include_panel and "collector_exchange" in heavy:
        try:
            from game.collector_exchange import build_collector_exchange_payload, collector_schema_ready

            if collector_schema_ready(conn):
                payload["collector_exchange"] = build_collector_exchange_payload(user_id, conn=conn)
                if "collector_exchange" not in panels_built:
                    panels_built.append("collector_exchange")
        except Exception:
            pass

    if include_panel and "auction_house" in heavy:
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
                if "auction_house" not in panels_built:
                    panels_built.append("auction_house")
        except Exception:
            pass

    if include_panel and "defense" in heavy:
        try:
            from game.live_state import defense_panel_for_game_state

            defense_panel = defense_panel_for_game_state(user_id, conn=conn)
            if defense_panel is not None:
                payload["defense"] = defense_panel
                if "defense" not in panels_built:
                    panels_built.append("defense")
        except Exception:
            pass

    if include_panel and "shipyard" in heavy:
        try:
            from game.live_state import shipyard_panel_for_game_state

            shipyard_panel = shipyard_panel_for_game_state(user_id, conn=conn)
            if shipyard_panel is not None:
                payload["shipyard"] = shipyard_panel
                payload["shipyard_queue"] = shipyard_panel.get("queue")
                if "shipyard" not in panels_built:
                    panels_built.append("shipyard")
        except Exception:
            pass

    if include_panel and "research" in heavy and (research.get("techs") is not None):
        if "research" not in panels_built:
            panels_built.append("research")

    try:
        set_request_perf_meta("panels_built", ",".join(panels_built) if panels_built else "")
        set_request_perf_meta("panel_page", page or "")
        record_request_perf_phase(
            "panel_total_ms",
            (time.perf_counter() - panel_block_t0) * 1000.0,
        )
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

    if not lightweight:
        try:
            from game.codex import codex_for_game_state

            payload["codex"] = codex_for_game_state(user_id, conn=conn)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("[GC CODEX] game-state payload failed")
            payload["codex"] = {"ok": False, "catalog": {"catalog_ready": False, "article_count": 0, "category_count": 0}}

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
    panel_page: str = "",
    panel_tab: Optional[str] = None,
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

    from game.live_state import record_request_perf_phase, set_request_perf_meta

    page = _resolve_effective_panel_page(panel_page, finish_source)
    set_request_perf_meta("finish_source", str(finish_source or "game_state"))
    set_request_perf_meta("include_panel", 1 if include_panel else 0)
    set_request_perf_meta("panel_page", page or "")
    if panel_delta_keys:
        set_request_perf_meta("panel_delta", 1)

    conn = db()
    try:
        ctx_t0 = time.perf_counter()
        ctx = _load_page_live_context(
            finish_source=str(finish_source or "game_state"),
            include_panel=include_panel,
            panel_page=page,
            conn=conn,
            close_conn=False,
        )
        record_request_perf_phase("live_context_ms", (time.perf_counter() - ctx_t0) * 1000.0)
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
            panel_page=page,
            panel_tab=panel_tab,
            conn=conn,
        )
        from game.live_state import current_action_perf

        perf = current_action_perf()
        payload_ms = (time.perf_counter() - payload_t0) * 1000.0
        if perf is not None:
            perf.add_payload_ms(payload_ms)
        record_request_perf_phase("payload_ms", payload_ms)
        # Mutations / panel builds change nav badges — don't let idle probe_skip hide them.
        if not lightweight:
            try:
                from game.live_state import clear_diet_poll_fingerprint

                clear_diet_poll_fingerprint(user_id)
            except Exception:
                pass
        return payload, user_id
    finally:
        try:
            from game.db import in_transaction
            from game.models import commit

            if in_transaction(conn):
                commit(conn)
        except Exception:
            pass
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
        "api_buildings_mine_evolve",
        "game_state_buildings_finish",
        "api_planets_active",
        "api_fleet_send",
        "api_fleet_bulk_launch_presets",
        "api_fleet_recall",
        "api_timekeeper_apply",
        # Meta/reward HUD actions — no buildings/research catalog needed
        "api_login_rewards_claim",
        "api_battle_pass_claim",
        "api_battle_pass_claim_op",
        "api_vote_rewards_claim",
        "api_vote_rewards_claim_all",
        "api_galactic_politics_vote",
        "api_galactic_politics_bloc",
        "api_galactic_politics_res_propose",
        "api_galactic_politics_res_vote",
        "api_referrals_apply",
        "api_referrals_claim",
    )


def _hud_only_game_state(finish_source: str) -> dict:
    """GC-PERF: meta/reward mutations — HUD + queues, skip full panel catalog."""
    state, _ = _build_game_state_payload(
        include_panel=False,
        finish_source=str(finish_source or "action"),
        action_slim=True,
    )
    return state if isinstance(state, dict) else {}


def _fleet_mutation_game_state(finish_source: str) -> dict:
    """Slim post-mutation state for fleet send/recall (GC-PERF-FLEET-SEND)."""
    try:
        state, _ = _build_game_state_payload(
            include_panel=False,
            finish_source=finish_source,
            action_slim=True,
        )
        return state if isinstance(state, dict) else {}
    except Exception:
        logger.exception("fleet mutation game-state failed source=%s", finish_source)
        return {}


def _timekeeper_apply_game_state(domain: str | None = None) -> dict:
    """GC-PERF-TK-003/004: HUD + queue slices — no full buildings/codex catalog."""
    state, _ = _build_game_state_payload(
        include_panel=False,
        finish_source="api_timekeeper_apply",
        action_slim=True,
    )
    dom = str(domain or "").strip().lower()
    if dom in ("shipyard", "defense", "troops"):
        try:
            from game.live_state import attach_timekeeper_domain_queue_slices

            conn = db()
            try:
                attach_timekeeper_domain_queue_slices(
                    state, int(session.get("user_id") or 0), dom, conn=conn
                )
            finally:
                conn.close()
        except Exception:
            logger.exception(
                "timekeeper_apply queue slice attach failed domain=%s",
                dom,
            )
    return state


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

    state, _ = _build_game_state_payload(
        include_panel=True,
        finish_source=finish_source,
        panel_page="defense",
    )
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
@require_login_api
def api_status():
    """Alias von /api/game-state (gleiches Schema)."""
    return api_game_state()


@app.route("/api/notifications/summary")
@require_login_api
def api_notifications_summary():
    """Lightweight notification heartbeat — unread + attack alerts only (no queue finish)."""
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    from game.live_state import notification_summary_for_client

    conn = db()
    try:
        payload = notification_summary_for_client(user_id, conn=conn)
        return jsonify(payload)
    finally:
        conn.close()


@app.route("/api/game-state")
@require_login_api
def api_game_state():
    want_panel = request.args.get("include_panel", "").lower() in ("1", "true", "yes")
    delta_keys = _parse_panel_delta_buildings_param()
    panel_page, panel_tab = _resolve_game_state_panel_scope()
    since_raw = request.args.get("since", "").strip()
    delta_raw = os.environ.get("GC_STATE_DELTA", "1").strip().lower()
    delta_enabled = delta_raw not in ("0", "false", "no", "off")

    # GC-PERF-STATE-004: idle diet short-circuit before expensive payload build.
    if delta_enabled and since_raw.isdigit() and not want_panel and not delta_keys:
        user = get_current_user()
        if user:
            from game.live_state import set_request_perf_meta, try_diet_poll_early_unchanged

            since_val = int(since_raw)
            set_request_perf_meta("delta_since", since_val)
            early = try_diet_poll_early_unchanged(int(user["id"]), since_val)
            if early is not None:
                return jsonify(early)

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
            panel_page=panel_page,
            panel_tab=panel_tab,
        )
    else:
        payload, _player_id = _build_game_state_payload(
            include_panel=False,
            finish_source="game_state",
        )
    if not payload.get("ok"):
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    # GC-PERF-LIVE-001: diet delta short-circuit default ON (client handles unchanged).
    # Set GC_STATE_DELTA=0|false|off to disable. Defense-in-depth after full build.
    if delta_enabled and since_raw.isdigit() and not want_panel and not delta_keys:
        from game.live_state import build_delta_game_state, set_request_perf_meta

        since_val = int(since_raw)
        set_request_perf_meta("delta_since", since_val)
        payload = build_delta_game_state(payload, since=since_val)

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


@app.route("/api/collector-exchange/redeem", methods=["POST"])
@require_login
def api_collector_exchange_redeem():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    offer_key = str(data.get("offer_key") or "").strip()
    request_id = _extract_request_id(data)

    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.collector_exchange import collector_schema_ready, redeem_collector_offer
    from game.inventory import run_inventory_mutation
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        if not collector_schema_ready(conn):
            state, _ = _build_game_state_payload(include_panel=True, finish_source="api_collector_exchange")
            return jsonify({"ok": False, "reason": "collector_exchange_unavailable", "state": state}), 503
        planet = get_context_planet(user_id, conn=conn)
        planet_id = int(planet["id"])
    finally:
        conn.close()

    try:
        ok, reason, result = run_inventory_mutation(
            lambda conn: redeem_collector_offer(
                user_id,
                offer_key,
                conn=conn,
                request_id=request_id,
                planet_id=planet_id,
                player_id=user_id,
            )
        )
    except Exception:
        state, _ = _build_game_state_payload(include_panel=True, finish_source="api_collector_exchange")
        return jsonify({"ok": False, "reason": "collector_redeem_failed", "state": state}), 500

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_collector_exchange")
    resp: Dict[str, Any] = {
        "ok": bool(ok),
        "reason": reason,
        "state": state,
    }
    if ok and result is not None:
        resp["job"] = result
    elif not ok and result is not None:
        resp["payload"] = result

    if request_id and ok:
        save_idempotent_action(user_id, request_id, resp)

    status = 200 if ok else 400
    if reason in ("collector_exchange_unavailable", "inventory_unavailable"):
        status = 503
    return jsonify(resp), status


@app.route("/api/trader/fuel-exchange", methods=["POST"])
@require_login
def api_fuel_exchange_buy():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    from game.exchange import execute_exchange, exchange_schema_ready, get_exchange_config
    from game.planet_evolution.repository import get_context_planet

    if not exchange_schema_ready(db()):
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
        cfg = get_exchange_config(conn=conn)
        metal_amount = units * max(1, int(cfg["fuel_metal_per_unit"]))
        ok, reason, result = execute_exchange(
            player_id=user_id,
            planet_id=int(planet["id"]),
            from_resource="metal",
            to_resource="fuel_cells",
            amount=metal_amount,
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
@require_login_api
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
    except Exception as exc:
        from game.db import is_db_lock_error

        if is_db_lock_error(exc):
            try:
                rollback(conn)
            except Exception:
                pass
            body = fleet_err("lock_busy", data={"retry": True})
            body["reason"] = "lock_busy"
            body["retry"] = True
            return jsonify(body), 409
        raise
    finally:
        conn.close()


@app.route("/api/fleet/resolve-target", methods=["GET", "POST"])
@require_login_api
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
@require_login_api
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
@require_login_api
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
        state = _fleet_mutation_game_state("api_fleet_send")
        body = fleet_err("fleet_unavailable", data={"state": state})
        return jsonify(body), 503

    data = request.get_json(silent=True) or {}
    galaxy_quick_spy = bool(data.get("galaxy_quick_spy"))
    galaxy_quick_attack = bool(data.get("galaxy_quick_attack"))
    world_boss_auto_attack = bool(data.get("world_boss_auto_attack"))
    quick_flags = sum(1 for f in (galaxy_quick_spy, galaxy_quick_attack, world_boss_auto_attack) if f)
    if quick_flags > 1:
        return jsonify(fleet_err("invalid_request")), 400
    mission_raw = str(data.get("mission_type") or "").strip().lower()
    if galaxy_quick_spy and mission_raw != "spy":
        return jsonify(fleet_err("invalid_mission")), 400
    if galaxy_quick_attack and mission_raw != "attack":
        return jsonify(fleet_err("invalid_mission")), 400
    if world_boss_auto_attack and mission_raw != "attack":
        return jsonify(fleet_err("invalid_mission")), 400
    ships = {}
    if not galaxy_quick_spy and not galaxy_quick_attack and not world_boss_auto_attack:
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
        send_ships = ships
        send_resources = data.get("resources") or {}
        send_speed = speed_percent
        preset_id_send = int(data["preset_id"]) if data.get("preset_id") else None
        quick_spy_meta = None
        quick_attack_meta = None
        wb_auto_meta = None
        if galaxy_quick_attack:
            from game.fleet import resolve_galaxy_quick_attack

            preset_id_raw = int(data.get("preset_id") or 0)
            ok_atk, atk_reason, atk_ctx = resolve_galaxy_quick_attack(
                user_id, preset_id_raw, conn=conn
            )
            if not ok_atk:
                return False, atk_reason, atk_ctx
            send_ships = atk_ctx.get("ships") or {}
            send_resources = atk_ctx.get("resources") or {}
            send_speed = int(atk_ctx.get("speed_percent") or 100)
            preset_id_send = int(atk_ctx.get("preset_id") or preset_id_raw)
            quick_attack_meta = atk_ctx
        elif galaxy_quick_spy:
            from game.fleet import resolve_galaxy_quick_spy_ships

            ok_spy, spy_reason, spy_ctx = resolve_galaxy_quick_spy_ships(
                user_id, int(origin_id), conn=conn
            )
            if not ok_spy:
                return False, spy_reason, spy_ctx
            send_ships = spy_ctx.get("ships") or {}
            quick_spy_meta = spy_ctx
        elif world_boss_auto_attack:
            from game.fleet import resolve_world_boss_auto_attack_ships

            ok_wb, wb_reason, wb_ctx = resolve_world_boss_auto_attack_ships(
                user_id,
                int(origin_id),
                target_galaxy=int(data.get("target_galaxy") or 0),
                target_system=int(data.get("target_system") or 0),
                target_position=int(data.get("target_position") or 0),
                conn=conn,
            )
            if not ok_wb:
                return False, wb_reason, wb_ctx
            send_ships = wb_ctx.get("ships") or {}
            wb_auto_meta = wb_ctx
        send_troops = data.get("troops") or {}
        if galaxy_quick_attack or galaxy_quick_spy or world_boss_auto_attack:
            send_troops = {}
        ok, reason, result = send_fleet(
            player_id=user_id,
            origin_planet_id=origin_id,
            target_galaxy=int(data.get("target_galaxy") or 0),
            target_system=int(data.get("target_system") or 0),
            target_position=int(data.get("target_position") or 0),
            mission_type=str(data.get("mission_type") or ""),
            ships=send_ships,
            resources=send_resources,
            speed_percent=send_speed,
            preset_id=preset_id_send,
            batch_id=int(data["batch_id"]) if data.get("batch_id") else None,
            colony_name=str(data.get("colony_name") or "").strip() or None,
            world_key=target_req.get("world_key"),
            target_type=target_req.get("target_type"),
            target_planet_id=target_req.get("target_planet_id"),
            target_world_x=target_req.get("target_world_x"),
            target_world_y=target_req.get("target_world_y"),
            expedition_hours=int(data["expedition_hours"]) if data.get("expedition_hours") not in (None, "") else None,
            troops=send_troops,
            conn=conn,
        )
        if ok and result and quick_spy_meta:
            merged = dict(result)
            merged["galaxy_quick_spy"] = quick_spy_meta
            return True, reason, merged
        if ok and result and quick_attack_meta:
            merged = dict(result)
            merged["galaxy_quick_attack"] = quick_attack_meta
            return True, reason, merged
        if ok and result and wb_auto_meta:
            merged = dict(result)
            merged["world_boss_auto_attack"] = wb_auto_meta
            return True, reason, merged
        return ok, reason, result

    ok, reason, result = _fleet_write_transaction(_send)

    if ok and result:
        state = _fleet_mutation_game_state("api_fleet_send")
        live = {
            "fleet": result.get("fleet"),
            "updated_ships": result.get("updated_ships"),
            "updated_resources": result.get("updated_resources"),
            "active_slots": result.get("active_slots"),
            "fuel_cost": result.get("fuel_cost"),
        }
        if result.get("galaxy_quick_spy"):
            live["galaxy_quick_spy"] = result["galaxy_quick_spy"]
        if result.get("galaxy_quick_attack"):
            live["galaxy_quick_attack"] = result["galaxy_quick_attack"]
        if result.get("world_boss_auto_attack"):
            live["world_boss_auto_attack"] = result["world_boss_auto_attack"]
        body = fleet_ok(live, message_key="fleet_send_success")
        body["state"] = state
        return jsonify(body)

    state = _fleet_mutation_game_state("api_fleet_send")
    err_data: Dict[str, Any] = {"state": state}
    if isinstance(result, dict):
        for context_key in (
            "attack_limit",
            "noob_protection",
            "troop_slots_needed",
            "troop_berths",
            "retry",
        ):
            if result.get(context_key) is not None:
                err_data[context_key] = result[context_key]
    if reason == "lock_busy":
        err_data["retry"] = True
        body = fleet_err("lock_busy", data=err_data)
        body["reason"] = "lock_busy"
        body["retry"] = True
        return jsonify(body), 409
    return jsonify(fleet_err(reason or "generic", data=err_data)), 400


@app.route("/api/fleet/bulk-launch-presets", methods=["POST"])
@require_login_api
def api_fleet_bulk_launch_presets():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_bulk import launch_selected_presets
    from game.fleet_origin import resolve_fleet_origin_planet_id

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        state = _fleet_mutation_game_state("api_fleet_bulk_launch_presets")
        body = fleet_err("fleet_unavailable", data={"state": state})
        body["state"] = state
        return jsonify(body), 503

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    preset_ids = data.get("preset_ids") or []
    if not isinstance(preset_ids, list) or not preset_ids:
        state = _fleet_mutation_game_state("api_fleet_bulk_launch_presets")
        body = fleet_err("bulk_no_selection", data={"state": state})
        body["state"] = state
        return jsonify(body), 400

    def _bulk(conn):
        dom_raw = request.headers.get("X-GC-Dom-Planet-Id") or data.get("dom_planet_id")
        dom_planet_id = int(dom_raw) if dom_raw not in (None, "") else None
        origin_id, _origin_audit = resolve_fleet_origin_planet_id(
            user_id,
            data.get("origin_planet_id"),
            conn=conn,
            dom_planet_id=dom_planet_id,
        )
        return launch_selected_presets(
            user_id,
            int(origin_id),
            preset_ids,
            conn=conn,
        )

    ok, reason, result = _fleet_write_transaction(_bulk)
    state = _fleet_mutation_game_state("api_fleet_bulk_launch_presets")
    if ok:
        body = fleet_ok(result or {}, message_key="fleet_bulk_launch_success")
        body["state"] = state
        if request_id:
            save_idempotent_action(user_id, request_id, body)
        return jsonify(body)

    body = fleet_err(reason or "bulk_launch_failed", data={"state": state})
    body["state"] = state
    return jsonify(body), 400


@app.route("/api/fleet/recall", methods=["POST"])
@require_login_api
def api_fleet_recall():
    from game.fleet import fleet_schema_ready
    from game.fleet_api import fleet_err, fleet_ok, fleet_recall_movement

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        state = _fleet_mutation_game_state("api_fleet_recall")
        return jsonify(fleet_err("fleet_unavailable", data={"state": state})), 503

    data = request.get_json(silent=True) or {}
    try:
        movement_id = int(data.get("movement_id") or 0)
    except (TypeError, ValueError):
        movement_id = 0
    if movement_id <= 0:
        state = _fleet_mutation_game_state("api_fleet_recall")
        body = fleet_err("fleet_not_found", data={"state": state})
        body["state"] = state
        return jsonify(body), 400

    def _recall(conn):
        return fleet_recall_movement(user_id, movement_id, conn=conn)

    ok, reason, result = _fleet_write_transaction(_recall)
    state = _fleet_mutation_game_state("api_fleet_recall")
    if ok:
        body = fleet_ok(result or {}, message_key="fleet_recall_success")
        body["state"] = state
        return jsonify(body)
    body = fleet_err(reason or "fleet_recall_failed", data={"state": state})
    body["state"] = state
    return jsonify(body), 400


@app.route("/api/fleet/presets", methods=["GET"])
@require_login_api
def api_fleet_presets_list():
    from game.fleet import filter_galaxy_attack_presets, fleet_schema_ready, list_presets
    from game.fleet_api import fleet_err, fleet_ok

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503
    presets = list_presets(user_id)
    if request.args.get("galaxy_attack") in ("1", "true", "yes"):
        presets = filter_galaxy_attack_presets(presets)
    return jsonify(fleet_ok({"presets": presets}, message_key="fleet_presets_ok"))


@app.route("/api/fleet/presets", methods=["POST"])
@require_login_api
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
@require_login_api
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
@require_login_api
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
@require_login_api
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
    planet = None
    user_id = int(session.get("user_id") or 0)
    if user_id:
        conn = db()
        try:
            planet = get_context_planet(user_id, conn=conn)
            buildings = get_planet_buildings(int(planet["id"]), conn=conn)
            research = get_research_levels(user_id=user_id, conn=conn)
            card, err = build_ship_detail_card(
                ship_key,
                buildings=buildings,
                research=research,
                player_id=user_id,
                conn=conn,
                planet=planet,
            )
        finally:
            conn.close()
    else:
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
    planet = None
    user_id = int(session.get("user_id") or 0)
    if user_id:
        conn = db()
        try:
            planet = get_context_planet(user_id, conn=conn)
            buildings = get_planet_buildings(int(planet["id"]), conn=conn)
            research = get_research_levels(user_id=user_id, conn=conn)
            card, err = build_defense_detail_card(
                defense_key,
                buildings=buildings,
                research=research,
                player_id=user_id,
                conn=conn,
                planet=planet,
            )
        finally:
            conn.close()
    else:
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


@app.route("/api/troop-units/<troop_key>")
@require_login
def api_troop_detail(troop_key: str):
    from game.models import get_planet_buildings
    from game.planet_evolution.repository import get_context_planet
    from game.troop_detail import build_troop_detail_card

    buildings = None
    user_id = int(session.get("user_id") or 0)
    if user_id:
        conn = db()
        try:
            planet = get_context_planet(user_id, conn=conn)
            buildings = get_planet_buildings(int(planet["id"]), conn=conn)
            card, err = build_troop_detail_card(troop_key, buildings=buildings)
        finally:
            conn.close()
    else:
        card, err = build_troop_detail_card(troop_key, buildings=buildings)
    if err:
        return (
            render_template(
                "partials/ship_detail_error.html",
                error_key=err,
            ),
            404,
        )
    return render_template("partials/troop_detail_view.html", card=card)


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


@app.route("/api/combat-simulator/run", methods=["POST"])
@require_login
def api_combat_simulator_run():
    from game.auth import get_current_user
    from game.combat_simulator import handle_combat_simulator_run

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    user = get_current_user()
    is_admin = bool(user and int(user.get("is_admin") or 0))
    result = handle_combat_simulator_run(data, user_id, is_admin=is_admin)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route("/api/combat-simulator/defaults", methods=["GET"])
@require_login
def api_combat_simulator_defaults():
    from game.combat_simulator import build_combat_simulator_defaults
    from game.planet_evolution.repository import get_context_planet

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    conn = db()
    try:
        planet = get_context_planet(user_id, conn=conn)
        if not planet:
            return jsonify({"ok": False, "error": "planet_not_found"}), 400
        spy_report_id = None
        try:
            raw_spy = request.args.get("spy_report_id")
            if raw_spy is not None and str(raw_spy).strip():
                spy_report_id = int(raw_spy)
        except (TypeError, ValueError):
            spy_report_id = None
        from game.combat_simulator import build_combat_simulator_page_context

        if spy_report_id:
            page_ctx = build_combat_simulator_page_context(
                user_id, conn=conn, spy_report_id=spy_report_id
            )
            if page_ctx.get("spy_import_error"):
                return jsonify({"ok": False, "error": page_ctx["spy_import_error"]}), 400
            defaults = page_ctx.get("defaults") or {}
            presets = page_ctx.get("presets") or {}
            return jsonify(
                {
                    "ok": True,
                    "defaults": defaults,
                    "presets": presets,
                    "imported_spy": page_ctx.get("imported_spy"),
                    "spy_report_id": page_ctx.get("spy_report_id"),
                    "route_labels": page_ctx.get("route_labels"),
                }
            )
        defaults = build_combat_simulator_defaults(user_id, conn=conn)
        return jsonify({"ok": True, "defaults": defaults})
    finally:
        conn.close()


@app.route("/api/combat-simulator/spy-reports", methods=["GET"])
@require_login
def api_combat_simulator_spy_reports():
    from game.combat_simulator import list_combat_simulator_spy_reports

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    conn = db()
    try:
        payload = list_combat_simulator_spy_reports(user_id, conn=conn)
        return jsonify({"ok": True, **payload})
    finally:
        conn.close()


@app.route("/api/combat-simulator/import-spy-report", methods=["POST"])
@require_login
def api_combat_simulator_import_spy_report():
    from game.combat_simulator import import_spy_report_for_simulator

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    try:
        message_id = int(data.get("message_id") or 0)
    except (TypeError, ValueError):
        message_id = 0
    if message_id <= 0:
        return jsonify({"ok": False, "error": "invalid_message_id"}), 400

    conn = db()
    try:
        imported, err = import_spy_report_for_simulator(user_id, message_id, conn=conn)
        if err or imported is None:
            return jsonify({"ok": False, "error": err or "import_failed"}), 400
        return jsonify({"ok": True, "import": imported})
    finally:
        conn.close()


@app.route("/api/vault/state", methods=["GET"])
@require_login_api
def api_vault_state():
    """Player Secret Vault exposure (account meta steal caps + current loot)."""
    from game.fleet_api import fleet_err, fleet_ok
    from game.vault_raid import build_vault_panel_state

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    conn = db()
    try:
        payload = build_vault_panel_state(user_id, conn=conn)
        return jsonify(fleet_ok({"vault": payload}, message_key="secret_vault_state_ok"))
    finally:
        conn.close()


@app.route("/api/troops/state", methods=["GET"])
@require_login_api
def api_troops_state():
    from game.fleet_api import fleet_err, fleet_ok
    from game.models import get_planet_buildings
    from game.shipyard import resolve_owned_planet_id
    from game.troops import build_troops_state, troop_queue_table_ready, troops_schema_ready

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    raw_pid = request.args.get("planet_id")
    req_pid = int(raw_pid) if raw_pid not in (None, "") else None
    conn = db()
    try:
        if not troops_schema_ready(conn) or not troop_queue_table_ready(conn):
            return jsonify(fleet_err("troops_unavailable")), 503
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        from game.troops import finish_planet_troop_jobs

        finish_planet_troop_jobs(int(planet_id), conn=conn)
        bld = get_planet_buildings(int(planet_id), conn=conn) or {}
        payload = build_troops_state(
            int(planet_id),
            barracks_level=int(bld.get("barracks") or 0),
            conn=conn,
        )
        return jsonify(fleet_ok({"troops": payload}, message_key="troops_state_ok"))
    finally:
        conn.close()


@app.route("/api/troops/train", methods=["POST"])
@require_login_api
def api_troops_train():
    from game.fleet_api import fleet_err, fleet_ok
    from game.models import get_planet_buildings
    from game.number_format import parse_int_number
    from game.shipyard import resolve_owned_planet_id
    from game.troops import (
        build_troops_state,
        enqueue_troop_train,
        troop_queue_table_ready,
        troops_schema_ready,
    )

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401

    data = request.get_json(silent=True) or {}
    troop_key = str(data.get("troop_key") or "").strip()
    amount = parse_int_number(data.get("amount") or 1, default=0)
    if amount <= 0:
        return jsonify(fleet_err("invalid_amount")), 400

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    conn = db()
    try:
        if not troops_schema_ready(conn) or not troop_queue_table_ready(conn):
            return jsonify(fleet_err("troops_unavailable")), 503
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason, result = enqueue_troop_train(
            player_id=user_id,
            planet_id=int(planet_id),
            troop_key=troop_key,
            amount=amount,
            conn=conn,
        )
        if not ok:
            return jsonify(fleet_err(reason or "generic")), 400
        bld = get_planet_buildings(int(planet_id), conn=conn) or {}
        troops = build_troops_state(
            int(planet_id),
            barracks_level=int(bld.get("barracks") or 0),
            conn=conn,
        )
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_troops_train")
    body = fleet_ok({"result": result, "troops": troops}, message_key="troops_train_ok")
    body["state"] = state
    if request_id:
        save_idempotent_action(user_id, request_id, body)
    return jsonify(body)


@app.route("/api/troops/cancel", methods=["POST"])
@require_login_api
def api_troops_cancel():
    from game.fleet_api import fleet_err, fleet_ok
    from game.models import get_planet_buildings
    from game.shipyard import resolve_owned_planet_id
    from game.troops import (
        build_troops_state,
        cancel_troop_job,
        troop_queue_table_ready,
        troops_schema_ready,
    )

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

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    conn = db()
    try:
        if not troops_schema_ready(conn) or not troop_queue_table_ready(conn):
            return jsonify(fleet_err("troops_unavailable")), 503
        raw_pid = data.get("planet_id")
        req_pid = int(raw_pid) if raw_pid not in (None, "") else None
        planet_id, err = resolve_owned_planet_id(user_id, req_pid, conn=conn)
        if err:
            return jsonify(fleet_err(err)), 404
        ok, reason = cancel_troop_job(user_id, job_id, conn=conn)
        if not ok:
            return jsonify(fleet_err(reason or "generic")), 400
        bld = get_planet_buildings(int(planet_id), conn=conn) or {}
        troops = build_troops_state(
            int(planet_id),
            barracks_level=int(bld.get("barracks") or 0),
            conn=conn,
        )
    finally:
        conn.close()

    state, _ = _build_game_state_payload(include_panel=True, finish_source="api_troops_cancel")
    body = fleet_ok({"troops": troops}, message_key="troops_cancel_ok")
    body["state"] = state
    if request_id:
        save_idempotent_action(user_id, request_id, body)
    return jsonify(body)


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
    """Tick + load planet rows for logistics preview (delegates to fleet owner)."""
    from game.fleet import _load_planet_rows_for_collect

    return _load_planet_rows_for_collect(planet_ids, conn=conn)


def _build_logistics_preview(
    *,
    user_id: int,
    data: Mapping[str, Any],
    conn,
) -> Dict[str, Any]:
    """Server-side logistics plan preview (collect / distribute legs)."""
    from game.fleet import (
        _fleet_cargo_multiplier,
        build_collect_route,
        build_distribute_route,
        build_fleet_send_preview,
        get_fleet_slot_status,
        get_planet_ships,
    )
    from game.fleet_calc import (
        allocate_auto_cargo_ships_for_targets,
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

    ships_mode = str(data.get("ships_selection_mode") or "manual").strip().lower() or "manual"
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
        "ships_selection_mode": ships_mode,
        "ships_used": {},
    }

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
        ships_stock_by_source: Dict[int, Dict[str, int]] = {}
        for sid in source_ids:
            ships_stock_by_source[int(sid)] = get_planet_ships(int(sid), conn=conn)
        skip_empty = ships_mode == "auto_cargo"
        manual_ships = ships if ships_mode == "manual" else None
        if ships_mode == "manual" and not ships:
            base["block_reason"] = "no_ships"
            return base
        distinct_galaxies = {
            int(planet_rows[sid]["galaxy"])
            for sid in source_ids
            if sid in planet_rows and planet_rows[sid].get("galaxy") is not None
        }
        cargo_multiplier_by_galaxy = {
            g: _fleet_cargo_multiplier(int(user_id), conn, galaxy=g) for g in distinct_galaxies
        }
        route_ok, route_reason, route_legs = build_collect_route(
            origin_planet_id=hub_id,
            source_planet_ids=source_ids,
            planet_rows_by_id=planet_rows,
            ships_stock_by_source=ships_stock_by_source,
            free_fleet_slots=int(slots["free"]),
            player_id=int(user_id),
            ships_selection_mode=ships_mode,
            manual_ships=manual_ships,
            speed_percent=speed_percent,
            cargo_multiplier_by_galaxy=cargo_multiplier_by_galaxy,
            skip_empty_ship_legs=skip_empty,
            skip_invalid_planets=skip_empty,
        )
        if route_ok and route_legs:
            ships_used: Dict[str, int] = {}
            for leg in route_legs:
                for sk, qty in (leg.get("ships") or {}).items():
                    ships_used[str(sk)] = int(ships_used.get(str(sk), 0)) + int(qty)
            base["ships_used"] = ships_used
            for leg in route_legs:
                origin_row = planet_rows.get(int(leg["origin_planet_id"])) or {}
                cargo_deliverable = calculate_loaded_resources(leg.get("resources"))
                leg_previews = build_fleet_send_preview(
                    player_id=int(user_id),
                    origin_planet=origin_row,
                    target_galaxy=int(leg["galaxy"]),
                    target_system=int(leg["system"]),
                    target_position=int(leg["position"]),
                    mission_type="transport",
                    ships=leg["ships"],
                    resources=cargo_deliverable,
                    speed_percent=speed_percent,
                    conn=conn,
                )
                prow = planet_rows.get(int(leg["planet_id"])) or {}
                legs.append(
                    {
                        "planet_id": int(leg["planet_id"]),
                        "origin_planet_id": int(leg["origin_planet_id"]),
                        "name": str(prow.get("name") or ""),
                        "coordinates": format_coordinates(
                            int(prow.get("galaxy") or 0),
                            int(prow.get("system") or 0),
                            int(prow.get("position") or 0),
                        ),
                        "flight_seconds": int(leg_previews.get("flight_seconds") or 0),
                        "cargo_total": int(leg_previews.get("cargo_total") or 0),
                        "cargo_used": int(leg_previews.get("cargo_used") or 0),
                        "cargo_free": int(leg_previews.get("cargo_free") or 0),
                        "fuel_cost": int(leg_previews.get("fuel_cost") or 0),
                        "can_send": bool(leg_previews.get("can_send")),
                        "block_reason": str(leg_previews.get("block_reason") or ""),
                        "resources": cargo_deliverable,
                        "ships": dict(leg["ships"]),
                    }
                )
    elif mode == "distribute":
        target_ids = [int(x) for x in (data.get("target_planet_ids") or [])]
        resources_mode = str(data.get("resources_mode") or "equal").strip().lower()
        planet_rows = _logistics_planet_rows(conn, [origin_id, *target_ids])
        clamp_to_cargo = False
        if ships_mode == "auto_cargo":
            if resources_mode == "equal":
                cargo_needed = loaded_resource_total(calculate_loaded_resources(data.get("resources")))
            else:
                cargo_needed = 0
                parsed = data.get("target_resources") or {}
                if isinstance(parsed, Mapping):
                    for raw in parsed.values():
                        cargo_needed += loaded_resource_total(calculate_loaded_resources(raw))
            # All free slots — no mass-expo reserve.
            launchable = min(max(1, len(target_ids)), max(0, int(slots["free"])))
            ships = allocate_auto_cargo_ships_for_targets(
                get_planet_ships(origin_id, conn=conn),
                cargo_needed,
                launchable,
            )
            clamp_to_cargo = True
        if not ships:
            base["block_reason"] = "no_ships"
            return base
        base["ships_used"] = dict(ships)
        origin_row_for_mult = planet_rows.get(origin_id) or {}
        hub_galaxy = int(origin_row_for_mult.get("galaxy") or 0) or None
        cargo_multiplier = _fleet_cargo_multiplier(int(user_id), conn, galaxy=hub_galaxy)
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
            cargo_multiplier=cargo_multiplier,
            for_preview=True,
            clamp_to_cargo=clamp_to_cargo,
            skip_invalid_planets=clamp_to_cargo,
        )
        if route_ok and route_legs:
            origin_row = planet_rows.get(origin_id) or dict(planet)
            for leg in route_legs:
                cargo_deliverable = calculate_loaded_resources(leg.get("resources"))
                cargo_requested = calculate_loaded_resources(
                    leg.get("resources_requested") or leg.get("resources")
                )
                leg_previews = build_fleet_send_preview(
                    player_id=int(user_id),
                    origin_planet=origin_row,
                    target_galaxy=int(leg["galaxy"]),
                    target_system=int(leg["system"]),
                    target_position=int(leg["position"]),
                    mission_type="transport",
                    ships=leg["ships"],
                    resources=cargo_deliverable if clamp_to_cargo else cargo_requested,
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
                        "resources": cargo_deliverable,
                        "resources_requested": cargo_requested,
                    }
                )
    else:
        base["block_reason"] = "invalid_logistics_mode"
        return base

    if not route_ok or not legs:
        base["block_reason"] = route_reason or "no_deliverable_resources"
        return base

    distribute_requested_total = 0
    if mode == "distribute":
        distribute_requested_total = sum(
            loaded_resource_total(leg.get("resources_requested") or leg.get("resources") or {})
            for leg in legs
        )

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
    if mode == "distribute" and distribute_requested_total <= 0:
        can_launch = False
        if not block_reason:
            block_reason = "no_resources"
    elif mode == "distribute" and distribute_requested_total > 0:
        deliverable_total = loaded_resource_total(delivered_total or {})
        if deliverable_total <= 0:
            can_launch = False
            if not block_reason:
                block_reason = "no_deliverable_resources"

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
@require_login_api
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
@require_login_api
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
@require_login_api
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


@app.route("/api/fleet/mass-expedition/preview", methods=["POST"])
@require_login_api
def api_fleet_mass_expedition_preview():
    from game.fleet import fleet_schema_ready, preview_mass_expedition_slot_split
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_calc import normalize_ships

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    ships = normalize_ships(data.get("ships") or {})
    conn = db()
    try:
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(user_id, conn=conn)
        origin_id = int(data.get("origin_planet_id") or planet["id"])
        ok, reason, preview = preview_mass_expedition_slot_split(
            player_id=user_id,
            origin_planet_id=origin_id,
            ships=ships,
            conn=conn,
        )
    finally:
        conn.close()

    if ok and preview is not None:
        return jsonify(fleet_ok(preview, message_key="fleet_mass_expo_preview_ok"))
    return jsonify(fleet_err(reason, data=preview or {})), 400


@app.route("/api/fleet/mass-expedition", methods=["POST"])
@require_login_api
def api_fleet_mass_expedition():
    from game.fleet import fleet_schema_ready, mass_expedition, mass_expedition_from_ships
    from game.fleet_api import fleet_err, fleet_ok
    from game.fleet_calc import normalize_ships

    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify(fleet_err("not_logged_in")), 401
    if not fleet_schema_ready(db()):
        return jsonify(fleet_err("fleet_unavailable")), 503

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    ships_payload = data.get("ships")
    use_ship_split = ships_payload is not None

    def _mass_expo(conn):
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(user_id, conn=conn)
        origin_id = int(data.get("origin_planet_id") or planet["id"])
        if use_ship_split:
            ships = normalize_ships(ships_payload or {})
            speed = int(data["speed_percent"]) if data.get("speed_percent") is not None else 100
            return mass_expedition_from_ships(
                player_id=user_id,
                origin_planet_id=origin_id,
                ships=ships,
                speed_percent=speed,
                conn=conn,
            )
        return mass_expedition(
            player_id=user_id,
            origin_planet_id=origin_id,
            preset_id=int(data.get("preset_id") or 0),
            waves=int(data.get("waves") or 1),
            target_slots=int(data["target_slots"]) if data.get("target_slots") is not None else None,
            speed_percent=int(data["speed_percent"]) if data.get("speed_percent") is not None else None,
            conn=conn,
        )

    try:
        ok, reason, result = _fleet_write_transaction(_mass_expo)
    except Exception:
        logger.exception("mass expedition failed user=%s", user_id)
        return jsonify(fleet_err("server_error")), 500

    if ok and result:
        state = _fleet_mutation_game_state("api_fleet_mass_expedition")
        body = fleet_ok(result, message_key="fleet_mass_expo_success")
        body["state"] = state
        if request_id:
            save_idempotent_action(user_id, request_id, body)
        return jsonify(body)

    state = _fleet_mutation_game_state("api_fleet_mass_expedition")
    err_data: Dict[str, Any] = {"state": state}
    if isinstance(result, dict):
        err_data.update(result)
    return jsonify(fleet_err(reason, data=err_data)), 400


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


@app.route("/api/buildings/stage-layout", methods=["POST"])
@require_login
def api_buildings_stage_layout():
    """GC-BST-10: save/reset per-planet building stage prop positions (display-only)."""
    from game.buildings import save_stage_layout
    from game.planet_evolution.repository import get_context_planet

    data = request.get_json(silent=True) or {}
    user_id = int(session.get("user_id") or 0)
    if user_id <= 0:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    # Display-only layout: do not finish queues or rebuild panels (avoids prop thrash mid-arrange).
    planet = get_context_planet(user_id)
    if not planet:
        state, _ = _build_game_state_payload(include_panel=False, action_slim=True)
        return jsonify({"ok": False, "reason": "no_planet", "state": state}), 400

    reset = bool(data.get("reset"))
    positions = data.get("positions") if isinstance(data.get("positions"), list) else []
    ok, reason, extra = save_stage_layout(
        int(planet["id"]),
        user_id,
        positions,
        reset=reset,
    )
    if not ok:
        state, _ = _build_game_state_payload(include_panel=False, action_slim=True)
        status = 403 if reason == "forbidden" else 400
        return jsonify({"ok": False, "reason": reason, "state": state}), status

    resp = _action_json_response(
        True,
        "ok",
        payload=extra,
        finish_source="api_buildings_stage_layout",
        include_panel=False,
    )
    response_obj = resp.get_json()
    if isinstance(response_obj, dict) and extra:
        response_obj["stage_layout"] = (extra or {}).get("layout")
        state = response_obj.get("state")
        if isinstance(state, dict):
            state["building_stage_layout"] = (extra or {}).get("layout")
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
        return jsonify(response_obj)
    return resp


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


@app.route("/api/buildings/mine-evolve", methods=["POST"])
@require_login
def api_buildings_mine_evolve():
    """EPIC-29 / GC-2901: Industrial Ascension for production mines."""
    from game.mine_evolution import evolve_mine
    from game.planet_evolution.repository import get_context_planet

    data = request.get_json(silent=True) or {}
    building_type = (data.get("building_type") or request.form.get("building_type") or "").strip()
    if not building_type:
        state, _ = _build_game_state_payload(include_panel=True)
        return jsonify({"ok": False, "reason": "missing_building_type", "state": state}), 400

    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    user_id = int(user_id)

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    planet = get_context_planet(user_id)
    if not planet:
        return jsonify({"ok": False, "reason": "no_planet"}), 400

    ok, reason, extra = evolve_mine(user_id, planet, building_type)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_buildings_mine_evolve",
        include_panel=False,
        panel_delta_keys=[building_type] if building_type else None,
    )
    response_obj = resp.get_json()
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
    return resp


@app.route("/api/shipyard/forge-campaign", methods=["GET"])
@require_login
def api_shipyard_forge_campaign():
    """EPIC-30 / GC-3006: Stellar Forge — current 4-pillar campaign state."""
    from game.db import db
    from game.planet_evolution.repository import get_context_planet
    from game.stellar_forge import panel_forge_fields

    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    conn = db()
    try:
        planet = get_context_planet(int(user_id), conn=conn)
        if not planet:
            return jsonify({"ok": False, "reason": "no_planet"}), 400
        # GC-PERF-PANEL-CONN-001: one connection for both lookups instead of
        # panel_forge_fields opening its own — this endpoint was measurably
        # slow to open (two connections + a second, orphaned EffectResolver).
        fields = panel_forge_fields(planet, conn=conn)
    finally:
        conn.close()

    return jsonify({"ok": True, "forge": fields})


@app.route("/api/shipyard/forge-campaign/start", methods=["POST"])
@require_login
def api_shipyard_forge_campaign_start():
    """EPIC-30 / GC-3006: Begin a Stellar Forge Ascension campaign for the next rank."""
    from game.planet_evolution.repository import get_context_planet
    from game.stellar_forge import start_campaign

    data = request.get_json(silent=True) or {}
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    user_id = int(user_id)

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    planet = get_context_planet(user_id)
    if not planet:
        return jsonify({"ok": False, "reason": "no_planet"}), 400

    ok, reason, extra = start_campaign(user_id, planet)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_shipyard_forge_campaign_start",
        include_panel=False,
    )
    response_obj = resp.get_json()
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
    return resp


@app.route("/api/shipyard/forge-tribute", methods=["POST"])
@require_login
def api_shipyard_forge_tribute():
    """EPIC-30 / GC-3006: Pay the Industrial Tribute (Pillar 1) for the active campaign."""
    from game.planet_evolution.repository import get_context_planet
    from game.stellar_forge import pay_tribute

    data = request.get_json(silent=True) or {}
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    user_id = int(user_id)

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    planet = get_context_planet(user_id)
    if not planet:
        return jsonify({"ok": False, "reason": "no_planet"}), 400

    ok, reason, extra = pay_tribute(user_id, planet)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_shipyard_forge_tribute",
        include_panel=False,
    )
    response_obj = resp.get_json()
    if request_id and isinstance(response_obj, dict):
        save_idempotent_action(user_id, request_id, response_obj)
    return resp


@app.route("/api/shipyard/forge-ascend", methods=["POST"])
@require_login
def api_shipyard_forge_ascend():
    """EPIC-30 / GC-3006: Complete the Stellar Forge Ascension once all 4 pillars are done."""
    from game.planet_evolution.repository import get_context_planet
    from game.stellar_forge import ascend

    data = request.get_json(silent=True) or {}
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401
    user_id = int(user_id)

    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    planet = get_context_planet(user_id)
    if not planet:
        return jsonify({"ok": False, "reason": "no_planet"}), 400

    ok, reason, extra = ascend(user_id, planet)
    resp = _action_json_response(
        ok,
        reason,
        payload=extra if not ok else None,
        job=extra if ok else None,
        finish_source="api_shipyard_forge_ascend",
        include_panel=False,
        panel_delta_keys=["orbital_shipyard"],
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
            planet_state = get_planet_state_payload(
                active_id, player_id=user_id, conn=conn, ssr_boot=True
            )
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
    from game.planet_visuals import apply_herocard_urls_to_switcher_planets

    return jsonify({
        "ok": True,
        "planets": apply_herocard_urls_to_switcher_planets(
            list_player_planets_for_switcher(user_id),
            versioned_static_url,
        ),
    })


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
    if not ok and reason == "lock_busy":
        return jsonify({"ok": False, "reason": reason, "retry": True}), 409
    state, _ = _build_game_state_payload(
        include_panel=False,
        finish_source="api_planets_active",
        action_slim=True,
    )
    # GC-BST-22: stage positions immediately on soft buildings switch (display-only).
    if ok and isinstance(state, dict):
        try:
            from game.buildings import resolve_stage_layout

            state["building_stage_layout"] = resolve_stage_layout(planet_id)
        except Exception:
            pass
    planets = None
    if ok:
        from game.galaxy import sync_galaxy_view_session_for_planet
        from game.planet_evolution.repository import get_context_planet

        sync_galaxy_view_session_for_planet(session, get_context_planet(user_id))
        from game.planet_evolution.service import list_player_planets_for_switcher
        from game.planet_visuals import apply_herocard_urls_to_switcher_planets

        planets = apply_herocard_urls_to_switcher_planets(
            list_player_planets_for_switcher(user_id),
            versioned_static_url,
        )
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


@app.route("/api/planets/<int:planet_id>/research/cancel", methods=["POST"])
@require_login
def api_planet_research_cancel(planet_id: int):
    """GC-PE-CANCEL-001 — cancel planet research job with refund (owner: cancel_planet_research_job)."""
    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get("job_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "reason": "missing_job_id"}), 400
    if job_id <= 0:
        return jsonify({"ok": False, "reason": "missing_job_id"}), 400
    from game.planet_evolution.planet_research import cancel_planet_research_job
    from game.models import get_planet_owner_id

    if get_planet_owner_id(planet_id) != int(session["user_id"]):
        return jsonify({"ok": False, "reason": "forbidden"}), 403
    ok, reason = cancel_planet_research_job(planet_id, job_id)
    return _action_json_response(ok, reason, finish_source="api_planet_research_cancel")


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
    """Deprecated — use Control Center JSON APIs (`/api/admin/*`)."""
    flash(
        T("admin_legacy_post_deprecated")
        or "Legacy Admin-POST ist deaktiviert. Bitte das Control Center (AJAX) nutzen.",
        "error",
    )
    return redirect(url_for("admin_panel"))


@app.route("/admin/resources", methods=["POST"])
@require_login
@require_admin
def admin_resources():
    """Deprecated — use POST /api/admin/resources."""
    flash(
        T("admin_legacy_post_deprecated")
        or "Legacy Admin-POST ist deaktiviert. Bitte das Control Center (AJAX) nutzen.",
        "error",
    )
    return redirect(url_for("admin_panel"))


@app.route("/admin/wipe", methods=["POST"])
@require_login
@require_admin
def admin_wipe_universe():
    """Deprecated — use universe reset in Control Center."""
    flash(
        T("admin_wipe_deprecated")
        or "Legacy-Wipe ist deaktiviert. Nutze „Universum resetten“ im Admin Panel.",
        "error",
    )
    return redirect(url_for("admin_panel"))


@app.route("/admin/ban", methods=["POST"])
@require_login
@require_admin
def admin_ban_user():
    """Deprecated — use Players tab /api/admin/players ban actions."""
    flash(
        T("admin_legacy_post_deprecated")
        or "Legacy Admin-POST ist deaktiviert. Bitte das Control Center (AJAX) nutzen.",
        "error",
    )
    return redirect(url_for("admin_panel"))


@app.route("/admin/unban", methods=["POST"])
@require_login
@require_admin
def admin_unban_user():
    """Deprecated — use Players tab /api/admin unban actions."""
    flash(
        T("admin_legacy_post_deprecated")
        or "Legacy Admin-POST ist deaktiviert. Bitte das Control Center (AJAX) nutzen.",
        "error",
    )
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
        "internal_error": 500,
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


@app.route("/api/admin/performance", methods=["GET"])
@require_admin_api
def api_admin_performance():
    return _admin_json(admin_api_logic.api_performance())


@app.route("/api/admin/players", methods=["GET"])
@require_admin_api
def api_admin_players_search():
    online_raw = str(request.args.get("online") or "").strip().lower()
    online_only = online_raw in ("1", "true", "yes")
    return _admin_json(
        admin_api_logic.search_players(
            request.args.get("q", ""),
            online_only=online_only,
        )
    )


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


@app.route("/api/admin/player/<int:player_id>/research", methods=["POST"])
@require_admin_api
def api_admin_player_research(player_id: int):
    return _admin_json(admin_api_logic.set_player_research(_admin_actor_id(), player_id, _admin_body()))


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


@app.route("/api/admin/promos/state", methods=["GET"])
@require_admin_api
def api_admin_promos_state():
    return _admin_json(admin_api_logic.promos_admin_state())


@app.route("/api/admin/promos/creators", methods=["POST"])
@require_admin_api
def api_admin_promos_create_creator():
    return _admin_json(admin_api_logic.create_creator_admin(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/promos/codes", methods=["POST"])
@require_admin_api
def api_admin_promos_create_code():
    return _admin_json(admin_api_logic.create_promo_admin(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/promos/codes/active", methods=["POST"])
@require_admin_api
def api_admin_promos_set_active():
    return _admin_json(admin_api_logic.set_promo_active_admin(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/promos/payout", methods=["POST"])
@require_admin_api
def api_admin_promos_payout():
    return _admin_json(admin_api_logic.payout_creator_admin(_admin_actor_id(), _admin_body()))


@app.route("/api/admin/promos/<int:creator_id>/ledger.csv", methods=["GET"])
@require_admin_api
def api_admin_promos_ledger_csv(creator_id: int):
    from flask import Response

    res = admin_api_logic.creator_ledger_csv_admin(int(creator_id))
    if not res.get("ok"):
        return _admin_json(res)
    return Response(
        res.get("csv") or "",
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=creator_{creator_id}_ledger.csv"
        },
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


@app.route("/api/admin/planet/<int:planet_id>/buildings", methods=["POST"])
@require_admin_api
def api_admin_planet_buildings(planet_id: int):
    return _admin_json(admin_api_logic.set_planet_buildings_bulk(_admin_actor_id(), planet_id, _admin_body()))


@app.route("/api/admin/planet/<int:planet_id>/defense", methods=["POST"])
@require_admin_api
def api_admin_planet_defense(planet_id: int):
    return _admin_json(admin_api_logic.set_planet_defense_stock(_admin_actor_id(), planet_id, _admin_body()))


@app.route("/api/admin/inactive/storage-boost", methods=["POST"])
@require_admin_api
def api_admin_inactive_storage_boost():
    return _admin_json(admin_api_logic.boost_inactive_storage(_admin_actor_id(), _admin_body()))


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


@app.route("/api/admin/fleet-mission-locks", methods=["GET"])
@require_admin_api
def api_admin_fleet_mission_locks_get():
    return _admin_json(admin_api_logic.get_fleet_mission_locks_admin())


@app.route("/api/admin/fleet-mission-locks", methods=["POST"])
@require_admin_api
def api_admin_fleet_mission_locks_set():
    return _admin_json(
        admin_api_logic.set_fleet_mission_lock_admin(_admin_actor_id(), _admin_body())
    )


@app.route("/api/admin/fleet-mission-locks/reset-attack-protection", methods=["POST"])
@require_admin_api
def api_admin_fleet_mission_locks_reset_attack():
    return _admin_json(
        admin_api_logic.reset_fleet_attack_protection_admin(_admin_actor_id(), _admin_body())
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
    from game.config import init_config
    from game.dev_singleton import ensure_dev_port_available

    init_config()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    db_path = str(os.environ.get("GC_DB_PATH") or "").replace("\\", "/")
    if sys.platform == "win32" and db_path in ("/data/game.db", "data/game.db"):
        print(
            "[GC] WARN: GC_DB_PATH=/data/game.db is for Railway, not local Windows dev. "
            "Use GC_DB_PATH=game/game.db and FLASK_DEBUG=1 in .env — see .env.example.",
            file=sys.stderr,
        )
    if is_production() and is_debug_enabled():
        print("[GC] ERROR: Refusing to run production with FLASK_DEBUG=1", file=sys.stderr)
        raise SystemExit(1)
    # Local SQLite: serialize Werkzeug requests (threaded=0). Concurrent threads
    # contend on the single writer → busy_timeout waits → PJAX timeouts →
    # hard-load cascades (CloseWait pileup). Override with GC_FLASK_THREADED=1.
    db_backend = os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()
    threaded_default = "0" if (not is_production() and db_backend == "sqlite") else ("1" if not is_production() else "0")
    threaded_raw = os.environ.get("GC_FLASK_THREADED", threaded_default).strip().lower()
    threaded = threaded_raw in ("1", "true", "yes", "on")
    reloader_default = "0" if sys.platform == "win32" else ("1" if is_debug_enabled() else "0")
    reloader_raw = os.environ.get("GC_FLASK_RELOADER", reloader_default).strip().lower()
    use_reloader = reloader_raw in ("1", "true", "yes", "on")
    if not threaded and not is_production() and db_backend == "sqlite":
        print("[GC] Flask threaded=0 (SQLite local default — set GC_FLASK_THREADED=1 to override)")
    # GC-AST-LIVE: the /ws/galaxy/<g>/<s> route holds a long-lived connection
    # open. Under the non-threaded local Werkzeug dev server that would pin
    # the server's single worker thread for as long as the socket is open,
    # freezing every other request on the site. Only mark WS safe here when
    # this process can actually serve concurrent requests (threaded=1); this
    # __main__ block never runs under gunicorn, where ws_long_lived_safe()
    # instead checks GUNICORN_WORKER_CLASS (see that function's docstring).
    app.config["GC_WS_LONG_LIVED_SAFE"] = bool(threaded)
    if not threaded:
        print(
            "[GC] Galaxy live-push (WS) disabled on this non-threaded dev server — "
            "falls back to polling. Set GC_FLASK_THREADED=1 to test it locally."
        )
    # One local server only: free PORT before bind (skip in production / GC_SINGLE_INSTANCE=0).
    # With Werkzeug reloader, only the child process binds — free there.
    if (not use_reloader) or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        ensure_dev_port_available(port)
    app.run(host=host, port=port, debug=is_debug_enabled(), threaded=threaded, use_reloader=use_reloader)
