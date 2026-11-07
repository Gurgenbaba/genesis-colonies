"""Progression-bottleneck analysis (measurement only) - contract tests.

The analysis must attribute every second of a world's life to exactly one cause, keep the
counterfactual levers inside the sandbox (restored afterwards, labelled in the output), keep the
improved policy legal (same rules, no free anything) and stay deterministic.  Horizons are short.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (ROOT, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import player_journey_sim as pj  # noqa: E402
import progression_bottleneck_analysis as pb  # noqa: E402
from game.planet_evolution import expansion_protocol as ep  # noqa: E402


def _run(topology="S1", policy="active", days=30.0, *, lever="none", strategy="v1", seed=None, sid="t"):
    sc = pj.Scenario(sid, topology, policy, "mid", "none", days, lever=lever, strategy=strategy, rng_seed=seed)
    return pj.run_scenario(sc, curve="uni1")


def _slim(result, key="final"):
    return pb._slim_snapshot(result[key] if key == "final" else result["checkpoints"][key])


def test_time_ledger_sums_to_world_age_for_every_world_and_policy():
    for strategy in ("v1", "v2"):
        res = _run("S11", "active", 45.0, strategy=strategy, seed=pj.ELIGIBLE_HOME_SEED)
        snap = _slim(res)
        assert len(snap["per_world"]) >= 2, "S11 must have founded a colony so late-born worlds are covered"
        for w in snap["per_world"]:
            assert abs(sum(w["time_ledger_sec"].values()) - w["age_sec"]) < 0.05, (strategy, w["idx"])
        assert pb.ledger_conservation_error(snap) < 1e-6
        assert sum(pb.ledger_shares(snap).values()) == pytest.approx(100.0, abs=1e-6)
        assert sum(snap["research_time_ledger_sec"].values()) == pytest.approx(snap["elapsed_sec"], abs=0.05)


def test_only_known_causes_are_used():
    known = {k for k, _ in pb.LEDGER_COLUMNS} | {"storage_cap_below_cost"}
    res = _run("S11", "casual", 45.0, seed=pj.ELIGIBLE_HOME_SEED)
    for w in _slim(res)["per_world"]:
        assert set(w["time_ledger_sec"]) <= known


def test_continuous_play_has_no_player_latency_but_windowed_play_does():
    opt = pb.ledger_shares(_slim(_run("S1", "optimizer", 20.0)))
    casual = pb.ledger_shares(_slim(_run("S1", "casual", 20.0)))
    assert opt.get("player_not_acting", 0.0) < 0.5
    assert casual.get("player_not_acting", 0.0) > 5.0


def test_baseline_run_is_deterministic_and_levers_do_not_leak_into_it():
    base1 = _run("S1", "active", 20.0)
    _run("S1", "active", 20.0, lever="free_storage")
    _run("S11", "active", 20.0, lever="no_colony_chain", seed=pj.ELIGIBLE_HOME_SEED)
    base2 = _run("S1", "active", 20.0)
    drop = lambda r: {k: v for k, v in r.items() if k != "wall_seconds"}  # noqa: E731
    assert json.dumps(drop(base1), sort_keys=True) == json.dumps(drop(base2), sort_keys=True)
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15, "the sandbox-only maturity patch must be restored"


def test_unknown_lever_or_strategy_is_rejected():
    with pj.Sandbox() as sb:
        with pytest.raises(ValueError):
            pj.Journey(pj.Scenario("t", "S1", "active", "mid", lever="make_it_easy"), sb)
        with pytest.raises(ValueError):
            pj.Journey(pj.Scenario("t", "S1", "active", "mid", strategy="v9"), sb)


def test_levers_are_labelled_and_act_only_on_their_brake():
    base = _slim(_run("S1", "active", 40.0))
    free_storage = _run("S1", "active", 40.0, lever="free_storage")
    assert free_storage["lever"] == "free_storage" and free_storage["lever_label"] == pj.LEVERS["free_storage"]
    fs = _slim(free_storage)
    assert pb.production_losses(fs)["depot_metal"] == 0.0 and pb.production_losses(fs)["depot_crystal"] == 0.0
    assert pb.production_losses(base)["depot_crystal"] >= 0.0

    free_energy = _slim(_run("S1", "active", 40.0, lever="free_energy"))
    assert all(w["lost_to_energy_metal"] == 0 for w in free_energy["per_world"])
    assert pb.ledger_shares(free_energy).get("wait_energy_drag", 0.0) == 0.0

    income = _slim(_run("S1", "active", 40.0, lever="income_x1.25"))
    assert pb.income(income) > pb.income(base), "more income must not lower income"


def test_instant_build_and_instant_research_shorten_only_their_timers():
    with pj.Sandbox() as sb:
        plain = pj.Journey(pj.Scenario("t", "S1", "active", "mid"), sb)
        fast = pj.Journey(pj.Scenario("t", "S1", "active", "mid", lever="instant_build"), sb)
        job = pj.Job(1, "build", "metal_mine", 50, 0, 0, "mines", 0)
        assert plain.duration_for(plain.hw(), job) > 100.0
        assert fast.duration_for(fast.hw(), job) <= max(1.0, plain.duration_for(plain.hw(), job) * pj.LEVER_TIME_FACTOR) + 1e-9
    cost = _run("S1", "active", 10.0, lever="free_research_cost")
    assert (cost["final"]["spend_metal"] or {}).get("research", 0) == 0


def test_no_colony_chain_lever_only_lowers_the_maturity_gate():
    base = _run("S11", "active", 70.0, seed=pj.ELIGIBLE_HOME_SEED)
    lev = _run("S11", "active", 70.0, lever="no_colony_chain", seed=pj.ELIGIBLE_HOME_SEED)
    assert lev["final"]["worlds"] > base["final"]["worlds"]
    assert "colony_maturity_required" not in lev["blockers"]
    # every other gate is still enforced (slots / homeworld level / tech); the admin ceiling is untouched
    assert lev["final"]["worlds"] <= pj.TARGET_WORLDS
    assert lev["invariants"]["ok"]


def test_improved_policy_is_legal_and_does_not_skip_expansion_prerequisites():
    for style in ("casual", "active", "optimizer"):
        res = _run("S11", style, 60.0, strategy="v2", seed=pj.ELIGIBLE_HOME_SEED)
        assert res["policy_version"] == "pj-policy/2"
        assert res["invariants"]["ok"], res["invariants"]
        assert res["final"]["worlds"] >= 2, f"v2 must still prepare and launch the Seed Ark ({style})"
    v1 = _run("S1", "active", 60.0, strategy="v1")
    v2 = _run("S1", "active", 60.0, strategy="v2")
    assert v1["invariants"]["ok"] and v2["invariants"]["ok"]
    assert v2["final"]["paid_accelerators"] == 0 and v2["final"]["free_accelerators_applied_sec"] == 0
    # same canonical rules, same queue depth: only the choice differs
    assert v1["transit_sec"] == v2["transit_sec"]


def test_colony_pipeline_ledger_covers_the_whole_horizon():
    res = _run("S11", "active", 45.0, seed=pj.ELIGIBLE_HOME_SEED)
    snap = _slim(res)
    assert sum(snap["colony_pipeline_sec"].values()) == pytest.approx(snap["elapsed_sec"], abs=0.05)
    assert "gate:colony_maturity_required" in snap["colony_pipeline_sec"]


def test_matrix_shape_and_no_live_data():
    specs = pb.build_matrix(730.0, quick=False)
    # per strategy: S1 = 3 styles x (baseline + 12 levers), S11 = 3 styles x (baseline + 17 levers)
    assert len(specs) == 2 * (3 * 13 + 3 * 18)
    ids = [s["sid"] for s in specs]
    assert len(set(ids)) == len(ids)
    assert not any(s["topology"] == "S1" and s["lever"] in pb.COLONY_LEVERS for s in specs)
    assert {s["lever"] for s in specs} - {"none"} == {k for k in pj.LEVERS if k != "none"}
    assert {s["strategy"] for s in specs} == {"v1", "v2"}
    assert {s["policy"] for s in specs} == {"casual", "active", "optimizer"}
    assert all(s["days"] == 730.0 for s in specs)


def test_aggregation_helpers_on_synthetic_data():
    snap = {
        "worlds": 1,
        "empire_metal_h": 100, "empire_crystal_h": 50,
        "per_world": [
            {"age_sec": 100.0, "time_ledger_sec": {"busy": 10.0, "wait_metal": 60.0, "player_not_acting": 30.0},
             "produced_metal": 90, "wasted_metal": 10, "produced_crystal": 100, "wasted_crystal": 0, "produced_fuel": 5, "wasted_fuel": 95,
             "lost_to_energy_metal": 10, "lost_to_energy_crystal": 0, "lost_to_energy_fuel": 0},
        ],
    }
    sh = pb.ledger_shares(snap)
    assert sh == {"busy": 10.0, "wait_metal": 60.0, "player_not_acting": 30.0}
    loss = pb.production_losses(snap)
    assert loss["depot_metal"] == pytest.approx(10.0) and loss["depot_fuel"] == pytest.approx(95.0)
    assert loss["energy_metal"] == pytest.approx(100.0 * 10 / 110)
    assert pb.rel(110, 100) == pytest.approx(10.0) and pb.rel(1, 0) is None
    assert pb.income(snap) == 150.0


def test_interval_ledger_covers_only_the_interval_and_late_born_worlds():
    start = {"per_world": [{"idx": 0, "age_sec": 100.0, "time_ledger_sec": {"busy": 50.0, "wait_metal": 50.0}}]}
    end = {
        "per_world": [
            {"idx": 0, "age_sec": 200.0, "time_ledger_sec": {"busy": 60.0, "wait_metal": 140.0}},
            {"idx": 1, "age_sec": 40.0, "time_ledger_sec": {"busy": 40.0}},  # founded inside the interval
        ]
    }
    sh = pb.ledger_delta_shares(end, start)
    # interval world-seconds: world 0 -> 100 (busy 10, wait 90), world 1 -> 40 (busy 40)
    assert sh["busy"] == pytest.approx(100.0 * 50 / 140)
    assert sh["wait_metal"] == pytest.approx(100.0 * 90 / 140)
    assert sum(sh.values()) == pytest.approx(100.0)
    assert pb.ledger_delta_shares(end, None)["busy"] == pytest.approx(100.0 * 100 / 240)


def test_lever_deltas_and_render_on_synthetic_results():
    def mk(strategy, lever, inc_m, worlds):
        s = {"day": 365, "worlds": worlds, "mine_depth_max": 100, "mine_depth_median": 100, "mine_depth_min": 100, "crystal_depth_max": 100,
             "empire_metal_h": inc_m, "empire_crystal_h": inc_m, "empire_fuel_h": 0, "hw_planet_level": 30, "research": {},
             "research_time_ledger_sec": {"busy": 1.0}, "colony_pipeline_sec": {"gate:colony_maturity_required": 1.0}, "elapsed_sec": 1.0,
             "per_world": [{"idx": 0, "age_sec": 10.0, "time_ledger_sec": {"busy": 10.0}, "produced_metal": 1, "wasted_metal": 0,
                            "produced_crystal": 1, "wasted_crystal": 0, "produced_fuel": 0, "wasted_fuel": 0,
                            "lost_to_energy_metal": 0, "lost_to_energy_crystal": 0, "lost_to_energy_fuel": 0}]}
        return {"sid": f"S11-{strategy}-{lever}", "topology": "S11", "policy": "active", "strategy": strategy, "lever": lever,
                "days": 730.0, "status": "complete", "snapshots": {"182.5": s, "365": s, "730": s}, "mine_milestone_day": {},
                "colonies_founded_day": [], "invariants": {"ok": True, "violations": []}, "mandates_earned": [], "blockers": {}}

    results = []
    for style in pb.STYLES:
        for strategy in pb.STRATEGIES:
            for lever, inc, worlds in (("none", 100, 5), ("no_colony_chain", 150, 8)):
                r = mk(strategy, lever, inc, worlds)
                r["policy"] = style
                r["sid"] = f"S11-{style}-{strategy}-{lever}"
                results.append(r)
    d = pb.lever_deltas(results, "S11", "v2", "no_colony_chain", "365")
    assert d["income_pct"] == pytest.approx(50.0) and d["worlds_delta"] == pytest.approx(3.0)
    md = pb.render_markdown({"meta": {"code_sha": "x" * 12, "analysis_version": pb.ANALYSIS_VERSION, "scenarios": len(results), "days": 730, "economy_curve": "uni1"},
                             "assumptions": pb.ASSUMPTIONS, "results": results})
    assert "measurement only" in md and "Counterfactual levers" in md and "no_colony_chain" in md
    assert "Serial PL15 colony chain" in md


def test_cli_quick_smoke_writes_json_and_markdown(tmp_path):
    out_json, out_md = tmp_path / "pb.json", tmp_path / "pb.md"
    before = os.environ.get("GC_DB_PATH")
    rc = pb.main(["--quick", "--days", "12", "--workers", "1", "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0 and out_json.exists() and out_md.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["meta"]["analysis_version"] == pb.ANALYSIS_VERSION
    assert all(r["invariants"]["ok"] for r in data["results"])
    assert "Where does the build-queue time go" in out_md.read_text(encoding="utf-8")
    assert os.environ.get("GC_DB_PATH") == before


def test_candidate_time_levers_scale_only_their_own_timer():
    with pj.Sandbox() as sb:
        plain = pj.Journey(pj.Scenario("t", "S1", "active", "mid"), sb)
        build = pj.Journey(pj.Scenario("t", "S1", "active", "mid", lever="build_time_x0.88"), sb)
        research = pj.Journey(pj.Scenario("t", "S1", "active", "mid", lever="research_time_x0.88"), sb)
        job = pj.Job(1, "build", "metal_mine", 50, 0, 0, "mines", 0)
        assert build.duration_for(build.hw(), job) == pytest.approx(0.88 * plain.duration_for(plain.hw(), job))
        assert research.duration_for(research.hw(), job) == pytest.approx(plain.duration_for(plain.hw(), job))

        durations = {}
        for name, j in (("plain", plain), ("research", research), ("build", build)):
            rj = pj.Job(2, "research", "mining_tech", 20, 0, 0, "research", 0)
            j.t = 0.0
            j.rqueue = [rj]
            j.start_research()
            durations[name] = rj.finish - rj.start
        assert durations["research"] == pytest.approx(0.88 * durations["plain"])
        assert durations["build"] == pytest.approx(durations["plain"])


def test_colony_gate_levers_restore_the_canonical_constant_and_never_slow_expansion():
    base = _run("S11", "active", 80.0, seed=pj.ELIGIBLE_HOME_SEED)
    pl10 = _run("S11", "active", 80.0, lever="colony_gate_pl10", seed=pj.ELIGIBLE_HOME_SEED)
    pl5 = _run("S11", "active", 80.0, lever="colony_gate_pl5", seed=pj.ELIGIBLE_HOME_SEED)
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15
    assert base["final"]["worlds"] <= pl10["final"]["worlds"] <= pl5["final"]["worlds"] <= pj.TARGET_WORLDS
    for r in (base, pl10, pl5):
        assert r["invariants"]["ok"]


def test_auto_start_reserves_but_never_starts_something_unaffordable():
    base = _run("S1", "casual", 60.0, strategy="v2")
    auto = _run("S1", "casual", 60.0, strategy="v2", lever="auto_start")
    assert auto["invariants"]["ok"], auto["invariants"]  # no negative stock, no queue overflow, no level skip
    assert auto["lever_label"] == pj.LEVERS["auto_start"]
    # removing action-window latency cannot make a windowed player slower on the same rules
    b, a = _slim(base), _slim(auto)
    assert pb.income(a) >= pb.income(b) * 0.98
    # only the single reserved purchase starts early; the queue still idles between windows afterwards
    assert pb.ledger_shares(a).get("player_not_acting", 0.0) > 0.0
    assert pb.ledger_conservation_error(a) < 1e-6
    # a continuous player gets nothing from the lever (nothing to reserve ahead of)
    opt = _run("S1", "optimizer", 30.0, strategy="v2")
    opt_auto = _run("S1", "optimizer", 30.0, strategy="v2", lever="auto_start")
    assert pb.income(_slim(opt_auto)) == pytest.approx(pb.income(_slim(opt)), rel=0.05)
