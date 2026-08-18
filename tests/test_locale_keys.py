"""GC-537: locale key audit — all used keys must exist in locale JSON files."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = ROOT / "scripts" / "check_locale_keys.py"
LOCALES_DIR = ROOT / "locales"


def test_all_used_locale_keys_present():
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_no_untranslated_locale_values():
    """Non-German locale values must not be verbatim copies of de.json.

    Guards against the translation regression this test was added for: whole
    strings copy-pasted from German and never actually translated. See
    scripts/audit_locale_keys.py:find_untranslated_strings / the exceptions
    list there for deliberately-shared format templates and brand names.
    """
    sys.path.insert(0, str(ROOT))
    from scripts.audit_locale_keys import find_untranslated_strings

    de = json.loads((LOCALES_DIR / "de.json").read_text(encoding="utf-8"))
    problems: dict[str, list[str]] = {}
    for locale in ("es", "fr", "pl", "pt", "ru", "tr"):
        hits = find_untranslated_strings(locale, de)
        if hits:
            problems[locale] = [key for key, _ in hits]

    assert not problems, f"Untranslated (verbatim German) locale values found: {problems}"
