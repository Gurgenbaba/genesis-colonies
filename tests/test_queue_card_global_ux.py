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
        "compact_id": "build-mini-queue",
        "compact_label": "build-mini-queue",
        "card_attr": "data-building-card",
        "skip_card_queue": True,
        "mini_queue": True,
    },
    "research": {
        "template": "templates/research.html",
        "compact_id": "research-mini-queue",
        "compact_label": "research-mini-queue",
        "card_attr": "data-research-card",
        "skip_card_queue": True,
        "mini_queue": True,
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
        "queue_list_ids": ["pe-planet-tech-queue-list", "pe-ascension-queue-list"],
        "card_attrs": ["data-planet-tech-card", "data-ascension-card"],
        "card_queue": "pe_card_queue_block",
        "skip_compact": True,
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
    macro = _read("templates/partials/page_mini_queue_strip.html")
    assert "gc-mini-queue-strip" in macro
    assert "gc-mini-queue-card" in macro
    for page, cfg in QUEUE_PAGES.items():
        html = _read(cfg["template"])
        if cfg.get("queue_list_ids"):
            for list_id in cfg["queue_list_ids"]:
                assert list_id in html, f"{page}: missing queue list #{list_id}"
            assert "gc-card-queue-list" in html, f"{page}: missing gc-card-queue-list"
            continue
        compact_ids = cfg.get("compact_ids") or ([cfg["compact_id"]] if cfg.get("compact_id") else [])
        if cfg.get("skip_compact") or not compact_ids:
            assert "render_page_mini_queue_strip" in html or "gc-card-queue-list" in html, (
                f"{page}: missing mini queue or card queue list"
            )
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
                    assert "render_page_mini_queue_strip" in html, (
                        f"{page}: #{compact_id} must use mini queue strip"
                    )
            else:
                assert "render_page_mini_queue_strip" in html


def test_buildings_uses_page_compact_header_only():
    html = _read("templates/buildings.html")
    assert "build-mini-queue" in html
    assert "render_page_mini_queue_strip" in html
    assert "build-queue-root" not in html
    assert "gc-page-queue-panel" not in html
    base = _read("templates/base.html")
    assert "data-global-queue-hud" not in base
    assert "gc-header-row-queues" not in base
    assert "data-fleet-global-hud" not in base


def test_compact_headers_have_no_timers():
    # Mini-queue headers intentionally show live timers for active jobs.
    for page, cfg in QUEUE_PAGES.items():
        if cfg.get("skip_compact") or cfg.get("mini_queue"):
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
    """GC-GUI-DECLUTTER-004: no header queue HUD DOM — sync + ticker only."""
    js = _read("static/main.js")
    base = _read("templates/base.html")
    assert "data-global-queue-hud" not in base
    assert "initGlobalQueueHud" in js
    assert "renderGlobalQueueHud" in js
    assert "_syncGlobalQueueHudLiveState" in js
    assert "_createGlobalQueueHudRow" not in js
    assert "_handleGlobalQueueHudCancel" not in js
    assert "global_queue_hud" in js
    assert "GC-GUI-DECLUTTER-004" in js


def test_ingame_sticky_header_occludes_scrolling_main():
    """GC-GUI-DECLUTTER-005: sticky header/res-bar must be opaque above main content."""
    css = _read("static/style.css")
    assert "GC-GUI-DECLUTTER-005" in css
    block = css.split("GC-GUI-DECLUTTER-005")[1].split("body.gc-body-ingame .gc-layout")[0]
    assert "background-color: rgb(4, 10, 20)" in block
    assert "z-index: var(--gc-z-sticky, 200)" in block
    assert "backdrop-filter: none" in block
    layout = css.split("body.gc-body-ingame .gc-layout{")[1].split("}")[0]
    assert "z-index: 0" in layout


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
    # GC-UNIT-QUEUE-DEDUP-001 / GC-PERF-CARD-TIMERS-001: unit + building/research
    # queues never render live ETA into item cards (mini-queue only).
    render_guard = js.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split(
        "const sig = cardQueueJobSignature"
    )[0]
    assert 'domain === "building" || domain === "research"' in render_guard
    assert 'domain === "shipyard" || domain === "defense"' in render_guard
    assert 'domain === "planet_research" || domain === "ascension"' in render_guard
    assert "_isPeQueueListHost" in render_guard
    assert "return null" in render_guard
    assert "GC-PERF-CARD-TIMERS-001" in js
    assert "GC-GUI-DECLUTTER-001" in js
    assert "_syncPeItemCardInQueueClasses" in js
    pe_patch = js.split("function patchPePlanetTechCardQueues(rdx)")[1].split(
        "function applyPeResearchCardQueueJobs"
    )[0]
    assert "_syncPeItemCardInQueueClasses" in pe_patch
    assert "[data-planet-tech-card]" in pe_patch
    assert "[data-ascension-card]" in pe_patch
    assert "function renderHeroQueueOverlay" in js
    assert "clearHeroQueueVisuals" in js
    assert "applyCardInQueueClasses" in js
    hero = js.split("function renderHeroQueueOverlay(cardEl, queueJob, opts)")[1].split(
        "function _cardQueueTimerMeta"
    )[0]
    assert "clearHeroQueueVisuals" in hero
    assert "applyCardInQueueClasses" in hero
    assert "return null" in hero
    assert "gc-bld-hero-queue-pct" not in hero
    patch_sy = js.split("function patchShipyardCardQueues(page")[1].split("function shipyardIconUrl")[0]
    assert "clearAllProductionCardQueues(page)" in patch_sy
    assert "patchCardQueuesFromOwnerMap" not in patch_sy
    patch_def = js.split("function patchDefenseCardQueues(page")[1].split("function _syncDefenseQueueLiveState")[0]
    assert "clearAllProductionCardQueues(page)" in patch_def
    assert "patchCardQueuesFromOwnerMap" not in patch_def
    render_block = js.split("GC.renderCardQueueBlock = function renderCardQueueBlock")[1].split(
        "return block;"
    )[0]
    assert "gc-card-queue-block--active" in render_block or 'isActive ? "active" : "queued"' in render_block
    assert "gc-card-queue-block--queued" in render_block or 'isActive ? "active" : "queued"' in render_block
    assert "gc-card-queue-bar-fill" in render_block
    assert "applyQueueJobTimerAttrs" in render_block


def test_buildings_research_cards_have_no_live_queue_timers():
    """GC-PERF-CARD-TIMERS-001 / GC-GUI-DECLUTTER-002: per-card % / ETA removed; mini-queue remains the live surface."""
    for rel in ("templates/buildings.html", "templates/research.html"):
        html = _read(rel)
        assert "render_hero_queue" not in html
        assert "gc-bld-hero-queue" not in html
        assert "data-hero-queue" not in html
        assert "gc-bld-hero-queue-pct" not in html
        assert "render_page_mini_queue_strip" in html
        assert "data-hero-time-chip" in html
        # Catalog duration only — no live countdown attrs on the time chip path.
        chip = html.split("data-hero-time-chip")[1].split("{% endmacro %}")[0]
        assert "data-countdown-at" not in chip
        assert "gc-hero-time-text" in chip
    research = _read("templates/research.html")
    assert "render_research_card_footer" not in research
    assert "data-research-time-footer" not in research
    assert "gc-card-footer-row--time" not in research
    img = _read("templates/partials/card_hero_img_macros.html")
    assert "gc-bld-hero-img-stack--progress" not in img
    assert "gc-bld-card-hero-img--muted" not in img
    # Panel patch must refresh catalog duration even while the card is in-queue.
    js = _read("static/main.js")
    building_patch = js.split("function patchBuildingPanel(rowsByTab, buildQueueRaw)")[1].split(
        "function patchResearchEffects"
    )[0]
    assert "setHeroTimeChipIdle(row, b.time_seconds" in building_patch
    assert 'gc-building-card--in-queue")) {\n          setHeroTimeChipIdle' not in building_patch
    research_patch = js.split("function patchResearchPanel(techs, researchRaw)")[1].split(
        "function patchQueuePanelsImmediate"
    )[0]
    assert "setHeroTimeChipIdle(row, tech.time_seconds" in research_patch
    assert 'gc-research-card--in-queue")) {\n        setHeroTimeChipIdle' not in research_patch


def test_main_js_no_legacy_queue_panel_roots():
    js = _read("static/main.js")
    assert 'getElementById("build-queue-root")' not in js
    assert 'getElementById("research-queue-root")' not in js
    assert "data-shipyard-queue-list" not in js
    assert "pe-planet-research-active" not in js


def test_style_unified_queue_compact_and_reduced_motion():
    css = _read("static/style.css")
    assert ".gc-mini-queue-strip{" in css
    assert ".gc-mini-queue-card--active{" in css
    assert ".gc-page-queue-compact" not in css
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
    idx = css.find("\n.gc-card-queue-block:not(.gc-bld-hero-queue){")
    assert idx >= 0, "compact .gc-card-queue-block rule missing"
    block = css[idx : idx + 500]
    assert "max-width: 100%" in block
    assert "min-width: 0" in block


def test_queue_containers_use_horizontal_flex_row():
    """Regression: queue job cards must sit in one horizontal row on desktop, not a vertical list."""
    css = _read("static/style.css")

    list_idx = css.find("\n.gc-card-queue-list{")
    assert list_idx >= 0, "missing .gc-card-queue-list rule"
    list_block = css[list_idx : list_idx + 480]
    assert "display: flex" in list_block
    assert "flex-direction: row" in list_block
    assert "justify-content: flex-start" in list_block
    assert "flex-direction: column" not in list_block

    child_idx = css.find("\n.gc-card-queue-list > .gc-card-queue-block:not(.gc-bld-hero-queue){")
    assert child_idx >= 0, "missing horizontal queue card flex child rule"
    child_block = css[child_idx : child_idx + 320]
    # GC-QUEUE-SLOT-001: fixed slot width — do not stretch when the queue is short.
    assert "flex: 0 0 var(--gc-queue-card-slot-w" in child_block
    assert "flex: 1 1 0" not in child_block
    assert "--gc-queue-card-slot-w" in css[list_idx : list_idx + 200] or "248px" in child_block

    strip_idx = css.find("\n.gc-mini-queue-strip{")
    assert strip_idx >= 0, "missing .gc-mini-queue-strip rule"
    strip_block = css[strip_idx : strip_idx + 420]
    assert "display: flex" in strip_block
    assert "flex-direction: row" in strip_block
    assert "justify-content: flex-start" in strip_block
    assert "flex-direction: column" not in strip_block

    card_idx = css.find("\n.gc-mini-queue-card{")
    assert card_idx >= 0, "missing .gc-mini-queue-card rule"
    card_block = css[card_idx : card_idx + 520]
    assert "flex: 0 0 var(--gc-queue-card-slot-w" in card_block
    assert "flex: 1 1 0" not in card_block


def test_queue_cards_use_fixed_slot_width_no_stretch():
    """GC-QUEUE-SLOT-001: equal-width left-aligned slots; short queues leave empty space on the right."""
    css = _read("static/style.css")
    assert "--gc-queue-card-slot-w: 248px" in css
    assert "--gc-queue-card-slot-w: 220px" in css
    assert "flex: 1 1 calc(50% - 6px)" not in css
    assert css.count("flex: 0 0 var(--gc-queue-card-slot-w") >= 3

    # Mobile queue override keeps horizontal nowrap (no 50%-stretch wrap).
    mobile_queue_idx = css.find(".gc-card-queue-list,\n  .gc-mini-queue-strip{")
    assert mobile_queue_idx >= 0
    mobile_chunk = css[mobile_queue_idx : mobile_queue_idx + 280]
    assert "flex-wrap: nowrap" in mobile_chunk
    assert "--gc-queue-card-slot-w: 220px" in mobile_chunk


def test_queue_engine_unchanged():
    text = _read("game/queue_engine.py")
    assert "queue_card" not in text


def test_planet_evolution_merges_queue_cards_into_visible_list():
    html = _read("templates/planet_evolution.html")
    assert "pe_visible_tech_cards" in html
    assert "rdx.recommended" in html
    assert "pe-planet-tech-queue-list" in html
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
