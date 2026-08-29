from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def patch_main_js() -> None:
    p = ROOT / "static/main.js"
    text = p.read_text(encoding="utf-8")

    # The canonical planet switch already updates fleet-page + runtime data and
    # explicitly refreshes /api/fleet/state for the new planet. What was missing:
    # Fleet/Logistics URLs were not planet-scoped, so a soft-nav cache could reuse
    # old SSR HTML for another colony.
    if "GC-FLT-SCOPE-001 nav href scope" not in text:
        old = '''    document.querySelectorAll(".overview-wrapper[data-planet-id]").forEach((el) => {\n      el.dataset.planetId = String(pid);\n    });\n  }\n'''
        new = '''    document.querySelectorAll(".overview-wrapper[data-planet-id]").forEach((el) => {\n      el.dataset.planetId = String(pid);\n    });\n\n    // GC-FLT-SCOPE-001 nav href scope: make Fleet/Logistics soft-nav cache keys\n    // colony-specific. The server still owns/validates the canonical active planet.\n    document\n      .querySelectorAll(\n        'a[data-nav-module="fleet"], a[data-nav-module="logistics"], a[data-fleet-mode-tab]'\n      )\n      .forEach((link) => {\n        const href = String(link.getAttribute("href") || "").trim();\n        if (!href) return;\n        try {\n          const scoped = new URL(href, window.location.origin);\n          scoped.searchParams.set("planet_id", String(pid));\n          link.setAttribute("href", `${scoped.pathname}${scoped.search}${scoped.hash}`);\n        } catch (_) {}\n      });\n  }\n'''
        if text.count(old) != 1:
            raise SystemExit(f"static/main.js: syncScopedPlanetIds tail count={text.count(old)}")
        text = text.replace(old, new, 1)

    # GC-FLEET-PLANET-SWITCH-001 already updates stock rows after an explicit
    # planet-gated Fleet refresh. Make the entire ship UI hide/show as one unit so
    # a server-rendered zero-ship planet can transition to a planet with ships.
    if "data-fleet-ships-content" not in text:
        old = '''        const noShipsPanel = page.querySelector(".fleet-no-ships-panel");\n        const sendForm = page.querySelector("#fleet-send-form");\n        if (noShipsPanel) noShipsPanel.hidden = totalShips > 0;\n        if (sendForm) sendForm.hidden = totalShips <= 0;\n'''
        new = '''        const noShipsPanel = page.querySelector(".fleet-no-ships-panel");\n        const shipsContent = page.querySelector("[data-fleet-ships-content]");\n        const sendForm = page.querySelector("#fleet-send-form");\n        if (noShipsPanel) noShipsPanel.hidden = totalShips > 0;\n        if (shipsContent) shipsContent.hidden = totalShips <= 0;\n        if (sendForm) sendForm.hidden = totalShips <= 0;\n'''
        if text.count(old) != 1:
            raise SystemExit(f"static/main.js: Fleet has_ships toggle anchor count={text.count(old)}")
        text = text.replace(old, new, 1)

    p.write_text(text, encoding="utf-8")


