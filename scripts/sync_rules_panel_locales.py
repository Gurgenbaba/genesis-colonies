#!/usr/bin/env python3
"""Merge rules_panel_* keys from game/game_rules_panel.py into locales/*.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
LOCALE_NAMES = ("de", "en", "fr", "es", "pl", "tr", "ru", "pt")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from game.game_rules_panel import RULES_PANEL_STRINGS, all_rules_panel_locale_keys

    expected = set(all_rules_panel_locale_keys())
    changed = 0
    for loc in LOCALE_NAMES:
        strings = RULES_PANEL_STRINGS.get(loc) or RULES_PANEL_STRINGS["en"]
        missing = expected - set(strings.keys())
        if missing:
            print(f"WARN {loc}: missing keys {sorted(missing)[:5]}… ({len(missing)} total)")
        path = LOCALES / f"{loc}.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for key, value in strings.items():
            if data.get(key) != value:
                data[key] = value
                changed += 1
        # Drop stale codex game_rules keys if present
        stale = [k for k in data if k.startswith("codex_game_rules_")]
        for key in stale:
            del data[key]
            changed += 1
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print(f"sync_rules_panel_locales: {changed} updates across {len(LOCALE_NAMES)} locales")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
