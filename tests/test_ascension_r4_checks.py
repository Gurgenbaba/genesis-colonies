"""Robustness checks of the Ascension candidate r4 (measurement only): stress policies, AP compatibility, seeds, gates, analysis, suites."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.mine_evolution import nodebuster as nb  # noqa: E402
from game.planet_evolution import expansion_protocol as ep  # noqa: E402
from scripts import ascension_milestones_analysis as mi  # noqa: E402
from scripts import ascension_r4_checks as rc  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

C = mi.CANDIDATES


def _profiles(count: int, best: int) -> dict:
    state = {"ascension_count": count, "points_earned": 0, "points_unspent": 0, "best_depth": best, "last_depth": best}
    return {"metal_mine": {"state": state, "skills": {}}, "crystal_mine": {"state": dict(state), "skills": {}}}


# ---------------------------------------------------------------------------
# Stress policies
# ---------------------------------------------------------------------------


def test_stress_policies_parse():
    assert pj.parse_asc_policy("A200") == (True, 200, "A", 1)
    assert pj.parse_asc_policy("C200") == (True, 200, "C", 1)
    assert pj.parse_asc_policy("L200+1") == (True, 200, "L", 1)  # micro ladder
    assert pj.parse_asc_policy("O350") == (True, 350, "O", 1)
    for bad in ("A150", "A200x2", "A", "C", "C200x2", "A200+25"):
        with pytest.raises(ValueError):
            pj.parse_asc_policy(bad)
    for arm in rc.STRESS_ARMS_S1 + rc.STRESS_ARMS_S11 + rc.CASUAL_ARMS + rc.STRATEGY_ARMS + rc.GRID_ARMS:
        pj.parse_asc_policy(arm)


def test_crystal_only_and_button_masher_targets():
    def target(mode: str, key: str, count: int, best: int):
        sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc=mode)
        with pj.economy_curve("uni1"), pj.Sandbox() as sb:
            j = pj.Journey(sc, sb)
            w = copy.copy(j.worlds[0])
            w.asc_any = count > 0
            j.profiles = lambda _w: _profiles(count, best)  # type: ignore[assignment]
            return j.asc_target(w, key)

    assert target("C200", "crystal_mine", 0, 0) == 200 and target("C200", "metal_mine", 0, 0) is None and target("C200", "crystal_mine", 1, 200) is None
    assert target("A200", "metal_mine", 0, 0) == 200 and target("A200", "metal_mine", 50, 900) == 200  # always eligible, however often it has reset


def test_button_masher_has_a_weekly_cooldown_and_never_holds_a_mine():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="A200")
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j = pj.Journey(sc, sb)
        w = j.worlds[0]
        w.buildings["metal_mine"], w.buildings["crystal_mine"] = 250, 100
        calls = []

        def fake(ww, key):
            calls.append((round(j.t / pj.DAY), key))
            j.asc_last[(ww.idx, key)] = j.t / pj.DAY

        j.ascend = fake  # type: ignore[assignment]
        for day in (10, 12, 16, 17, 25):
            j.t = day * pj.DAY
            j.maybe_ascend(w)
        assert calls == [(10, "metal_mine"), (17, "metal_mine"), (25, "metal_mine")]  # not on day 12 / 16 (cooldown 7 days)
        assert j.asc_hold(w, "metal_mine", {"metal_mine": 250}) is False  # keeps building between presses


def test_gate_lever_pl12_patches_and_restores_the_gate():
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15
    with pj.lever_context("colony_gate_pl12"):
        assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 12 and pj.universe_key()[3] == 12
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15 and pj.universe_key()[3] == 15


# ---------------------------------------------------------------------------
# AP fairness and compatibility
# ---------------------------------------------------------------------------


def test_record_based_ap_are_never_more_generous_than_canonical_and_sum_to_the_record():
    with ar.rules_context(C["r4"]):
        f = nb.ascension_points_for_depth
        levels = list(range(0, 641, 5))
        record_rule = {(lv, pv): f(lv, previous_best=pv) for lv in levels for pv in levels}
    canonical = {(lv, pv): nb.ascension_points_for_depth(lv) for lv in levels for pv in levels}
    assert all(0 <= record_rule[k] <= canonical[k] for k in canonical)  # never more AP than the game awards today for the same reset, never negative
    # any sequence of resets from a fresh mine earns points_for_depth(highest level reached): farming cannot add to it
    seq = [200, 200, 250, 225, 250, 300, 300, 260, 400, 399, 400]
    with ar.rules_context(C["r4"]):
        total, record = 0, 0
        for lv in seq:
            total += nb.ascension_points_for_depth(lv, previous_best=record)
            record = max(record, lv)
    assert total == nb.ascension_points_for_depth(max(seq)) and total < sum(nb.ascension_points_for_depth(lv) for lv in seq)


def test_existing_ap_and_skills_survive_a_switch_to_record_based_ap_through_the_real_owner():
    """A mine that ascended three times at L200 under today's rules (3 AP earned, one skill bought) keeps everything when the record rule takes over."""
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="O200")
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j = pj.Journey(sc, sb)
        w = j.worlds[0]

        def ascend_at(level: int):
            buildings = dict(w.buildings)
            buildings["metal_mine"] = level
            sb.set_buildings(w.planet_id, buildings)
            w.buildings = buildings
            ok, reason, data = sb.ascend_mine(w.planet_id, "metal_mine")
            assert ok, reason
            return data

        for _ in range(3):  # canonical rules: 1 AP per reset at L200, no record needed
            assert ascend_at(200)["points_gain"] == 1
        ok, reason, _data = sb.buy_skill(w.planet_id, "metal_mine", "frugal_rebuild")
        assert ok, reason
        before = sb.asc_profiles(w.planet_id)["metal_mine"]
        assert before["state"]["points_earned"] == 3 and before["state"]["points_unspent"] == 2 and before["skills"]["frugal_rebuild"] == 1

        with ar.rules_context(C["r4"]):
            again = ascend_at(200)  # same depth as the record: nothing new
            deeper = ascend_at(250)  # a real record: the increment only
            after = sb.asc_profiles(w.planet_id)["metal_mine"]
        assert again["points_gain"] == 0 and deeper["points_gain"] == 2  # f(250) - f(200) = 3 - 1
        assert after["state"]["points_earned"] == 5 and after["state"]["points_unspent"] == 4  # nothing was taken away, nothing double counted
        assert after["skills"]["frugal_rebuild"] == 1 and after["state"]["best_depth"] == 250 and after["state"]["ascension_count"] == 5


