#!/usr/bin/env python3
from pathlib import Path

path = Path("game/messages.py")
src = path.read_text(encoding="utf-8")
old = '''    if cat == "trade":
        return (
            " AND category = 'system' AND ("
            "metadata_json LIKE '%\\\"mission_type\\\":\\\"transport\\\"%' OR "
            "metadata_json LIKE '%\\\"mission_type\\\":\\\"collect\\\"%' OR "
            "metadata_json LIKE '%\\\"mission_type\\\":\\\"deploy\\\"%' OR "
            "metadata_json LIKE '%\\\"mission_type\\\":\\\"recycle\\\"%' OR "
            "metadata_json LIKE '%\\\"report_phase\\\"%'"
            ")",
            [],
        )
'''
new = '''    if cat == "trade":
        patterns = [
            '%"mission_type":"transport"%',
            '%"mission_type":"collect"%',
            '%"mission_type":"deploy"%',
            '%"mission_type":"recycle"%',
            '%"report_phase"%',
        ]
        return (
            " AND category = 'system' AND ("
            + " OR ".join("metadata_json LIKE ?" for _ in patterns)
            + ")",
            patterns,
        )
'''
if old not in src:
    raise SystemExit("target trade category block not found")
src = src.replace(old, new, 1)
path.write_text(src, encoding="utf-8")
