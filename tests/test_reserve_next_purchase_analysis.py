"""Reserve-next-purchase value analysis: matrix, lever split in the simulator, pure aggregation, report.  Sandbox only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts import player_journey_sim as pj
from scripts import reserve_next_purchase_analysis as rn


def fake(topo: str, style: str, variant: str, *, income: float, produced: float, depth_days: Dict[int, float], founded=(10.0, 60.0)) -> Dict[str, Any]:
    snaps: Dict[str, Any] = {}
    for key in ("182.5", "365", "730"):
        f = float(key) / 365.0
        snaps[key] = {
            "empire_metal_h": income * f * 0.7, "empire_crystal_h": income * f * 0.3, "worlds": 2,
            "per_world": [{"produced_metal": produced * f, "produced_crystal": 0.0}], "elapsed_sec": float(key) * 86400,
        }
    snaps["end"] = dict(snaps["730"])
    series = []
    for d in range(0, 731, 5):
        peak = max([lvl for lvl, day in depth_days.items() if d >= day] + [0])
        series.append([d, income * d / 365.0, peak, 0, 2])
    return {
        "sid": f"{topo}-{style}-never-{variant}", "topology": topo, "style": style, "variant": variant, "arm": "never", "gate": "PL15", "days": 730.0,
        "founded_days": list(founded), "snapshots": snaps, "series": series, "invariants": {"ok": True, "violations": []},
    }


def synthetic() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for topo in rn.TOPOLOGIES:
        for style, scale in (("casual", 0.5), ("active", 0.8), ("optimizer", 1.0)):
            for variant, gain, earlier in (("none", 1.0, 0.0), ("builds", 1.2, 20.0), ("research", 1.05, 5.0), ("both", 1.3, 25.0)):
                out.append(fake(topo, style, variant, income=100.0 * scale * gain, produced=1_000.0 * scale * gain, depth_days={100: 100.0 - earlier, 150: 200.0 - earlier, 200: 320.0 - earlier}))
    return out


def test_matrix_shape_and_levers():
    specs = rn.build_specs()
    assert len(specs) == len(rn.TOPOLOGIES) * len(rn.STYLES) * len(rn.VARIANT_ORDER) == 24
    assert len({s["sid"] for s in specs}) == 24 and all(s["lever"] in pj.LEVERS for s in specs)
    assert {s["lever"] for s in specs} == {"none", "auto_start_build", "auto_start_research", "auto_start"}
    assert all(s["rng_seed"] == (pj.ELIGIBLE_HOME_SEED if s["topology"] == "S11" else None) for s in specs)


def test_split_levers_are_side_study_levers():
    assert {"auto_start_build", "auto_start_research"} <= pj.ASCENSION_ONLY_LEVERS  # they must not enlarge the bottleneck-report matrix
    assert pj.RESERVE_BUILD_LEVERS == {"auto_start", "auto_start_build"} and pj.RESERVE_RESEARCH_LEVERS == {"auto_start", "auto_start_research"}


def test_day_of_depth_and_effect():
    res = synthetic()
    assert rn.day_of_depth(rn.pick(res, "S1", "casual", "none"), 150) == 200.0
    assert rn.day_of_depth(rn.pick(res, "S1", "casual", "none"), 9_999) is None and rn.day_of_depth(None, 100) is None
    e = rn.effect(res, "S1", "casual", "builds")
    assert e["income"]["365"] == pytest.approx(20.0) and e["produced"]["730"] == pytest.approx(20.0)
    assert e["days_to_depth"] == {100: -20.0, 150: -20.0, 200: -20.0}
    assert e["worlds_12mo"] == 0.0 and e["world11_shift"] is None  # only 3 worlds exist in the synthetic set
    assert rn.effect(res, "S1", "casual", "nonexistent") == {"income": {}, "produced": {}, "days_to_depth": {}, "worlds_12mo": None, "world11_shift": None}


def test_casual_share_is_relative_to_the_optimizer_without_the_feature():
    res = synthetic()
    assert rn.casual_share(res, "S11", "none")["365"] == pytest.approx(0.5)
    assert rn.casual_share(res, "S11", "both")["365"] == pytest.approx(0.65)


def test_render_markdown_and_cli_render_from_json(tmp_path: Path):
    res = synthetic()
    text = rn.render_markdown(res)
    assert "# Reserve next purchase" in text and "## S1 (one planet)" in text and "## S11 (up to 11 planets)" in text
    assert "Simulator invariants hold in all runs: True" in text and "| casual | builds |" in text
    src, out = tmp_path / "r.json", tmp_path / "r.md"
    src.write_text(json.dumps({"meta": {}, "results": res}), encoding="utf-8")
    assert rn.main(["--render-from", str(src), "--out-md", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Reserve next purchase")


def test_real_run_lever_split_changes_the_run_and_keeps_the_invariants():
    runs = {}
    for variant in rn.VARIANT_ORDER:
        spec = next(s for s in rn.build_specs() if s["topology"] == "S1" and s["policy"] == "casual" and s["variant"] == variant)
        runs[variant] = rn.run_spec(dict(spec, days=45.0, sid=spec["sid"] + "-short"))
    assert all(r["invariants"]["ok"] for r in runs.values())
    produced = {v: rn.cga.produced(rn.cga.snap(r, "end")) for v, r in runs.items()}
    assert len({round(p) for p in produced.values()}) == 4  # none / builds / research / both are four different games
    assert produced["builds"] > produced["none"] and produced["both"] > produced["none"]  # a casual player on one planet gains from reserving builds
