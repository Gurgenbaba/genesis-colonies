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
    assert "GC.formatLocaleDateTime" in fmt
    assert "sameDay" not in fmt
    main = _read("static/main.js")
    assert "function formatLocaleDateTime(ts)" in main
    assert "GC.formatLocaleDateTime = formatLocaleDateTime" in main
    locale_fmt = main.split("function formatLocaleDateTime(ts)")[1].split("GC.formatLocaleDateTime")[0]
    assert "dateStyle" in locale_fmt
    assert "timeStyle" in locale_fmt
    assert "sameDay" not in locale_fmt


def test_main_js_deferred_chat_boot_resumes_without_rebootstrap():
    src = _read("static/main.js")
    block = src.split("function scheduleDeferredChatBoot()")[1].split("function syncScopedPlanetIds")[0]
    assert "GC._chatBootstrapDone" in block
    assert "GC.resumeChatPolling()" in block
    assert block.index("GC._chatBootstrapDone") < block.index("GC.resumeChatPolling()")
    init_section = src.split("function initPage")[1].split("function formatDuration")[0]
    assert "scheduleDeferredChatBoot()" in init_section
    assert "GC.resumeChatPolling()" not in init_section


def test_main_js_shell_does_not_init_chat():
    src = _read("static/main.js")
    shell = src.split("function initShellOnce")[1].split("function initPage")[0]
    assert "initChat" not in shell


def test_main_js_special_panel_uses_open_tchat():
    src = _read("static/main.js")
    block = src.split('key === "chat"')[1][:500]
    assert "GC.openTChat" in block
    assert "openTChat failed" in block


def test_chat_poll_uses_messages_delta_not_bootstrap_when_hidden():
    """GC-PERF-003: pollTick must not re-fetch /api/chat/bootstrap on every hidden tick."""
    src = _read("static/js/chat.js")
    poll = src.split("async function pollTick()")[1].split("function startPolling()")[0]
    assert "refreshBootstrap()" not in poll
    assert "/api/chat/messages" in poll
    assert "applyIncomingPollMessages" in poll


def test_chat_idle_poll_slows_when_panel_closed():
    """GC-PERF-CHAT-IDLE-001: closed panel uses intervalClosed; open stays at interval."""
    src = _read("static/js/chat.js")
    assert "intervalClosed: 45000" in src
    delay_fn = src.split("function pollDelayMs()")[1].split("function schedulePoll()")[0]
    assert "document.hidden" in delay_fn
    assert "isChatPanelVisible()" in delay_fn
    assert "intervalClosed" in delay_fn
    assert "intervalHidden" in delay_fn
    schedule = src.split("function schedulePoll()")[1].split("async function pollTick()")[0]
    assert "pollDelayMs()" in schedule
    set_open = src.split("function setOpen(open)")[1].split("function toggleMaximize()")[0]
    assert set_open.count("schedulePoll()") >= 2


def test_chat_resume_polling_does_not_schedule_bootstrap_refresh():
    src = _read("static/js/chat.js")
    resume = src.split("function resumeChatPolling()")[1].split("async function sendMessage")[0]
    assert "scheduleBootstrapRefresh" not in resume
    assert "schedulePoll()" in resume


def test_chat_bootstrap_only_on_initial_lifecycle():
    src = _read("static/js/chat.js")
    assert "GC._chatBootstrapDone" in src
    init_bootstrap = src.split("async function runInitialBootstrap()")[1].split("async function initChatCore()")[0]
    assert "GC._chatBootstrapDone = true" in init_bootstrap
    assert 'apiFetch("/api/chat/bootstrap"' in src.split("async function bootstrap()")[1].split("function stopPolling()")[0]
    poll = src.split("async function pollTick()")[1].split("function startPolling()")[0]
    assert "/api/chat/bootstrap" not in poll
