"""GC-PERF-TK-010 — Timekeeper queue patching must stay queue-only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    return src.split(start, 1)[1].split(end, 1)[0]


def test_shipyard_queue_serializer_has_explicit_skip_finish_contract():
    src = _read("game/shipyard_queue.py")
    block = _block(src, "def shipyard_queue_for_client(", "\ndef ")
    assert "skip_finish: bool = False" in block
    assert "if shipyard_queue_table_ready(conn) and not skip_finish:" in block


def test_defense_queue_serializer_has_explicit_skip_finish_contract():
    src = _read("game/defense.py")
    block = _block(src, "def defense_queue_for_client(", "\ndef build_defense_api_payload(")
    assert "skip_finish: bool = False" in block
    assert "if defense_queue_table_ready(conn) and not skip_finish:" in block


def test_timekeeper_shipyard_and_defense_do_not_build_full_catalog_panels():
    src = _read("game/live_state.py")
    sy = _block(
        src,
        "def _timekeeper_shipyard_queue_slice(",
        "\ndef _timekeeper_defense_queue_slice(",
    )
    defense = _block(
        src,
        "def _timekeeper_defense_queue_slice(",
        "\ndef attach_timekeeper_domain_queue_slices(",
    )
    attach = _block(
        src,
        "def attach_timekeeper_domain_queue_slices(",
        "\ndef _head_card_jobs(",
    )

    assert "shipyard_queue_for_client(" in sy
    assert "skip_finish=True" in sy
    assert "build_shipyard_api_payload" not in sy

    assert "defense_queue_for_client(" in defense
    assert "skip_finish=True" in defense
    assert "build_defense_api_payload" not in defense

    shipyard_branch = attach.split('if dom == "shipyard":', 1)[1].split(
        'elif dom == "defense":', 1
    )[0]
    defense_branch = attach.split('elif dom == "defense":', 1)[1].split(
        'elif dom == "troops":', 1
    )[0]
    assert "shipyard_panel_for_game_state" not in shipyard_branch
    assert "_timekeeper_shipyard_queue_slice" in shipyard_branch
    assert "defense_panel_for_game_state" not in defense_branch
    assert "_timekeeper_defense_queue_slice" in defense_branch
