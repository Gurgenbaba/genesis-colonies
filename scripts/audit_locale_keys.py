#!/usr/bin/env python3
"""GC-900C — read-only locale audit across all supported languages."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from game.i18n import SUPPORTED_LOCALES  # noqa: E402
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

_GERMAN_CHARS = re.compile(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]")
_FORBIDDEN_NON_DE = (
    "Abbau-Pfad",
    "Deuterium",
    "Mining Path",
    "Resource Path",
)
_FORBIDDEN_EN = _FORBIDDEN_NON_DE + ("Ferronit",)


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


def _find_german_strings(locale: str) -> list[tuple[str, str]]:
    if locale == "de":
        return []
    data = _load_json(LOCALES_DIR / f"{locale}.json")
    hits: list[tuple[str, str]] = []
    for key, val in data.items():
        if key.startswith("language_name_"):
            continue
        if isinstance(val, str) and _GERMAN_CHARS.search(val):
            if re.search(r"\b(und|der|die|das|nicht|für|Sie|Ihr|Spieler|Gebäude|Forschung|Allianz|Kolonie|Schiff|Flotte|Werft|Stufe)\b", val, re.I):
                hits.append((key, val))
            elif "ß" in val:
                hits.append((key, val))
    return hits


def _find_forbidden(locale: str) -> list[str]:
    data = _load_json(LOCALES_DIR / f"{locale}.json")
    hits: list[str] = []
    for key, val in data.items():
        if not isinstance(val, str):
            continue
        if locale == "en":
            if re.search(r"Ferronit(?!e)", val):
                hits.append(f"{key}: Ferronit")
            for term in ("Abbau-Pfad", "Deuterium", "Mining Path", "Resource Path"):
                if term in val:
                    hits.append(f"{key}: {term}")
                    break
        else:
            for term in _FORBIDDEN_NON_DE:
                if term in val:
                    hits.append(f"{key}: {term}")
                    break
    return hits


def main() -> int:
    used = collect_used_keys() | _collect_extra_keys()
    de = _load_json(LOCALES_DIR / "de.json")
    failed = False

    print(f"Used keys (code + registries): {len(used)}")
    print(f"de.json entries: {len(de)}")

    for locale in sorted(SUPPORTED_LOCALES):
        path = LOCALES_DIR / f"{locale}.json"
        if not path.exists():
            print(f"\n{locale}: MISSING FILE")
            failed = True
            continue
        data = _load_json(path)
        used_missing = find_missing(locale, used)
        canon_missing = sorted(set(de) - set(data))
        extra = sorted(set(data) - set(de))
        unused = find_unused(locale, used)
        german = _find_german_strings(locale)
        forbidden = _find_forbidden(locale)

        print(f"\n== {locale}.json ==")
        print(f"entries: {len(data)} | missing used: {len(used_missing)} | missing vs de: {len(canon_missing)} | extra vs de: {len(extra)}")

        if used_missing:
            failed = True
            print("Missing used keys:")
            for key in used_missing[:15]:
                print(f"- {key}")
            if len(used_missing) > 15:
                print(f"... and {len(used_missing) - 15} more")

        if canon_missing:
            failed = True
            print("Missing vs de.json:")
            for key in canon_missing[:10]:
                print(f"- {key}")

        if german:
            failed = True
            print(f"German strings ({len(german)}):")
            for key, val in german[:5]:
                print(f"- {key}: {val[:60]}")

        if forbidden:
            failed = True
            print(f"Forbidden terms ({len(forbidden)}):")
            for hit in forbidden[:5]:
                print(f"- {hit}")

        if unused:
            print(f"Possibly unused ({len(unused)}) — first 5:")
            for key in unused[:5]:
                print(f"- {key}")

    if failed:
        return 1
    print("\nOK — locale audit passed for all supported languages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
