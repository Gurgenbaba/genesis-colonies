
"""GC-FLT-UX-02 — partial-success bulk launch for saved fleet presets.

This module is an orchestration adapter only. Fleet validation, math, stock
deduction, slot accounting, protection and diplomacy stay authoritative in
``game.fleet.send_fleet`` and existing ``fleet_movements`` state.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Mapping, Sequence, Tuple

MAX_BULK_PRESETS = 50
SAFE_SKIP_CONTEXT_KEYS = (
    "attack_limit",
    "noob_protection",
    "troop_slots_needed",
    "troop_berths",
)


def _json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw in (None, ""):
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _normalize_preset_ids(values: Sequence[Any]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in values:
        try:
            preset_id = int(raw)
        except (TypeError, ValueError):
            continue
        if preset_id <= 0 or preset_id in seen:
            continue
        seen.add(preset_id)
        out.append(preset_id)
    return out


def _safe_skip_context(result: Any) -> Dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    return {
        key: result[key]
        for key in SAFE_SKIP_CONTEXT_KEYS
        if result.get(key) is not None
    }


def _skip(preset_id: int, name: str, reason: str, result: Any = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "preset_id": int(preset_id),
        "name": str(name or ""),
        "reason": str(reason or "generic"),
    }
    context = _safe_skip_context(result)
    if context:
        row["context"] = context
    return row


def _create_batch(player_id: int, *, conn) -> int:
    now = float(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO fleet_batches
            (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
        VALUES (?, 'custom', 'bulk_presets', 'running', 0, ?, ?);
        """,
        (int(player_id), now, now),
    )
    return int(cur.lastrowid)


def launch_selected_presets(
    player_id: int,
    origin_planet_id: int,
    preset_ids: Sequence[Any],
    *,
    conn,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    """Launch selected owned presets sequentially with partial success.

    Normal per-preset validation failures are collected in ``skipped`` and do
    not roll back successful launches. Structural request errors remain fatal.
    """
    from .fleet import send_fleet
    from .fleet_calc import normalize_ships

    ids = _normalize_preset_ids(preset_ids)
    if not ids:
        return False, "bulk_no_selection", None
    if len(ids) > MAX_BULK_PRESETS:
        return False, "bulk_too_many_presets", None

    placeholders = ",".join("?" for _ in ids)
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM fleet_presets WHERE player_id = ? AND id IN ({placeholders});",
        (int(player_id), *ids),
    )
    presets = {int(row["id"]): dict(row) for row in cur.fetchall()}

    started: list[Dict[str, Any]] = []
    skipped: list[Dict[str, Any]] = []
    batch_id: int | None = None

    for preset_id in ids:
        preset = presets.get(int(preset_id))
        if not preset:
            skipped.append(_skip(preset_id, "", "bulk_preset_not_found"))
            continue

        name = str(preset.get("name") or "")
        mission = str(preset.get("mission_type") or "").strip().lower()
        try:
            galaxy = int(preset.get("target_galaxy") or 0)
            system = int(preset.get("target_system") or 0)
            position = int(preset.get("target_position") or 0)
        except (TypeError, ValueError):
            galaxy = system = position = 0

        ships = normalize_ships(_json_object(preset.get("ships_json")))
        if not ships:
            skipped.append(_skip(preset_id, name, "no_ships"))
            continue
        if not mission or galaxy <= 0 or system <= 0 or position <= 0:
            skipped.append(_skip(preset_id, name, "bulk_preset_incomplete"))
            continue

        if batch_id is None:
            batch_id = _create_batch(int(player_id), conn=conn)

        resources = _json_object(preset.get("resources_json"))
        try:
            speed_percent = int(preset.get("speed_percent") or 100)
        except (TypeError, ValueError):
            speed_percent = 100

        ok, reason, result = send_fleet(
            player_id=int(player_id),
            origin_planet_id=int(origin_planet_id),
            target_galaxy=galaxy,
            target_system=system,
            target_position=position,
            mission_type=mission,
            ships=ships,
            resources=resources,
            speed_percent=speed_percent,
            preset_id=int(preset_id),
            batch_id=int(batch_id),
            conn=conn,
        )
        if not ok:
            skipped.append(_skip(preset_id, name, reason or "generic", result))
            continue

        fleet = result.get("fleet") if isinstance(result, Mapping) else {}
        fleet = fleet if isinstance(fleet, Mapping) else {}
        started.append(
            {
                "preset_id": int(preset_id),
                "name": name,
                "mission_type": mission,
                "target_galaxy": galaxy,
                "target_system": system,
                "target_position": position,
                "movement_id": int(fleet.get("id") or fleet.get("movement_id") or 0),
                "status": str(fleet.get("status") or "outbound"),
            }
        )

    if batch_id is not None:
        conn.execute(
            """
            UPDATE fleet_batches
            SET status = 'completed', total_fleets = ?, updated_at = ?
            WHERE id = ? AND player_id = ?;
            """,
            (len(started), float(time.time()), int(batch_id), int(player_id)),
        )

    return True, "", {
        "batch_id": int(batch_id) if batch_id is not None else None,
        "started_count": len(started),
        "skipped_count": len(skipped),
        "started": started,
        "skipped": skipped,
    }