def test_rank_score_uses_the_record_not_the_restart_level():
    """The ranking counts max(current level, best depth): a restart at 85 % of the record cannot lower or raise it."""
    profiles = _profiles(3, 300)
    assert nb.score_level(1, "metal_mine", 255, profiles=profiles) == 300 and nb.score_level(1, "metal_mine", 320, profiles=profiles) == 320
    with ar.rules_context(C["r4"]):
        assert nb.score_level(1, "metal_mine", 255, profiles=profiles) == 300
        assert nb.reset_start_level({}, 300) == 273  # 91 % of the record (tier 2); the score above does not depend on it


# ---------------------------------------------------------------------------
# The world seed does not move the economy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("topology,seeds,days", [("S1", (1, 3), 60.0), ("S11", (2, 13), 150.0)])
def test_world_seed_does_not_change_the_economy(topology, seeds, days):
    out = []
    for seed in seeds:
        res = pj.run_scenario(pj.Scenario(f"seed{seed}", topology, "active", "mid", "none", days, rng_seed=seed, strategy="v2", asc="never"))
        out.append((int(res["final"]["empire_metal_h"]), int(res["final"]["empire_crystal_h"]), int(res["final"].get("worlds", 1)), res["invariants"]["ok"]))
    assert out[0] == out[1] and out[0][3]  # identical to the last unit: seeds only pin the homeworld's coordinates and DNA


