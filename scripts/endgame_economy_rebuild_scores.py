#!/usr/bin/env python3
"""Guarded one-shot ranking rebuild for the Endgame Economy V2 activation.

Run only after the service process itself is configured with active / pivot 120 / q3.
The script deliberately refuses every other configuration.
"""

from __future__ import annotations

import json

from game.db import db
from game.production_formula import (
    ENDGAME_PRODUCTION_PIVOT_LEVEL,
    ENDGAME_PRODUCTION_TAIL_POWER,
    endgame_economy_mode,
)
from game.ranking import recalculate_all_rankings


def main() -> int:
    mode = endgame_economy_mode()
    pivot = int(ENDGAME_PRODUCTION_PIVOT_LEVEL)
    power = int(ENDGAME_PRODUCTION_TAIL_POWER)
    if (mode, pivot, power) != ("active", 120, 3):
        raise SystemExit(
            f"refusing V2 score rebuild: expected active/pivot=120/q=3, got "
            f"{mode}/pivot={pivot}/q={power}"
        )

    conn = db()
    try:
        result = recalculate_all_rankings(refresh_scores=True, conn=conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(json.dumps({"ok": True, "mode": mode, "pivot": pivot, "tail_power": power, "result": result}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
