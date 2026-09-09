from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_research_actions_use_queue_only_action_state():
    src = _read("app.py")
    start = _block(
        src,
        "def api_research_start():",
        '@app.route("/api/research/cancel"',
    )
    cancel = _block(
        src,
        "def api_research_cancel():",
        "# --------------------------------------------------------------------------\n# PLANET EVOLUTION",
    )
    for block, source in (
        (start, "api_research_start"),
        (cancel, "api_research_cancel"),
    ):
        assert f'finish_source="{source}"' in block
        assert "include_panel=False" in block

    diet = _block(
        src,
        "def _uses_action_state_diet(",
        "def _hud_only_game_state(",
    )
    assert '"api_research_start"' in diet
    assert '"api_research_cancel"' in diet


def test_research_actions_use_post_mutation_read_only_projection():
    src = _read("app.py")
    registry = _block(
        src,
        "_POST_MUTATION_READ_ONLY_LIVE_SOURCES = frozenset(",
        "def _use_post_mutation_read_path",
    )
    assert '"api_research_start"' in registry
    assert '"api_research_cancel"' in registry


def test_research_queue_mutation_reuses_vacation_connection():
    src = _read("game/research.py")
    block = _block(src, "def queue_research(", "def cancel_research_job")
    assert "vacation_blocks_outbound(uid, conn=db())" not in block
    assert "conn = db()" in block
    assert "vacation_blocks_outbound(uid, conn=conn)" in block
    assert block.index("conn = db()") < block.index(
        "vacation_blocks_outbound(uid, conn=conn)"
    )
    assert block.count("conn = db()") == 1


def test_canonical_panel_refresh_aborts_ordinary_poll_before_fetch():
    src = _read("static/main.js")
    canonical = _block(
        src,
        "async function forceCanonicalGameStateRefresh(reason, opts)",
        "GC.forceCanonicalGameStateRefresh = forceCanonicalGameStateRefresh",
    )
    assert "GC.refreshInFlight || GC.polling?.abort" in canonical
    assert "abortInFlightGameStateFetches()" in canonical
    assert canonical.index("abortInFlightGameStateFetches()") < canonical.index(
        'GC.fetchJSON(panelUrl'
    )


def test_normal_game_state_coalesces_onto_canonical_panel_refresh():
    src = _read("static/main.js")
    refresh = _block(
        src,
        "async function refreshGameState(reason)",
        "GC.refreshGameState = refreshGameState",
    )
    gate = 'if (_queuePanelRefreshInFlight && reasonStr !== "planet_switch")'
    assert gate in refresh
    assert "return _queuePanelRefreshInFlight;" in refresh
    assert refresh.index(gate) < refresh.index("if (GC.refreshInFlight)")


def test_queue_only_research_state_has_existing_frontend_patch_path():
    src = _read("static/main.js")
    immediate = _block(
        src,
        "function patchQueuePanelsImmediate(data)",
        "function hasMountedQueuePage()",
    )
    assert "const researchRaw = data.research ?? null;" in immediate
    assert "else if (researchRaw != null" in immediate
    assert "patchCardQueuesFromOwnerMap(" in immediate
    assert "renderResearchQueue(researchRaw);" in immediate


def test_timekeeper_finish_still_requests_one_canonical_panel_reconcile():
    src = _read("static/main.js")
    assert 'forceCanonicalGameStateRefresh("timekeeper_apply")' in src
