"""Story Ops locales must not be EN-parity for es/fr/pl/pt/ru/tr."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"

STORY_PREFIXES = (
    "story_",
    "nav_story",
    "nav_badge_story",
    "free_shop",
    "inv_ark",
    "inv_story",
    "codex_unlock_story",
)

# Short proper nouns / brands that may legitimately match EN.
BRAND_ALLOWLIST = {
    "Story Ops",
    "Genesis Ark",
    "Living Lattice",
    "Androgyn Echo",
    "Androgyn-Echo",
    "Ark-Token",
    "Free Shop",
    "Timekeeper",
    "Pause",
    "Stop",
    "Ark Signal",
    "Void Patrol",
    "High Command",
    "Imperium",
    "Androgyn",
    "Ferronite",
    "Crytite",
}


def _is_story_key(key: str) -> bool:
    return any(key.startswith(p) for p in STORY_PREFIXES)


def _is_brand_only(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if text in BRAND_ALLOWLIST:
        return True
    # Very short UI tokens
    if len(text) <= 12 and text in BRAND_ALLOWLIST:
        return True
    return False


def test_story_ops_locales_not_en_parity():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    keys = sorted(k for k in en if _is_story_key(k))
    assert len(keys) >= 300

    for locale in ("es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in data]
        assert not missing, f"{locale} missing story keys: {missing[:5]}"

        identical = [
            k
            for k in keys
            if data.get(k) == en.get(k) and not _is_brand_only(str(en.get(k) or ""))
        ]
        # Allow a small residue of brands/MT edge cases; block mass EN-parity.
        assert len(identical) < 80, (
            f"{locale} still EN-parity on {len(identical)} non-brand keys "
            f"(sample: {identical[:8]})"
        )
