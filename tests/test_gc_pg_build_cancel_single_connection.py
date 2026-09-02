"""PG production regression: building cancel must not open a second owner lookup connection."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cancel_build_uses_mutation_connection_for_owner_lookup():
    src = (ROOT / "game/buildings.py").read_text(encoding="utf-8")
    block = src.split("def cancel_build_job_for_planet(", 1)[1].split("# =============================================================================", 1)[0]
    assert "SELECT player_id FROM planets WHERE id = ? LIMIT 1;" in block
    assert "owner_row = conn.execute(" in block
    assert "get_planet_owner_id(planet_id)" not in block
    assert "lock_planet_for_update(conn, planet_id)" in block
    assert "refund_build_job(" in block
    assert "recalculate_build_queue_finish_times(" in block


def test_queue_contract_still_requires_finish_refund_delete_reschedule_order():
    src = (ROOT / "game/buildings.py").read_text(encoding="utf-8")
    block = src.split("def cancel_build_job_for_planet(", 1)[1].split("# =============================================================================", 1)[0]
    positions = [
        block.index("finish_due_work("),
        block.index("refund_build_job("),
        block.index("delete_build_job("),
        block.index("recalculate_build_queue_finish_times("),
        block.index("commit(conn)"),
    ]
    assert positions == sorted(positions)
