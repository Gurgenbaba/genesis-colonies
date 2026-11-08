"""Ascension milestones (First Awakening, record tiers, repeat resets): rule patches, policies, metrics, acceptance, report (measurement only)."""

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
from scripts import ascension_milestones_analysis as mi  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402

C = mi.CANDIDATES


def _profiles(count: int, best: int, skills=None) -> dict:
    state = {"ascension_count": count, "points_earned": 0, "points_unspent": 0, "best_depth": best, "last_depth": best}
    return {"metal_mine": {"state": state, "skills": dict(skills or {})}, "crystal_mine": {"state": dict(state), "skills": {}}}


# ---------------------------------------------------------------------------
# Rule patches
# ---------------------------------------------------------------------------


def test_canonical_stays_canonical_and_every_new_candidate_is_a_change():
    assert C["canon"].is_canon()
    for key in mi.ORDER:
        if key != "canon":
            assert not C[key].is_canon(), key
    assert set(mi.REFS) <= set(C) and len(C) == len(mi.ORDER) == 35


def test_record_tier_follows_the_best_depth_and_is_capped():
    c = C["c_both"]  # step 50, cap 3
    assert [c.tier_of(d) for d in (0, 199, 200, 249, 250, 299, 300, 349, 350, 1000)] == [0, 0, 0, 0, 1, 1, 2, 2, 3, 3]
    assert C["c_both25"].tier_of(275) == 3 and C["c_both25"].tier_of(225) == 1
    assert C["aw15"].tier_of(500) == 0  # no tiers: always 0


def test_restart_level_grows_with_the_record_tier_and_stays_below_l200():
    with ar.rules_context(C["c_both"]):
        starts = [nb.reset_start_level({}, d) for d in (200, 249, 250, 300, 350, 400, 1000)]
    assert starts == [150, 186, 197, 199, 199, 199, 199]  # 75 % (tier 0), 75 % of 249, 79 % of 250, 83 % of 300 -> clamped below L200
    with ar.rules_context(C["aw15"]):
        assert nb.reset_start_level({}, 300) == 199 and nb.reset_start_level({}, 200) == 150
    assert nb.reset_start_level({}, 300) == 0  # restored


def test_awakening_applies_once_a_mine_has_ascended_and_never_stacks():
    prof = lambda count, best: _profiles(count, best)  # noqa: E731
    with ar.rules_context(C["aw15"]):
        assert nb.production_multiplier_for(1, "metal_mine", profiles=prof(0, 0)) == pytest.approx(1.0)  # not ascended yet
        one = nb.production_multiplier_for(1, "metal_mine", profiles=prof(1, 200))
        many = nb.production_multiplier_for(1, "metal_mine", profiles=prof(9, 200))
        deep = nb.production_multiplier_for(1, "metal_mine", profiles=prof(1, 900))
    assert one == pytest.approx(1.15) and many == pytest.approx(1.15) and deep == pytest.approx(1.15)  # not by count, not by depth (no tiers)


def test_tier_output_depends_on_the_record_not_on_the_number_of_resets():
    prof = lambda count, best: _profiles(count, best)  # noqa: E731
    with ar.rules_context(C["c_yield"]):  # awakening 15 % + 5 % per tier, max 3
        m = lambda count, best: nb.production_multiplier_for(1, "metal_mine", profiles=prof(count, best))  # noqa: E731
        assert m(1, 200) == pytest.approx(1.15)
        assert m(50, 200) == pytest.approx(1.15)  # a farm at the same depth earns nothing more
        assert m(2, 250) == pytest.approx(1.20) and m(3, 300) == pytest.approx(1.25) and m(4, 350) == pytest.approx(1.30)
        assert m(9, 5000) == pytest.approx(1.30)  # capped


def test_rebuild_cost_tiers_apply_inside_the_window_only_and_respect_the_floor():
    def bps(candidate, count, best, target, skills=None):
        with ar.rules_context(candidate):
            return nb.rebuild_bps_for_target(1, "metal_mine", target, profiles=_profiles(count, best, skills))

    c = C["c_rebuild"]  # cost x0.40, -5 pp per tier, floor 2500
    assert bps(c, 1, 200, 150)[0] == 4000 and bps(c, 2, 250, 200)[0] == 3500 and bps(c, 3, 300, 200)[0] == 3000 and bps(c, 4, 350, 200)[0] == 2500
    assert bps(c, 9, 900, 200)[0] == 2500  # floor
    assert bps(c, 2, 250, 251)[0] == 10000  # above the record: nothing is discounted (canonical)
    assert bps(c, 0, 0, 150)[0] == 10000  # never ascended
    assert bps(C["rank1_fast"], 3, 300, 200)[0] == 4000  # no tiers in the reference
    assert nb.rebuild_bps_for_target(1, "metal_mine", 200, profiles=_profiles(2, 250))[0] == 10000  # canonical rules (patch restored): a rebuild without skills is not discounted


