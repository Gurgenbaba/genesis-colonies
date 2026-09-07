"""GC-PERF-TK-FINISH-DELTA-013 — finished Build boosts patch one card immediately."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_timekeeper_service_exposes_only_finished_build_head_key():
    src = _read("game/timekeeper.py")
    block = _block(src, "def apply_timekeeper(", "\ndef recent_transactions(")

    assert 'head_building_key = (' in block
    assert '_row_field(rows[0], "building_type")' in block
    assert '"finished_building_key": (' in block
    assert 'head_building_key if dom == "build" and jobs_finished else ""' in block


def test_timekeeper_response_builds_delta_only_for_committed_finished_build():
    src = _read("app.py")
    helper = _block(
        src,
        "def _timekeeper_apply_game_state(",
        "\ndef _is_buildings_queue_action_source(",
    )
    assert "panel_delta_keys: Optional[List[str]] = None" in helper
    assert "panel_delta_keys=panel_delta_keys" in helper

    route = _block(
        src,
        "def api_timekeeper_apply():",
        '\n\n@app.route("/api/inventory/craft"',
    )
    assert 'applied_domain = str(result.get("domain") or domain or "").strip().lower()' in route
    assert 'if applied_domain == "build" and jobs_finished and finished_building_key' in route
    state_call = route.split("_timekeeper_apply_game_state(", 2)[2].split(")", 1)[0]
    assert "panel_delta_keys=panel_delta_keys" in state_call


def test_existing_browser_delta_patch_and_full_reconcile_safety_net_remain():
    src = _read("static/main.js")

    immediate = src.split("function patchQueuePanelsImmediate(data)", 1)[1].split(
        "let _finishRefreshTimer", 1
    )[0]
    assert "data.buildings_panel_delta || data.buildings_panel" in immediate

    submit = src.split("async function submitTimekeeperApplyFromBtn(openBtn)", 1)[1].split(
        "function initTimekeeperOnce()", 1
    )[0]
    assert 'forceCanonicalGameStateRefresh("timekeeper_apply")' in submit
    assert "jobs_finished" in submit
