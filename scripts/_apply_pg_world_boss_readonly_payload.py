#!/usr/bin/env python3
"""Apply the tiny GC-PG World Boss read-only payload patch.

This helper exists only because the target module is large; it performs exact,
fail-closed source replacements so the resulting product diff stays tiny.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "game" / "world_boss.py"


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match, found {count}: {old!r}")
    return text.replace(old, new, 1)


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    src = replace_once(
        src,
        "    flush_auto: bool = True,\n) -> Dict[str, Any]:",
        "    flush_auto: bool = False,\n) -> Dict[str, Any]:",
    )
    src = replace_once(
        src,
        '    # Opportunistic auto-fire so "Auto aktiv + CD frei" works without waiting on fleet_worker.\n',
        "    # Read payloads stay mutation-free by default. Auto-fire is owned by\n"
        "    # fleet_worker/tick_world_boss_auto_attacks; flush_auto=True is an\n"
        "    # explicit mutation opt-in for narrow internal/test callers only.\n",
    )
    TARGET.write_text(src, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