def test_rebuild_time_tiers_and_floors():
    def bps(candidate, count, best, target):
        with ar.rules_context(candidate):
            return nb.rebuild_bps_for_target(1, "metal_mine", target, profiles=_profiles(count, best))

    m1 = C["m1"]  # cost x0.30 / time x0.70, -6 pp cost and -10 pp time per tier, floors 1000 / 2000
    assert bps(m1, 1, 200, 150) == (3000, 7000) and bps(m1, 2, 250, 200) == (2400, 6000) and bps(m1, 3, 300, 200) == (1800, 5000) and bps(m1, 4, 350, 200) == (1200, 4000)
    assert bps(m1, 9, 9000, 200) == (1200, 4000)  # capped at three tiers
    assert bps(m1, 2, 250, 260) == (10000, 10000)  # above the record
    with ar.rules_context(m1):
        assert nb.rebuild_time_bps({}) == 7000 and nb.rebuild_time_bps({"rapid_rebuild": 10}) == 2000  # the candidate's own floor
    assert nb.rebuild_time_bps({}) == 10000 and nb.rebuild_time_bps({"rapid_rebuild": 10}) == 3500  # canonical, restored


def test_ap_by_record_rule_function():
    with ar.rules_context(C["m1"]):
        f = nb.ascension_points_for_depth
        assert f(200) == 1 and f(250) == 3 and f(300) == 6  # a first reset (record 0): the full award
        assert f(250, previous_best=200) == 2 and f(300, previous_best=250) == 3 and f(300, previous_best=200) == 5  # increments: the total only depends on the record
        assert f(250, previous_best=250) == 0 and f(200, previous_best=300) == 0 and f(199, previous_best=0) == 0  # no record, no points
    assert nb.ascension_points_for_depth(250) == 3
    assert pj.expected_ascension_points(250, 200) == 3  # canonical: independent of the record
    with ar.rules_context(C["m1"]):
        assert pj.expected_ascension_points(250, 200) == 2


def test_ap_by_record_through_the_real_owner_in_a_sandbox():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="O200")
    seen = []
    with pj.economy_curve("uni1"), pj.Sandbox() as sb, ar.rules_context(C["m1"]):
        j = pj.Journey(sc, sb)
        w = j.worlds[0]
        for level in (200, 250, 250, 200, 300, 260):
            buildings = dict(w.buildings)
            buildings["metal_mine"] = level
            sb.set_buildings(w.planet_id, buildings)
            w.buildings = buildings
            ok, reason, data = sb.ascend_mine(w.planet_id, "metal_mine")
            assert ok, reason
            seen.append((int(data["points_gain"]), int(data["level"]), int(data["best_depth"])))
    assert [g for g, _l, _b in seen] == [1, 2, 0, 0, 3, 0]  # a farm at the same depth earns nothing; the sum is points_for_depth(best) = 6
    assert [b for _g, _l, b in seen] == [200, 250, 250, 250, 300, 300]
    assert seen[0][1] == 170 and all(level == 199 for _g, level, _b in seen[1:])  # restart 85 % of the record, always below L200


def test_restart_ceiling_keeps_a_share_of_a_deep_record():
    with ar.rules_context(C["n1"]):  # keep 85 % of the record, no ceiling
        starts = [nb.reset_start_level({}, d) for d in (200, 250, 300, 400)]
    assert starts == [170, 212, 255, 340]  # a deeper record keeps a deeper restart (canonical: always below L200)
    with ar.rules_context(C["n3"]):  # +2 pp per tier
        assert nb.reset_start_level({}, 300) == 267 and nb.reset_start_level({}, 250) == 217  # 89 % of 300 (tier 2), 87 % of 250 (tier 1)
    with ar.rules_context(C["m1"]):
        assert nb.reset_start_level({}, 300) == 199  # the canonical ceiling still applies to the older candidates
    assert not C["n1"].is_canon() and C["n1"].restart_ceiling > 199 and C["m1"].restart_ceiling == 199


