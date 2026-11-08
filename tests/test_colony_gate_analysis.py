"""PL10 vs PL15 colony-gate analysis (measurement only): matrix, lever, aggregation, report plumbing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.planet_evolution import expansion_protocol as ep  # noqa: E402
from scripts import colony_gate_analysis as cg  # noqa: E402
from scripts import player_journey_sim as pj  # noqa: E402


def _snap(income_m: float, income_c: float, produced: float, worlds: int, *, depths=None, pipeline=None, elapsed=730 * 86400.0) -> dict:
    return {
        "worlds": worlds,
        "empire_metal_h": income_m,
        "empire_crystal_h": income_c,
        "mine_depth_max": max(depths or [0]),
        "mine_depth_by_world": depths or [],
        "planet_levels": [30] * worlds,
        "elapsed_sec": elapsed,
        "colony_pipeline_sec": pipeline or {},
        "per_world": [{"produced_metal": produced * 0.6, "produced_crystal": produced * 0.4}],
    }


def _fake(style: str, arm: str, gate: str, *, founded, income: float, produced: float, days: float = 730.0, series=None, pipeline=None, depths=None) -> dict:
    snaps = {k: _snap(income * f, income * f / 2, produced * f, 1 + len(founded), depths=depths, pipeline=pipeline) for k, f in (("182.5", 0.05), ("365", 0.3), ("730", 1.0), ("end", 1.0))}
    return {
        "sid": f"S11-{style}-{arm}-{gate}",
        "style": style,
        "arm": arm,
        "gate": gate,
        "days": days,
        "status": "complete",
        "founded_days": list(founded),
        "gate_audit": [],
        "snapshots": snaps,
        "series": series if series is not None else [(d, income * min(1.0, d / 730.0) * 1.5, 100 + d // 10, 0, 5) for d in range(0, 731, 5)],
        "invariants": {"ok": True, "violations": []},
    }


# ---------------------------------------------------------------------------
# The experiment's definition
# ---------------------------------------------------------------------------


def test_matrix_shape_and_levers():
    specs = cg.build_matrix()
    assert len(specs) == 3 * 3 * 2 + 3 * 2  # styles x arms x gates + the 48-month `never` runs
    assert len({s["sid"] for s in specs}) == len(specs)
    assert {s["topology"] for s in specs} == {"S11"} and {s["rng_seed"] for s in specs} == {pj.ELIGIBLE_HOME_SEED}
    for s in specs:
        assert s["lever"] == ("none" if s["gate"] == "PL15" else "colony_gate_pl10")
        assert (s["asc"], s["asc_skills"]) == cg.ARMS[s["arm"]]
    ext = [s for s in specs if s["days"] == cg.EXT_DAYS]
    assert len(ext) == 6 and {s["arm"] for s in ext} == {"never"}
    quick = cg.build_matrix(quick=True)
    assert len(quick) == 1 * 3 * 2 and {s["policy"] for s in quick} == {"active"}
    assert len(cg.build_matrix(extended=False)) == 18


def test_gate_lever_is_the_sandbox_patch_and_is_restored():
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15  # PL15 is what the game does
    with pj.lever_context(cg.GATES["PL10"]):
        assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 10
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15
    with pj.lever_context(cg.GATES["PL15"]):
        assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def test_world_day_days_per_colony_and_pct():
    r = _fake("active", "never", "PL15", founded=[10.0, 60.0, 110.0], income=1e9, produced=1e12)
    assert cg.world_day(r, 1) == 0.0 and cg.world_day(r, 2) == 10.0 and cg.world_day(r, 4) == 110.0
    assert cg.world_day(r, 5) is None
    assert cg.days_per_colony(r) == pytest.approx(50.0)
    assert cg.days_per_colony({"founded_days": [5.0]}) is None
    assert cg.pct(130.0, 100.0) == pytest.approx(30.0) and cg.pct(None, 1.0) is None and cg.pct(1.0, 0) is None


def test_income_production_and_depth_summary():
    s = _snap(6e9, 4e9, 1e12, 4, depths=[300, 250, 200, 100])
    assert cg.income(s) == 1e10 and cg.produced(s) == pytest.approx(1e12)
    d = cg.depth_summary(s)
    assert d == {"min": 100.0, "median": 225.0, "max": 300.0, "worlds": 4.0}
    assert cg.depth_summary({"mine_depth_by_world": []}) is None


def test_gate_share_and_pipeline_shares():
    s = _snap(1, 1, 1, 3, pipeline={"gate:colony_maturity_required": 365 * 86400.0, "target_reached": 182.5 * 86400.0, "ark_building_or_flying": 0.0})
    assert cg.gate_share(s) == pytest.approx(0.5)
    sh = cg.pipeline_shares(s)
    assert sh["colony maturity gate"] == pytest.approx(0.5) and sh["all colonies founded"] == pytest.approx(0.25) and sh["homeworld slot gate"] == 0.0
    assert cg.gate_share(_snap(1, 1, 1, 1)) is None and cg.pipeline_shares(None) == {}


def test_lead_days_counts_how_much_earlier_the_faster_run_reaches_the_reference_income():
    ref = _fake("active", "never", "PL15", founded=[10.0], income=1e9, produced=1e12, series=[(d, 1e9 * d / 730.0, 0, 0, 1) for d in range(0, 731, 5)])
    fast = _fake("active", "never", "PL10", founded=[10.0], income=1e9, produced=1e12, series=[(d, 1e9 * (d + 60) / 730.0, 0, 0, 1) for d in range(0, 731, 5)])
    # the reference has income(365) = 0.3 * (1e9 + 0.5e9) in the fake snapshots; build both consistently instead:
    ref["snapshots"]["365"] = _snap(1e9 * 365 / 730.0, 0.0, 1, 1)
    assert cg.lead_days(fast, ref, "365") == pytest.approx(60, abs=5)
    slow = _fake("active", "never", "PL10", founded=[10.0], income=1e9, produced=1e12, series=[(d, 1e9 * (d - 60) / 730.0, 0, 0, 1) for d in range(0, 731, 5)])
    assert cg.lead_days(slow, ref, "365") is None  # never reaches it before the checkpoint


def test_fairness_ratios_and_cross_comparison_inputs():
    res = [
        _fake("casual", "never", "PL15", founded=[14.0] * 9 + [640.0], income=5e11, produced=2e15),
        _fake("optimizer", "never", "PL15", founded=[7.0] * 9 + [440.0], income=1e12, produced=4e15),
    ]
    f = cg.fairness(res, "never", "PL15")
    assert f["day_11th_ratio"] == pytest.approx(640.0 / 440.0)
    assert f["income_730"] == pytest.approx(0.5) and f["produced_730"] == pytest.approx(0.5)
    assert cg.fairness(res, "never", "PL10") == {}


# ---------------------------------------------------------------------------
# A real (short) run: the lever must move the colony chain
# ---------------------------------------------------------------------------


def test_lower_gate_brings_the_fourth_world_forward_in_a_real_run():
    base = {"topology": "S11", "policy": "active", "strategy": "v2", "arm": "never", "asc": "never", "asc_skills": "rebuild_first", "days": 100.0, "rng_seed": pj.ELIGIBLE_HOME_SEED}
    r15 = cg.run_spec({**base, "sid": "t-15", "gate": "PL15", "lever": "none"})
    r10 = cg.run_spec({**base, "sid": "t-10", "gate": "PL10", "lever": "colony_gate_pl10"})
    assert r15["invariants"]["ok"] and r10["invariants"]["ok"]
    assert cg.world_day(r15, 2) == cg.world_day(r10, 2)  # the first colony is not gated
    w15, w10 = cg.world_day(r15, 4), cg.world_day(r10, 4)
    assert w10 is not None and (w15 is None or w10 < w15)
    assert ep.COLONY_MATURITY_REQUIRED_LEVEL == 15  # restored after the PL10 run
    assert r10["snapshots"]["end"]["colony_pipeline_sec"]  # the pipeline ledger is carried through


# ---------------------------------------------------------------------------
# Report plumbing
# ---------------------------------------------------------------------------


def _synthetic_data() -> dict:
    results = []
    for style, f15, f10, inc in (("casual", 64.0, 42.0, 5e11), ("active", 48.0, 27.0, 9e11), ("optimizer", 44.0, 23.0, 1e12)):
        for arm in cg.ARMS:
            for gate, step, mult in (("PL15", f15, 1.0), ("PL10", f10, 1.3)):
                founded = [round(7 + step * i, 1) for i in range(10)]
                pipeline = {"gate:colony_maturity_required": 300 * 86400.0, "target_reached": 200 * 86400.0}
                results.append(_fake(style, arm, gate, founded=founded, income=inc * mult, produced=inc * mult * 4000, pipeline=pipeline, depths=[300, 280, 250, 200]))
        for gate, mult in (("PL15", 1.0), ("PL10", 1.2)):
            r = _fake(style, "never", gate, founded=[round(7 + 40 * i, 1) for i in range(10)], income=inc * 1.5 * mult, produced=inc * 6000 * mult, days=cg.EXT_DAYS)
            for k in cg.EXT_KEYS:
                r["snapshots"][k] = r["snapshots"]["730"]
            results.append(r)
    return {"meta": {"version": cg.ANALYSIS_VERSION, "scenarios": len(results), "days": cg.DAYS, "extended_days": cg.EXT_DAYS, "gates": cg.GATES, "arms": sorted(cg.ARMS)}, "results": results}


def test_render_and_cli_roundtrip(tmp_path):
    data = _synthetic_data()
    md = cg.render_markdown(data)
    for needle in ("Colony timeline", "Economic lead of PL10 over PL15 - arm `never`", "arm `T200`", "Casual fairness", "Do the late colonies stay shallow", "What limits the colony chain", "Correction of the earlier", "Does the lead persist", "none violated"):
        assert needle in md, needle
    src, out = tmp_path / "gate.json", tmp_path / "gate.md"
    src.write_text(json.dumps(data), encoding="utf-8")
    assert cg.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert out.read_text(encoding="utf-8").strip() == md.strip()


def test_invariant_violations_are_reported():
    data = _synthetic_data()
    data["results"][0]["invariants"] = {"ok": False, "violations": ["level skip metal_mine 3->5"]}
    md = cg.render_markdown(data)
    assert "level skip metal_mine 3->5" in md and "none violated" not in md
