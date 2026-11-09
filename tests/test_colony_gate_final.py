"""PL10 / PL12 / PL15 final comparison: matrix shape, pure aggregation on synthetic results, report, and short real runs.  Sandbox only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from scripts import colony_gate_final as cgf
from scripts import player_journey_sim as pj


def fake(style: str, gate: str, rate: int = 0, days: float = 730.0, *, founded: List[float], income: float = 100.0, produced: float = 1_000.0, fix: bool = False, exp_xp: int = 0) -> Dict[str, Any]:
    snaps: Dict[str, Any] = {}
    for key in ("182.5", "365", "730", "1095", "1460"):
        if float(key) <= days + 1e-9:
            f = float(key) / 365.0
            snaps[key] = {
                "empire_metal_h": income * f * 0.7,
                "empire_crystal_h": income * f * 0.3,
                "worlds": 1 + sum(1 for d in founded if d <= float(key)),
                "per_world": [{"produced_metal": produced * f * 0.6, "produced_crystal": produced * f * 0.4}],
                "colony_pipeline_sec": {"gate:colony_maturity_required": 0.4 * float(key) * 86400},
                "elapsed_sec": float(key) * 86400,
            }
    snaps["end"] = dict(snaps[max(snaps, key=lambda k: float(k) if k != "end" else -1)])
    series = [[d, income * d / 365.0, 100 + d // 10, 0, 1 + sum(1 for x in founded if x <= d)] for d in range(0, int(days) + 1, 5)]
    return {
        "sid": f"S11-{style}-never-{gate}-x{rate}-{int(days)}d", "style": style, "arm": "never", "gate": gate, "days": float(days), "status": "ok",
        "founded_days": list(founded), "snapshots": snaps, "series": series, "invariants": {"ok": True, "violations": []},
        "xp_by_source": {"expedition": exp_xp}, "expeditions_per_day": rate, "fix556": fix,
    }


def synthetic(rate: int = 0, fix: bool = False, shift: float = 0.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # 10 colonies: PL15 every 40 days, PL12 every 33, PL10 every 26 (days), income scales with how early the empire completes
    for style, scale in (("casual", 0.5), ("active", 0.8), ("optimizer", 1.0)):
        for gate, step, inc in (("PL15", 40.0, 100.0), ("PL12", 33.0, 112.0), ("PL10", 26.0, 125.0)):
            founded = [10.0 + step * i + shift for i in range(10)]
            out.append(fake(style, gate, rate, 730.0, founded=founded, income=inc * scale, produced=1_000.0 * inc / 100.0 * scale, fix=fix))
    return out


# ---------------------------------------------------------------------------
# matrix
# ---------------------------------------------------------------------------


def test_base_and_fix_matrix_shape():
    base, fix = cgf.build_specs("base"), cgf.build_specs("fix")
    assert len(base) == 3 * 3 * len(cgf.BASE_RATES) + 3 * 3 * len(cgf.EXT_RATES) == 54
    assert len(fix) == 3 * 3 * len(cgf.FIX_RATES) == 18
    for specs in (base, fix):
        assert len({s["sid"] for s in specs}) == len(specs)
        assert {s["topology"] for s in specs} == {"S11"} and {s["arm"] for s in specs} == {"never"} and {s["strategy"] for s in specs} == {"v2"}
        assert {s["rng_seed"] for s in specs} == {pj.ELIGIBLE_HOME_SEED}
        assert all(s["lever"] in pj.LEVERS for s in specs)
    assert {s["gate"] for s in base} == set(cgf.GATE_ORDER)
    long_runs = [s for s in base if s["days"] > 730]
    assert {s["expeditions_per_day"] for s in long_runs} == set(cgf.EXT_RATES) and len(long_runs) == 18
    with pytest.raises(ValueError):
        cgf.build_specs("nope")


def test_gate_levers_match_the_gate_labels():
    for gate, lever in cgf.GATES.items():
        assert pj.LEVER_GATE_LEVEL.get(lever, 15) == cgf.GATE_LEVEL[gate]


def test_outpost_hold_detection_matches_the_source():
    import inspect

    from game.planet_evolution import planet_level

    assert cgf.outpost_hold_applied() == ("held_until_established" in inspect.getsource(planet_level.add_planet_xp))


# ---------------------------------------------------------------------------
# aggregation on synthetic results
# ---------------------------------------------------------------------------


def test_timeline_and_pl12_share():
    res = synthetic()
    tl = cgf.timeline(res)
    assert tl["active"]["PL15"][11] == 10.0 + 40.0 * 9 and tl["active"]["PL10"][11] == 10.0 + 26.0 * 9 and tl["active"]["PL15"][2] == 10.0
    share = cgf.pl12_share(res, "active")
    assert share["day_11th"] == pytest.approx((40 - 33) / (40 - 26))
    assert 0.0 < share["produced_730"] < 1.0 and share["produced_1460"] is None  # no 48-month run in the synthetic set


def test_economy_vs_pl15_and_missing_horizon():
    res = synthetic()
    e = cgf.economy_vs_pl15(res, "optimizer", "PL10")
    assert e["730"]["income_pct"] == pytest.approx(25.0) and e["730"]["produced_pct"] == pytest.approx(25.0)
    assert e["365"]["income_pct"] == pytest.approx(25.0)
    assert e["1460"] == {"income_pct": None, "produced_pct": None, "lead_days": None}
    assert e["730"]["lead_days"] is not None and e["730"]["lead_days"] > 0


def test_dose_response_rows_and_gains():
    res = synthetic(0) + synthetic(6, shift=-12.0)
    rows = cgf.dose_response(res, "casual")
    assert [r["rate"] for r in rows] == [0, 6]
    assert rows[0]["gain_pl12"] == 7 * 9 and rows[0]["gain_pl10"] == 14 * 9
    assert rows[1]["day_11th"]["PL15"] == rows[0]["day_11th"]["PL15"] - 12.0


def test_fix_effect_shifts_and_missing_data():
    base, fixed = synthetic(0), synthetic(0, fix=True, shift=9.0)
    e = cgf.fix_effect(base, fixed, "active", "PL12", 0)
    assert e["shift_4th"] == 9.0 and e["shift_11th"] == 9.0 and e["produced_pct"] == pytest.approx(0.0)
    assert cgf.fix_effect(base, fixed, "active", "PL12", 6) == {}


def test_fairness_same_and_habit_mix():
    res = synthetic(0) + synthetic(3) + synthetic(15, shift=-20.0)
    same = cgf.fairness(res, "PL15", 0, 0)
    habit = cgf.fairness(res, "PL15", 3, 15)
    assert same["day_11th"] == pytest.approx(1.0) and same["income_730"] == pytest.approx(0.5)
    assert habit["day_11th"] > same["day_11th"]  # the optimizer who runs expeditions is earlier, so the casual player is relatively later


# ---------------------------------------------------------------------------
# report and CLI
# ---------------------------------------------------------------------------


def test_render_markdown_with_and_without_the_fix():
    base = synthetic(0) + synthetic(3) + synthetic(6) + synthetic(15)
    no_fix = cgf.render_markdown(base)
    assert "## 1. Colony timeline" in no_fix and "## 5. Outpost-XP fix (#556)" in no_fix and "No run with the fix is loaded." in no_fix
    assert "Invariants hold in all runs: True" in no_fix
    with_fix = cgf.render_markdown(base, synthetic(0, fix=True, shift=5.0) + synthetic(6, fix=True, shift=5.0))
    assert "No run with the fix is loaded." not in with_fix and "+5" in with_fix


def test_cli_report_from_saved_suites(tmp_path: Path):
    for name, rates in (("base", (0, 3, 6, 15)), ("fix", (0, 6))):
        results = [r for rate in rates for r in synthetic(rate, fix=name == "fix")]
        (tmp_path / f"{name}.json").write_text(json.dumps({"meta": {}, "results": results}), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cgf.main(["--report", str(out), "--base-json", str(tmp_path / "base.json"), "--fix-json", str(tmp_path / "fix.json")]) == 0
    assert "Colony gate PL10 / PL12 / PL15" in out.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        cgf.main(["--report", str(out), "--base-json", str(tmp_path / "missing.json")])


# ---------------------------------------------------------------------------
# short real runs through the canonical owners
# ---------------------------------------------------------------------------


def _short(style: str, gate: str, rate: int, days: float) -> Dict[str, Any]:
    spec = next(s for s in cgf.build_specs("base") if s["policy"] == style and s["gate"] == gate and s["expeditions_per_day"] == rate and s["days"] == 730.0)
    return cgf.run_spec(dict(spec, days=days, sid=spec["sid"] + "-short"))


def test_real_run_carries_expedition_xp_and_restores_the_gate():
    from game.planet_evolution import expansion_protocol as ep

    before = int(ep.COLONY_MATURITY_REQUIRED_LEVEL)
    res = _short("active", "PL12", 6, 100.0)
    assert int(ep.COLONY_MATURITY_REQUIRED_LEVEL) == before  # the lever patches the constant for one run only
    assert res["expeditions_per_day"] == 6 and res["xp_by_source"].get("expedition", 0) >= 6 * 15 * 90
    assert res["invariants"]["ok"] and res["fix556"] == cgf.outpost_hold_applied()


def test_expedition_xp_goes_to_the_colony_that_holds_the_chain_under_a_lower_gate():
    """Under PL10 the focus colony must be judged against gate 10, not the constant 15: expedition XP may never make the chain slower."""
    quiet, busy = _short("active", "PL10", 0, 130.0), _short("active", "PL10", 15, 130.0)
    k = min(len(quiet["founded_days"]), len(busy["founded_days"]))
    assert k >= 2 and len(busy["founded_days"]) >= len(quiet["founded_days"])
    assert all(b <= q + 1e-9 for b, q in zip(busy["founded_days"][:k], quiet["founded_days"][:k]))
    assert busy["founded_days"][k - 1] < quiet["founded_days"][k - 1]  # and it really speeds the chain up


def test_fix_summary_reports_mean_range_and_sign_counts():
    base = synthetic(0) + synthetic(6)
    fixed = synthetic(0, fix=True, shift=3.0) + synthetic(6, fix=True, shift=-1.0)
    sm = cgf.fix_summary(base, fixed)
    assert sm["shift_4th"]["n"] == 18.0 and sm["shift_4th"]["mean"] == pytest.approx(1.0) and sm["shift_4th"]["min"] == -1.0 and sm["shift_4th"]["max"] == 3.0
    assert sm["shift_11th"]["positive"] == 9.0
    assert "Over all 18 pairs" in cgf.render_markdown(base, fixed)
