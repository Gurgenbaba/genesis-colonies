#!/usr/bin/env python3
"""Run the tokenized UNI1 prelaunch reset synchronously before serving traffic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    token = str(os.environ.get("GC_UNI1_PRELAUNCH_RESET_TOKEN", "") or "").strip()
    if not token:
        print("[GC] UNI1 prelaunch reset: no token configured; skipping.")
        return 0

    from game.config import init_config

    init_config()

    from game.uni1_prelaunch import run_uni1_prelaunch_reset_once

    result = run_uni1_prelaunch_reset_once(token)
    print(
        "[GC] UNI1 prelaunch reset: "
        f"skipped={bool(result.get('skipped'))} token={result.get('token')!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
