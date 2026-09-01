"""P0 regression gates for live PostgreSQL failures reported after deploy."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_records_aggregate_queries_group_selected_player_name_for_postgres():
    src = _read("game/records.py")
    assert "GROUP BY p.player_id, pl.name\n        ORDER BY value DESC" in src
    assert "GROUP BY ps.player_id, pl.name\n            HAVING" in src
    assert src.count("GROUP BY p.player_id, pl.name\n            HAVING") == 2
    assert "GROUP BY c.player_id, pl.name\n        HAVING" in src


def test_build_enqueue_vacation_probe_does_not_orphan_db_checkout():
    src = _read("game/buildings.py")
    block = src.split("def queue_build_for_planet(", 1)[1].split("\n\ndef cancel_build_job_for_planet", 1)[0]
    assert "vacation_blocks_outbound(user_id, conn=db())" not in block
    assert "conn = db()\n    ok_vacation, vac_reason = vacation_blocks_outbound(user_id, conn=conn)" in block
    assert "if not ok_vacation:\n        conn.close()" in block


def test_planet_switch_post_response_reads_share_one_checkout():
    src = _read("app.py")
    block = src.split("def api_planets_set_active():", 1)[1].split("\n\n@app.route", 1)[0]
    assert "switch_conn = db()" in block
    assert "get_context_planet(user_id, conn=switch_conn)" in block
    assert "list_player_planets_for_switcher(user_id, conn=switch_conn)" in block
    assert "finally:\n            switch_conn.close()" in block
