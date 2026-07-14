"""GC-PERF-004 — notification poll cadence and game-state dedup contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_notification_poll_intervals_reduced():
    src = _read("static/main.js")
    assert "const NOTIFICATION_POLL_MS = 12000" in src
    assert "const NOTIFICATION_POLL_HIDDEN_MS = 20000" in src
    assert "const NOTIFICATION_POLL_MS = 1000" not in src


def test_notification_poll_skips_when_game_state_fresh():
    src = _read("static/main.js")
    poll = src.split("function scheduleNotificationPoll(ms)")[1].split("GC.stopNotificationPoll = stopNotificationPoll")[0]
    assert "shouldSkipNotificationPollFetch()" in poll
    assert "scheduleNotificationPoll(next)" in poll
    skip = src.split("function shouldSkipNotificationPollFetch()")[1].split("function stopNotificationPoll()")[0]
    assert "_lastGameStateNotificationAt" in skip
    assert "NOTIFICATION_GAME_STATE_DEDUP_MS" in skip


def test_game_state_marks_notification_fresh():
    src = _read("static/main.js")
    assert "function markNotificationFreshFromGameState(data)" in src
    assert "function notificationRevisionFromHud(data)" in src
    hud = src.split("function patchShellHudFromState(data, opts)")[1].split("GC.patchShellHudFromState = patchShellHudFromState")[0]
    assert "markNotificationFreshFromGameState(data)" in hud


def test_notification_revision_dedup_still_active():
    src = _read("static/main.js")
    apply = src.split("function applyNotificationSummary(data, reason)")[1].split("function scheduleNotificationPoll")[0]
    assert "_lastAppliedNotificationRevision" in apply
    assert "revision === _lastAppliedNotificationRevision" in apply
