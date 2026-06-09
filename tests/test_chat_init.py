"""Chat panel init, open handlers, and bootstrap dedupe (static contracts)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_chat_partial_has_fab_and_panel():
    tpl = _read("templates/partials/chat.html")
    assert 'id="gc-chat-root"' in tpl
    assert "data-chat-fab" in tpl
    assert "data-chat-panel" in tpl
    assert "data-chat-close" in tpl


def test_base_includes_chat_js_after_main():
    base = _read("templates/base.html")
    main_pos = base.find("main.js")
    chat_pos = base.find("js/chat.js")
    assert main_pos >= 0 and chat_pos > main_pos


def test_chat_js_global_handlers_and_idempotent_init():
    src = _read("static/js/chat.js")
    assert "installGlobalChatHandlers" in src
    assert "CHAT.uiBound" in src
    assert "GC.initChat = initChat" in src
    assert "GC._chatBootstrapDone" in src
    assert "GC._chatWantsOpen" in src
    assert "data-special-open-window='chat'" in src
    assert "chat:bootstrap skipped/reused" in src
    assert "chat:open" in src
    assert "chat:bound" in src
    assert "setOpen(true)" in src.split("async function openTChat")[1].split("GC.initChat = initChat")[0]
    tail = src.split("GC.initChat = initChat")[1]
    assert "DOMContentLoaded" not in tail
    assert "initChatOnce" not in src
    assert "GC._chatInitialized" not in src


def test_chat_js_bootstrap_interval_60s():
    src = _read("static/js/chat.js")
    assert "bootstrapIntervalMs: 60000" in src


def test_chat_js_message_time_includes_date_outside_today():
    src = _read("static/js/chat.js")
    fmt = src.split("function formatTime(ts)")[1].split("function isNearBottom")[0]
    assert "Intl.DateTimeFormat" in fmt
    assert "dateStyle" in fmt
    assert "timeStyle" in fmt
    assert 'toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })' not in fmt


def test_main_js_init_page_calls_init_chat_not_resume():
    src = _read("static/main.js")
    init_section = src.split("function initPage")[1].split("function formatDuration")[0]
    assert "GC.initChat()" in init_section
    assert "GC.resumeChatPolling()" not in init_section


def test_main_js_shell_does_not_init_chat():
    src = _read("static/main.js")
    shell = src.split("function initShellOnce")[1].split("function initPage")[0]
    assert "initChat" not in shell


def test_main_js_special_panel_uses_open_tchat():
    src = _read("static/main.js")
    block = src.split('target === "chat"')[1][:500]
    assert "GC.openTChat" in block
    assert "openTChat failed" in block
