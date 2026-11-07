"""Mine-Ascension simulation (asc-model/1, measurement only) - contract tests.

The simulator may only decide WHEN to call the canonical Nodebuster owner.  These tests lock: the reset, AP grant and
skill purchases go through ``nodebuster.ascend_mine`` / ``purchase_skill`` (no second engine, no free AP, no skipped
prerequisites), rebuild discounts and production hooks read the sandbox state, the canonical queue rules (no mine cap
beyond the old ceiling) are used, the arms are identical until the first decision differs, and nothing is forced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (ROOT, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ascension_analysis as aa  # noqa: E402
import player_journey_sim as pj  # noqa: E402
from game.buildings import _nodebuster_rebuild_bps, _scale_bps  # noqa: E402
from game.effects import EffectResolver  # noqa: E402
from game.mine_evolution import nodebuster as nb  # noqa: E402

DEEP = {
    "metal_mine": 205,
    "crystal_mine": 203,
    "solar_plant": 215,
    "metal_storage": 100,
    "crystal_storage": 100,
    "geothermal_nexus": 50,
    "planet_core_nexus": 50,
    "nanofactory": 20,
    "command_center": 6,
    "research_lab": 10,
}


def _journey(sb, asc="T200", order="rebuild_first", policy="optimizer", days=30.0, levels=None):
    sc = pj.Scenario("t", "S1", policy, "mid", "none", days, strategy="v2", asc=asc, asc_skills=order)
    j = pj.Journey(sc, sb)
    w = j.hw()
    if levels is not None:  # TEST-ONLY head start so the mechanism can be exercised without simulating a year
        w.buildings.update(levels)
        sb.set_buildings(w.planet_id, w.buildings)
        j.research.update({"mining_tech": 20, "crystal_tech": 20, "storage_tech": 40})
        j.research_ver += 1
    return j, w


# --------------------------------------------------------------------------- mode parsing / matrix


def test_asc_modes_parse_and_reject_invalid():
    assert pj.parse_asc_mode("legacy") == (False, None)
    assert pj.parse_asc_mode("never") == (True, None)
    assert pj.parse_asc_mode("T250") == (True, 250)
    for bad in ("T150", "T", "forever", "t200"):
        with pytest.raises(ValueError):
            pj.parse_asc_mode(bad)


def test_unknown_skill_order_is_rejected():
    with pj.Sandbox() as sb:
        with pytest.raises(ValueError):
            pj.Journey(pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="never", asc_skills="free_ap"), sb)


def test_matrix_shape():
    main = aa.build_matrix(730.0, quick=False, extended=False)
    assert len(main) == 2 * 3 * len(aa.MAIN_ARMS)
    assert len(aa.build_matrix(730.0, quick=False, extended=True)) == len(main) + 3 * len(aa.EXT_ARMS)
    assert len(aa.build_matrix(400.0, quick=True)) == 2 * 1 * 3
    outpost = aa.build_matrix(730.0, quick=False, subset="outpost")
    assert len(outpost) == 3 * len(aa.SENSITIVITY_ARMS) and {s["topology"] for s in outpost} == {"S11"}
    assert len({s["sid"] for s in main}) == len(main)


# --------------------------------------------------------------------------- canonical reset


def test_ascension_runs_through_the_canonical_owner():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, levels=DEEP)
        j.maybe_ascend(w)
        assert len(j.asc_runs) == 1 and not j.asc_rejections
        run = j.asc_runs[0]
        assert run["mine"] == "metal_mine" and run["from_level"] == 205
        # canonical award, restart level and best depth - read back from the sandbox DB, not from the simulator
        prof = sb.asc_profiles(w.planet_id)["metal_mine"]
        assert prof["state"]["ascension_count"] == 1
        assert prof["state"]["points_earned"] == nb.ascension_points_for_depth(205) == 1
        assert prof["state"]["best_depth"] == 205
        assert w.buildings["metal_mine"] == nb.reset_start_level(prof["skills"], 205) == 0
        # only the selected mine resets
        assert w.buildings["crystal_mine"] == 203 and sb.asc_profiles(w.planet_id)["crystal_mine"]["state"]["ascension_count"] == 0
        # the single AP bought Frugal Rebuild (priority order) through purchase_skill
        assert prof["skills"]["frugal_rebuild"] == 1 and prof["state"]["points_unspent"] == 0
        assert [e["skill"] for e in j.asc_skill_log] == ["frugal_rebuild"]


def test_no_reset_below_threshold_with_pending_mine_job_or_forced():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, levels={**DEEP, "metal_mine": 199, "crystal_mine": 150})
        j.maybe_ascend(w)
        assert j.asc_runs == []  # below the threshold nothing happens
        w.buildings["metal_mine"] = 205
        w.queue.append(pj.Job(1, "build", "metal_mine", 206, 1, 1, "mines", w.idx))
        j.maybe_ascend(w)
        assert j.asc_runs == []  # canonical owner would answer queue_pending; the policy never asks
        # the canonical owner itself refuses a reset below L200 (the simulator cannot bypass it)
        sb.set_buildings(w.planet_id, {**w.buildings, "crystal_mine": 150})
        ok, reason, _ = sb.ascend_mine(w.planet_id, "crystal_mine")
        assert (ok, reason) == (False, "level_too_low")
    with pj.Sandbox() as sb:
        never, w = _journey(sb, asc="never", levels=DEEP)
        never.maybe_ascend(w)
        assert never.asc_runs == [] and w.buildings["metal_mine"] == 205  # `never` never resets


def test_stagger_rule_only_one_mine_rebuilds_at_a_time():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, levels={**DEEP, "crystal_mine": 210})
        j.maybe_ascend(w)
        assert [r["mine"] for r in j.asc_runs] == ["crystal_mine"]  # the deeper mine goes first
        assert j.asc_rebuilding(w, "crystal_mine") and j.asc_stagger_blocked(w, "metal_mine")
        j.maybe_ascend(w)
        assert len(j.asc_runs) == 1  # metal waits until crystal has climbed back through its best depth
        # while blocked the policy keeps deepening the other mine instead of parking it
        assert not j.asc_hold(w, "metal_mine", dict(w.buildings))


def test_skills_follow_canonical_costs_and_prerequisites():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        # yield_first needs 2 AP for Deep Yield: with 1 AP it saves instead of buying something cheaper
        j, w = _journey(sb, order="yield_first", levels=DEEP)
        j.maybe_ascend(w)
        prof = sb.asc_profiles(w.planet_id)["metal_mine"]
        assert prof["state"]["points_unspent"] == 1 and not any(prof["skills"].values())
        # a locked skill cannot be bought by asking for it directly
        ok, reason, _ = sb.buy_skill(w.planet_id, "metal_mine", "overdrive")
        assert (ok, reason) == (False, "skill_prerequisite")
        ok, reason, _ = sb.buy_skill(w.planet_id, "metal_mine", "deep_yield")
        assert (ok, reason) == (False, "insufficient_points")
        assert sb.asc_profiles(w.planet_id)["metal_mine"]["state"]["points_unspent"] == 1  # nothing was granted for free
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, order="yield_first", asc="T225", levels={**DEEP, "metal_mine": 225})
        j.maybe_ascend(w)
        prof = sb.asc_profiles(w.planet_id)["metal_mine"]
        assert prof["state"]["points_earned"] == 2 and prof["skills"]["deep_yield"] == 1 and prof["state"]["points_unspent"] == 0


def test_ap_invariants_hold_and_detect_tampering():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, order="yield_first", asc="T225", levels={**DEEP, "metal_mine": 226})
        j.maybe_ascend(w)
        j.check_asc_invariants()
        assert j.invariant_violations == []
        sb.conn.execute("UPDATE planet_mine_ascension_state SET points_unspent = points_unspent + 5 WHERE planet_id = ? AND building_type = 'metal_mine';", (w.planet_id,))
        sb.conn.commit()
        j._bump_asc()
        j.check_asc_invariants()
        assert any("AP spent mismatch" in v for v in j.invariant_violations)


# --------------------------------------------------------------------------- rebuild discount / production hooks


def test_rebuild_discount_uses_the_exact_canonical_basis_points():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, levels=DEEP)
        raw = pj._upgrade_cost("metal_mine", 100)
        assert j.ucost("metal_mine", 100, w) == raw  # no discount before the first Ascension
        j.maybe_ascend(w)  # Frugal Rebuild rank 1 -> -5.5 % while climbing back through the best depth
        cost_bps, time_bps = _nodebuster_rebuild_bps(w.planet_id, "metal_mine", 101, conn=sb.conn)
        assert cost_bps == 9450 and time_bps == 10000
        assert j.ucost("metal_mine", 100, w) == (_scale_bps(raw[0], 9450), _scale_bps(raw[1], 9450))
        assert j.ucost("metal_mine", 100, w)[0] < raw[0]
        beyond = pj._upgrade_cost("metal_mine", 205)  # target 206 > best depth 205: full price again
        assert j.ucost("metal_mine", 205, w) == beyond
        # the other (non-ascended) mine and non-mines are never discounted
        assert j.ucost("crystal_mine", 100, w) == pj._upgrade_cost("crystal_mine", 100)
        assert j.ucost("solar_plant", 100, w) == pj._upgrade_cost("solar_plant", 100)


def test_resolver_bound_to_the_planet_is_identical_without_ascension_state():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, levels=DEEP)
        plain = j.stats(w)
        w.asc_any = True  # bound resolver, empty Nodebuster state
        j._stat_cache.clear()
        bound = j.stats(w)
        w.asc_any = False
        for key in ("m_ps", "c_ps", "f_ps", "cap_m", "cap_c", "ratio", "supply", "demand"):
            assert bound[key] == plain[key], key


def test_production_and_storage_hooks_read_the_sandbox_state():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, order="yield_first", asc="T225", levels={**DEEP, "metal_mine": 225})
        before = j.stats(w)
        j.maybe_ascend(w)  # reset + Deep Yield rank 1 (+2.5 % on that mine only)
        after = j.stats(w)
        assert after["m_ps"] < before["m_ps"] * 0.2  # the reset mine no longer produces
        assert after["c_ps"] == before["c_ps"]  # the other mine is untouched
        # same buildings, planet-bound resolver with the skill vs plain resolver: the skill adds at most +2.5 %
        buildings = {**w.buildings, "metal_mine": 225}
        bound = j._new_resolver(w, buildings, j.research)
        plain = pj.EffectResolver(dict(buildings), dict(j.research), settings=j.settings, planet_position=w.slot)
        rate_bound, rate_plain = bound.production_rates_per_sec()[0], plain.production_rates_per_sec()[0]
        assert 1.0 < rate_bound / rate_plain <= 1.025 + 1e-9
        assert isinstance(bound, EffectResolver) and bound.planet_id == w.planet_id


# --------------------------------------------------------------------------- queue rules


def test_canonical_queue_cap_replaces_the_resolver_cap_only_for_mines_and_solar():
    with pj.Sandbox() as sb:
        legacy, w = _journey(sb, asc="legacy")
        never, w2 = _journey(sb, asc="never")
        r = legacy._resolver(w, {"metal_mine": 10})
        assert legacy.max_level(w, r, "metal_mine") == r.get_max_building_level("metal_mine") == 50
        assert never.max_level(w2, r, "metal_mine") == nb.QUEUE_SAFETY_SENTINEL
        assert never.max_level(w2, r, "solar_plant") == nb.QUEUE_SAFETY_SENTINEL
        assert never.max_level(w2, r, "metal_storage") == r.get_max_building_level("metal_storage")
        assert never.max_level(w2, r, "nanofactory") == r.get_max_building_level("nanofactory")


def test_uncapped_arms_equal_legacy_until_a_mine_passes_the_old_ceiling():
    runs = {}
    for asc in ("legacy", "never", "T200"):
        sc = pj.Scenario(f"t-{asc}", "S1", "optimizer", "mid", "none", 60.0, strategy="v2", asc=asc)
        runs[asc] = pj.run_scenario(sc, curve="uni1")
    key = lambda r: [(d["empire_metal_h"], d["empire_crystal_h"], d["mine_depth_max"]) for d in r["daily"]]  # noqa: E731
    assert key(runs["legacy"]) == key(runs["never"]) == key(runs["T200"])
    assert all(r["invariants"]["ok"] for r in runs.values())
    # no reset is forced: nothing reaches L200 in 60 days
    assert runs["T200"]["ascension_runs"] == [] and runs["never"]["ascension_runs"] == []


# --------------------------------------------------------------------------- end-to-end with a head start


def test_policy_ascends_rebuilds_and_keeps_the_ledger_conserved():
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j, w = _journey(sb, order="rebuild_first", days=25.0, levels={**DEEP, "metal_mine": 200, "crystal_mine": 150})
        w.metal = w.crystal = 5e15  # TEST-ONLY head start stock
        res = j.run()
        assert res["invariants"]["ok"], res["invariants"]
        runs = res["ascension_runs"]
        assert runs and runs[0]["mine"] == "metal_mine" and runs[0]["from_level"] == 200
        assert runs[0]["reset_level"] == 0 and runs[0]["income_after_h"] < runs[0]["income_before_h"]
        # the world kept rebuilding the reset mine (climbing) and the crystal mine was never reset while it was below L200
        assert res["final"]["per_world"][0]["buildings"].get("metal_mine", 0) > 0
        for wd in res["final"]["per_world"]:
            assert abs(sum(wd["time_ledger_sec"].values()) - wd["age_sec"]) < 0.05
        asc = res["final"]["ascension"]
        assert asc["ascensions_total"] == len(runs) and asc["ap_earned_total"] == sum(nb.ascension_points_for_depth(r["from_level"]) for r in runs)
        assert asc["ap_spent_total"] <= asc["ap_earned_total"]


# --------------------------------------------------------------------------- aggregation helpers


def _res(arm, series, runs=(), days=730.0, topo="S1", style="optimizer", snaps=None):
    return {"topology": topo, "policy": style, "arm": arm, "days": days, "series": series, "ascension_runs": list(runs), "snapshots": snaps or {}, "colonies_founded_day": [], "invariants": {"ok": True, "violations": []}}


def test_crossing_day_requires_the_income_to_stay_above():
    ref = [[10, 100], [20, 100], [30, 100], [40, 100]]
    arm = [[10, 50], [20, 120], [30, 90], [40, 130]]
    assert aa.crossing_day(arm, ref) == 40  # 20 was only a spike
    assert aa.crossing_day([[10, 50], [20, 60]], ref) is None
    assert aa.crossing_day(arm, ref, after_day=30) == 40


def test_ascension_day_helpers_and_rebuild_stats():
    runs = [
        {"world": 0, "mine": "metal_mine", "day": 100.0, "rebuild_to_best_days": 50.0, "income_recovered_days": 40.0, "income_before_h": 100, "income_after_h": 40},
        {"world": 0, "mine": "metal_mine", "day": 160.0, "rebuild_to_best_days": 70.0, "income_recovered_days": None, "income_before_h": 100, "income_after_h": 60},
        {"world": 1, "mine": "metal_mine", "day": 170.0, "rebuild_to_best_days": None, "income_recovered_days": None, "income_before_h": 100, "income_after_h": 50},
        {"world": 0, "mine": "metal_mine", "day": 300.0, "rebuild_to_best_days": None, "income_recovered_days": None, "income_before_h": 100, "income_after_h": 70},
    ]
    res = _res("T200", [], runs)
    assert aa.nth_ascension_day(res, 1) == 100.0 and aa.nth_ascension_day(res, 3) == 170.0 and aa.nth_ascension_day(res, 9) is None
    assert aa.third_on_one_mine_day(res) == 300.0  # third run of (world 0, metal) - not the third run overall
    st = aa.rebuild_stats(res)
    assert st["runs"] == 4 and st["rebuilt"] == 2 and st["rebuild_days_median"] == 60.0
    assert st["income_recovered_median"] == 40.0 and st["income_cliff_pct_median"] == 45.0  # cliffs 60, 40, 50, 30 %


def test_render_on_synthetic_data_and_cli_roundtrip(tmp_path):
    snap = {"empire_metal_h": 1000, "empire_crystal_h": 500, "mine_depth_max": 120, "crystal_depth_max": 118, "worlds": 1, "per_world": [
        {"idx": 0, "age_sec": 100.0, "time_ledger_sec": {"busy": 60.0, "wait_metal": 40.0}, "wasted_metal": 0, "wasted_crystal": 0, "wasted_fuel": 0, "produced_metal": 10, "produced_crystal": 5, "produced_fuel": 1, "lost_to_energy_metal": 0, "lost_to_energy_crystal": 0, "lost_to_energy_fuel": 0}],
        "ascension": {"ascensions_total": 1, "ascensions_max_single_mine": 1, "ap_earned_total": 1, "ap_spent_total": 1, "peak_depth_max": 205, "mines": [{"skills": {"frugal_rebuild": 1}}]}}
    results = []
    for topo in aa.TOPOLOGIES:
        for style in aa.STYLES:
            for arm in aa.MAIN_ARMS:
                results.append(_res(arm, [[5, 100, 10, 0, 1], [10, 120, 12, 1, 1]], [{"world": 0, "mine": "metal_mine", "day": 8.0, "rebuild_to_best_days": 1.0, "income_recovered_days": 1.0, "income_before_h": 10, "income_after_h": 5}], topo=topo, style=style, snaps={"182.5": snap, "365": snap, "730": snap}))
    data = {"meta": {"analysis_version": aa.ANALYSIS_VERSION, "sim_version": pj.SIM_VERSION, "asc_model_version": pj.ASC_MODEL_VERSION, "code_sha": "0" * 40}, "results": results, "extended": []}
    md = aa.render_markdown(data)
    for heading in ("## 1. Production", "## 2. Ascend or keep building", "## 3. Are three Ascensions reachable", "## 4. Reset and rebuild", "## 6. Queue utilisation", "## 10. Invariants"):
        assert heading in md
    out = tmp_path / "r.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    md_path = tmp_path / "r.md"
    assert aa.main(["--render-from", str(out), "--out-md", str(md_path)]) == 0
    assert md_path.read_text(encoding="utf-8").startswith("# GC - Mine Ascension")