def test_cost_floor_is_part_of_the_candidate():
    with ar.rules_context(C["aw15_soft"]):
        assert nb.rebuild_cost_bps({}) == 3000
        assert nb.rebuild_cost_bps({"frugal_rebuild": 10}) == 2500
    with ar.rules_context(C["rank1_fast"]):
        assert nb.rebuild_cost_bps({"frugal_rebuild": 10}) == 3500  # the canonical floor for the old candidates
    assert nb.rebuild_cost_bps({}) == 10000


def test_all_patches_are_restored():
    names = ("ascension_points_for_depth", "rebuild_cost_bps", "reset_start_level", "rebuild_production_multiplier_for", "production_multiplier_for", "production_bonus_bps", "skill_point_cost", "rebuild_bps_for_target", "rebuild_time_bps", "ascend_mine")
    saved = {n: getattr(nb, n) for n in names}
    for key in mi.ORDER:
        with ar.rules_context(C[key]):
            pass
        assert {n: getattr(nb, n) for n in names} == saved, key


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_selective_and_capped_policies_parse():
    assert pj.parse_asc_policy("P200") == (True, 200, "P", 1)
    assert pj.parse_asc_policy("H200") == (True, 200, "H", 1)
    assert pj.parse_asc_policy("P200x2") == (True, 200, "P", 2)
    assert pj.parse_asc_policy("L200+50x3") == (True, 200, "L", 50)
    assert pj.parse_asc_cap("L200+50x3") == 3 and pj.parse_asc_cap("L200+50") is None and pj.parse_asc_cap("O200x4") is None and pj.parse_asc_cap("never") is None
    for bad in ("L200+50x0", "L200+50x", "L200x3", "L200+x3", "H200+25", "P", "G200x2", "M200x2"):
        with pytest.raises(ValueError):
            pj.parse_asc_policy(bad)
    for arms in mi.ARMS_BY_TOPOLOGY.values():
        for arm in arms:
            pj.parse_asc_policy(arm)


def test_asc_target_of_selective_and_capped_policies():
    def target(mode: str, key: str, count: int, best: int, idx: int = 0):
        sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc=mode)
        with pj.economy_curve("uni1"), pj.Sandbox() as sb:
            j = pj.Journey(sc, sb)
            w = copy.copy(j.worlds[0])
            w.idx = idx
            w.asc_any = count > 0
            j.profiles = lambda _w: _profiles(count, best)  # type: ignore[assignment]
            return j.asc_target(w, key)

    assert target("P200", "metal_mine", 0, 0) == 200 and target("P200", "crystal_mine", 0, 0) is None  # only the metal mine
    assert target("P200", "metal_mine", 1, 200) is None
    assert target("H200", "metal_mine", 0, 0, idx=0) == 200 and target("H200", "metal_mine", 0, 0, idx=3) is None  # only the homeworld
    assert target("L200+50x3", "metal_mine", 0, 0) == 200 and target("L200+50x3", "metal_mine", 1, 200) == 250 and target("L200+50x3", "metal_mine", 2, 255) == 305
    assert target("L200+50x3", "metal_mine", 3, 310) is None  # the cap: three resets per mine
    assert target("L200+50", "metal_mine", 9, 600) == 650  # uncapped ladder


# ---------------------------------------------------------------------------
# Metrics and acceptance on synthetic results
# ---------------------------------------------------------------------------


