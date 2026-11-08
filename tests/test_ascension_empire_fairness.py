"""Ascension reward fairness at empire scale (S11): scope policies M / G / O, empire metrics, criteria, report (measurement only)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ascension_empire_fairness as ef  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402


def _profiles(count: int, best: int) -> dict:
    state = {"ascension_count": count, "points_earned": 0, "points_unspent": 0, "best_depth": best, "last_depth": best}
    return {"metal_mine": {"state": state, "skills": {}}, "crystal_mine": {"state": dict(state), "skills": {}}}


# ---------------------------------------------------------------------------
# Scope policies of the simulator
# ---------------------------------------------------------------------------


def test_scope_policies_parse():
    assert pj.parse_asc_policy("M200") == (True, 200, "M", 1)
    assert pj.parse_asc_policy("G200") == (True, 200, "G", 1)
    assert pj.parse_asc_policy("O200") == (True, 200, "O", 1)
    for bad in ("M150", "G", "M", "G200x4", "M200+25"):
        with pytest.raises(ValueError):
            pj.parse_asc_policy(bad)
    for arm in ef.SCOPE_ARMS + ef.GUARD_ARMS:
        pj.parse_asc_policy(arm)


def test_single_mine_policy_resets_one_mine_in_the_whole_empire():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="M200")
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j = pj.Journey(sc, sb)
        w = j.worlds[0]
        w.asc_any = False
        assert j.asc_target(w, "metal_mine") == 200 and j.asc_target(w, "crystal_mine") == 200  # nobody has reset yet
        j.asc_runs.append({"world": 0, "mine": "metal_mine"})
        assert j.asc_target(w, "metal_mine") is None and j.asc_target(w, "crystal_mine") is None  # one reset, then never again
        other = copy.copy(w)
        other.idx = 1
        other.asc_any = False
        assert j.asc_target(other, "metal_mine") is None  # not even on another planet that never reset


def test_serial_policy_blocks_across_planets_but_the_parallel_one_does_not():
    def blocked(mode: str) -> bool:
        sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc=mode)
        with pj.economy_curve("uni1"), pj.Sandbox() as sb:
            j = pj.Journey(sc, sb)
            w = j.worlds[0]
            other = copy.copy(w)
            other.idx = 1
            j.worlds.append(other)
            j.asc_rebuilding = lambda ww, kk: ww is other and kk == "metal_mine"  # type: ignore[assignment]
            return bool(j.asc_stagger_blocked(w, "metal_mine"))

    assert blocked("G200") is True  # another planet is rebuilding: wait for the empire-wide slot
    assert blocked("O200") is False  # planets run in parallel
    assert blocked("M200") is False


def test_serial_policy_keeps_the_same_planet_rule_and_does_not_block_itself():
    sc = pj.Scenario("t", "S1", "optimizer", "mid", "none", 5.0, strategy="v2", asc="G200")
    with pj.economy_curve("uni1"), pj.Sandbox() as sb:
        j = pj.Journey(sc, sb)
        w = j.worlds[0]
        j.asc_rebuilding = lambda ww, kk: kk == "metal_mine"  # type: ignore[assignment]
        assert j.asc_stagger_blocked(w, "metal_mine") is False  # the mine itself is not "another" rebuild
        assert j.asc_stagger_blocked(w, "crystal_mine") is True  # the other mine of the same planet rebuilds


# ---------------------------------------------------------------------------
# Metrics on synthetic runs
# ---------------------------------------------------------------------------


def test_parallel_rebuilds_are_counted_by_interval_overlap():
    runs = [
        {"day": 100.0, "rebuild_to_best_days": 50.0},
        {"day": 120.0, "rebuild_to_best_days": 10.0},
        {"day": 150.0, "rebuild_to_best_days": 20.0},  # starts when the first one ends: no overlap with it
    ]
    assert ef.max_parallel_rebuilds(runs, 1000.0) == 2
    assert ef.max_parallel_rebuilds([{"day": 10.0, "rebuild_to_best_days": 5.0}, {"day": 15.0, "rebuild_to_best_days": 5.0}], 100.0) == 1
    assert ef.max_parallel_rebuilds([{"day": 10.0, "rebuild_to_best_days": None}, {"day": 500.0, "rebuild_to_best_days": 1.0}], 600.0) == 2  # unfinished: to the horizon
    assert ef.max_parallel_rebuilds([], 100.0) == 0


def test_resets_by_and_extras():
    series = [(0, 1, 1, 0, 1), (365, 1, 1, 3, 4), (730, 1, 1, 9, 11)]
    assert ef.resets_by(series, 400) == 3 and ef.resets_by(series, 730) == 9 and ef.resets_by(series, -1) == 0
    res = {
        "days": 730.0, "series": series, "founded_days": [100.0, 200.0, 300.0, 500.0],
        "runs": [
            {"world": 0, "mine": "metal_mine", "day": 300.0, "from_level": 200, "rebuild_to_best_days": 60.0},
            {"world": 2, "mine": "metal_mine", "day": 320.0, "from_level": 200, "rebuild_to_best_days": 60.0},
            {"world": 0, "mine": "crystal_mine", "day": 400.0, "from_level": 201, "rebuild_to_best_days": 60.0},
        ],
    }
    x = ef.extras(res)
    assert x["resets"] == 3 and x["planets"] == 2 and x["mines"] == 3 and x["max_parallel"] == 2
    assert x["first_world"] == 0 and x["first_from_level"] == 200 and x["worlds_at_first_reset"] == 4  # 3 colonies founded by day 300 + the homeworld
    assert x["resets_by_730"] == 9


# ---------------------------------------------------------------------------
# Criteria on synthetic results
# ---------------------------------------------------------------------------


def _series(fn, days: int = 2190):
    return [(d, fn(d), 100 + d // 10, 0, 11) for d in range(0, days + 1, 5)]


def _res(style, arm, cand, fn, *, runs=(), days=2190.0):
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
    return {"sid": f"S11-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": days, "snapshots": snaps, "series": series,
            "runs": list(runs), "skill_log": [], "founded_days": [], "invariants": {"ok": True, "violations": []}}


RUN = {"world": 0, "mine": "metal_mine", "day": 400.0, "ap_gain": 1, "from_level": 200, "income_before_h": 1000.0, "income_after_h": 800.0, "income_recovered_days": 20.0, "rebuild_to_best_days": 30.0}


def _never():
    return [_res(style, "never", "canon", lambda d: 1000.0) for style in ef.STYLES]


def _scope_results(cand: str, parallel_fn, serial_fn, single_fn, farm_fn, ladder_fn, farm_per_style=None):
    out = []
    for style in ef.STYLES:
        out.append(_res(style, "M200", cand, single_fn, runs=[RUN]))
        out.append(_res(style, "G200", cand, serial_fn, runs=[RUN] * 22))
        out.append(_res(style, "O200", cand, parallel_fn, runs=[RUN] * 22))
        fn = (farm_per_style or {}).get(style, farm_fn)
        out.append(_res(style, "O200x4", cand, fn, runs=[RUN] * 88))
        out.append(_res(style, "L200+25", cand, ladder_fn, runs=[RUN] * 60))
    return out


def test_empire_criteria_pass_for_a_bounded_candidate_and_fail_for_a_scaling_one():
    flat = lambda d: 1000.0  # noqa: E731
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1060.0)  # noqa: E731
    results = _never() + _scope_results("ok", good, good, flat, good, good)
    c = ef.criteria(results, "ok")
    assert c["scale_ok"] and c["scope_ok"] and c["guard_ok"] and c["payback_class"] in ("good", "ok") and c["all_pass"]
    assert c["scopes"]["M200"]["resets"][0] == 1 and c["scopes"]["O200"]["resets"][0] == 22
    scaling = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1400.0)  # noqa: E731  the whole empire profits far too much
    results = _never() + _scope_results("big", scaling, good, flat, good, good)
    c = ef.criteria(results, "big")
    assert c["scale_ok"] is False and c["scope_ok"] is False and c["all_pass"] is False
    assert c["parallel_gain"] > 0.2  # resetting everything at once beats the serial order by far


def test_empire_payback_is_judged_on_the_slowest_style():
    fast = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1100.0)  # noqa: E731
    slow = lambda d: 1000.0 if d < 400 else (500.0 if d < 700 else 1200.0)  # noqa: E731
    results = _never() + [_res(style, "O200", "rank1_fast", slow if style == "casual" else fast, runs=[RUN] * 22) for style in ef.STYLES]
    c = ef.criteria(results, "rank1_fast")
    assert c["scopes"]["O200"]["payback"][0] < ar.C2_PAYBACK_DAYS < ar.C2_PAYBACK_DAYS_OK < c["scopes"]["O200"]["payback"][2]
    assert c["payback_class"] == "no" and c["all_pass"] is False


def test_farming_that_pays_for_one_style_fails_the_empire_guard():
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1060.0)  # noqa: E731
    boost = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1060.0 + 0.4 * (d > 600) * 1000.0)  # noqa: E731
    results = _never() + _scope_results("farm", good, good, good, good, good, farm_per_style={"casual": boost})
    c = ef.criteria(results, "farm")
    assert c["farm_pays_for"] == ["casual"] and c["guard_ok"] is False and c["all_pass"] is False and c["scale_ok"] and c["scope_ok"]


def test_missing_arms_give_none_not_a_verdict():
    c = ef.criteria(_never(), "rank1_fast")
    assert c["scale_ok"] is None and c["scope_ok"] is None and c["guard_ok"] is None and c["all_pass"] is False


def test_a_horizon_too_short_for_48_months_gives_no_verdict_instead_of_no():
    short = lambda d: 1000.0 if d < 400 else 900.0  # noqa: E731
    results = [_res(s, "never", "canon", lambda d: 1000.0, days=730.0) for s in ef.STYLES] + [_res(s, "O200", "rank1_fast", short, runs=[RUN], days=730.0) for s in ef.STYLES]
    c = ef.criteria(results, "rank1_fast")
    assert c["scale_ok"] is None and c["all_pass"] is False


def test_vs_s1_compares_the_same_candidate_and_arm():
    flat = lambda d: 1000.0  # noqa: E731
    better = lambda d: 1000.0 if d < 400 else 1100.0
    s11 = [_res(s, "O200", "x", better) for s in ef.STYLES] + _never()
    s1 = [_res(s, "O200", "x", flat, runs=[RUN]) for s in ef.STYLES] + _never()
    cmp = ef.vs_s1(s11, s1, "x")
    assert cmp["1460"]["s11"][0] > cmp["1460"]["s1"][0] and cmp["1460"]["s1"][0] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Matrix and report
# ---------------------------------------------------------------------------


def test_matrix_shape():
    specs = ef.build_matrix()
    assert len(specs) == 27 and len({s["sid"] for s in specs}) == 27
    per_style = [s for s in specs if s["style"] == "active"]
    assert sorted(s["arm"] + ":" + s["cand"] for s in per_style) == sorted(
        ["never:canon", "O200:canon", "M200:rank1_fast", "G200:rank1_fast", "O200:rank1_fast", "O200x4:rank1_fast", "L200+25:rank1_fast", "O200:fast_p10", "O200x4:fast_p10"]
    )
    assert len(ef.build_matrix(quick=True)) == 9 and all(s["days"] == ef.DAYS for s in specs)
    for s in specs:
        pj.parse_asc_policy(s["arm"])
        assert s["cand"] in ar.CANDIDATES


def test_render_and_cli_roundtrip(tmp_path):
    flat = lambda d: 1000.0  # noqa: E731
    good = lambda d: 1000.0 if d < 400 else (800.0 if d < 430 else 1060.0)  # noqa: E731
    results = _never() + _scope_results("rank1_fast", good, good, flat, good, good)
    for style in ef.STYLES:
        results.append(_res(style, "O200", "canon", lambda d: 1000.0 if d < 400 else 700.0, runs=[RUN] * 22))
        results.append(_res(style, "O200", "fast_p10", good, runs=[RUN] * 22))
        results.append(_res(style, "O200x4", "fast_p10", good, runs=[RUN] * 88))
    data = {"meta": ef.meta_block(ef.build_matrix()), "results": results}
    s1 = [_res(style, "O200", c, good, runs=[RUN]) for style in ef.STYLES for c in ef.CAND_ORDER]
    md = ef.render_markdown(data, s1)
    for needle in ("## 2. Reference candidate by scope", "`M200`", "`G200`", "## 4. Does it scale?", "## 5. Verdict", "## 6. Limits", "Parallel vs serial"):
        assert needle in md
    assert "S1 / S11" in md
    src = tmp_path / "in.json"
    src.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out.md"
    assert ef.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert "## 5. Verdict" in out.read_text(encoding="utf-8")
