#!/usr/bin/env python3
"""Emit a read-only V1/V2 Endgame Economy ranking comparison as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from game.db import db
from game.endgame_economy_shadow import build_shadow_ranking_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--noob-factor", type=int, default=5)
    parser.add_argument("--max-pair-examples", type=int, default=250)
    args = parser.parse_args()

    conn = db()
    try:
        report = build_shadow_ranking_report(
            conn=conn,
            noob_factor=max(1, int(args.noob_factor)),
            max_pair_examples=max(0, int(args.max_pair_examples)),
        )
    finally:
        conn.close()

    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