def _series(fn, days: int = 2190):
    return [(d, fn(d), 100 + d // 10, 0, 1) for d in range(0, days + 1, 5)]


def _res(style, arm, cand, fn, *, runs=(), days=2190.0):
    series = _series(fn, int(days))
    cum = dict(ar.cumulative(series))
    snaps = {}
    for key in ar.CHECK_KEYS:
        d = int(float(key))
        if d <= days:
            snaps[key] = {"empire_metal_h": fn(d) * 0.6, "empire_crystal_h": fn(d) * 0.4, "produced": cum[d], "ascensions_total": len(runs), "ap_earned_total": 1, "ap_spent_total": 0, "skills": {}, "peak_depth_max": 100, "day": d}
    return {"sid": f"S1-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": days, "snapshots": snaps, "series": series, "runs": list(runs), "skill_log": [], "invariants": {"ok": True, "violations": []}}


def _run(day, no):
    return {"world": 0, "mine": "metal_mine", "run": no, "day": float(day), "ap_gain": 1, "from_level": 200, "income_before_h": 1000.0, "income_after_h": 700.0, "income_recovered_days": 25.0, "rebuild_to_best_days": 30.0}


def _never():
    return [_res(s, "never", "canon", lambda d: 1000.0) for s in mi.STYLES]


def _set(cand, o200, x2, x3, farm, ladder=None, p200=None):
    out = []
    for s in mi.STYLES:
        out += [
            _res(s, "O200", cand, o200, runs=[_run(400, 1)]),
            _res(s, "P200", cand, p200 or o200, runs=[_run(400, 1)]),
            _res(s, "L200+50x2", cand, x2, runs=[_run(400, 1), _run(800, 2)]),
            _res(s, "L200+50x3", cand, x3, runs=[_run(400, 1), _run(800, 2), _run(1200, 3)]),
            _res(s, "O200x4", cand, farm, runs=[_run(400, 1)] * 4),
            _res(s, "L200+50", cand, ladder or x3, runs=[_run(400, 1)] * 6),
            _res(s, "L200+25", cand, ladder or x3, runs=[_run(400, 1)] * 9),
        ]
    return out


def test_marginal_value_of_the_second_and_third_reset():
    o200 = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    x2 = lambda d: o200(d) if d < 800 else (800.0 if d < 830 else 1200.0)  # noqa: E731  the second reset: a dip, then +100 more
    x3 = lambda d: x2(d) if d < 1200 else (800.0 if d < 1230 else 1250.0)  # noqa: E731
    results = _never() + _set("good", o200, x2, x3, o200)
    m2 = mi.marginal(results, "good", "L200+50x2", "O200", 2)
    m3 = mi.marginal(results, "good", "L200+50x3", "L200+50x2", 3)
    assert set(m2) == set(mi.STYLES) and m2["active"]["gain"] > 0.05 and m2["active"]["day"] == 800.0
    assert m2["active"]["payback_day"] is not None and 0 < m2["active"]["payback_day"] < 400
    assert m3["active"]["gain"] > 0 and m3["active"]["day"] == 1200.0
    assert mi.reset_day(ar.find(results, "active", "O200", "good"), 2) is None  # one reset only


def test_acceptance_for_a_good_and_a_bad_candidate():
    o200 = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    x2 = lambda d: o200(d) if d < 800 else (800.0 if d < 830 else 1180.0)  # noqa: E731
    x3 = lambda d: x2(d) if d < 1200 else (800.0 if d < 1230 else 1200.0)  # noqa: E731
    good = _set("good", o200, x2, x3, o200)
    c = mi.criteria(_never() + good, "good")
    assert c["k1_payback"] in ("fast", "ok") and c["k2_repeats"] and c["k3_no_farm"] and c["k4_never_legit"] and c["all_pass"]
    # a farm that beats every sensible policy -> K3 fails; a second reset that loses money -> K2 fails; a first reset that never pays back -> K1 fails
    farm_pays = lambda d: o200(d) * 1.0 if d < 700 else 1500.0  # noqa: E731
    c = mi.criteria(_never() + _set("farm", o200, x2, x3, farm_pays), "farm")
    assert c["k3_no_farm"] is False and not c["all_pass"]
    x2_bad = lambda d: o200(d) if d < 800 else 700.0  # noqa: E731
    c = mi.criteria(_never() + _set("bad2", o200, x2_bad, x2_bad, o200), "bad2")
    assert c["k2_repeats"] is False and not c["all_pass"]
    never_pays = lambda d: 1000.0 if d < 400 else 700.0  # noqa: E731
    c = mi.criteria(_never() + _set("slow", never_pays, never_pays, never_pays, never_pays), "slow")
    assert c["k1_payback"] == "no" and c["slowest_payback"] is None and not c["all_pass"]


def test_a_too_strong_best_response_breaks_never_legit():
    o200 = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    huge = lambda d: o200(d) if d < 800 else 1600.0  # noqa: E731
    c = mi.criteria(_never() + _set("huge", o200, huge, huge, o200), "huge")
    assert c["k4_never_legit"] is False and c["max_style_ratio"] > ar.STYLE_MAX


def test_best_start_uses_the_faster_of_the_whole_empire_and_the_metal_mines_only():
    slow = lambda d: 1000.0 if d < 400 else (500.0 if d < 700 else 1200.0)  # noqa: E731  pays back after ~1,050 days
    quick = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731  pays back after ~90 days
    results = _never()
    for s in mi.STYLES:
        results.append(_res(s, "O200", "pick", slow, runs=[_run(400, 1)]))
        results.append(_res(s, "P200", "pick", quick if s == "casual" else slow, runs=[_run(400, 1)]))
    c = mi.criteria(results, "pick")
    assert c["k1_payback"] == "no"  # the whole-empire campaign is too slow for everybody ...
    assert c["k1_best_start"] == "no" and c["slowest_best_start"] > mi.PAYBACK_OK_DAYS  # ... and the other styles have no quicker start either
    for s in ("active", "optimizer"):
        results = [r for r in results if not (r["style"] == s and r["arm"] == "P200")] + [_res(s, "P200", "pick", quick, runs=[_run(400, 1)])]
    c = mi.criteria(results, "pick")
    assert c["k1_payback"] == "no" and c["k1_best_start"] in ("fast", "ok") and c["slowest_best_start"] <= mi.PAYBACK_OK_DAYS


def test_a_slow_first_reset_is_classified_by_its_slowest_style():
    fast = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    slow = lambda d: 1000.0 if d < 400 else (500.0 if d < 700 else 1200.0)  # noqa: E731
    results = _never()
    for s in mi.STYLES:
        results.append(_res(s, "O200", "mixed", slow if s == "casual" else fast, runs=[_run(400, 1)]))
    c = mi.criteria(results, "mixed")
    assert c["payback_days"][0] < mi.PAYBACK_OK_DAYS < c["slowest_payback"] and c["k1_payback"] == "no"


# ---------------------------------------------------------------------------
# Matrix and report
# ---------------------------------------------------------------------------


def test_matrix_shape():
    s1, s11 = mi.build_matrix("S1"), mi.build_matrix("S11")
    assert len(s1) == (35 * 7 + 1) * 3 == 738 and len(s11) == 3 * (1 + 35 * 7 - 6 - 5)  # canon and fast_p10 run fewer arms at empire scale
    assert len({s["sid"] for s in s1}) == len(s1) and all(s["sid"].startswith("S1-") for s in s1) and all(s["sid"].startswith("S11-") for s in s11)
    assert len(mi.build_matrix("S1", quick=True)) == 35 * 7 + 1
    assert len(mi.build_matrix("S1", candidates=("canon", "aw15"), arms=("O200",))) == (2 * 1 + 1) * 3
    for s in s1 + s11:
        pj.parse_asc_policy(s["arm"])


def test_render_and_cli_roundtrip(tmp_path):
    o200 = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    x2 = lambda d: o200(d) if d < 800 else (800.0 if d < 830 else 1180.0)  # noqa: E731
    x3 = lambda d: x2(d) if d < 1200 else (800.0 if d < 1230 else 1200.0)  # noqa: E731
    results = _never() + _set("canon", lambda d: 1000.0 if d < 400 else 700.0, lambda d: 700.0, lambda d: 700.0, lambda d: 600.0) + _set("aw15", o200, x2, x3, o200)
    data = {"meta": mi.meta_block(mi.build_matrix("S1")), "results": results}
    md = mi.render_markdown(data)
    for needle in ("## 1. Candidates", "## 2. The first reset", "## 3. The second and third reset", "## 4. Selective and late resets", "## 5. Acceptance", "`aw15`", "awakening +15 %"):
        assert needle in md
    src = tmp_path / "in.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out.md"
    assert mi.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert "## 5. Acceptance" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# One real run
# ---------------------------------------------------------------------------


def test_real_run_applies_the_awakening_once_per_mine_and_keeps_the_invariants():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 470.0, strategy="v2", asc="O200")
    with ar.rules_context(C["c_yield"]):
        res = pj.run_scenario(sc)
    runs = res["ascension_runs"]
    assert runs and res["invariants"]["ok"], res["invariants"]
    assert all(int(r["run"]) == 1 for r in runs)  # one reset per mine
    assert all(int(r["reset_level"]) == 150 for r in runs)  # restart 75 % of L200
    assert nb.reset_start_level({}, 200) == 0  # the owner is restored