# ---------------------------------------------------------------------------
# Suites and analysis on synthetic series
# ---------------------------------------------------------------------------


def test_suites_are_well_formed():
    sizes = {}
    for suite in rc.SUITES:
        specs = rc.build_specs(suite)
        sizes[suite] = len(specs)
        assert len({s["sid"] for s in specs}) == len(specs)
        for s in specs:
            pj.parse_asc_policy(s["arm"])
            assert s["cand_params"]["key"] == s["cand"]
    assert sizes == {"casual": 12, "grid": 357, "stress": 63, "strategy": 57, "gates": 42}
    assert all(s["strategy"] == "v1" and s["variant"] == "v1" for s in rc.build_specs("strategy"))
    assert {s["lever"] for s in rc.build_specs("gates")} == {"colony_gate_pl10", "colony_gate_pl12"}
    assert all(s.get("lever", "none") in pj.LEVERS and s.get("strategy", "v2") in pj.STRATEGY_VERSIONS for suite in rc.SUITES for s in rc.build_specs(suite))  # the simulator accepts every scenario of every suite
    assert pj.LEVER_GATE_LEVEL["colony_gate_pl12"] == 12 and "colony_gate_pl12" in pj.LEVERS
    assert "colony_gate_pl12" in pj.ASCENSION_ONLY_LEVERS  # a side-study lever: it must not enlarge the bottleneck-report matrix
    assert all(s["diag"] and s["days"] == 1460.0 for s in rc.build_specs("casual"))


def test_grid_candidates_are_r4_with_one_change():
    grid = rc.grid_candidates()
    assert len(grid) == 13 + 4 and "g700_250" not in grid and "g700_300" not in grid  # r4 and r1 are not repeated
    base = ar.asdict(C["r4"])
    for key, cand in grid.items():
        diff = {k for k, v in ar.asdict(cand).items() if v != base[k]} - {"key", "label"}
        assert 1 <= len(diff) <= 2 and not cand.is_canon(), key
    assert all(c.restart_ceiling > 199 and c.ap_by_record for c in grid.values())


