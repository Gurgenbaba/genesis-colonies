#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "scripts/apply_gc_player_changelog.py"

text = APPLY.read_text(encoding="utf-8")
old = '    specific = _specific_player_summary(f"{scope} {cleaned}")\n    if specific:\n'
new = '    specific = None if technical else _specific_player_summary(f"{scope} {cleaned}")\n    if specific:\n'
if old not in text and new not in text:
    raise SystemExit("player changelog humanizer anchor not found")
if old in text:
    APPLY.write_text(text.replace(old, new, 1), encoding="utf-8")
print("GC player changelog technical-prefix fix applied")
