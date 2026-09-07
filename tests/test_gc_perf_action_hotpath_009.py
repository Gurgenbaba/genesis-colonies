"""GC-PERF-ACTION-009 — Build/Timekeeper response paths must not repeat due-work."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_build_and_timekeeper_action_state_use_post_mutation_read_path():
    src = _read("app.py")
    constants = _block(
        src,
        "_POST_MUTATION_READ_ONLY_LIVE_SOURCES = frozenset(",
        "\n\n\ndef _use_post_mutation_read_path",
    )
    assert '"api_buildings_upgrade"' in constants
    assert '"api_buildings_cancel"' in constants
    assert '"api_timekeeper_apply"' in constants

    live = _block(src, "def _load_page_live_context(", "\ndef _stash_shell_boot_for_inject")
    assert "use_post_mutation_live_path = _use_post_mutation_read_path(src)" in live
    assert "read_player_live_state_after_mutation(user_id, conn=conn)" in live
    assert "and not use_post_mutation_live_path" in live


def test_post_mutation_projection_cannot_finish_queues_again():
    src = _read("game/logic.py")
    block = _block(
        src,
        "def read_player_live_state_after_mutation(",
        "\ndef read_player_live_state_for_poll(",
    )
    assert "_read_player_live_state_no_writes(uid, conn, player, planet)" in block
    assert "mark_request_live_refreshed()" in block
    assert "finish_player_due_work(" not in block
    assert "_res.update_planet_resources(" not in block


def test_build_upgrade_skips_legacy_preload_connections():
    src = _read("app.py")
    block = _block(
        src,
        "def api_buildings_upgrade():",
        '@app.route("/api/buildings/mine-evolve"',
    )
    assert "_player_context_for_action()" not in block
    assert 'user_id = int(session.get("user_id") or 0)' in block
    assert 'queue_build({"id": user_id}, {}, building_type' in block


def test_build_wrapper_defers_planet_resolution_to_mutation_connection():
    src = _read("game/logic.py")
    block = _block(src, "def queue_build(", "\ndef cancel_build(")
    assert "get_context_planet(" not in block
    assert "planet=None" in block
    assert "buildings={}" in block

    bsrc = _read("game/buildings.py")
    mutation = _block(
        bsrc,
        "def queue_build_for_planet(",
        "\ndef cancel_build_job_for_planet(",
    )
    assert "planet: Optional[dict]" in mutation
    assert "planet = get_context_planet(user_id, conn=conn)" in mutation
    assert "ok_vacation, vac_reason = vacation_blocks_outbound(user_id, conn=conn)" in mutation


def test_post_mutation_read_path_is_gated_on_confirmed_commit():
    src = _read("app.py")
    live = _block(src, "def _load_page_live_context(", "\ndef _stash_shell_boot_for_inject")
    assert "post_mutation_committed: bool = False" in live
    assert (
        "use_post_mutation_live_path = bool(post_mutation_committed) "
        "and _use_post_mutation_read_path(src)"
    ) in live

    action = _block(src, "def _action_json_response(", "\ndef _defense_json_response(")
    assert "post_mutation_committed=bool(ok)" in action

    tk = _block(src, "def api_timekeeper_apply():", '\n\n@app.route("/api/inventory/craft"')
    assert "post_mutation_committed=True" in tk
