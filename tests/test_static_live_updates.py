"""
Regression guards for PJAX-safe messages inbox and chat polling (static JS contracts).

Run: python -m pytest tests/test_static_live_updates.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_messages_js_always_reinits_and_persistent_cleanup():
    src = _read("static/js/messages.js")
    assert "persistent: true" in src
    assert "listLoaded" in src
    assert "readActiveFilterFromDom" in src
    assert "getMessagesDom" in src
    assert "GC.messagesPageState && !force" not in src
    assert "resetMessagesPageState" in src
    assert "_messagesInitSeq" in src
    assert "requestSeq" in src
    assert "isCurrentRequest" in src
    assert "bootMessagesIfPresent" not in src


def test_messages_js_initial_load_and_stale_request_guards():
    src = _read("static/js/messages.js")
    assert "state.loading = true" in src
    assert "state.listLoaded = true" in src
    assert "isCurrentRequest(state, initSeq, requestId)" in src
    assert "showLoadingList" in src
    assert "showErrorList" in src
    assert "requestAnimationFrame(startLoad)" in src
    assert "bypass GC.fetchJSON" in src
    assert "await GC.fetchJSON" not in src
    assert "loadGen" not in src


def test_messages_js_tab_and_initial_share_load_list():
    src = _read("static/js/messages.js")
    assert "state.loadList = loadList" in src
    assert "state.loadList?.()" in src
    tab_section = src.split("tabBtn.dataset.filter")[1][:400]
    assert "loadList" in tab_section


def test_messages_js_debug_gated():
    src = _read("static/js/messages.js")
    assert "msgDebug" in src
    assert "GC.DEBUG" in src


def test_chat_js_poll_updates_last_id_and_resume_bootstrap():
    src = _read("static/js/chat.js")
    assert "applyIncomingPollMessages" in src
    assert "bumpLastMsgId" in src
    assert "isActivelyViewingRoom" in src
    assert "refreshBootstrap()" in src
    assert "resumeChatPolling" in src
    assert "chatDebug" in src


def test_main_js_init_page_resumes_chat_after_pjax():
    src = _read("static/main.js")
    assert "GC.initChat()" in src
    assert "GC.resumeChatPolling()" in src
    assert 'mod();' in src or "mod({ force: true })" not in src.split("page === \"messages\"")[1][:120]
