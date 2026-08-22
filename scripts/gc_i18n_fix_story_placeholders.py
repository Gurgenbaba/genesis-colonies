#!/usr/bin/env python3
"""One-shot GC-I18N-HARDENING repair for translated Story Ark placeholders.

Locale translators changed the *identifier* inside ``%(amount)s`` and one Russian
translation also localized the trailing ``s`` formatter. Runtime formatting passes
``amount=...``, so those strings leak raw placeholders to players.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
KEYS = ("story_ark_token_chapter_body", "story_ark_token_toast")
_LOOSE_PERCENT = re.compile(r"%\([^)]+\)[A-Za-zА-Яа-яЁё]")


def main() -> int:
    changed_files: list[str] = []
    for path in sorted(LOCALES.glob("*.json")):
        if path.name == "de.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for key in KEYS:
            value = str(data.get(key) or "")
            if not value or "%" not in value:
                continue
            fixed, count = _LOOSE_PERCENT.subn("%(amount)s", value, count=1)
            if count and fixed != value:
                data[key] = fixed
                changed = True
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed_files.append(path.name)

    print("Story placeholder repair:", ", ".join(changed_files) if changed_files else "no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
