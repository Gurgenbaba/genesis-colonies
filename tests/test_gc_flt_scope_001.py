from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_zero_ship_ssr_keeps_healable_fleet_dom_mounted():
    tpl = (ROOT / "templates/fleet.html").read_text(encoding="utf-8")
    assert "data-fleet-ships-content" in tpl
    assert 'fleet-no-ships-panel" aria-live="polite"{% if fleet_ctx.has_ships %} hidden{% endif %}' in tpl
    assert 'data-fleet-ships-content{% if not fleet_ctx.has_ships %} hidden{% endif %}' in tpl
    assert 'id="fleet-send-form"' in tpl
    assert 'novalidate{% if not fleet_ctx.has_ships %} hidden{% endif %}' in tpl
    # The old branch physically omitted ship rows/form for zero-ship SSR and made
    # the subsequent planet-gated live refresh unable to heal the page.
    assert "{% if not fleet_ctx.has_ships %}\n      <section" not in tpl


def test_fleet_live_refresh_can_flip_empty_state_to_real_ship_ui():
    source = (ROOT / "static/main.js").read_text(encoding="utf-8")
    start = source.index("// GC-FLEET-PLANET-SWITCH-001: drop stale /api/fleet/state")
    block = source[start : start + 4500]
    assert 'page.querySelector("[data-fleet-ships-content]")' in block
    assert "shipsContent.hidden = totalShips <= 0" in block
    assert "noShipsPanel.hidden = totalShips > 0" in block
    assert "sendForm.hidden = totalShips <= 0" in block


def test_planet_switch_scopes_fleet_navigation_urls():
    source = (ROOT / "static/main.js").read_text(encoding="utf-8")
    start = source.index("function syncScopedPlanetIds(planetId) {")
    block = source[start : start + 4200]
    assert 'a[data-nav-module="fleet"]' in block
    assert 'a[data-nav-module="logistics"]' in block
    assert "a[data-fleet-mode-tab]" in block
    assert 'scoped.searchParams.set("planet_id", String(pid))' in block


def test_fleet_navigation_links_are_server_scoped_to_active_planet():
    sidebar = (ROOT / "templates/partials/sidebar.html").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    fleet = (ROOT / "templates/fleet.html").read_text(encoding="utf-8")
    assert "HEADER_ACTIVE_PLANET.planet_id" in sidebar
    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in sidebar
    assert "HEADER_ACTIVE_PLANET.planet_id" in base
    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in base
    assert "url_for('fleet_view', mode='collect', planet_id=_fleet_nav_planet_id)" in base
    assert "url_for('fleet_view', planet_id=_fleet_scope_pid)" in fleet
    assert "url_for('fleet_view', mode='collect', planet_id=_fleet_scope_pid)" in fleet
    assert "url_for('fleet_view', mode='distribute', planet_id=_fleet_scope_pid)" in fleet


def test_existing_planet_gated_fleet_refresh_remains_canonical():
    source = (ROOT / "static/main.js").read_text(encoding="utf-8")
    start = source.index("// GC-FLEET-PLANET-SWITCH-001: soft fleet refresh with explicit planet gate")
    block = source[start : start + 1600]
    assert "await GC.refreshFleetState(fleetPage" in block
    assert "planetId," in block
    assert 'reason: "planet_switch"' in block
    assert "force: true" in block


def test_legacy_logistics_redirect_preserves_planet_scope():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.index("def logistics_view():")
    block = source[start : start + 1500]
    assert 'request.args.get("planet_id")' in block
    assert 'redirect_args["planet_id"] = requested_planet_id' in block
    assert 'redirect(url_for("fleet_view", **redirect_args))' in block
