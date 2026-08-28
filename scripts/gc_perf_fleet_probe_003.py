from __future__ import annotations

from pathlib import Path


PATH = Path("game/live_state.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "        from game.fleet import build_active_fleets_payload, fleet_schema_ready\n",
        "        from game.fleet import fleet_schema_ready\n",
        "probe fleet import",
    )

    helper = '''\n\ndef _fleet_probe_slice(player_id: int, *, conn) -> Dict[str, Any]:\n    \"\"\"Cheap active-Fleet structure for the diet poll fingerprint.\n\n    The full Fleet drawer needs planet names, parsed ship/resource JSON and derived\n    timer/progress fields. ``compute_poll_version`` only hashes movement identity,\n    phase and canonical phase deadlines, so the probe reads those columns directly\n    from ``fleet_movements`` and avoids the full HUD reconstruction path.\n    \"\"\"\n    from game.fleet_defs import ACTIVE_FLEET_STATUSES\n\n    placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)\n    rows = conn.execute(\n        f\"\"\"\n        SELECT id, status, arrival_at, return_at, holding_until\n        FROM fleet_movements\n        WHERE player_id = ? AND status IN ({placeholders})\n        ORDER BY id ASC;\n        \"\"\",\n        (int(player_id), *ACTIVE_FLEET_STATUSES),\n    ).fetchall()\n    items = [\n        {\n            \"movement_id\": int(row[\"id\"]),\n            \"status\": str(row[\"status\"] or \"\"),\n            \"arrival_at\": int(float(row[\"arrival_at\"] or 0)),\n            \"return_at\": int(float(row[\"return_at\"] or 0)),\n            \"holding_until\": int(float(row[\"holding_until\"] or 0)),\n        }\n        for row in rows\n    ]\n    count = len(items)\n    return {\n        \"count\": count,\n        \"active_fleet_count\": count,\n        \"items\": items,\n    }\n'''
    anchor = "\ndef probe_poll_version(player_id: int, conn) -> Optional[int]:\n"
    if "def _fleet_probe_slice(" in text:
        raise SystemExit("fleet probe helper already exists")
    text = replace_once(text, anchor, helper + anchor, "probe helper anchor")

    text = replace_once(
        text,
        "            fleets = active_fleets_poll_slice(build_active_fleets_payload(uid, conn=conn))\n",
        "            fleets = _fleet_probe_slice(uid, conn=conn)\n",
        "full Fleet HUD probe call",
    )

    old_fp = '''                    "arrival_at": int(float(item.get("arrival_at") or 0)),\n                    "return_at": int(float(item.get("return_at") or 0)),\n                }\n'''
    new_fp = '''                    "arrival_at": int(float(item.get("arrival_at") or 0)),\n                    "return_at": int(float(item.get("return_at") or 0)),\n                    "holding_until": int(float(item.get("holding_until") or 0)),\n                }\n'''
    text = replace_once(text, old_fp, new_fp, "Fleet fingerprint deadlines")

    sort_anchor = '''            )\n    return {\n        "count": fleets.get("count") or fleets.get("active_fleet_count"),\n        "items": slim_items,\n    }\n'''
    sort_replacement = '''            )\n    # Fingerprint identity must not depend on display/query ordering.\n    slim_items.sort(\n        key=lambda row: (\n            int(row.get("id") or 0),\n            str(row.get("status") or ""),\n            int(row.get("arrival_at") or 0),\n            int(row.get("return_at") or 0),\n            int(row.get("holding_until") or 0),\n        )\n    )\n    return {\n        "count": fleets.get("count") or fleets.get("active_fleet_count"),\n        "items": slim_items,\n    }\n'''
    text = replace_once(text, sort_anchor, sort_replacement, "Fleet fingerprint ordering")

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
