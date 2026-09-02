from pathlib import Path


MAIN_JS = Path("static/main.js")


def _main_js() -> str:
    return MAIN_JS.read_text(encoding="utf-8")


def test_world_boss_live_poll_is_not_fixed_one_second_interval():
    js = _main_js()
    assert 'GC.setSafeInterval(wbLivePollTick, 1000)' not in js
    assert 'setInterval(wbLivePollTick, 1000)' not in js
    assert 'const wbLivePollDelayMs = () =>' in js
    assert 'return autoOn ? 3000 : 7000;' in js


def test_world_boss_live_poll_suspends_hidden_tab_network_work():
    js = _main_js()
    marker = 'const wbLivePollTick = () => {'
    start = js.index(marker)
    block = js[start : start + 700]
    assert 'if (document.hidden) return;' in block
    assert 'document.addEventListener("visibilitychange", wbHandleVisibilityChange);' in js
    assert 'document.removeEventListener("visibilitychange", wbHandleVisibilityChange);' in js


def test_world_boss_live_poll_keeps_no_overlap_guard():
    js = _main_js()
    marker = 'const wbLivePollTick = () => {'
    start = js.index(marker)
    scheduler_marker = '// GC-PG-WB-POLL-001: the old fixed 1s loop'
    end = js.index(scheduler_marker, start)
    block = js[start:end]
    assert 'data-wb-auto-poll-busy' in block
    assert 'card.dataset.wbAutoPollBusy = "1";' in block
    assert 'delete card.dataset.wbAutoPollBusy;' in block


def test_world_boss_live_poll_initial_refresh_remains_prompt():
    js = _main_js()
    assert 'wbScheduleLivePoll(1000);' in js
    assert 'wbLivePollTick();\n      wbScheduleLivePoll(wbLivePollDelayMs());' in js
