#!/usr/bin/env python3
"""Replace direct schema_ready(db()) calls with a short-lived checked connection."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"

HELPER = '''\n\ndef _schema_ready_with_short_conn(check_fn) -> bool:\n    """Run a schema readiness probe without leaking a pooled DB connection."""\n    conn = db()\n    try:\n        return bool(check_fn(conn))\n    finally:\n        conn.close()\n'''


def main() -> int:
    src = APP.read_text(encoding="utf-8")
    if "def _schema_ready_with_short_conn(" not in src:
        anchor = '\n\ndef _fleet_write_transaction(work):\n'
        if src.count(anchor) != 1:
            raise SystemExit("schema-ready helper anchor not unique")
        src = src.replace(anchor, HELPER + anchor, 1)

    pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*_schema_ready)\(db\(\)\)")
    src, count = pattern.subn(r"_schema_ready_with_short_conn(\1)", src)
    if count < 1:
        raise SystemExit("expected at least one direct schema_ready(db()) call")

    if pattern.search(src):
        raise SystemExit("direct schema_ready(db()) call remained after patch")

    APP.write_text(src, encoding="utf-8")
    print(f"patched {count} leaking schema readiness probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
