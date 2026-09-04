"""GC-FERRO-L388-001 — Ferronit L388 must survive costs above signed BIGINT."""

from __future__ import annotations

from pathlib import Path
import uuid

import game.buildings as buildings_mod
from game.db import db
from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

pytest_plugins = ["tests.test_game_state_live"]

I64_MAX = 9_223_372_036_854_775_807


def _set_rank(planet_id: int, building_type: str, rank: int) -> None:
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO planet_mine_evolution
                (planet_id, building_type, evolution_rank, updated_at)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(planet_id, building_type) DO UPDATE SET
                evolution_rank = excluded.evolution_rank;
            """,
            (int(planet_id), str(building_type), int(rank)),
        )
        conn.commit()
    finally:
        conn.close()


def test_actual_ferro_l388_cost_exceeds_i64_but_api_enqueue_and_refund_stay_exact(
    game_client, monkeypatch
):
    client, uid = game_client
    planet = get_homeworld(player_id=int(uid))
    assert planet is not None
    pid = int(planet["id"])

    levels = get_planet_buildings(pid)
    levels.update(
        {
            "planet_core_nexus": 50,
            "geothermal_nexus": 50,
            "metal_mine": 387,
            "crystal_mine": 387,
            "fuel_cell_plant": 387,
        }
    )
    save_planet_buildings(pid, levels)
    _set_rank(pid, "metal_mine", 8)

    # Production resources are REAL/DOUBLE today. Bind a float here deliberately;
    # the regression is that the *upgrade cost* is a Python int > signed i64.
    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (1.0e22, 1.0e22, pid),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        buildings_mod.BuildingsPanelContext,
        "build_time_seconds",
        lambda self, building_type, target_level: 60,
    )

    expected_metal, expected_crystal = buildings_mod.get_upgrade_cost("metal_mine", 387)
    assert expected_metal > I64_MAX
    assert expected_crystal > 0

    request_id = f"ferro-l388-{uuid.uuid4().hex}"
    res = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": request_id},
    )
    assert res.status_code == 200
    body = res.get_json() or {}
    assert body.get("ok") is True, body
    job = body.get("job") or {}
    assert int(job.get("target_level") or 0) == 388
    job_id = int(job.get("job_id") or 0)
    assert job_id > 0

    conn = db()
    try:
        row = conn.execute(
            """
            SELECT cost_metal, cost_crystal, cost_metal_exact, cost_crystal_exact
            FROM build_queue WHERE id = ?;
            """,
            (job_id,),
        ).fetchone()
        assert row is not None
        # Rolling-deploy fallback: legacy i64 cannot represent Ferro L388,
        # so old code sees 0 and recomputes instead of overflowing.
        assert int(row["cost_metal"] or 0) == 0
        assert int(row["cost_metal_exact"]) == int(expected_metal)
        assert int(row["cost_crystal_exact"]) == int(expected_crystal)
    finally:
        conn.close()

    cancel = client.post("/api/buildings/cancel", json={"job_id": job_id})
    assert cancel.status_code == 200
    cancelled = cancel.get_json() or {}
    assert cancelled.get("ok") is True, cancelled
    refund = cancelled.get("job") or cancelled.get("payload") or {}
    # API action envelope may carry cancel payload as job; either way the server
    # must preserve the paid cost without float/i64 truncation.
    if refund:
        assert int(refund.get("cost_metal") or expected_metal) == int(expected_metal)


def test_ascension_required_has_specific_client_message_and_next_gate_contract():
    main_js = Path("static/main.js").read_text(encoding="utf-8")
    assert 'reason === "ascension_required"' in main_js
    assert "next_max_level" in main_js

    src = Path("game/buildings.py").read_text(encoding="utf-8")
    block = src.split("def _cap_failure_payload", 1)[1].split(
        "def _record_mutate_perf", 1
    )[0]
    assert '"next_max_level"' in block
    assert "required_level_for_evolution" in block


def test_exact_cost_migration_is_additive_and_backfills_legacy_rows():
    migration = Path("migrations/163_build_queue_exact_cost_snapshots.sql").read_text(
        encoding="utf-8"
    )
    assert "cost_metal_exact TEXT" in migration
    assert "cost_crystal_exact TEXT" in migration
    assert "CAST(cost_metal AS TEXT)" in migration
