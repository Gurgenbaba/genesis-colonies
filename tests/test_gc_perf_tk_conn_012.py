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
