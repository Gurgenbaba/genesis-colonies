"""GC-PERF-NAV-007 — common navigation / action-state hotpath contracts."""

from __future__ import annotations

from pathlib import Path

from game import codex

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _inject_block() -> str:
    src = _read("app.py")
    return src.split("def inject_globals():", 1)[1].split(
        "# --------------------------------------------------------------------------\n"
        "# BOOTSTRAP",
        1,
    )[0]


def _payload_block() -> str:
    src = _read("app.py")
    return src.split("def _payload_from_live_context(", 1)[1].split(
        "\ndef _build_game_state_payload(",
        1,
    )[0]


def test_pjax_does_not_rebuild_shell_codex_or_user_options():
    block = _inject_block()

    codex_part = block.split("codex_panel:", 1)[1].split(
        "rules_panel_ctx:",
        1,
    )[0]
    assert 'auth_user.get("id") and not simple_layout' in codex_part
    assert "build_codex_template_context(" in codex_part
    assert "record_visit=False" in codex_part

    options_part = block.split("client_runtime_config = {", 1)[1].split(
        "header_active_boosters:",
        1,
    )[0]
    assert 'auth_user.get("id") and not simple_layout' in options_part
    assert "_options_conn = db()" in options_part
    assert "get_notify_sound_settings(_uid, conn=_options_conn)" in options_part
    assert "get_spy_probe_settings(_uid, conn=_options_conn)" in options_part
    assert "get_buildings_ui_settings(_uid, conn=_options_conn)" in options_part


def test_codex_route_visit_uses_existing_page_live_connection():
    src = _read("app.py")
    block = src.split("def _load_page_live_context(", 1)[1].split(
        "\ndef _stash_shell_boot_for_inject(",
        1,
    )[0]

    assert "codex_route_for_endpoint" in block
    assert "record_codex_route_visit(" in block
    assert "conn=conn" in block
    assert "codex_visit_recorded" in block
    assert (
        "wrote_live or try_visit or codex_visit_recorded or "
        "consume_request_poll_safety_net_write()"
    ) in block


def test_codex_template_context_computes_one_unlock_snapshot(monkeypatch):
    calls = {"unlocks": 0}
    seen = {}

    def fake_unlocked(player_id, *, conn):
        calls["unlocks"] += 1
        assert player_id == 77
        assert conn is sentinel
        return {"overview", "fleet"}

    def fake_panel(player_id, *, conn, unlocked_ids=None):
        seen["panel"] = unlocked_ids
        return {"bands": []}

    def fake_tip(player_id, *, conn=None, unlocked_ids=None, when=None):
        seen["tip"] = unlocked_ids
        return None

    def fake_client(player_id, *, conn=None, locale=None, unlocked_ids=None):
        seen["client"] = unlocked_ids
        return {"articles": {}}

    sentinel = object()
    monkeypatch.setattr(codex, "unlocked_codex_ids", fake_unlocked)
    monkeypatch.setattr(codex, "build_codex_panel_state", fake_panel)
    monkeypatch.setattr(codex, "commander_tip_for_date", fake_tip)
    monkeypatch.setattr(codex, "build_codex_client_config", fake_client)
    monkeypatch.setattr(codex, "codex_route_for_endpoint", lambda endpoint: None)
    monkeypatch.setattr(codex, "primary_codex_for_route", lambda route: None)

    result = codex.build_codex_template_context(
        77,
        "overview",
        conn=sentinel,
        record_visit=False,
    )

    assert result["CODEX_PANEL"] == {"bands": []}
    assert calls["unlocks"] == 1
    assert seen["panel"] == {"overview", "fleet"}
    assert seen["tip"] == {"overview", "fleet"}
    assert seen["client"] == {"overview", "fleet"}


def test_action_and_diet_skip_payloads_their_diets_discard():
    block = _payload_block()

    assert "if not lightweight and not action_slim:" in block
    assert "get_overview_planet_teaser(" in block
    assert "codex_for_game_state(" in block

    # Universe-wide stats are discarded by both apply_*_state_diet functions.
    stats = block.split("# GC-PERF-NAV-007: diet + mutation action states", 1)[1].split(
        "from game.planet_evolution.service import list_player_planets_for_switcher",
        1,
    )[0]
    assert "if not lightweight and not action_slim:" in stats
    assert "get_player_stats(conn=conn)" in stats

    # Mutation state only needs the compact Battle Pass HUD/claim counters.
    assert "include_tracks=not lightweight and not action_slim" in block


def test_common_score_and_rank_reuse_payload_request_connection():
    block = _payload_block()

    assert "get_player_score_cached(user_id, read_only=True, conn=conn)" in block
    assert "get_player_rank(user_id, conn=conn)" in block
    assert "get_player_score_cached(user_id, read_only=True) or {" not in block


def test_player_stats_accepts_caller_owned_connection():
    src = _read("game/models.py")
    block = src.split("def get_player_stats(", 1)[1].split(
        "\ndef ensure_player_and_homeworld(",
        1,
    )[0]

    assert "conn: sqlite3.Connection | None = None" in block
    assert "own_conn = conn is None" in block
    assert "c = conn or db()" in block
    assert "get_registered_player_count(conn=c)" in block
    assert "get_online_player_count(conn=c" in block
