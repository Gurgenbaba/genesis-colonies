"""GC-PERF-LAUNCH-001 — production-cadence diet early exit."""

from __future__ import annotations

from pathlib import Path

from game import live_state


ROOT = Path(__file__).resolve().parents[1]


def test_diet_probe_skip_ttl_covers_production_idle_cadence():
    # Production idle default is 12s with ±12.5% stable jitter => <=13.5s.
    assert live_state.diet_probe_skip_ttl_sec() >= 13.5


def test_game_state_early_exit_reuses_authenticated_session_id():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    block = source.split("def api_game_state():", 1)[1].split(
        '@app.route("/api/exchange/rates")', 1
    )[0]
    early = block.split("# GC-PERF-STATE-004", 1)[1].split("if delta_keys:", 1)[0]

    assert 'user_id = int(session.get("user_id") or 0)' in early
    assert "get_current_user()" not in early
    assert "try_diet_poll_early_unchanged(user_id, since_val)" in early
