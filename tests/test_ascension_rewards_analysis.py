"""Ascension reward candidates (sandbox rule patches, measurement only): rules, policies, metrics, criteria, report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.mine_evolution import nodebuster as nb  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

PATCHED = ("ascension_points_for_depth", "rebuild_cost_bps", "reset_start_level", "rebuild_production_multiplier_for", "production_multiplier_for")


def _profiles(count: int, best: int, skills=None) -> dict:
    state = {"ascension_count": count, "points_earned": 0, "points_unspent": 0, "best_depth": best, "last_depth": best}
    return {"metal_mine": {"state": state, "skills": dict(skills or {})}, "crystal_mine": {"state": dict(state), "skills": {}}}


# ---------------------------------------------------------------------------
# The sandbox patch
# ---------------------------------------------------------------------------


def test_min_level_constant_mirrors_the_owner():
    assert ar.ASCENSION_MIN_LEVEL == nb.ASCENSION_MIN_LEVEL == 200


def test_canonical_candidate_patches_nothing_and_every_other_one_restores():
    before = {n: getattr(nb, n) for n in PATCHED}
    with ar.rules_context(ar.CANDIDATES["canon"]):
        assert {n: getattr(nb, n) for n in PATCHED} == before
    for key, cand in ar.CANDIDATES.items():
        if cand.is_canon():
            continue
        with ar.rules_context(cand):
            assert any(getattr(nb, n) is not before[n] for n in PATCHED), key
        assert {n: getattr(nb, n) for n in PATCHED} == before, key
    with pytest.raises(RuntimeError):
        with ar.rules_context(ar.CANDIDATES["fast_p"]):
            raise RuntimeError("scenario failed")
    assert {n: getattr(nb, n) for n in PATCHED} == before


def test_ap_rules_of_the_candidates():
    canon = [nb.ascension_points_for_depth(d) for d in (199, 200, 225, 250, 300)]
    assert canon == [0, 1, 2, 3, 6]
    with ar.rules_context(ar.CANDIDATES["ap3"]):
        assert [nb.ascension_points_for_depth(d) for d in (199, 200, 225, 250, 300)] == [0, 3, 4, 5, 8]
    with ar.rules_context(ar.CANDIDATES["ap_steep"]):
        assert [nb.ascension_points_for_depth(d) for d in (199, 200, 210, 250, 300)] == [0, 1, 2, 6, 12]


def test_rebuild_cost_start_level_and_floor():
    with ar.rules_context(ar.CANDIDATES["cost40"]):
        assert nb.rebuild_cost_bps({}) == 4000
        assert nb.rebuild_cost_bps({"frugal_rebuild": 1}) == 3500  # skills can no longer go below the canonical floor
    assert nb.rebuild_cost_bps({}) == 10000 and nb.rebuild_cost_bps({"frugal_rebuild": 2}) == 8900
    with ar.rules_context(ar.CANDIDATES["restart75"]):
        assert nb.reset_start_level({}, 200) == 150
        assert nb.reset_start_level({}, 400) == 199  # always below the activation level
        assert nb.reset_start_level({"reconstruction": 10}, 200) == 150  # the larger of skill and floor
        assert nb.reset_start_level({"reconstruction": 10}, 100) == 120
    assert nb.reset_start_level({}, 200) == 0


def test_fading_surge_is_zero_at_the_record_and_never_a_cliff():
    cand = ar.CANDIDATES["fade100"]
    prof = _profiles(1, 200)
    with ar.rules_context(cand):
        vals = [nb.rebuild_production_multiplier_for(1, "metal_mine", lvl, profiles=prof) for lvl in (0, 50, 100, 150, 199, 200, 201)]
    assert vals[0] == pytest.approx(2.0) and vals[2] == pytest.approx(1.5)
    assert vals == sorted(vals, reverse=True)  # fades monotonically
    assert vals[-2] == 1.0 and vals[-1] == 1.0  # nothing at or beyond the best depth
    # the climb never meets a drop in output: production grows faster than the surge fades (checked on the real curve in the sim)
    with ar.rules_context(cand):
        assert nb.rebuild_production_multiplier_for(1, "metal_mine", 100, profiles=_profiles(0, 200)) == 1.0  # no Ascension yet
        assert nb.rebuild_production_multiplier_for(1, "fuel_cell_plant", 100, profiles=prof) == 1.0  # not a production mine


def test_fading_surge_keeps_mine_output_strictly_increasing_on_the_real_curve():
    """Output x surge must still grow with every level - an abrupt end of the surge would make the next level reduce output."""
    from game import production_formula as pf

    prof = _profiles(1, 200)
    for key in ("fade100", "soft", "soft_p"):
        with pj.economy_curve("uni1"), ar.rules_context(ar.CANDIDATES[key]):
            outputs = [float(pf.mine_output_decimal("metal", lvl)) * nb.rebuild_production_multiplier_for(1, "metal_mine", lvl, profiles=prof) for lvl in range(12, 260)]
        assert all(b > a for a, b in zip(outputs, outputs[1:])), key
    # the canonical Legacy Reconstruction surge (+100 % until the record, then nothing) is exactly the cliff the candidates avoid
    prof_legacy = _profiles(1, 200, {"legacy_reconstruction": 1})
    with pj.economy_curve("uni1"):
        at_record = float(pf.mine_output_decimal("metal", 200)) * nb.rebuild_production_multiplier_for(1, "metal_mine", 200, profiles=prof_legacy)
        above = float(pf.mine_output_decimal("metal", 201)) * nb.rebuild_production_multiplier_for(1, "metal_mine", 201, profiles=prof_legacy)
        window = float(pf.mine_output_decimal("metal", 201)) * nb.rebuild_production_multiplier_for(1, "metal_mine", 201, profiles=_profiles(1, 200, {"legacy_reconstruction": 1, "breakthrough_window": 1}))
    assert above < at_record < 2.0 * above  # one level above the record the canonical +100 % surge is gone and output falls by ~half
    assert window > at_record  # the Breakthrough window removes the cliff for 50 levels


def test_prestige_is_capped_and_per_mine():
    cand = ar.CANDIDATES["prestige"]
    with ar.rules_context(cand):
        mult = [nb.production_multiplier_for(1, "metal_mine", profiles=_profiles(n, 200)) for n in (0, 1, 2, 3, 4, 10)]
    assert mult == pytest.approx([1.0, 1.05, 1.10, 1.15, 1.15, 1.15])
    assert cand.prestige_max_bps() == 1500
    with ar.rules_context(cand):  # skills multiply on top, the prestige part itself stays bounded
        both = nb.production_multiplier_for(1, "metal_mine", profiles=_profiles(3, 200, {"deep_yield": 4}))
    assert both == pytest.approx(1.10 * 1.15)


def test_strong_first_yield_rank_candidate():
    with ar.rules_context(ar.CANDIDATES["rank1_yield"]):
        assert [nb.production_bonus_bps({"deep_yield": r}) for r in range(0, 4)] == [0, 1000, 1250, 1500]
        assert nb.skill_point_cost("deep_yield", 0) == 1
        assert nb.skill_point_cost("deep_yield", 1) == 2 and nb.skill_point_cost("frugal_rebuild", 0) == 1  # only the first rank is cheaper
        assert nb.production_bonus_bps({"deep_yield": 1, "overdrive": 1}) == 1500  # overdrive still adds its own +5 %
        assert nb.production_multiplier({"deep_yield": 1}) == pytest.approx(1.10)
    assert [nb.production_bonus_bps({"deep_yield": r}) for r in range(0, 3)] == [0, 250, 500] and nb.skill_point_cost("deep_yield", 0) == 2


def test_candidates_are_well_formed():
    assert ar.CANDIDATES["canon"].is_canon() and sum(c.is_canon() for c in ar.CANDIDATES.values()) == 1
    for cand in ar.CANDIDATES.values():
        assert cand.ap_order in pj.ASC_SKILL_ORDERS
        assert cand.key in ar.CANDIDATES and cand.label


def test_every_candidate_is_bounded():
    for cand in ar.CANDIDATES.values():
        assert cand.prestige_max_bps() <= 3000  # at most +30 % from prestige
        assert 0 <= cand.restart_pct <= 90 and cand.rebuild_cost_bps >= 3500 or cand.is_canon()


# ---------------------------------------------------------------------------
# The new policies of the simulator
# ---------------------------------------------------------------------------


def test_policy_parsing():
    assert pj.parse_asc_policy("never") == (True, None, "", 0)
    assert pj.parse_asc_policy("legacy") == (False, None, "", 0)
    assert pj.parse_asc_policy("T250") == (True, 250, "T", 0)
    assert pj.parse_asc_policy("O200") == (True, 200, "O", 1)  # one reset per mine
    assert pj.parse_asc_policy("L200+25") == (True, 200, "L", 25)
    assert pj.parse_asc_policy("O200x4") == (True, 200, "O", 4)  # farm: four resets per mine, then keep building
    assert pj.parse_asc_mode("O300") == (True, 300)  # the older two-value API still works
    for bad in ("O150", "L200", "L200+0", "L200+x", "X200", "O", "", "O200x0", "O200x", "O200xa"):
        with pytest.raises(ValueError):
            pj.parse_asc_policy(bad)
    for arm in ar.ARMS:
        pj.parse_asc_policy(arm)


def _journey(mode: str):
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc=mode)
    return sc


def test_asc_target_per_policy():
    def target(mode: str, count: int, best: int) -> object:
        with pj.economy_curve("uni1"), pj.Sandbox() as sb:
            j = pj.Journey(_journey(mode), sb)
            w = j.worlds[0]
            w.asc_any = count > 0
            j.profiles = lambda _w: _profiles(count, best)  # type: ignore[assignment]
            return j.asc_target(w, "metal_mine")

    assert target("T200", 0, 0) == 200 and target("T200", 3, 200) == 200  # treadmill: always the same depth
    assert target("O200", 0, 0) == 200 and target("O200", 1, 200) is None  # once per mine
    assert target("O200x4", 3, 200) == 200 and target("O200x4", 4, 200) is None  # four resets per mine
    assert target("L200+25", 0, 0) == 200 and target("L200+25", 1, 200) == 225 and target("L200+25", 2, 260) == 285  # must beat the record
    assert target("never", 0, 0) is None


def test_one_shot_policy_resets_each_mine_exactly_once_and_ap_invariants_hold_under_a_candidate():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 520.0, strategy="v2", asc="O200")
    with ar.rules_context(ar.CANDIDATES["ap3"]):
        res = pj.run_scenario(sc)
    runs = res["ascension_runs"]
    assert runs and res["invariants"]["ok"], res["invariants"]
    per_mine = {}
    for r in runs:
        per_mine[(r["world"], r["mine"])] = per_mine.get((r["world"], r["mine"]), 0) + 1
    assert set(per_mine.values()) == {1}  # no treadmill
    assert all(int(r["ap_gain"]) == 3 for r in runs)  # the candidate's award, accepted by the invariant check
    assert nb.ascension_points_for_depth(200) == 1  # and the owner is restored


# ---------------------------------------------------------------------------
# Metrics on synthetic series
# ---------------------------------------------------------------------------


def _series(fn, days: int = 2190):
    return [(d, fn(d), 100 + d // 10, 0) for d in range(0, days + 1, 5)]


def _res(style, arm, cand, fn, *, runs=(), skill_log=(), days=2190.0):
    series = _series(fn, int(days))
    cum = dict(ar.cumulative(series))
    snaps = {}
    for key in ar.CHECK_KEYS:
        d = int(float(key))
        if d <= days:
            snaps[key] = {
                "empire_metal_h": fn(d) * 0.6, "empire_crystal_h": fn(d) * 0.4, "produced": cum[d], "ascensions_total": len(runs), "ap_earned_total": sum(r["ap_gain"] for r in runs),
                "ap_spent_total": 0, "skills": {}, "peak_depth_max": 100, "day": d,
            }
    return {"sid": f"S1-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": days, "snapshots": snaps, "series": series, "runs": list(runs), "skill_log": list(skill_log), "invariants": {"ok": True, "violations": []}}


def test_cumulative_and_ratio_helpers():
    cum = ar.cumulative([(0, 100.0), (5, 100.0), (10, 200.0)])
    assert cum[0] == (0, 0.0) and cum[1][1] == pytest.approx(100.0 * 24 * 5) and cum[2][1] == pytest.approx(100.0 * 24 * 5 + 150.0 * 24 * 5)
    a, b = [(0, 50.0), (5, 100.0)], [(0, 100.0), (5, 100.0), (10, 100.0)]
    assert ar.ratio_series(a, b) == [(0, 0.5), (5, 1.0)]


def test_sustained_first_reach_worst_and_agg():
    ratios = [(0, 1.0), (10, 0.5), (20, 0.8), (30, 1.02), (40, 0.98), (50, 1.05), (60, 1.1)]
    assert ar.first_reach(ratios, 10, 1.0) == 30
    assert ar.sustained_from(ratios, 10, 1.0) == 50  # day 40 dips below again
    assert ar.sustained_from(ratios, 10, 1.2) is None
    assert ar.worst_after(ratios, 5, 40) == (0.5, 10)
    assert ar.worst_after(ratios, 100, 40) == (None, None)
    assert ar.ratio_at_day(ratios, 22) == 0.8 and ar.ratio_at_day(ratios, 200) is None
    assert ar.agg([1.0, None, 3.0, 2.0]) == (2.0, 1.0, 3.0) and ar.agg([None]) is None


def _style_set(cand: str, reset_fn, guard_fn, cliff: float = 0.8, recovered: float = 20.0):
    out = []
    run = {"day": 400.0, "ap_gain": 3, "mine": "metal_mine", "world": 0, "income_before_h": 1000.0, "income_after_h": 1000.0 * cliff, "income_recovered_days": recovered}
    for style in ar.STYLES:
        out.append(_res(style, "O200", cand, reset_fn, runs=[run], skill_log=[{"day": 400.0, "skill": "frugal_rebuild", "rank": 1}]))
        for arm in ("T200", "L200+25"):
            out.append(_res(style, arm, cand, guard_fn, runs=[{"day": 400.0, "ap_gain": 3}] * 9))
    return out


def _never():
    return [_res(style, "never", "canon", lambda d: 1000.0) for style in ar.STYLES]


def test_metrics_and_criteria_on_a_good_and_a_bad_candidate():
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1050.0)  # noqa: E731
    bad = lambda d: 1000.0 if d < 400 else 600.0  # noqa: E731
    results = _never() + _style_set("good", good, lambda d: 1000.0) + _style_set("bad", bad, lambda d: 500.0, cliff=0.6, recovered=200.0)
    m = ar.metrics(ar.find(results, "active", "O200", "good"), ar.reference(results, "active"))
    assert m["first_reset_day"] == 400.0
    assert m["worst_ratio"] == pytest.approx(0.8) and m["cliff"] == pytest.approx(0.8) and m["recovered_days"] == 20.0
    assert 100 <= m["payback_day"] <= 200 and m["income_breakeven_day"] <= 40
    assert m["real_advantage_day"] is None  # +5 % is not yet a "real" (>= +10 %) advantage
    strong = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1150.0)  # noqa: E731
    sres = _never() + _style_set("strong", strong, lambda d: 1000.0)
    sm = ar.metrics(ar.find(sres, "active", "O200", "strong"), ar.reference(sres, "active"))
    assert sm["real_advantage_day"] == pytest.approx(35.0, abs=10) and sm["payback_day"] < m["payback_day"]
    assert m["produced_1460"] == pytest.approx(1.0, abs=0.1) and m["ap"]["first_run_ap"] == 3 and m["ap"]["first_skill_day"] == 400.0
    c = ar.criteria(results, "good")
    assert c["c1_valuable"] and c["c2_payback"] == "good" and c["c3_never_legit"] and c["guard_ok"] is True
    b = ar.criteria(results, "bad")
    assert not b["c1_valuable"] and b["c2_payback"] == "no" and not b["c3_never_legit"]
    assert ar.metrics(ar.find(results, "active", "T200", "good"), ar.reference(results, "active"))["payback_day"] is not None


def test_farming_metrics_detect_whether_extra_resets_pay():
    base = lambda d: 1000.0  # noqa: E731
    pays = lambda d: 1000.0 * (1.0 + 0.1 * (d > 600))  # noqa: E731  more resets -> +10 %
    results = _never()
    for style in ar.STYLES:
        results += [
            _res(style, "O200", "farm", base, runs=[{"day": 400.0, "ap_gain": 1}]),
            _res(style, "O200x4", "farm", pays, runs=[{"day": 400.0, "ap_gain": 1}] * 4),
            _res(style, "O200x8", "farm", pays, runs=[{"day": 400.0, "ap_gain": 1}] * 8),
            _res(style, "O200", "flat", base, runs=[{"day": 400.0, "ap_gain": 1}]),
            _res(style, "O200x4", "flat", base, runs=[{"day": 400.0, "ap_gain": 1}] * 4),
        ]
    f = ar.farming_metrics(results, "farm")
    assert f["farming_pays"] is True and f["extra_reset_gain"] > 0.03 and f["arms"]["O200x8"]["2190"][0] > f["arms"]["O200"]["2190"][0]
    flat = ar.farming_metrics(results, "flat")
    assert flat["farming_pays"] is False and abs(flat["extra_reset_gain"]) < 1e-9
    assert ar.farming_metrics(results, "absent")["farming_pays"] is None


def test_farming_that_pays_for_one_style_fails_the_guard_even_if_the_median_does_not():
    base = lambda d: 1000.0  # noqa: E731
    boost = lambda d: 1000.0 * (1.0 + 0.4 * (d > 600))  # noqa: E731
    results = _never() + _style_set("casual_farm", lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1050.0), lambda d: 1000.0)
    for style in ar.STYLES:
        results += [
            _res(style, "O200x4", "casual_farm", boost if style == "casual" else base, runs=[{"day": 400.0, "ap_gain": 1}] * 4),
            _res(style, "O200x8", "casual_farm", base, runs=[{"day": 400.0, "ap_gain": 1}] * 8),
        ]
    f = ar.farming_metrics(results, "casual_farm")
    assert f["pays_for"] == ["casual"] and f["farming_pays"] is True and f["max_style_ratio"] > ar.STYLE_MAX
    c = ar.criteria(results, "casual_farm")
    assert c["guard_ok"] is False and c["all_pass"] is False and c["c1_valuable"] and c["c2_payback"] == "good"


def test_all_pass_requires_every_criterion():
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1050.0)  # noqa: E731
    results = _never() + _style_set("ok", good, lambda d: 1000.0)
    c = ar.criteria(results, "ok")
    assert c["all_pass"] is True and c["max_style_ratio"] <= ar.STYLE_MAX
    too_strong = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1400.0)  # noqa: E731
    results = _never() + _style_set("strong", too_strong, lambda d: 1000.0)
    c = ar.criteria(results, "strong")
    assert c["c3_never_legit"] is False and c["all_pass"] is False  # `never` would no longer be a legitimate choice


def test_thresholds_are_defined_in_code_not_in_the_data():
    th = ar.thresholds()
    assert th["c1_cliff"] == pytest.approx(0.667) and th["style_max"] == 1.25 and th["c3"] == [0.85, 1.15]
    assert ar.meta_block([{"days": 2190.0}])["thresholds"] == th


def test_merge_results_replaces_by_scenario_id():
    old = [{"sid": "a", "v": 1}, {"sid": "b", "v": 1}]
    new = [{"sid": "b", "v": 2}, {"sid": "c", "v": 2}]
    merged = ar.merge_results(old, new)
    assert [r["sid"] for r in merged] == ["a", "b", "c"] and {r["sid"]: r["v"] for r in merged} == {"a": 1, "b": 2, "c": 2}


def test_guard_flags_an_unbounded_treadmill():
    runaway = lambda d: 1000.0 * (1.0 + max(0, d - 400) / 800.0)  # noqa: E731  grows without bound
    results = _never() + _style_set("runaway", lambda d: 1000.0, runaway)
    g = ar.guard_metrics(results, "runaway")
    assert g["ok"] is False and g["arms"]["T200"]["ok"] is False


# ---------------------------------------------------------------------------
# Matrix and report plumbing
# ---------------------------------------------------------------------------


def test_matrix_shape():
    specs = ar.build_matrix()
    assert len(specs) == 3 * (1 + len(ar.CANDIDATES) * len(ar.RESET_ARMS)) == 444
    assert len({s["sid"] for s in specs}) == len(specs)
    quick = ar.build_matrix(730.0, quick=True)
    assert len(quick) == 1 + len(ar.CANDIDATES) * len(ar.RESET_ARMS) and {s["style"] for s in quick} == {"active"}
    assert {s["arm"] for s in specs} == set(ar.ARMS)


def test_render_and_cli_roundtrip(tmp_path):
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1050.0)  # noqa: E731
    results = _never() + _style_set("good", good, lambda d: 1000.0)
    specs = ar.build_matrix(candidates=("good",)) if False else [{"days": 2190.0}]
    data = {"meta": ar.meta_block(specs), "results": results}
    md = ar.render_markdown(data)
    assert "## 2. The first reset" in md and "## 5. Design criteria" in md and "## 6. Guard" in md and "none violated" in md
    src, out = tmp_path / "rw.json", tmp_path / "rw.md"
    src.write_text(json.dumps(data), encoding="utf-8")
    assert ar.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == md.strip()