def _series(fn, days: int = 2190):
    return [(d, fn(d), 100 + d // 10, 0, 1) for d in range(0, days + 1, 5)]


def _res(style, arm, cand, fn, *, runs=(), days=2190.0, variant="", diag=None):
    series = _series(fn, int(days))
    cum = dict(ar.cumulative(series))
    snaps = {}
    for key in ar.CHECK_KEYS:
        d = int(float(key))
        if d <= days:
            snaps[key] = {"empire_metal_h": fn(d) * 0.6, "empire_crystal_h": fn(d) * 0.4, "produced": cum[d], "ascensions_total": len(runs), "ap_earned_total": len(runs), "ap_spent_total": 0, "skills": {}, "peak_depth_max": 100, "day": d}
    out = {"sid": f"{variant}-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": days, "snapshots": snaps, "series": series, "runs": list(runs), "skill_log": [], "invariants": {"ok": True, "violations": []}, "variant": variant}
    if diag:
        out["diag"] = diag
    return out


def _run(day, no, mine="metal_mine"):
    return {"world": 0, "mine": mine, "run": no, "day": float(day), "ap_gain": 1, "from_level": 200, "income_before_h": 1000.0, "income_after_h": 800.0, "income_recovered_days": 20.0, "rebuild_to_best_days": 30.0}


def test_stress_rows_compare_every_arm_with_the_best_sensible_policy():
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    bad = lambda d: 1000.0 if d < 400 else 600.0  # noqa: E731
    results = [_res(s, "never", "canon", lambda d: 1000.0) for s in rc.STYLES]
    for s in rc.STYLES:
        results += [_res(s, "O200", "x", good, runs=[_run(400, 1)]), _res(s, "A200", "x", bad, runs=[_run(400, 1)] * 40), _res(s, "C200", "x", good, runs=[_run(400, 1, "crystal_mine")])]
    rows = rc.stress_rows(results, "x", ("A200", "C200", "O350"))
    assert set(rows) == {"A200", "C200"} and rows["A200"]["worst_gap"] < -0.2 and rows["A200"]["resets"][0] == 40
    assert rows["C200"]["worst_gap"] == pytest.approx(0.0, abs=1e-9)  # as good as the best, not better


def test_margins_and_grid_summary():
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    x2 = lambda d: good(d) if d < 800 else (800.0 if d < 830 else 1180.0)  # noqa: E731
    x3 = lambda d: x2(d) if d < 1200 else (800.0 if d < 1230 else 1200.0)  # noqa: E731
    results = [_res(s, "never", "canon", lambda d: 1000.0) for s in rc.STYLES]
    for s in rc.STYLES:
        results += [_res(s, "O200", "r4", good, runs=[_run(400, 1)]), _res(s, "P200", "r4", good, runs=[_run(400, 1)]), _res(s, "L200+50x2", "r4", x2, runs=[_run(400, 1), _run(800, 2)]),
                    _res(s, "L200+50x3", "r4", x3, runs=[_run(400, 1), _run(800, 2), _run(1200, 3)]), _res(s, "O200x4", "r4", good, runs=[_run(400, 1)] * 4)]
    rows = rc.grid_rows(results, ["r4", "absent"])
    assert [r["cand"] for r in rows] == ["r4"] and rows[0]["criteria"]["all_pass"]
    m = rows[0]["margins"]
    assert m["k1_days"] > 200 and m["k2_gain"] > 0 and m["k4_ratio"] > 0
    summary = rc.grid_summary(rows)
    assert summary["passing"] == ["r4"] and summary["neighbours"] == 0


def test_gate_rows_use_the_variants_own_reference():
    quick = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    slow = lambda d: 1000.0 if d < 400 else (500.0 if d < 700 else 1200.0)  # noqa: E731
    results = [_res(s, "never", "canon", lambda d: 1000.0, variant="PL12") for s in rc.STYLES]
    for s in rc.STYLES:
        results += [_res(s, "O200", "r4", slow if s == "casual" else quick, runs=[_run(400, 1)], variant="PL12"), _res(s, "P200", "r4", quick, runs=[_run(400, 1)], variant="PL12")]
    row = rc.gate_rows(rc.by_variant(results, "PL12"), "r4")
    assert row["o200_slowest"] > 365 and row["p200_slowest"] < 365 and row["k1_best_start"] in ("fast", "ok")
    assert rc.by_variant(results, "PL10") == []


def test_casual_rows_describe_resets_and_spend():
    diag = lambda mines, research: {"365": {"spend_metal": {"mines": mines, "research": research}, "spend_crystal": {"mines": mines / 2, "research": research / 2}, "research_queue_busy_pct": 80.0, "colony_pipeline_sec": {"gate:colony_maturity_required": 1000.0}, "planet_queue_busy_pct": [50.0, 70.0]}}
    results = [_res("casual", "never", "canon", lambda d: 1000.0, variant="diag", diag=diag(10.0, 5.0))]
    results.append(_res("casual", "O200", "r4", lambda d: 1000.0 if d < 400 else 900.0, runs=[_run(400, 1), _run(450, 1, "crystal_mine")], variant="diag", diag=diag(14.0, 4.0)))
    rows = rc.casual_rows(results)
    assert set(rows) == {"never", "O200"} and rows["O200"]["resets"] == 2 and rows["O200"]["campaign_days"] == 50.0
    assert rows["O200"]["spend_mines_365"] == pytest.approx(21.0) and rows["never"]["spend_mines_365"] == pytest.approx(15.0)
    assert rows["O200"]["planet_queue_busy_365"] == pytest.approx(60.0) and rows["O200"]["metrics"]["first_reset_day"] == 400.0


def _criteria(slowest=300.0, gain2=0.03, gain3=0.01, min_style=0.0, median48=1.10, top=1.20, farm=True):
    return {"slowest_payback": slowest, "gain2": (gain2, min_style, gain2), "gain3": (gain3, gain3, gain3), "k3_no_farm": farm, "produced_1460": (median48, median48, median48), "max_style_ratio": top}


def test_threshold_sweep_shows_how_much_the_verdict_owes_to_the_limits():
    strict, weak_repeat, strong = _criteria(), _criteria(gain2=0.012), _criteria(top=1.27)
    assert rc.passes_with(strict) and not rc.passes_with(weak_repeat) and not rc.passes_with(strong)
    assert rc.passes_with(weak_repeat, k2_min_gain=0.01) and rc.passes_with(strong, k4_max=1.30)
    assert not rc.passes_with(_criteria(slowest=370.0)) and rc.passes_with(_criteria(slowest=370.0), k1_max=400.0)
    assert not rc.passes_with(_criteria(farm=False)) and not rc.passes_with(_criteria(median48=1.20)) and not rc.passes_with({})
    assert not rc.passes_with(_criteria(gain3=-0.01)) and not rc.passes_with(_criteria(min_style=-0.05))
    rows = [{"cand": "a", "criteria": strict}, {"cand": "b", "criteria": weak_repeat}, {"cand": "c", "criteria": strong}]
    sweep = rc.threshold_sweep(rows)
    assert sweep[(0.02, 1.25)] == ["a"] and sweep[(0.0, 1.25)] == ["a", "b"] and sweep[(0.02, 1.30)] == ["a", "c"] and sweep[(0.0, 1.30)] == ["a", "b", "c"]


def test_render_report_from_synthetic_suites(tmp_path):
    quick = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    x2 = lambda d: quick(d) if d < 800 else (800.0 if d < 830 else 1180.0)  # noqa: E731
    x3 = lambda d: x2(d) if d < 1200 else (800.0 if d < 1230 else 1200.0)  # noqa: E731
    never = [_res(s, "never", "canon", lambda d: 1000.0) for s in rc.STYLES]
    s1 = list(never)
    for s in rc.STYLES:
        s1 += [_res(s, "O200", "r4", quick, runs=[_run(400, 1)]), _res(s, "P200", "r4", quick, runs=[_run(400, 1)]), _res(s, "L200+50x2", "r4", x2, runs=[_run(400, 1), _run(800, 2)]),
               _res(s, "L200+50x3", "r4", x3, runs=[_run(400, 1), _run(800, 2), _run(1200, 3)]), _res(s, "O200x4", "r4", quick, runs=[_run(400, 1)] * 4)]
    stress = [dict(_res(s, "A200", "r4", lambda d: 1000.0 if d < 400 else 600.0, runs=[_run(400, 1)] * 30), topology="S1") for s in rc.STYLES]
    casual = [_res("casual", "never", "canon", lambda d: 1000.0, variant="diag"), _res("casual", "O200", "r4", quick, runs=[_run(400, 1), _run(450, 1, "crystal_mine")], variant="diag")]
    md = rc.render_markdown({"s1": s1, "s11": [], "grid": [], "stress": stress, "strategy": [dict(r, variant="v1") for r in s1], "gates": [], "casual": casual})
    for needle in ("## 2. Player strategy", "## 4. Farming stress", "`A200`", "## 5. Why is the casual", "## 6. Limits"):
        assert needle in md
    out = tmp_path / "r.md"
    ar_dir = tmp_path
    (ar_dir / "artifacts" / "ascension_milestones").mkdir(parents=True)
    (ar_dir / "artifacts" / "ascension_milestones" / "s1.json").write_text(json.dumps({"results": s1}), encoding="utf-8")
    loaded = rc.load_all(ar_dir)
    assert len(loaded["s1"]) == len(s1) and loaded["grid"] == [] and loaded["s11"] == []
    out.write_text(rc.render_markdown(loaded), encoding="utf-8")
    assert "Robustness checks of Ascension candidate r4" in out.read_text(encoding="utf-8")
