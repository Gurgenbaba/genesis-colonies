"""Generate docs/GC-864_LOOT_BALANCE_TABLE.md from live loot pools."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.economy_balance import generate_loot_balance_table_markdown

OUT = ROOT / "docs" / "GC-864_LOOT_BALANCE_TABLE.md"


def main() -> None:
    OUT.write_text(generate_loot_balance_table_markdown(), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
