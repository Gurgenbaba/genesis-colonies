from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_main_js() -> None:
    p = ROOT / "static/main.js"
    text = p.read_text(encoding="utf-8")

    # GC-FLT-SCOPE-001: bind Fleet's own page scope and every Fleet/Logistics
    # navigation surface to the same planet the canonical planet switcher just
    # selected. Insert directly after the stable function declaration instead of
    # depending on internal tuple/list implementation details.
    if "GC-FLT-SCOPE-001 nav scope" not in text:
        marker = "const syncScopedPlanetIds = (pid) => {"
        if text.count(marker) != 1:
            raise SystemExit(
                f"static/main.js: syncScopedPlanetIds marker count={text.count(marker)}"
            )
        addition = '''const syncScopedPlanetIds = (pid) => {\n    // GC-FLT-SCOPE-001 nav scope: Fleet must never lose the selected origin planet.\n    const fleetPage = document.querySelector("[data-fleet-page]");\n    if (fleetPage) fleetPage.dataset.planetId = String(pid);\n\n    document\n      .querySelectorAll('a[data-nav-module="fleet"], a[data-nav-module="logistics"]')\n      .forEach((link) => {\n        const href = String(link.getAttribute("href") || "").trim();\n        if (!href) return;\n        try {\n          const scoped = new URL(href, window.location.origin);\n          scoped.searchParams.set("planet_id", String(pid));\n          link.setAttribute("href", `${scoped.pathname}${scoped.search}${scoped.hash}`);\n        } catch (_) {}\n      });'''
        text = text.replace(marker, addition, 1)

    # A Fleet page cannot safely morph from a server-rendered no-ships planet to
    # another planet: ship cards/forms may not exist in the DOM at all. Once the
    # canonical POST switch is committed, rebuild /fleet from SSR for that planet.
    if "GC-FLT-SCOPE-001 Fleet SSR rebuild" not in text:
        fn_start = text.find("const switchPlanetFast = async (planetId) => {")
        if fn_start < 0:
            raise SystemExit("static/main.js: switchPlanetFast not found")
        # Limit the regex search to a generous local window; the match itself is
        # anchored on the canonical token guard + applyLiveState success sequence.
        block_end = min(len(text), fn_start + 14000)
        block = text[fn_start:block_end]
        pattern = re.compile(
            r'(if \(token !== _planetSwitchToken\) return false;\s*'
            r'if \(res\?\.state\) \{\s*await applyLiveState\(res\.state\);\s*\})'
        )
        match = pattern.search(block)
        if not match:
            raise SystemExit("static/main.js: successful switch/applyLiveState anchor not found")
        replacement = match.group(1) + '''\n\n      // GC-FLT-SCOPE-001 Fleet SSR rebuild: changing planet while Fleet is open\n      // must rebuild ship cards/empty state from the newly committed planet.\n      if (document.querySelector("[data-fleet-page]")) {\n        const scopedFleetUrl = new URL(window.location.href);\n        scopedFleetUrl.searchParams.set("planet_id", String(pid));\n        window.location.assign(scopedFleetUrl.toString());\n        return true;\n      }'''
        block = block[: match.start()] + replacement + block[match.end() :]
        text = text[:fn_start] + block + text[block_end:]

    p.write_text(text, encoding="utf-8")


def patch_templates() -> None:
    # Desktop/mobile sidebar uses the same partial, so one change covers both.
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
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit("sidebar.html: fleet nav anchor missing")
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
    if old_fleet in text:
        text = text.replace(old_fleet, new_fleet, 1)
    elif new_fleet not in text:
        raise SystemExit("base.html: bottom fleet nav anchor missing")
    old_log = '<a href="{{ url_for(\'fleet_view\') }}?mode=collect"\n       data-nav-module="logistics"'
    new_log = '<a href="{{ url_for(\'fleet_view\', mode=\'collect\', planet_id=_fleet_nav_planet_id) if _fleet_nav_planet_id else url_for(\'fleet_view\', mode=\'collect\') }}"\n       data-nav-module="logistics"'
    if old_log in text:
        text = text.replace(old_log, new_log, 1)
    elif new_log not in text:
        raise SystemExit("base.html: bottom logistics nav anchor missing")
    p.write_text(text, encoding="utf-8")


