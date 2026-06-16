"""GC-585 — Fleet route VFX on command map (frontend contract)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gc585_template_fleet_route_vfx_markup():
    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")
    for needle in (
        "galaxy-command-map-fleet-route-group",
        "galaxy-command-map-fleet-route-flow",
        "galaxy-command-map-fleet-route-ship--colonize",
        "galaxy-command-map-fleet-route-ship--expedition",
        "galaxy-command-map-fleet-route-ship--cargo",
        "galaxy-command-map-fleet-route-ship--attack",
        "animateMotion",
        "data-fleet-route-tooltip",
        "galaxy-command-map-fleet-route-dest--expedition",
    ):
        assert needle in tpl, f"missing template marker: {needle}"


def test_gc585_css_fleet_route_vfx():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    for needle in (
        ".galaxy-command-map-fleet-route-flow--colonize",
        ".galaxy-command-map-fleet-route-flow--expedition",
        ".galaxy-command-map-fleet-route-ship--cargo",
        ".galaxy-command-map-fleet-route-group--returning",
        "@keyframes galaxy-command-map-fleet-flow",
        ".galaxy-command-map-fleet-route-tooltip",
        ".galaxy-command-map-influence-blob",
        "stroke-linejoin: round",
    ):
        assert needle in css, f"missing css rule: {needle}"
    assert "animation-direction: reverse" not in css.split(".galaxy-command-map-fleet-route-group--returning")[1].split("}")[0]


def test_gc585_main_js_fleet_route_tooltips():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "function initCommandMapFleetRoutes()" in js
    assert "initCommandMapFleetRoutes();" in js
    assert "fleet_route_tooltip_from" in js
    assert "resolveRouteLabel" in js


def test_gc585_locale_tooltip_keys():
    import json

    for path in ("locales/en.json", "locales/de.json"):
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for key in (
            "fleet_route_tooltip_mission",
            "fleet_route_tooltip_from",
            "fleet_route_tooltip_to",
            "fleet_route_tooltip_status",
            "fleet_route_tooltip_eta",
        ):
            assert key in data, f"missing {key} in {path}"
