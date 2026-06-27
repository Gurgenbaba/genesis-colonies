#!/usr/bin/env python3
"""Merge rules_panel_* keys from game/game_rules_panel.py into locales/*.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
LOCALE_NAMES = ("de", "en", "fr", "es", "pl", "tr", "ru", "pt")
RULES_LANG = {"fr": "fr", "es": "es", "pl": "pl", "tr": "tr", "ru": "ru", "pt": "pt"}


def _translate_rules_panel_locales() -> dict[str, int]:
    from game.game_rules_panel import RULES_PANEL_STRINGS, all_rules_panel_locale_keys
    from scripts.gc900_translate_locales import translate_batch

    en = RULES_PANEL_STRINGS["en"]
    keys = sorted(all_rules_panel_locale_keys())
    stats: dict[str, int] = {}
    for loc in ("fr", "es", "pl", "tr", "ru", "pt"):
        path = LOCALES / f"{loc}.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        todo = [k for k in keys if k in en and data.get(k) == en.get(k)]
        changed = 0
        batch_size = 15
        print(f"rules_panel translate {loc}: {len(todo)} keys", flush=True)
        for i in range(0, len(todo), batch_size):
            chunk = todo[i : i + batch_size]
            translated = translate_batch(
                [en[k] for k in chunk],
                source="en",
                target=RULES_LANG[loc],
            )
            for key, new_val in zip(chunk, translated):
                if new_val and data.get(key) != new_val:
                    data[key] = new_val
                    changed += 1
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        stats[loc] = changed
        print(f"  {loc}: {changed} updates", flush=True)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--translate", action="store_true", help="Translate EN rules_panel strings")
    args = parser.parse_args()

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
    if args.translate:
        stats = _translate_rules_panel_locales()
        print("rules_panel translations:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
