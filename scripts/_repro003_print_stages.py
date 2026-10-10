#!/usr/bin/env python3
import json
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/concurrency_repro/repro003/stages_attribution.json")
d = json.loads(p.read_text(encoding="utf-8"))
for mode, payload in (d.get("modes") or {}).items():
    timed = payload.get("timed") or {}
    print(
        f"=== {mode} rc={payload.get('returncode')} "
        f"total_ms={timed.get('total_ms')} longest={timed.get('longest_stage')}"
    )
    if payload.get("parse_error"):
        print(" PARSE", payload.get("parse_error"))
        print(" STDERR", (payload.get("stderr_tail") or "")[-800:])
    for st in timed.get("stages") or []:
        s = st.get("summary") or {}
        print(
            f"  {st['stage']:20s} {st['duration_ms']:10.1f}ms ok={st.get('ok')} "
            f"mode={s.get('mode')} players={s.get('players_updated')} "
            f"dirty={s.get('dirty_cleared')} skipped={s.get('skipped_interval')}"
        )
