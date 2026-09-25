"""Long-horizon economy magnitude audit regression coverage."""

from __future__ import annotations

from scripts.audit_long_horizon_economy import build_audit


def test_long_horizon_audit_uses_consistent_topology_and_live_owners():
    audit = build_audit()
    topology = audit["topology"]

    assert topology["one_world"]["182.5d"] <= topology["eleven_world_pool"]["182.5d"]
    assert topology["one_world"]["365d"] <= topology["eleven_world_pool"]["365d"]
    assert topology["eleven_world_pool"]["365d"] <= topology["zero_cost_queue"]["365d"]

    rows = {row["key"]: row for row in audit["anchors"]}
    assert rows["1w_12m"]["worlds"] == 1
    assert rows["11w_12m"]["worlds"] == 11

    for row in rows.values():
        assert row["metal_per_hour"] > 0
        assert row["next_upgrade_total"] > 0
        assert row["next_queue_floor_seconds"] >= 10
        assert row["storage_buffer_hours"] >= 24
        assert row["metal_storage_v2_floor"] >= row["metal_per_hour"] * row["storage_buffer_hours"]
        assert 0 <= row["trader_cap_vs_empire_metal_day_pct"] <= 100
        military = row["military_sink"]
        assert military["resource_units_per_hour"] > 0
        assert military["queue_units_per_hour_rank0"] > 0
        assert military["queue_units_per_hour_rank10"] >= military["queue_units_per_hour_rank0"]
        assert {entry["slot"] for entry in row["energy"]} == {1, 8, 15}
        assert all(0 <= entry["grid_pct"] <= 100 for entry in row["energy"])
        assert all(0 <= entry["optimized_grid_pct"] <= 100 for entry in row["energy"])
        assert all(0 <= entry["optimized_balanced_pct"] <= 100 for entry in row["energy"])

    for row in (rows["1w_12m"], rows["11w_12m"]):
        targets = [entry["target_level"] for entry in row["research"]]
        assert targets == [60, 100, 120, 150, 200]
        assert all(entry["payment_total"] > 0 for entry in row["research"])
        assert all(entry["afford_hours"] > 0 for entry in row["research"])
        assert all(entry["late_infra_time_hours"] >= 10 / 3600 for entry in row["research"])
        assert all(entry["cumulative_afford_hours"] >= entry["afford_hours"] for entry in row["research"])
        assert all(entry["cumulative_queue_hours"] >= entry["late_infra_time_hours"] for entry in row["research"])
        assert all(
            entry["reach_floor_hours"]
            >= max(entry["cumulative_afford_hours"], entry["cumulative_queue_hours"])
            for entry in row["research"]
        )

    skip = audit["free_skip_economy"]
    assert skip["login_cycle_tk_equivalent_sec"] > 0
    assert skip["login_perfect_365_tk_equivalent_sec"] > skip["login_cycle_tk_equivalent_sec"] * 12
    assert skip["battle_pass_free_tk_equivalent_sec"] >= skip["battle_pass_free_tk_direct_sec"]
    assert skip["zero_cost_365_free_skip_ceiling"] >= skip["zero_cost_365_no_skip_ceiling"]
    assert skip["zero_cost_365_free_skip_ceiling"] < 1000
    assert skip["nodebuster_full_tree_ap"] == 339
    assert skip["inactive_human_real_queue_timers"] is True
    assert skip["shared_planner_synthetic_refill_sec"] == 36_000