def patch_app() -> None:
    old = '''    mode = (request.args.get("mode") or "collect").strip().lower()\n    if mode not in ("collect", "distribute"):\n        mode = "collect"\n    return redirect(f"{url_for('fleet_view')}?mode={mode}")\n'''
    new = '''    mode = (request.args.get("mode") or "collect").strip().lower()\n    if mode not in ("collect", "distribute"):\n        mode = "collect"\n\n    # GC-FLT-SCOPE-001: legacy /logistics redirects must preserve the selected\n    # origin planet. /fleet still resolves the canonical owned active planet; the\n    # query parameter is the client/server scope contract, never an ownership bypass.\n    redirect_args: Dict[str, Any] = {"mode": mode}\n    try:\n        requested_planet_id = int(request.args.get("planet_id") or 0)\n    except (TypeError, ValueError):\n        requested_planet_id = 0\n    if requested_planet_id > 0:\n        redirect_args["planet_id"] = requested_planet_id\n    return redirect(url_for("fleet_view", **redirect_args))\n'''
    p = ROOT / "app.py"
    text = p.read_text(encoding="utf-8")
    if "GC-FLT-SCOPE-001: legacy /logistics" not in text:
        if text.count(old) != 1:
            raise SystemExit(f"app.py: logistics redirect anchor count={text.count(old)}")
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")


def write_tests() -> None:
    p = ROOT / "tests/test_gc_flt_scope_001.py"
    p.write_text('''from __future__ import annotations\n\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parent.parent\n\n\ndef test_planet_switch_updates_fleet_page_scope_and_rebuilds_ssr():\n    source = (ROOT / "static/main.js").read_text(encoding="utf-8")\n    start = source.index("const syncScopedPlanetIds = (pid) => {")\n    scope = source[start : start + 3200]\n    assert 'const fleetPage = document.querySelector("[data-fleet-page]")' in scope\n    assert "fleetPage.dataset.planetId = String(pid)" in scope\n    assert 'a[data-nav-module="fleet"], a[data-nav-module="logistics"]' in scope\n    assert 'scoped.searchParams.set("planet_id", String(pid))' in scope\n\n    switch_start = source.index("const switchPlanetFast = async (planetId) => {")\n    switch_block = source[switch_start : switch_start + 14000]\n    assert "GC-FLT-SCOPE-001 Fleet SSR rebuild" in switch_block\n    assert 'document.querySelector("[data-fleet-page]")' in switch_block\n    assert 'scopedFleetUrl.searchParams.set("planet_id", String(pid))' in switch_block\n    assert "window.location.assign(scopedFleetUrl.toString())" in switch_block\n\n\ndef test_fleet_navigation_links_are_server_scoped_to_active_planet():\n    sidebar = (ROOT / "templates/partials/sidebar.html").read_text(encoding="utf-8")\n    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")\n    assert "HEADER_ACTIVE_PLANET.planet_id" in sidebar\n    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in sidebar\n    assert "HEADER_ACTIVE_PLANET.planet_id" in base\n    assert "url_for('fleet_view', planet_id=_fleet_nav_planet_id)" in base\n    assert "url_for('fleet_view', mode='collect', planet_id=_fleet_nav_planet_id)" in base\n\n\ndef test_legacy_logistics_redirect_preserves_planet_scope():\n    source = (ROOT / "app.py").read_text(encoding="utf-8")\n    start = source.index("def logistics_view():")\n    block = source[start : start + 1500]\n    assert 'request.args.get("planet_id")' in block\n    assert 'redirect_args["planet_id"] = requested_planet_id' in block\n    assert 'redirect(url_for("fleet_view", **redirect_args))' in block\n''', encoding="utf-8")


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
    patch_templates()
    write_tests()
    patch_ci()
    print("GC-FLT-SCOPE-001 codemod applied")


if __name__ == "__main__":
    main()
