"""
GC-536F — global queue card UX consolidation contracts.

Run: python -m pytest tests/test_queue_card_global_ux.py tests/test_queue_card_contract.py tests/test_queue_static_contract.py -q
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

QUEUE_PAGES = {
    "buildings": {
        "template": "templates/buildings.html",
        "skip_compact": True,
        "compact_id": "build-queue-compact",
        "card_attr": "data-building-card",
        "card_queue": "render_hero_queue",
    },
    "research": {
        "template": "templates/research.html",
        "compact_id": "research-queue-compact",
        "compact_label": "research-queue-compact-label",
        "card_attr": "data-research-card",
        "card_queue": "render_research_card_queue",
    },
    "shipyard": {
        "template": "templates/shipyard.html",
        "compact_id": "shipyard-mini-queue",
        "compact_label": "shipyard-mini-queue",
        "card_attr": "data-ship-card",
        "skip_card_queue": True,
        "mini_queue": True,
    },
    "planet_evolution": {
        "template": "templates/planet_evolution.html",
        "compact_ids": ["pe-planet-tech-queue-compact", "pe-ascension-queue-compact"],
        "card_attrs": ["data-planet-tech-card", "data-ascension-card"],
        "card_queue": "pe_card_queue_block",
    },
    "defense": {
        "template": "templates/defense.html",
        "compact_id": "defense-mini-queue",
        "compact_label": "defense-mini-queue",
        "card_attr": "data-defense-card",
        "skip_card_queue": True,
        "mini_queue": True,
    },
}

LEGACY_PANEL_MARKERS = [
    "build-queue-root",
    "research-queue-root",
    "data-shipyard-queue-list",
    "data-defense-queue-list",
    'id="pe-research-queue"',
    "pe-research-queue-cards",
    "gc-prog-queue-panel",
    "pe_research_job(",
    "pe-planet-research-active",
    "shipyard-job-active",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _compact_sections(html: str, compact_id: str) -> str:
    needle = f'id="{compact_id}"'
    start = html.find(needle)
    assert start >= 0, f"missing compact header #{compact_id}"
    tag_start = html.rfind("<div", 0, start)
    end = html.find("</div>", start)
    return html[tag_start:end]


def test_all_queue_pages_have_compact_status():
    macro = _read("templates/partials/page_queue_compact.html")
    assert "gc-page-queue-compact" in macro
    assert "data-page-queue-compact-body" in macro
    for page, cfg in QUEUE_PAGES.items():
        html = _read(cfg["template"])
        compact_ids = cfg.get("compact_ids") or ([cfg["compact_id"]] if cfg.get("compact_id") else [])
        if cfg.get("skip_compact") or not compact_ids:
            assert "render_page_queue_compact" in html, f"{page}: missing render_page_queue_compact"
            continue
        for compact_id in compact_ids:
            assert compact_id in html, f"{page}: missing compact id {compact_id}"
            if f'id="{compact_id}"' in html:
                section = _compact_sections(html, compact_id)
                if cfg.get("mini_queue"):
                    assert "gc-mini-queue-strip" in section, (
                        f"{page}: #{compact_id} must use gc-mini-queue-strip"
                    )
                else:
                    assert "gc-queue-compact" in section, (
                        f"{page}: #{compact_id} must use gc-queue-compact"
                    )
            else:
                assert "render_page_queue_compact" in html or "render_page_mini_queue_strip" in html


def test_buildings_uses_page_compact_header_only():
    html = _read("templates/buildings.html")
    assert "build-queue-compact" in html
    assert "build-queue-root" not in html
    assert "gc-page-queue-panel" not in html
    base = _read("templates/base.html")
    assert "data-global-queue-hud" not in base
    assert "gc-header-row-queues" not in base
    assert "data-fleet-global-hud" not in base


def test_compact_headers_have_no_timers():
    # GC-644C: page compact headers show live timers for active jobs.
    skip_timer_compact = {"buildings", "research", "shipyard", "defense"}
    for page, cfg in QUEUE_PAGES.items():
        if cfg.get("skip_compact") or page in skip_timer_compact:
            continue
        html = _read(cfg["template"])
        compact_ids = cfg.get("compact_ids") or [cfg["compact_id"]]
        for compact_id in compact_ids:
            section = _compact_sections(html, compact_id)
            assert "data-timer-target" not in section, f"{page}: timer in compact #{compact_id}"
            assert "data-countdown-at" not in section, f"{page}: countdown in compact #{compact_id}"


def test_no_legacy_queue_panels_as_primary_ux():
    for page, cfg in QUEUE_PAGES.items():
        html = _read(cfg["template"])
        for marker in LEGACY_PANEL_MARKERS:
            assert marker not in html, f"{page}: legacy marker still present: {marker}"


def test_all_queue_pages_use_card_queue_blocks():
    for page, cfg in QUEUE_PAGES.items():
        if cfg.get("skip_card_queue"):
            html = _read(cfg["template"])
            partial = _read("templates/partials/page_mini_queue_strip.html")
            assert "render_page_mini_queue_strip" in html, f"{page}: missing mini queue macro call"
            assert "gc-mini-queue-strip" in partial, f"{page}: missing gc-mini-queue-strip partial"
            card_attrs = cfg.get("card_attrs") or [cfg["card_attr"]]
            for attr in card_attrs:
                assert attr in html, f"{page}: missing {attr}"
            continue
        html = _read(cfg["template"])
        assert "gc-card-queue-block" in html, f"{page}: missing gc-card-queue-block"
        assert cfg["card_queue"] in html, f"{page}: missing card queue macro"
        card_attrs = cfg.get("card_attrs") or [cfg["card_attr"]]
        for attr in card_attrs:
            assert attr in html, f"{page}: missing {attr}"


def test_main_js_global_queue_hud_actions():
    js = _read("static/main.js")
    assert "initGlobalQueueHud" in js
    assert "renderGlobalQueueHud" in js
    assert "_handleGlobalQueueHudCancel" in js
    assert "data-global-queue-hud-chip" in js
    assert "global_queue_hud" in js


def test_main_js_uses_render_card_queue_block_for_all_domains():
    js = _read("static/main.js")
    assert "GC.renderCardQueueBlock = function renderCardQueueBlock" in js
    for fn in (
        "patchBuildingPanel",
        "patchResearchPanel",
        "patchShipyardCardQueues",
        "patchPePlanetTechCardQueues",
        "patchPeAscensionCardQueues",
        "patchDefenseCardQueues",
    ):
        assert fn in js, f"missing card queue patcher: {fn}"
    render_block = js.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split(
        "return block;"
    )[0]
    assert "gc-card-queue-block--active" in render_block or 'isActive ? "active" : "queued"' in render_block
    assert "gc-card-queue-block--queued" in render_block or 'isActive ? "active" : "queued"' in render_block
    assert "gc-card-queue-bar-fill" in render_block
    assert "applyQueueJobTimerAttrs" in render_block


def test_main_js_no_legacy_queue_panel_roots():
    js = _read("static/main.js")
    assert 'getElementById("build-queue-root")' not in js
    assert 'getElementById("research-queue-root")' not in js
    assert "data-shipyard-queue-list" not in js
    assert "pe-planet-research-active" not in js


def test_style_unified_queue_compact_and_reduced_motion():
    css = _read("static/style.css")
    assert ".gc-queue-compact{" in css
    assert ".gc-mini-queue-strip{" in css
    assert ".gc-mini-queue-card--active{" in css
    assert ".gc-card-queue-block--queued{" in css
    assert ".gc-card-queue-bar{" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    idx = css.find("\n@media (prefers-reduced-motion: reduce){")
    while idx >= 0:
        chunk = css[idx : idx + 800]
        if ".gc-card-queue-glyph," in chunk and ".gc-card-queue-scanline," in chunk:
            assert "animation: none !important" in chunk
            break
        idx = css.find("\n@media (prefers-reduced-motion: reduce){", idx + 1)
    else:
        raise AssertionError("queue card reduced-motion block not found")


def test_style_card_queue_mobile_safe():
    css = _read("static/style.css")
    idx = css.find("\n.gc-card-queue-block{")
    assert idx >= 0, "standalone .gc-card-queue-block rule missing"
    block = css[idx : idx + 500]
    assert "max-width: 100%" in block
    assert "min-width: 0" in block


def test_queue_engine_unchanged():
    text = _read("game/queue_engine.py")
    assert "queue_card" not in text


def test_planet_evolution_merges_queue_cards_into_visible_list():
    html = _read("templates/planet_evolution.html")
    assert "pe_visible_tech_cards" in html
    assert "rdx.queue_cards" in html
    assert "pe-research-queue-cards" not in html


def test_ssr_card_queue_uses_canonical_finish_timer():
    """GC-538: SSR card queues must not use start_at-only queued timers or 'Startet in'."""
    partial = _read("templates/partials/card_queue_macros.html")
    assert "queue_card_starts_in" not in partial
    assert "finish_ts" in partial
    assert "finish_time" in partial
    assert "data-timer-target" in partial
    assert "data-server-remaining" in partial
    for page, cfg in QUEUE_PAGES.items():
        if cfg.get("skip_card_queue"):
            continue
        html = _read(cfg["template"])
        macro_name = cfg["card_queue"]
        start = html.find(f"macro {macro_name}")
        assert start >= 0, f"{page}: missing macro {macro_name}"
        end = html.find("{% endmacro %}", start)
        section = html[start:end]
        assert "queue_card_starts_in" not in section, f"{page}: legacy queued timer text"
        assert "render_card_queue_timer" in section, f"{page}: must use shared card queue timer macro"
        assert "qj.status != 'active' and qj.start_at" not in section, (
            f"{page}: queued timer must not target start_at only"
        )
