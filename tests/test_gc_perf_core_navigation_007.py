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
    assert "codex_visit_recorded = bool(" in block
    assert "visit_result = maybe_record_page_visit_from_request(" in block
    assert 'visit_result.get("recorded")' in block
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


def test_game_settings_are_loaded_once_per_flask_request(monkeypatch):
    from flask import Flask
    from game import models

    app = Flask(__name__)
    calls = {"n": 0}

    class _Conn:
        def cursor(self):
            return object()

    def fake_ensure(_cur):
        calls["n"] += 1
        return {"queue_limit": "5", "speed": "1", "build_speed": "1"}

    monkeypatch.setattr(models, "_ensure_game_settings", fake_ensure)
    with app.test_request_context("/api/game-state"):
        first = models.get_game_settings(conn=_Conn())
        first["queue_limit"] = "999"
        second = models.get_game_settings(conn=_Conn())

    assert calls["n"] == 1
    assert second["queue_limit"] == "5"


def test_game_settings_write_invalidates_request_cache_contract():
    src = _read("game/models.py")
    block = src.split("def save_game_settings(", 1)[1].split(
        "# ======================================================================\n# RESEARCH",
        1,
    )[0]
    assert "_request_game_settings_cache_clear()" in block


def test_story_has_flag_batches_player_flags_once_per_request(monkeypatch):
    from flask import Flask
    from game.story import flags

    app = Flask(__name__)
    calls = {"n": 0}

    class _Rows:
        def fetchall(self):
            return [
                {"flag_key": "ark_awake", "flag_value": "1"},
                {"flag_key": "first_fleet", "flag_value": "1"},
            ]

    class _Conn:
        def execute(self, sql, params=None):
            assert "SELECT flag_key, flag_value FROM player_story_flags" in str(sql)
            assert tuple(params or ()) == (77,)
            calls["n"] += 1
            return _Rows()

    monkeypatch.setattr(flags, "flags_schema_ready", lambda _conn: True)
    with app.test_request_context("/api/fleet/state"):
        assert flags.has_flag(77, "ark_awake", conn=_Conn()) is True
        assert flags.has_flag(77, "first_fleet", conn=_Conn()) is True
        assert flags.has_flag(77, "missing", conn=_Conn()) is False

    assert calls["n"] == 1


def test_direct_postgres_game_settings_write_invalidates_request_memo():
    from flask import Flask, g
    from game.db_pg import _invalidate_request_hot_read_caches_for_sql

    app = Flask(__name__)
    with app.test_request_context("/api/admin/settings"):
        g.gc_game_settings_cache = {"queue_limit": "5"}
        _invalidate_request_hot_read_caches_for_sql(
            "UPDATE game_settings SET value = ? WHERE key = ?"
        )
        assert g.gc_game_settings_cache is None
