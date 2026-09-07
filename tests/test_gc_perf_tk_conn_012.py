"""GC-PERF-TK-CONN-012 — Timekeeper response rebuild reuses committed checkout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_game_state_builder_accepts_caller_owned_connection():
    src = _read("app.py")
    block = _block(src, "def _build_game_state_payload(", "\ndef _player_context_for_action(")

    signature = block.split(") -> Tuple[dict, int]:", 1)[0]
    assert "conn=None" in signature
    assert "authenticated_user_id: Optional[int] = None" in signature
    assert "own_conn = conn is None" in block
    assert "if own_conn:\n        conn = db()" in block
    assert "if own_conn:\n            conn.close()" in block
    assert "\n    conn = db()\n" not in block


def test_authenticated_user_shortcut_is_bound_to_current_session():
    src = _read("app.py")
    block = _block(src, "def _build_game_state_payload(", "\ndef _player_context_for_action(")

    assert "session_user_id = int(session.get(\"user_id\") or 0)" in block
    assert "if user_id <= 0 or session_user_id != user_id:" in block
    assert "user = get_current_user()" in block


def test_timekeeper_success_reuses_committed_connection_without_contract_change():
    src = _read("app.py")
    helper = _block(
        src,
        "def _timekeeper_apply_game_state(",
        "\ndef _is_buildings_queue_action_source(",
    )
    assert "conn=None" in helper.split(") -> dict:", 1)[0]
    assert "user_id: Optional[int] = None" in helper.split(") -> dict:", 1)[0]
    assert "_build_game_state_payload(" in helper
    assert "conn=conn" in helper
    assert "authenticated_user_id=int(user_id) if user_id is not None else None" in helper

    route = _block(
        src,
        "def api_timekeeper_apply():",
        '\n\n@app.route("/api/inventory/craft"',
    )
    success = route.split("commit(conn)", 1)[1]
    before_state = success.split("_timekeeper_apply_game_state(", 1)[0]
    assert "conn.close()" not in before_state
    call = success.split("_timekeeper_apply_game_state(", 1)[1].split(")", 1)[0]
    assert "post_mutation_committed=True" in call
    assert "conn=conn" in call
    assert "user_id=user_id" in call


def test_shipyard_defense_queue_attachment_reuses_supplied_connection():
    src = _read("app.py")
    helper = _block(
        src,
        "def _timekeeper_apply_game_state(",
        "\ndef _is_buildings_queue_action_source(",
    )
    assert "attach_conn = conn" in helper
    assert "own_attach_conn = attach_conn is None" in helper
    assert "if own_attach_conn:\n                attach_conn = db()" in helper
    assert "conn=attach_conn" in helper


def test_overview_connection_ownership_is_untouched():
    src = _read("app.py")
    block = _block(src, "def overview(", "\n@app.route")
    assert "own_conn = conn is None" not in block

def test_timekeeper_state_builder_accepts_authoritative_snapshot():
    src = _read("app.py")
    payload = _block(
        src,
        "def _payload_from_live_context(",
        "\ndef _build_game_state_payload(",
    )
    signature = payload.split(") -> Dict[str, Any]:", 1)[0]
    assert "timekeeper_snapshot: Optional[Dict[str, Any]] = None" in signature
    assert "if isinstance(timekeeper_snapshot, dict):" in payload
    assert 'payload["timekeeper"] = dict(timekeeper_snapshot)' in payload

    builder = _block(
        src,
        "def _build_game_state_payload(",
        "\ndef _player_context_for_action(",
    )
    assert "timekeeper_snapshot: Optional[Dict[str, Any]] = None" in builder.split(
        ") -> Tuple[dict, int]:", 1
    )[0]
    payload_call = builder.split("payload = _payload_from_live_context(", 1)[1].split(
        "\n        )", 1
    )[0]
    assert "timekeeper_snapshot=timekeeper_snapshot" in payload_call


def test_timekeeper_apply_feeds_ledger_snapshot_into_response_rebuild():
    src = _read("app.py")
    helper = _block(
        src,
        "def _timekeeper_apply_game_state(",
        "\ndef _is_buildings_queue_action_source(",
    )
    assert "timekeeper_snapshot: Optional[Dict[str, Any]] = None" in helper.split(
        ") -> dict:", 1
    )[0]
    assert "timekeeper_snapshot=timekeeper_snapshot" in helper

    route = _block(
        src,
        "def api_timekeeper_apply():",
        '\n\n@app.route("/api/inventory/craft"',
    )
    success = route.split("commit(conn)", 1)[1]
    call = success.split("_timekeeper_apply_game_state(", 1)[1].split(")", 1)[0]
    assert "timekeeper_snapshot=tk_slice" in call

    failure = route.split("if not ok:", 1)[1].split("commit(conn)", 1)[0]
    assert 'error_tk_slice = result.get("timekeeper")' in failure
    assert "timekeeper_snapshot=error_tk_slice" in failure

def test_timekeeper_partial_projection_skips_unchanged_meta_domains():
    src = _read("app.py")
    payload = _block(
        src,
        "def _payload_from_live_context(",
        "\ndef _build_game_state_payload(",
    )
    assert (
        "timekeeper_partial = bool(action_slim and isinstance(timekeeper_snapshot, dict))"
        in payload
    )
    assert 'if not timekeeper_partial:\n        try:\n            from game.battle_pass' in payload
    assert (
        'if not timekeeper_partial:\n        with perf_span("payload.liveops")'
        in payload
    )
    assert (
        "if not timekeeper_partial:\n"
        "        try:\n"
        "            from game.inventory_boosters import build_inventory_boosters_state"
        in payload
    )
    assert (
        "if not timekeeper_partial:\n"
        "        try:\n"
        "            from game.planet_evolution.service import list_player_planets_for_switcher"
        in payload
    )

    fleet_pos = payload.index('with perf_span("payload.fleets_hud")')
    fleet_prefix = payload[max(0, fleet_pos - 80):fleet_pos]
    assert "if not timekeeper_partial:" in fleet_prefix
    assert "fleet_hud_for_game_state" in payload

def test_timekeeper_partial_projection_skips_commander_and_score_reads():
    src = _read("app.py")
    payload = _block(
        src,
        "def _payload_from_live_context(",
        "\ndef _build_game_state_payload(",
    )

    commander = payload.split(
        "from game.commander_classes import serialize_for_client as serialize_commander", 1
    )[0]
    assert commander.rstrip().endswith("if not timekeeper_partial:\n        try:")

    score_pos = payload.index('with perf_span("payload.score")')
    score_prefix = payload[max(0, score_pos - 80):score_pos]
    assert "if not timekeeper_partial:" in score_prefix

    # Critical mutation-owned Timekeeper slice remains outside the skip.
    assert 'payload["timekeeper"] = dict(timekeeper_snapshot)' in payload

def test_timekeeper_partial_projection_skips_unrelated_notification_and_safety_reads():
    src = _read("app.py")
    payload = _block(
        src,
        "def _payload_from_live_context(",
        "\ndef _build_game_state_payload(",
    )

    notifications_pos = payload.index('with perf_span("payload.notifications")')
    notifications_prefix = payload[max(0, notifications_pos - 80):notifications_pos]
    assert "if not timekeeper_partial:" in notifications_prefix

    initiation_pos = payload.index("from game.live_state import initiation_for_game_state")
    initiation_prefix = payload[max(0, initiation_pos - 120):initiation_pos]
    assert "if not timekeeper_partial:" in initiation_prefix

    safety_pos = payload.index(
        "from game.live_state import account_safety_hud_for_game_state"
    )
    safety_prefix = payload[max(0, safety_pos - 120):safety_pos]
    assert "if not timekeeper_partial:" in safety_prefix

    # Fleet omission is now safe because GC-PERF-TK-024 preserves missing Fleet state.
    fleet_pos = payload.index('with perf_span("payload.fleets_hud")')
    fleet_prefix = payload[max(0, fleet_pos - 80):fleet_pos]
    assert "if not timekeeper_partial:" in fleet_prefix

