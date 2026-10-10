#!/usr/bin/env python3
"""Print REPRO-003 v2 differential summary + stage hold stats."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path("artifacts/concurrency_repro/repro003_v2")
summary = json.loads((OUT / "repro003_summary.json").read_text(encoding="utf-8"))
trees = (summary.get("differential") or summary).get("trees") or {}

print("=== DIFFERENTIAL (valid auth, absolute seed) ===")
for name in ("A_9027ec0", "B_b0fade84", "C_7f3990b"):
    t = trees.get(name) or {}
    print(f"\n{name} sha={str(t.get('sha') or '')[:12]}")
    print(f"  control: {t.get('control_game_state')}")
    print(f"  maint:   {t.get('maintenance_game_state')}")
    print(f"  penalty: {t.get('maintenance_penalty')}")
    ls = t.get("longest_writer_stage") or {}
    print(
        f"  longest_stage: {ls.get('stage')} {ls.get('duration_ms')}ms "
        f"summary={ls.get('summary')}"
    )
    print(f"  slow5 c/m: {t.get('slow5_control_avg')} / {t.get('slow5_maint_avg')}")

# Aggregate in-process stage durations across all maint reports
stage_ms = defaultdict(list)
ranking_modes = defaultdict(int)
for rep in OUT.glob("*/*_maint_report.json"):
    data = json.loads(rep.read_text(encoding="utf-8"))
    if data.get("INVALID"):
        print("INVALID", rep)
        continue
    for sr in data.get("stage_reports") or []:
        timed = sr.get("timed") or {}
        for st in timed.get("stages") or []:
            stage_ms[st["stage"]].append(float(st.get("duration_ms") or 0))
            if st["stage"] == "ranking":
                mode = str((st.get("summary") or {}).get("mode") or "?")
                ranking_modes[mode] += 1

print("\n=== IN-PROCESS STAGE durations (all maint ticks) ===")
for stage, vals in sorted(stage_ms.items(), key=lambda kv: -max(kv[1] or [0])):
    vals = sorted(vals)
    if not vals:
        continue
    p95 = vals[min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))]
    print(
        f"  {stage:20s} n={len(vals):3d} "
        f"p50={vals[len(vals)//2]:8.1f} p95={p95:8.1f} max={vals[-1]:8.1f}"
    )
print("ranking modes:", dict(ranking_modes))
print(
    "\nGATES:",
    f"SYSTEM={summary.get('SYSTEM_FAILURE_MODE')} "
    f"HIST={summary.get('HISTORICAL_REGRESSION')} "
    f"RC={summary.get('ROOT_CAUSE')}",
)
