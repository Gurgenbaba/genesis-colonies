#!/usr/bin/env python3
"""One-shot GC I18N phase-3 cleanup for game/research.py.

Removes German display copy from the canonical research config while preserving
legacy payload fields as locale-resolved compatibility values.
"""

from __future__ import annotations

import re
from pathlib import Path

PATH = Path("game/research.py")


def main() -> int:
    text = PATH.read_text(encoding="utf-8")

    import_anchor = "from .db import begin_write_transaction, commit, rollback, lock_planet_for_update, lock_player_for_update\n"
    if "from .i18n import tr\n" not in text:
        if import_anchor not in text:
            raise SystemExit("research.py import anchor not found")
        text = text.replace(import_anchor, "from .i18n import tr\n" + import_anchor, 1)

    block_start = text.index("RESEARCH_TECHS: Dict[str, Dict[str, Any]] = {")
    block_end = text.index("\n# Account-wide parallel fleet movements", block_start)
    config = text[block_start:block_end]

    config, label_count = re.subn(r'^\s{8}"label":\s*"[^"\n]*",\n', "", config, flags=re.MULTILINE)
    config, desc_count = re.subn(r'^\s{8}"description":\s*"[^"\n]*",\n', "", config, flags=re.MULTILINE)
    if label_count != 12 or desc_count != 12:
        raise SystemExit(f"unexpected research literal counts: labels={label_count}, descriptions={desc_count}")

    text = text[:block_start] + config + text[block_end:]

    old_label = '"label": cfg.get("label", tech),'
    new_label = '"label": tr(str(cfg.get("label_key") or tech)),'
    old_desc = '"description": cfg.get("description", ""),'
    new_desc = '"description": tr(str(cfg.get("description_key") or f"desc_{tech}")),'

    label_payload_count = text.count(old_label)
    desc_payload_count = text.count(old_desc)
    if label_payload_count != 2 or desc_payload_count != 2:
        raise SystemExit(
            f"unexpected legacy payload occurrences: label={label_payload_count}, description={desc_payload_count}"
        )
    text = text.replace(old_label, new_label)
    text = text.replace(old_desc, new_desc)

    final_config = text[block_start:text.index("\n# Account-wide parallel fleet movements", block_start)]
    if re.search(r'^\s{8}"(?:label|description)":', final_config, flags=re.MULTILINE):
        raise SystemExit("raw research label/description field remains in RESEARCH_TECHS")
    if text.count(new_label) != 2 or text.count(new_desc) != 2:
        raise SystemExit("translated compatibility payload verification failed")

    PATH.write_text(text, encoding="utf-8")
    print(
        "research i18n cleanup applied: "
        f"removed {label_count} labels + {desc_count} descriptions; translated compatibility payloads"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
