"""GC-563B / GC-571C — Command Map viewport markup and interaction tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_command_map_panel_has_viewport_wrappers():
    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")
    assert "data-command-map-viewport" in tpl
    assert "data-command-map-canvas" in tpl
    assert "data-world-width" in tpl
    assert "data-world-height" in tpl
    assert "data-hub-world-x" in tpl
    assert "data-hub-world-y" in tpl
    assert "data-default-scale" in tpl
    assert "--world-x:" in tpl
    assert "--world-y:" in tpl
    assert 'viewBox="0 0 {{ map_world_w }} {{ map_world_h }}"' in tpl
    assert "galaxy-command-map-sector-layer" in tpl
    assert "galaxy-command-map-bg" in tpl
    assert "data-command-map-bg" in tpl
    assert "galaxy-command-map-ambient-glow" in tpl
    assert "data-command-map-sector-root" in tpl
    assert "data-sector-seed" in tpl
    assert "galaxy-command-map-region-panel" not in tpl
    assert "data-command-map-reset" in tpl
    assert "galaxy-command-map-viewport" in tpl
    assert "galaxy-command-map-canvas" in tpl
    assert 'data-command-map-viewport="1"' not in tpl
    assert "galaxy-command-map-nodes--markers" in tpl
    assert "data-command-map-empty-panel" in tpl
    assert "data-command-map-detail-panel" in tpl


def test_command_map_panel_side_panel_hidden_rules():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    assert "[data-command-map-empty-panel][hidden]" in css
    assert "[data-command-map-detail-panel][hidden]" in css
    assert ".galaxy-command-map-site-inspector[hidden]" in css


def test_main_js_command_map_side_panel_state():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "function setCommandMapSidePanelState" in js
    assert "function resetCommandMapSidePanels" in js
    assert 'mode === "detail"' in js


def test_command_map_css_has_viewport_rules():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    assert ".galaxy-command-map-viewport{" in css
    assert ".galaxy-command-map-canvas{" in css
    assert ".galaxy-command-map-bg{" in css
    assert 'url("/static/img/map.png")' in css
    assert "background-repeat: repeat" in css
    assert "background-size: 1600px 900px" in css
    assert "left: -8000px" in css
    assert ".galaxy-command-map-ambient-glow{" in css
    assert "transform-origin: 0 0" in css
    assert "overflow: hidden" in css
    assert "touch-action: none" in css
    assert ".galaxy-command-map-node{" in css
    assert "position: absolute" in css
    assert "calc(var(--world-x" in css
    assert "calc(var(--world-y" in css
    assert ".galaxy-command-map-nodes--markers" in css
    assert ".galaxy-command-map-node.is-selected" in css


def test_main_js_has_command_map_viewport_init():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    block = js[js.index("function initCommandMapViewport") : js.index("function initCommandMapSiteInspector")]
    assert "function initCommandMapViewport" in js
    assert "function initCommandMapSectorLoader" in js
    assert "/api/command-map/sectors" in js
    assert "syncCommandMapBackgroundExtent" in js
    assert "COMMAND_MAP_VIEWPORT_STORAGE_KEY" in js
    assert "gc_command_map_viewport_v6" in js
    assert "isCommandMapInteractiveTarget" in js
    assert "isCommandMapPanSurface" in js
    assert "centerOnHub" in block
    assert "transformOrigin = \"0 0\"" in block
    assert "width / 2 - hubWorldX * state.zoom" in block
    assert "invalid hub world coords" in block
    assert "{ passive: false }" in block
    assert "isViewportStateValid" in block
    assert "clearViewportStorage" in block
    assert "initCommandMapViewport();" in js
    assert "GC.registerCleanup" in block