def patch_fleet_template() -> None:
    p = ROOT / "templates/fleet.html"
    text = p.read_text(encoding="utf-8")

    if "data-fleet-ships-content" not in text:
        old = '''      {% if not fleet_ctx.has_ships %}\n      <section class="gc-panel fleet-panel fleet-no-ships-panel" aria-live="polite">\n        <p class="fleet-empty">{{ T("fleet_no_ships_hint") }}</p>\n        <a href="{{ url_for('shipyard_view') }}" class="gc-nav-link gc-btn gc-btn-primary">{{ T("fleet_go_shipyard_btn") }}</a>\n      </section>\n      {% else %}\n\n      <form id="fleet-send-form" class="fleet-send-form" method="post" action="#" data-no-pjax novalidate>\n'''
        new = '''      {# GC-FLT-SCOPE-001: both states stay mounted so a planet-gated live refresh can\n         heal zero-ships -> ships without requiring stale SSR markup to grow nodes. #}\n      <section class="gc-panel fleet-panel fleet-no-ships-panel" aria-live="polite"{% if fleet_ctx.has_ships %} hidden{% endif %}>\n        <p class="fleet-empty">{{ T("fleet_no_ships_hint") }}</p>\n        <a href="{{ url_for('shipyard_view') }}" class="gc-nav-link gc-btn gc-btn-primary">{{ T("fleet_go_shipyard_btn") }}</a>\n      </section>\n\n      <div data-fleet-ships-content{% if not fleet_ctx.has_ships %} hidden{% endif %}>\n      <form id="fleet-send-form" class="fleet-send-form" method="post" action="#" data-no-pjax novalidate{% if not fleet_ctx.has_ships %} hidden{% endif %}>\n'''
        if text.count(old) != 1:
            raise SystemExit(f"fleet.html: no-ships branch opening count={text.count(old)}")
        text = text.replace(old, new, 1)

        old_close = '''        </section>\n\n      {% endif %}\n    </div>\n\n    <div class="fleet-ogame-logistics"'''
        new_close = '''        </section>\n\n      </div>\n    </div>\n\n    <div class="fleet-ogame-logistics"'''
        if text.count(old_close) != 1:
            raise SystemExit(f"fleet.html: no-ships branch closing count={text.count(old_close)}")
        text = text.replace(old_close, new_close, 1)

    # Keep in-page mode changes on the same planet-specific URL/cache namespace.
    if "_fleet_scope_pid" not in text:
        anchor = "{% set fleet_logistics_mode = fleet_mode if fleet_mode in ('collect', 'distribute') else 'collect' %}\n"
        if text.count(anchor) != 1:
            raise SystemExit("fleet.html: mode scope anchor missing")
        text = text.replace(
            anchor,
            anchor + "{% set _fleet_scope_pid = fleet_ctx.planet_id if fleet_ctx.planet_id is defined else none %}\n",
            1,
        )

        replacements = {
            '<a href="{{ url_for(\'fleet_view\') }}"\n       class="gc-page-tab fleet-mode-tab':
                '<a href="{{ url_for(\'fleet_view\', planet_id=_fleet_scope_pid) if _fleet_scope_pid else url_for(\'fleet_view\') }}"\n       class="gc-page-tab fleet-mode-tab',
            '<a href="{{ url_for(\'fleet_view\') }}?mode=collect"\n       class="gc-page-tab fleet-mode-tab':
                '<a href="{{ url_for(\'fleet_view\', mode=\'collect\', planet_id=_fleet_scope_pid) if _fleet_scope_pid else url_for(\'fleet_view\', mode=\'collect\') }}"\n       class="gc-page-tab fleet-mode-tab',
            '<a href="{{ url_for(\'fleet_view\') }}?mode=distribute"\n       class="gc-page-tab fleet-mode-tab':
                '<a href="{{ url_for(\'fleet_view\', mode=\'distribute\', planet_id=_fleet_scope_pid) if _fleet_scope_pid else url_for(\'fleet_view\', mode=\'distribute\') }}"\n       class="gc-page-tab fleet-mode-tab',
        }
        for old, new in replacements.items():
            if text.count(old) != 1:
                raise SystemExit(f"fleet.html: mode-tab anchor count={text.count(old)}: {old[:80]!r}")
            text = text.replace(old, new, 1)

    p.write_text(text, encoding="utf-8")


