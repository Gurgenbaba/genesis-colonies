#!/usr/bin/env python3
"""GC-LOCALE-PRE-RESET-SYNC — read-only locale key audit (code vs de/en.json)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.check_locale_keys import (  # noqa: E402
    LOCALES_DIR,
    _iter_source_files,
    _load_json,
    collect_used_keys,
    find_missing,
)

_RE_DATA_I18N = re.compile(
    r"""data-(?:i18n|title-key)=["']([a-zA-Z0-9][a-zA-Z0-9_]*)["']"""
)
_RE_REGISTRY_KEY_FIELD = re.compile(
    r"""\b(?:name_key|description_key|label_key|desc_key)\b\s*[:=]\s*["']([a-zA-Z0-9][a-zA-Z0-9_]*)["']"""
)


def _collect_extra_keys() -> set[str]:
    keys: set[str] = set()
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        keys.update(_RE_DATA_I18N.findall(text))
        keys.update(_RE_REGISTRY_KEY_FIELD.findall(text))
    return keys


def find_unused(locale: str, used: set[str]) -> list[str]:
    data = _load_json(LOCALES_DIR / f"{locale}.json")
    return sorted(k for k in data if k not in used)


def main() -> int:
    used = collect_used_keys() | _collect_extra_keys()
    de_missing = find_missing("de", used)
    en_missing = find_missing("en", used)
    de_unused = find_unused("de", used)
    en_unused = find_unused("en", used)

    print(f"Used keys (code + registries): {len(used)}")
    print(f"de.json entries: {len(_load_json(LOCALES_DIR / 'de.json'))}")
    print(f"en.json entries: {len(_load_json(LOCALES_DIR / 'en.json'))}")

    if de_missing:
        print("\nMissing in de.json:")
        for key in de_missing:
            print(f"- {key}")

    if en_missing:
        print("\nMissing in en.json:")
        for key in en_missing:
            print(f"- {key}")

    if de_unused:
        print(f"\nPossibly unused in de.json ({len(de_unused)}):")
        for key in de_unused[:40]:
            print(f"- {key}")
        if len(de_unused) > 40:
            print(f"... and {len(de_unused) - 40} more")

    if en_unused:
        print(f"\nPossibly unused in en.json ({len(en_unused)}):")
        for key in en_unused[:40]:
            print(f"- {key}")
        if len(en_unused) > 40:
            print(f"... and {len(en_unused) - 40} more")

    if de_missing or en_missing:
        return 1
    print("\nOK — all used locale keys are present in de.json and en.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
