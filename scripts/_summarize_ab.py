#!/usr/bin/env python3
"""Summarize prod infinity-load A/B artifacts."""
from __future__ import annotations

import json
from pathlib import Path

s = json.loads(Path("artifacts/prod_infinity_load_ab/summary.json").read_text(encoding="utf-8"))
for scale, data in s["scales"].items():
    print(f"== {scale} bytes={data.get('seed_bytes')} factor={data.get('factor')} ==")
    for label, v in data["labels"].items():
        r = v.get("report") or {}
        gs = ((r.get("api_game_state") or {}).get("timing") or {})
        c012 = ((r.get("count_claimable_directives") or {}).get("timing") or {})
        c013 = ((r.get("count_pending_government_votes") or {}).get("timing") or {})
        e013 = r.get("explain_state_013_shape") or {}
        e_st = r.get("explain_stable_gov_shape") or {}
        tc = r.get("table_counts") or {}
        print(
            f"  {label}: gs_p50={gs.get('p50_ms')} gs_p95={gs.get('p95_ms')} gs_max={gs.get('max_ms')} "
            f"out2s={(r.get('api_game_state') or {}).get('outlier_gt_2000ms')} "
            f"claim_p50={c012.get('p50_ms')} gov_p50={c013.get('p50_ms')} "
            f"013_ms={e013.get('one_shot_ms')} stable_ms={e_st.get('one_shot_ms')} "
            f"cycles={tc.get('gd_cycles')} votes={tc.get('gd_votes')} dirs={tc.get('player_directives')} "
            f"rc={v.get('returncode')}"
        )
        plan = e013.get("plan") or []
        if plan:
            print("    013plan0", plan[0])
        plan2 = e_st.get("plan") or []
        if plan2:
            print("    stableplan0", plan2[0])
