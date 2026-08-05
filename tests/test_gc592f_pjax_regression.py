"""GC-592F: PJAX reload regression guards after Command Center / sidebar changes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pjax_nav_link_covers_sidebar_and_command_center():
    src = _read("static/main.js")
    assert "#gc-sidebar-nav a[href]" in src
    assert "#gc-sidebar-nav-right a[href]" in src
    assert "a.gc-command-center-action-btn" in src
    assert "a.gc-command-center-fleet-link" in src
    assert "a.galaxy-view-tab" in src
    assert "a[data-gc-nav]" in src
    assert "a[data-pjax]" in src
    assert "a[data-pjax-link]" in src
    assert "a.gc-header-icon-btn" in src
    assert "header.gc-header a[href]" in src
    assert ".gc-topbar a[href]" in src


def test_header_topbar_links_are_pjax_marked():
    """Top bar LiveOps icons + logo must be PJAX-eligible (outside #main-content)."""
    rail = _read("templates/partials/header_icon_rail.html")
    assert 'data-gc-nav' in rail
    assert 'class="gc-header-icon-btn"' in rail
    assert "login_rewards_view" in rail
    assert "premium_view" in rail
    ini = _read("templates/partials/initiation_hud.html")
    assert "data-gc-nav" in ini
    base = _read("templates/base.html")
    logo = base.split("gc-hslot-brand")[1].split("gc-hslot")[0]
    assert "gc-logo" in logo
    assert "url_for('overview')" in logo
    assert "data-gc-nav" in logo
    assert "gc-hud-panel-score" in base


def test_command_center_js_links_use_gc_nav_link():
    src = _read("static/main.js")
    cc_section = src.split("function renderColonyCommandCenter")[1].split("function renderStrategicCommandCenter")[0]
    feed_section = src.split("function renderActivityFeed")[1].split("function renderColonyActionCard")[0]
    assert 'link.className = "gc-nav-link gc-command-center-fleet-link"' in cc_section
    assert 'link.className = "gc-nav-link gc-command-center-action-card gc-command-center-action-btn' in cc_section or 'renderColonyActionCard' in cc_section
    assert 'link.className = "gc-nav-link gc-command-center-activity-link gc-command-center-news-link"' in feed_section
    assert "link.dataset.gcNav = \"1\"" in feed_section


def test_command_center_primary_and_colony_open_use_navigate_to():
    src = _read("static/main.js")
    open_colony = src.split("async function onOpenColonyClick")[1].split("openColonyBtn?.addEventListener")[0]
    assert "applyActionState(res, \"planet_switch\")" in open_colony
    assert 'GC.navigateTo("/overview"' in open_colony
    assert "location.reload" not in open_colony
    assert "location.href" not in open_colony

    primary = src.split("function onPrimaryActionClick")[1].split("async function onOpenColonyClick")[0]
    assert "GC.navigateTo(`/fleet?" in primary
    assert "location.reload" not in primary


def test_galaxy_view_tabs_marked_for_pjax():
    tpl = _read("templates/galaxy.html")
    assert "gc-nav-link galaxy-view-tab galaxy-view-tab--classic" in tpl
    assert "galaxy-view-tab--world is-active" in tpl
    assert "galaxy_view_classic" not in tpl


def test_fleet_internal_links_marked_for_pjax():
    """The shipyard head link's class list was restyled to the shared
    gc-btn/gc-btn-primary button look (fleet-shipyard-head-link removed as a
    class hook), but it must still carry gc-nav-link so clicks stay on the
    PJAX path instead of a full navigation."""
    tpl = _read("templates/fleet.html")
    m = re.search(r'<a href="\{\{ url_for\(\'shipyard_view\'\) \}\}" class="([^"]+)"', tpl)
    assert m, "shipyard head link not found in templates/fleet.html"
    assert "gc-nav-link" in m.group(1).split()


def test_sidebar_module_links_are_pjax_eligible_markup():
    tpl = _read("templates/partials/sidebar.html")
    href_links = re.findall(r"<a\s+[^>]*href=\"[^\"]+\"[^>]*>", tpl)
    assert href_links, "sidebar should contain module links"
    for tag in href_links:
        assert "gc-nav-sub-link" in tag or "gc-nav-link" in tag, f"missing PJAX nav class: {tag}"


def test_gc804_leftmenu_state_restored_after_pjax_init():
    """GC-804: sidebar accordion persists via localStorage + restoreLeftmenuState after PJAX.

    Optimistic `_syncNavActive` on PJAX coalesce (latest-wins queue) is allowed so
    the rail highlights the destination while the single in-flight HTML fetch
    finishes — full accordion restore still runs via initPage after apply.
    """
    src = _read("static/main.js")
    navigate = src.split("GC.navigateTo = async function navigateTo", 1)[1].split("function initPjax", 1)[0]
    # Coalesce may call _syncNavActive; must not call restoreLeftmenuState directly.
    assert "GC.restoreLeftmenuState(url)" not in navigate
    assert "[GC] PJAX coalesce" in navigate
    # The initPage() call was factored out of navigateTo into the shared
    # applyPjaxPayload() helper (used by both the cached-galaxy-payload fast
    # path and the network-fetch path), so assert the call chain instead of
    # an inline call.
    assert "applyPjaxPayload(" in navigate
    apply_payload = src.split("async function applyPjaxPayload", 1)[1].split(
        "function pjaxPayloadFromDoc", 1
    )[0]
    assert "await GC.initPage(" in apply_payload
    init_pjax = src.split("function initPjax", 1)[1].split("// =========================", 2)[0]
    assert "tryHandleSubnavParentClick(link, e)" not in init_pjax
    assert "pathFromMenuUrl" in src
    assert "linkPathMatchesRoute" in src
    assert "resolveNavSectionExpanded" in src
    assert 'path.endsWith("/fleet")' in src.split("function applyLeftmenuPathRouteHints", 1)[1].split("function resolveLeftmenuRouteContext", 1)[0]


ALLOWLIST_HREF_ASSIGN = {
    # window.location.assign("/login") is the primary path; this is only a
    # fallback if assign() throws — a genuine full-page exit from the SPA on
    # auth loss, not an in-game PJAX navigation.
    (1048, 'window.location.href = "/login";'),
    # Radar / deep-link nav: only if GC.navigateTo is missing.
    (13944, "window.location.href = url;"),
    # Galaxy/system quick-nav input: only reached if GC.navigateTo is somehow
    # undefined (defensive fallback), mirroring the reloadCurrentPage /
    # locale-switch reload() fallbacks below.
    (37257, "else window.location.href = href;"),
}


def test_no_new_location_href_assignments_in_main_js():
    violations: list[str] = []
    for i, line in enumerate(_read("static/main.js").splitlines(), start=1):
        if re.search(r"\b(?:window\.)?location\.href\s*=", line):
            if "history.replaceState" in line:
                continue
            stripped = line.strip()
            if (i, stripped) in ALLOWLIST_HREF_ASSIGN:
                continue
            violations.append(f"static/main.js:{i}: {stripped}")
    assert not violations, "location.href = in main.js:\n" + "\n".join(violations)


def test_reload_fallback_is_allowlisted_only():
    src = _read("static/main.js")
    reload_lines = [
        (i, line.strip())
        for i, line in enumerate(src.splitlines(), start=1)
        if re.search(r"\b(?:window\.)?location\.reload\s*\(", line)
    ]
    allowed = {
        (2581, "window.location.reload();"),  # reloadCurrentPage fullDocument
        (2616, "window.location.reload();"),  # reloadCurrentPage navigateTo fallback
        (31893, "window.location.reload();"),  # locale switch fallback
    }
    assert reload_lines, "expected allowlisted location.reload() sites"
    assert set(reload_lines) == allowed, (
        "unexpected location.reload() in main.js:\n"
        + "\n".join(f"  {ln}:{txt}" for ln, txt in reload_lines if (ln, txt) not in allowed)
    )


def test_gc_stabilize_002_same_url_pjax_timeout_recovers_instead_of_freezing():
    """GC-STABILIZE-002 / local SQLite: PJAX fetch timeout must toast + release
    blockers and must NOT hard-load (location.assign while Werkzeug still
    finishes the aborted handler causes CloseWait lock cascades).
    """
    src = _read("static/main.js")
    navigate_fn = src.split("GC.navigateTo = async function navigateTo", 1)[1].split(
        "\n  function initPjax", 1
    )[0]
    abort_branch = navigate_fn.split('if (err?.name === "AbortError") {', 1)[1].split(
        "if (_activePjaxNavigation?.id !== navId) return;", 1
    )[0]
    assert "fetchTimedOut && !userAborted" in abort_branch
    assert 'showNotify(' in abort_branch
    assert 't("msg_status_refresh_failed"' in abort_branch
    assert 'GC.releaseShellNavigationBlockers("pjax_timeout")' in abort_branch
    assert "[GC] PJAX timeout (no hard-load)" in abort_branch
    assert "window.location.assign" not in abort_branch
    assert "GC.startPolling" in abort_branch


def test_gc_stabilize_002_pjax_aborts_chat_before_html_fetch():
    """GC-STABILIZE-002: after long idle, chat message polls keep hitting
    SQLite. Light PJAX already aborts hung /api/game-state polls; it must
    also abort in-flight chat polls (without stopping the schedule) so a
    rapid-click supersede chain does not wait behind chat for the writer.
    """
    main = _read("static/main.js")
    chat = _read("static/js/chat.js")
    assert "function abortInFlightChatFetches" in chat
    assert "GC.abortInFlightChatFetches = abortInFlightChatFetches" in chat
    navigate_fn = main.split("GC.navigateTo = async function navigateTo", 1)[1].split(
        "\n  function initPjax", 1
    )[0]
    # Coalesce returns before beginPjaxNavigation; abort must still run on the
    # path that actually starts an HTML fetch.
    start_fetch = navigate_fn.split("const nav = beginPjaxNavigation", 1)[0]
    assert 'GC.abortInFlightChatFetches("pjax_nav")' in start_fetch
    assert "abortInFlightGameStateFetches()" in start_fetch
    # Diet poll schedule must pause for the whole HTML fetch (not only abort
    # the in-flight request) — preserveGameLoop no longer keeps polls alive.
    assert "GC.stopPolling()" in start_fetch.split("const leavingAdmin", 1)[1]
    assert "if (!opts.preserveGameLoop)" not in start_fetch.split("const leavingAdmin", 1)[1].split(
        "const nav = beginPjaxNavigation", 1
    )[0]
    # Coalesce itself must not abort the in-flight HTML request.
    coalesce_branch = navigate_fn.split("[GC] PJAX coalesce", 1)[1].split(
        "const leavingAdmin", 1
    )[0]
    assert "abortInFlightChatFetches" not in coalesce_branch
    assert "abortInFlightGameStateFetches" not in coalesce_branch


def test_gc_pjax_fetch_timeout_above_sqlite_busy_timeout():
    """PJAX client timeout must exceed SQLite busy_timeout (20s) so a single
    lock wait is not misclassified as a dead navigation. Timeout recovery
    must not hard-load (CloseWait cascade).
    """
    src = _read("static/main.js")
    assert "const PJAX_FETCH_TIMEOUT_MS = 25000;" in src
    assert "shouldPjaxHardLoad" not in src
    navigate_fn = src.split("GC.navigateTo = async function navigateTo", 1)[1].split(
        "\n  function initPjax", 1
    )[0]
    abort_branch = navigate_fn.split('if (err?.name === "AbortError") {', 1)[1].split(
        "if (_activePjaxNavigation?.id !== navId) return;", 1
    )[0]
    assert "window.location.assign" not in abort_branch
    assert "[GC] PJAX timeout (no hard-load)" in abort_branch


def test_gc_local_sqlite_flask_threaded_default_off():
    """Local SQLite Werkzeug must default to threaded=0 (serialized requests)."""
    app_py = _read("app.py")
    run_block = app_py.split('if __name__ == "__main__":', 1)[1]
    assert 'threaded_default = "0" if (not is_production() and db_backend == "sqlite")' in run_block
    assert 'os.environ.get("GC_FLASK_THREADED", threaded_default)' in run_block

def test_gc_pjax_coalesce_keeps_inflight_html_fetch():
    """Local SQLite freezes when rapid nav aborts+restarts HTML PJAX — each
    aborted Werkzeug handler still runs. Latest destination must queue
    (`_pjaxPendingNav`) without aborting the in-flight fetch; stale HTML is
    discarded, then the pending URL is fetched (at most one HTML render).
    """
    src = _read("static/main.js")
    navigate_fn = src.split("GC.navigateTo = async function navigateTo", 1)[1].split(
        "\n  function initPjax", 1
    )[0]
    assert "let _pjaxPendingNav = null" in src
    assert "function flushPjaxPendingAfterActive" in src
    assert "[GC] PJAX coalesce" in navigate_fn
    assert "[GC] PJAX discard stale" in navigate_fn
    # Coalesce path must not call beginPjaxNavigation (which aborts).
    coalesce_branch = navigate_fn.split("[GC] PJAX coalesce", 1)[1].split(
        "const leavingAdmin", 1
    )[0]
    assert "beginPjaxNavigation" not in coalesce_branch
    assert "_pjaxCoalesceTail" in coalesce_branch