def patch_shell_templates() -> None:
    # Desktop/mobile sidebar uses the same partial.
    p = ROOT / "templates/partials/sidebar.html"
    text = p.read_text(encoding="utf-8")
    if "_fleet_nav_planet_id" not in text:
        anchor = "{% set _sn = SIDEBAR_NAV or {'full_nav': true, 'modules': {}} %}\n"
        if text.count(anchor) != 1:
            raise SystemExit("sidebar.html: top anchor missing")
        text = text.replace(
            anchor,
            anchor
            + "{% set _fleet_nav_planet_id = (HEADER_ACTIVE_PLANET.planet_id if HEADER_ACTIVE_PLANET is defined and HEADER_ACTIVE_PLANET else none) %}\n",
            1,
        )
        old = '<a href="{{ url_for(\'fleet_view\') }}"\n         data-nav-module="fleet"'
        new = '<a href="{{ url_for(\'fleet_view\', planet_id=_fleet_nav_planet_id) if _fleet_nav_planet_id else url_for(\'fleet_view\') }}"\n         data-nav-module="fleet"'
        if text.count(old) != 1:
            raise SystemExit(f"sidebar.html: fleet nav anchor count={text.count(old)}")
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")

    p = ROOT / "templates/base.html"
    text = p.read_text(encoding="utf-8")
    if "_fleet_nav_planet_id" not in text:
        anchor = "{% set _fleet_mode = request.args.get('mode', 'send')|lower %}\n"
        if text.count(anchor) != 1:
            raise SystemExit("base.html: fleet mode anchor missing")
        text = text.replace(
            anchor,
            anchor
            + "{% set _fleet_nav_planet_id = (HEADER_ACTIVE_PLANET.planet_id if HEADER_ACTIVE_PLANET is defined and HEADER_ACTIVE_PLANET else none) %}\n",
            1,
        )
        old_fleet = '<a href="{{ url_for(\'fleet_view\') }}"\n       data-nav-module="fleet"'
        new_fleet = '<a href="{{ url_for(\'fleet_view\', planet_id=_fleet_nav_planet_id) if _fleet_nav_planet_id else url_for(\'fleet_view\') }}"\n       data-nav-module="fleet"'
        if text.count(old_fleet) != 1:
            raise SystemExit(f"base.html: bottom fleet nav anchor count={text.count(old_fleet)}")
        text = text.replace(old_fleet, new_fleet, 1)

        old_log = '<a href="{{ url_for(\'fleet_view\') }}?mode=collect"\n       data-nav-module="logistics"'
        new_log = '<a href="{{ url_for(\'fleet_view\', mode=\'collect\', planet_id=_fleet_nav_planet_id) if _fleet_nav_planet_id else url_for(\'fleet_view\', mode=\'collect\') }}"\n       data-nav-module="logistics"'
        if text.count(old_log) != 1:
            raise SystemExit(f"base.html: bottom logistics nav anchor count={text.count(old_log)}")
        text = text.replace(old_log, new_log, 1)
    p.write_text(text, encoding="utf-8")


def patch_app() -> None:
    p = ROOT / "app.py"
    text = p.read_text(encoding="utf-8")
    if "GC-FLT-SCOPE-001: legacy /logistics" not in text:
        old = '''    mode = (request.args.get("mode") or "collect").strip().lower()\n    if mode not in ("collect", "distribute"):\n        mode = "collect"\n    return redirect(f"{url_for('fleet_view')}?mode={mode}")\n'''
        new = '''    mode = (request.args.get("mode") or "collect").strip().lower()\n    if mode not in ("collect", "distribute"):\n        mode = "collect"\n\n    # GC-FLT-SCOPE-001: preserve the planet-scoped navigation/cache key. The\n    # canonical active planet remains server-owned and is not mutated by this GET.\n    redirect_args: Dict[str, Any] = {"mode": mode}\n    try:\n        requested_planet_id = int(request.args.get("planet_id") or 0)\n    except (TypeError, ValueError):\n        requested_planet_id = 0\n    if requested_planet_id > 0:\n        redirect_args["planet_id"] = requested_planet_id\n    return redirect(url_for("fleet_view", **redirect_args))\n'''
        if text.count(old) != 1:
            raise SystemExit(f"app.py: logistics redirect anchor count={text.count(old)}")
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


