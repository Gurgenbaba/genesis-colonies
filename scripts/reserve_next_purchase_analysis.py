"""Value of "reserve next purchase" in the corrected model - measurement only.

The earlier numbers (``docs/GC_PROGRESSION_BOTTLENECK_REPORT.md``) came from the progression-bottleneck matrix before the simulators
were reconciled.  This repeats the measurement with the current model (no mine cap under ``nodebuster-v1``), splits the feature into its
two halves - the building queues (one reserved build per planet) and the account research queue - and reports who benefits
(casual / active / optimizer), on one planet (S1) and on up to eleven (S11).

The lever is the existing sandbox ``auto_start``: a purchase the player cannot afford yet is reserved and starts at the exact moment
the funds arrive (no latency, cost deducted at the start, never at the reservation, a stale pick is dropped).  It adds no resource and
shortens no timer.  Nothing in ``game/`` changes.

    python scripts/reserve_next_purchase_analysis.py --workers 10 --out-json artifacts/reserve_next/latest.json --out-md docs/GC_RESERVE_NEXT_PURCHASE_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import colony_gate_analysis as cga  # noqa: E402

ANALYSIS_VERSION = "reserve-next-purchase-analysis/1"
TOPOLOGIES: Tuple[str, ...] = ("S1", "S11")
STYLES: Tuple[str, ...] = cga.STYLES
VARIANTS: Dict[str, str] = {"none": "none", "builds": "auto_start_build", "research": "auto_start_research", "both": "auto_start"}  # label -> sandbox lever
VARIANT_ORDER: Tuple[str, ...] = ("none", "builds", "research", "both")
DAYS = 730.0
CHECKS: Tuple[str, ...] = ("182.5", "365", "730")
CHECK_LABEL = {"182.5": "6 mo", "365": "12 mo", "730": "24 mo"}
DEPTHS: Tuple[int, ...] = (100, 150, 200)


def build_specs(days: float = DAYS, topologies: Sequence[str] = TOPOLOGIES, styles: Sequence[str] = STYLES) -> List[Dict[str, Any]]:
    from scripts import player_journey_sim as pj

    mode, order = cga.ARMS["never"]
    out: List[Dict[str, Any]] = []
    for topo in topologies:
        for style in styles:
            for variant in VARIANT_ORDER:
                out.append(
                    {
                        "sid": f"{topo}-{style}-never-{variant}",
                        "topology": topo,
                        "policy": style,
                        "strategy": "v2",
                        "arm": "never",
                        "asc": mode,
                        "asc_skills": order,
                        "gate": "PL15",
                        "variant": variant,
                        "lever": VARIANTS[variant],
                        "days": float(days),
                        "rng_seed": pj.ELIGIBLE_HOME_SEED if topo == "S11" else None,
                    }
                )
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    res = cga.run_spec(spec)
    res["topology"] = spec["topology"]
    res["variant"] = spec["variant"]
    return res


def run_matrix(specs: List[Dict[str, Any]], workers: int) -> List[Dict[str, Any]]:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import time

    results: List[Dict[str, Any]] = []
    started = time.time()
    specs = sorted(specs, key=lambda s: (s["topology"] != "S11", s["sid"]))
    if workers <= 1:
        for i, spec in enumerate(specs, 1):
            results.append(run_spec(spec))
            print(f"[{i}/{len(specs)}] {spec['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_spec, s): s for s in specs}
            for i, fut in enumerate(as_completed(futures), 1):
                results.append(fut.result())
                print(f"[{i}/{len(specs)}] {futures[fut]['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["sid"])
    return results


# ---------------------------------------------------------------------------
# Aggregation (pure functions over slim results; unit-tested)
# ---------------------------------------------------------------------------


def pick(results: Sequence[Dict[str, Any]], topo: str, style: str, variant: str) -> Optional[Dict[str, Any]]:
    for r in results:
        if r["topology"] == topo and r["style"] == style and r["variant"] == variant:
            return r
    return None


def day_of_depth(res: Optional[Dict[str, Any]], depth: int) -> Optional[float]:
    """First sampled day on which the deepest mine reached ``depth`` (the series is sampled every 5 days)."""
    if not res:
        return None
    for day, _inc, peak, *_rest in res["series"]:
        if int(peak) >= depth:
            return float(day)
    return None


def effect(results: Sequence[Dict[str, Any]], topo: str, style: str, variant: str) -> Dict[str, Any]:
    """Change against the same style without the feature: income and production (percent) at 6 / 12 / 24 months, days earlier to a mine depth, worlds at 12 months."""
    base, var = pick(results, topo, style, "none"), pick(results, topo, style, variant)
    out: Dict[str, Any] = {"income": {}, "produced": {}, "days_to_depth": {}, "worlds_12mo": None, "world11_shift": None}
    if base is None or var is None:
        return out
    for key in CHECKS:
        sb, sv = cga.snap(base, key), cga.snap(var, key)
        out["income"][key] = cga.pct(cga.income(sv), cga.income(sb)) if sb and sv else None
        out["produced"][key] = cga.pct(cga.produced(sv), cga.produced(sb)) if sb and sv else None
    for depth in DEPTHS:
        a, b = day_of_depth(base, depth), day_of_depth(var, depth)
        out["days_to_depth"][depth] = None if a is None or b is None else b - a
    sb, sv = cga.snap(base, "365"), cga.snap(var, "365")
    if sb and sv:
        out["worlds_12mo"] = float(sv.get("worlds") or 0) - float(sb.get("worlds") or 0)
    d_b, d_v = cga.world_day(base, 11), cga.world_day(var, 11)
    out["world11_shift"] = None if d_b is None or d_v is None else d_v - d_b
    return out


def casual_share(results: Sequence[Dict[str, Any]], topo: str, variant: str) -> Dict[str, Optional[float]]:
    """Income of the casual player (with ``variant``) relative to the always-online optimizer WITHOUT the feature, 6 / 12 / 24 months."""
    c, o = pick(results, topo, "casual", variant), pick(results, topo, "optimizer", "none")
    out: Dict[str, Optional[float]] = {}
    for key in CHECKS:
        sc_, so_ = cga.snap(c, key), cga.snap(o, key)
        out[key] = cga.ratio(cga.income(sc_), cga.income(so_)) if sc_ and so_ else None
    return out


def invariants_ok(results: Sequence[Dict[str, Any]]) -> bool:
    return all(bool((r.get("invariants") or {}).get("ok", True)) for r in results)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _p(v: Optional[float], digits: int = 0) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def _d(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:+,.0f}"


def _sh(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{100.0 * v:.0f}%"


def render_markdown(results: Sequence[Dict[str, Any]]) -> str:
    L = [
        "# Reserve next purchase - value in the corrected model (generated)",
        "",
        "> Measurement only. Generated by `scripts/reserve_next_purchase_analysis.py`; curated reading and the design in `docs/GC_RESERVE_NEXT_PURCHASE.md`.",
        "",
        f"{len(results)} scenarios, policy v2, UNI1 curve, arm `never`, 24 months, gate PL15. Simulator invariants hold in all runs: {invariants_ok(results)}.",
        "",
        "`builds` = one reserved build per planet, `research` = one reserved account research, `both` = the sandbox lever `auto_start`. Change against the same style without the feature (income and cumulative production in percent; days = days earlier (negative) to the deepest mine reaching the level).",
    ]
    for topo in TOPOLOGIES:
        L += ["", f"## {topo}" + (" (one planet)" if topo == "S1" else " (up to 11 planets)"), "", "| Style | Reserve | Income 6 mo | 12 mo | 24 mo | Production 12 mo | 24 mo | Days to L100 / L150 / L200 | Worlds @12 mo | 11th world |", "|---|---|---:|---:|---:|---:|---:|---|---:|---:|"]
        for style in STYLES:
            for variant in VARIANT_ORDER[1:]:
                e = effect(results, topo, style, variant)
                if not e["income"]:
                    continue
                dd = " / ".join(_d(e["days_to_depth"].get(d)) for d in DEPTHS)
                L.append(
                    f"| {style} | {variant} | {_p(e['income']['182.5'])} | {_p(e['income']['365'])} | {_p(e['income']['730'])} | {_p(e['produced']['365'])} | {_p(e['produced']['730'])} | {dd}"
                    f" | {_d(e['worlds_12mo'])} | {_d(e['world11_shift'])} |"
                )
        L += ["", f"Casual income relative to the always-online optimizer without the feature ({topo}):", "", "| Reserve | 6 mo | 12 mo | 24 mo |", "|---|---:|---:|---:|"]
        for variant in VARIANT_ORDER:
            cs = casual_share(results, topo, variant)
            if all(v is None for v in cs.values()):
                continue
            L.append(f"| {variant} | {_sh(cs['182.5'])} | {_sh(cs['365'])} | {_sh(cs['730'])} |")
    L.append("")
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    args = ap.parse_args(argv)
    if args.render_from:
        results = json.loads(Path(args.render_from).read_text(encoding="utf-8"))["results"]
    else:
        specs = build_specs(args.days)
        results = run_matrix(specs, args.workers or max(1, (os.cpu_count() or 2) - 2))
        if args.out_json:
            out = Path(args.out_json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"meta": {"version": ANALYSIS_VERSION, "scenarios": len(specs), "days": args.days}, "results": results}), encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(render_markdown(results) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
