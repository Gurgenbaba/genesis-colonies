"""One-shot helper: preserve main locale formatting/order and only keep semantic PE value changes."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

LOCALES = ("de", "en", "fr", "es", "pl", "tr", "ru", "pt")
LINE_RE = re.compile(r'^(\s*)"([^"]+)":\s*(.*?)(,?)\s*$')

for locale in LOCALES:
    path = Path("locales") / f"{locale}.json"
    current_text = path.read_text(encoding="utf-8")
    current = json.loads(current_text)
    base_text = subprocess.check_output(
        ["git", "show", f"origin/main:locales/{locale}.json"],
        text=True,
        encoding="utf-8",
    )
    base = json.loads(base_text)
    if set(base) != set(current):
        raise SystemExit(f"{locale}: locale key set changed unexpectedly")

    changed = {key: current[key] for key in current if current[key] != base[key]}
    remaining = set(changed)
    output: list[str] = []
    for raw_line in base_text.splitlines(keepends=True):
        newline = "\n" if raw_line.endswith("\n") else ""
        line = raw_line[:-1] if newline else raw_line
        match = LINE_RE.match(line)
        if not match or match.group(2) not in changed:
            output.append(raw_line)
            continue
        indent, key, _old_value, comma = match.groups()
        output.append(
            f'{indent}{json.dumps(key, ensure_ascii=False)}: '
            f'{json.dumps(changed[key], ensure_ascii=False)}{comma}{newline}'
        )
        remaining.discard(key)

    if remaining:
        raise SystemExit(f"{locale}: could not rewrite keys: {sorted(remaining)}")

    cleaned = "".join(output)
    if json.loads(cleaned) != current:
        raise SystemExit(f"{locale}: minimized output changed locale semantics")
    path.write_text(cleaned, encoding="utf-8")
    print(f"{locale}: kept {len(changed)} semantic value change(s)")