def write_tests() -> None:
    p = ROOT / "tests/test_gc_flt_scope_001.py"
    p.write_text('''from __future__ import annotations\n\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parent.parent\n\n\ndef test_zero_ship_ssr_keeps_healable_fleet_dom_mounted():\n    tpl = (ROOT / "templates/fleet.html").read_text(encoding="utf-8")\n    assert "data-fleet-ships-content" in tpl\n    assert 'fleet-no-ships-panel" aria-live="polite"{% if fleet_ctx.has_ships %} hidden{% endif %}' in tpl\n    assert 'data-fleet-ships-content{% if not fleet_ctx.has_ships %} hidden{% endif %}' in tpl\n    assert 'id="fleet-send-form"' in tpl\n    assert 'novalidate{% if not fleet_ctx.has_ships %} hidden{% endif %}' in tpl\n    # The old branch physically omitted ship rows/form for zero-ship SSR and made\n    # the subsequent planet-gated live refresh unable to heal the page.\n    assert "{% if not fleet_ctx.has_ships %}\\n      <section" not in tpl\n\n\ndef test_fleet_live_refresh_can_flip_empty_state_to_real_ship_ui():\n    source = (ROOT / "static/main.js").read_text(encoding="utf-8")\n    start = source.index("// GC-FLEET-PLANET-SWITCH-001: drop stale /api/fleet/state")\n    block = source[start : start + 4500]\n    assert 'page.querySelector("[data-fleet-ships-content]")' in block\n    assert "shipsContent.hidden = totalShips <= 0" in block\n    assert "noShipsPanel.hidden = totalShips > 0" in block\n    assert "sendForm.hidden = totalShips <= 0" in block\n\n\ndef test_planet_switch_scopes_fleet_navigation_urls():\n    source = (ROOT / "static/main.js").read_text(encoding="utf-8")\n    start = source.index("function syncScopedPlanetIds(planetId) {")\n    block = source[start : start + 4200]\n    assert 'a[data-nav-module="fleet"]' in block\n    assert 'a[data-nav-module="logistics"]' in block\n    assert "a[data-fleet-mode-tab]" in block\n    assert 'scoped.searchParams.set("planet_id", String(pid))' in block\n\n\ndef test_fleet_navigation_links_are_server_scoped_to_active_planet():\n    sidebar = (ROOT / "templates/partials/sidebar.html").read_text(encoding="utf-8")\n    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")\n    fleet = (ROOT / "templates/fleet.html").read_text(encoding="utf-8")\n    assert "HEADER_ACTIVE_PLANET.planet_id" in sidebar\n    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in sidebar\n    assert "HEADER_ACTIVE_PLANET.planet_id" in base\n    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in base\n    assert "url_for('fleet_view', mode='collect', planet_id=_fleet_nav_planet_id)" in base\n    assert "url_for('fleet_view', planet_id=_fleet_scope_pid)" in fleet\n    assert "url_for('fleet_view', mode='collect', planet_id=_fleet_scope_pid)" in fleet\n    assert "url_for('fleet_view', mode='distribute', planet_id=_fleet_scope_pid)" in fleet\n\n\ndef test_existing_planet_gated_fleet_refresh_remains_canonical():\n    source = (ROOT / "static/main.js").read_text(encoding="utf-8")\n    start = source.index("// GC-FLEET-PLANET-SWITCH-001: soft fleet refresh with explicit planet gate")\n    block = source[start : start + 1600]\n    assert "await GC.refreshFleetState(fleetPage" in block\n    assert "planetId," in block\n    assert 'reason: "planet_switch"' in block\n    assert "force: true" in block\n\n\ndef test_legacy_logistics_redirect_preserves_planet_scope():\n    source = (ROOT / "app.py").read_text(encoding="utf-8")\n    start = source.index("def logistics_view():")\n    block = source[start : start + 1500]\n    assert 'request.args.get("planet_id")' in block\n    assert 'redirect_args["planet_id"] = requested_planet_id' in block\n    assert 'redirect(url_for("fleet_view", **redirect_args))' in block\n''', encoding="utf-8")


def patch_ci() -> None:
    p = ROOT / ".github/workflows/ci.yml"
    text = p.read_text(encoding="utf-8")
    if "tests/test_gc_flt_scope_001.py" not in text:
        anchor = "tests/test_gc_perf_resource_persist_001.py tests/test_gc_perf_buildings_002.py \\\n"
        if text.count(anchor) != 1:
            raise SystemExit(f"ci.yml: smoke anchor count={text.count(anchor)}")
        text = text.replace(
            anchor,
            "tests/test_gc_perf_resource_persist_001.py tests/test_gc_perf_buildings_002.py tests/test_gc_flt_scope_001.py \\\n",
            1,
        )
    p.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app()
    patch_main_js()
    patch_fleet_template()
    patch_shell_templates()
    write_tests()
    patch_ci()
    print("GC-FLT-SCOPE-001 codemod applied")


if __name__ == "__main__":
    main()
