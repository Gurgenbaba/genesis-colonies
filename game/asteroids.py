"""Galaxy asteroid belt — temporary harvestable fields (GC-AST).

Owner for spawn, TTL, claim, and loot rolls. Fleet send/arrival stays in ``fleet.py``
(mission ``recycle`` + ``harvest_reclaimer``). Galaxy attach stays in ``galaxy.py``.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .db import table_exists
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

ASTEROID_TABLE = "asteroid_fields"
ENGAGEMENT_TABLE = "asteroid_engagements"

STATUS_ACTIVE = "active"
STATUS_CLAIMED = "claimed"
STATUS_EXPIRED = "expired"

TTL_SECONDS = 2 * 3600
MAX_ACTIVE_ASTEROIDS = 15
INTER_WAVE_COOLDOWN_SEC = 45 * 60
BELT_SYSTEMS_PER_WAVE = 2
BELT_SIZE_RANGE = (3, 6)
DENSE_SYSTEM_LIMIT = 8
# How far down the density ranking we search for free classic slots when spawning.
SPAWN_SEARCH_SYSTEM_LIMIT = 64

SPAWN_RUNTIME_KEY = "asteroid_belt_last_spawn_at"

# Catalog: weighted types with resource split hints.
# Each resource (metal / crystal / fuel_cells) rolls independently in this band.
ASTEROID_RESOURCE_RANGE = (500_000, 5_000_000)

ASTEROID_CATALOG: Dict[str, Dict[str, Any]] = {
    "ferronite_rock": {
        "name_key": "asteroid_type_ferronite_rock",
        "desc_key": "asteroid_type_ferronite_rock_desc",
        "spawn_weight": 35,
        "split": {"metal": 0.70, "crystal": 0.25, "fuel_cells": 0.05},
        "resource_range": ASTEROID_RESOURCE_RANGE,
    },
    "crytite_shard": {
        "name_key": "asteroid_type_crytite_shard",
        "desc_key": "asteroid_type_crytite_shard_desc",
        "spawn_weight": 30,
        "split": {"metal": 0.25, "crystal": 0.70, "fuel_cells": 0.05},
        "resource_range": ASTEROID_RESOURCE_RANGE,
    },
    "fuel_ice": {
        "name_key": "asteroid_type_fuel_ice",
        "desc_key": "asteroid_type_fuel_ice_desc",
        "spawn_weight": 20,
        "split": {"metal": 0.15, "crystal": 0.15, "fuel_cells": 0.70},
        "resource_range": ASTEROID_RESOURCE_RANGE,
    },
    "mixed_belt": {
        "name_key": "asteroid_type_mixed_belt",
        "desc_key": "asteroid_type_mixed_belt_desc",
        "spawn_weight": 15,
        "split": {"metal": 0.40, "crystal": 0.40, "fuel_cells": 0.20},
        "resource_range": ASTEROID_RESOURCE_RANGE,
    },
}


def _now() -> float:
    return time.time()


def asteroid_schema_ready(conn) -> bool:
    return table_exists(conn, ASTEROID_TABLE)


def engagement_schema_ready(conn) -> bool:
    return table_exists(conn, ENGAGEMENT_TABLE)


def merge_asteroid_resource_meta(
    base: Mapping[str, Any] | None,
    meta_src: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Keep asteroid hunt stamps when rewriting fleet resources_json."""
    out: Dict[str, Any] = dict(base or {})
    src = meta_src or {}
    aid = int(src.get("asteroid_id") or out.get("asteroid_id") or 0)
    if aid > 0:
        out["asteroid_id"] = aid
    key = str(src.get("asteroid_key") or out.get("asteroid_key") or "").strip()
    if key:
        out["asteroid_key"] = key
    return out


def record_asteroid_engagement(
    player_id: int,
    asteroid_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> bool:
    """Durable hunt lock — survives arrival/recall resources_json wipes."""
    if not player_id or not asteroid_id or not engagement_schema_ready(conn):
        return False
    ts = float(now if now is not None else _now())
    conn.execute(
        """
        INSERT INTO asteroid_engagements (player_id, asteroid_id, engaged_at)
        VALUES (?, ?, ?)
        ON CONFLICT(player_id, asteroid_id) DO NOTHING;
        """,
        (int(player_id), int(asteroid_id), ts),
    )
    return True


def player_engaged_asteroid_ids(
    player_id: int,
    *,
    conn,
) -> Set[int]:
    if not player_id or not engagement_schema_ready(conn):
        return set()
    rows = conn.execute(
        """
        SELECT asteroid_id FROM asteroid_engagements
        WHERE player_id = ?;
        """,
        (int(player_id),),
    ).fetchall()
    out: Set[int] = set()
    for row in rows:
        try:
            aid = int(row["asteroid_id"])
            if aid > 0:
                out.add(aid)
        except (TypeError, ValueError, KeyError):
            continue
    return out


def viewer_asteroid_fleet_status_map(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map asteroid_id → outbound/returning fleet ETA for this viewer.

    Prefer coords of the live field at the fleet target; stamped ``asteroid_id``
    is only used when that field is still active (avoids stale-id miss).
    """
    if not player_id or not table_exists(conn, "fleet_movements"):
        return {}
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT id, status, arrival_at, resources_json,
               target_galaxy, target_system, target_position
        FROM fleet_movements
        WHERE player_id = ?
          AND mission_type = 'recycle'
          AND status IN ('outbound', 'returning');
        """,
        (int(player_id),),
    ).fetchall()
    by_id: Dict[int, Dict[str, Any]] = {}
    active_ids: Optional[Set[int]] = None
    for row in rows:
        status = str(row["status"] or "").strip().lower()
        stamped_id = 0
        try:
            import json

            raw = row["resources_json"]
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
            stamped_id = int((payload or {}).get("asteroid_id") or 0)
        except Exception:
            stamped_id = 0

        aid = 0
        # Always resolve against the active field at target coords first —
        # stamped ids go stale after TTL respawn at the same slot.
        try:
            g, s, p = (
                int(row["target_galaxy"]),
                int(row["target_system"]),
                int(row["target_position"]),
            )
        except (TypeError, ValueError, KeyError):
            g = s = p = 0
        if g > 0 and s > 0 and p > 0:
            ast = get_active_asteroid_at(g, s, p, conn=conn, now=ts)
            if ast:
                aid = int(ast["id"])
        if aid <= 0 and stamped_id > 0:
            if active_ids is None:
                active_ids = {
                    int(a["id"])
                    for a in list_active_asteroids(
                        conn=conn, now=ts, limit=MAX_ACTIVE_ASTEROIDS + 5
                    )
                }
            if stamped_id in active_ids:
                aid = stamped_id
        if aid <= 0:
            continue
        arrival = row["arrival_at"]
        try:
            arrival_f = float(arrival) if arrival is not None else None
        except (TypeError, ValueError):
            arrival_f = None
        prev = by_id.get(aid)
        # Prefer outbound over returning; earliest arrival wins.
        if prev and prev.get("fleet_status") == "outbound" and status != "outbound":
            continue
        if prev and status == prev.get("fleet_status"):
            prev_arr = prev.get("arrival_at")
            if (
                prev_arr is not None
                and arrival_f is not None
                and float(prev_arr) <= arrival_f
            ):
                continue
        by_id[aid] = {
            "fleet_status": status,
            "arrival_at": arrival_f,
            "movement_id": int(row["id"]),
            "engaged": True,
        }
    return by_id


def enrich_asteroid_viewer_state(
    asteroid: Mapping[str, Any],
    *,
    engaged_ids: Set[int],
    fleet_map: Mapping[int, Mapping[str, Any]],
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Attach viewer hunt flags onto an asteroid payload."""
    out = dict(asteroid)
    aid = int(out.get("id") or 0)
    fleet = dict(fleet_map.get(aid) or {})
    engaged = bool(aid and (aid in engaged_ids or fleet.get("engaged")))
    status = str(fleet.get("fleet_status") or "")
    arrival = fleet.get("arrival_at")
    try:
        arrival_f = float(arrival) if arrival is not None else None
    except (TypeError, ValueError):
        arrival_f = None
    ts = float(now if now is not None else _now())
    # Consistent "Unterwegs": any outbound hunt, including ETA still in the future.
    en_route = bool(status == "outbound")
    if not en_route and engaged and arrival_f is not None and arrival_f > ts:
        en_route = True
    out["viewer_engaged"] = engaged
    out["viewer_fleet_status"] = status if engaged else ""
    out["viewer_arrival_at"] = arrival_f
    out["viewer_en_route"] = en_route
    out["viewer_harvest_locked"] = en_route
    return out


def build_asteroid_board_entries(
    *,
    conn,
    now: Optional[float] = None,
    current_galaxy: Optional[int] = None,
    current_system: Optional[int] = None,
    viewer_player_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """UI rows for the Galaxy asteroid board (jump links + TTL sort)."""
    from .galaxy import format_coordinates, galaxy_view_href

    ts = float(now if now is not None else _now())
    expire_due_asteroids(conn=conn, now=ts)
    engaged_ids: Set[int] = set()
    fleet_map: Dict[int, Dict[str, Any]] = {}
    if viewer_player_id is not None and int(viewer_player_id) > 0:
        vid = int(viewer_player_id)
        engaged_ids = player_engaged_asteroid_ids(vid, conn=conn)
        fleet_map = viewer_asteroid_fleet_status_map(vid, conn=conn, now=ts)
        # Coords engagement without id still marks engaged via enrich when fleet matches.
        for aid, meta in fleet_map.items():
            if meta.get("engaged"):
                engaged_ids.add(int(aid))
    entries: List[Dict[str, Any]] = []
    for row in list_active_asteroids(conn=conn, now=ts, limit=MAX_ACTIVE_ASTEROIDS + 5):
        enriched = enrich_asteroid_viewer_state(
            row, engaged_ids=engaged_ids, fleet_map=fleet_map, now=ts
        )
        # Keep engaged hunts visible with en-route state (no silent vanish).
        g = int(enriched["galaxy"])
        s = int(enriched["system"])
        p = int(enriched["position"])
        coords = format_coordinates(g, s, p)
        href = galaxy_view_href(coords) or f"/galaxy?q={coords}"
        remaining = max(0, int(float(enriched.get("expires_at") or 0) - ts))
        entries.append(
            {
                "id": int(enriched["id"]),
                "asteroid_key": enriched["asteroid_key"],
                "name_key": enriched["name_key"],
                "desc_key": enriched.get("desc_key") or "",
                "galaxy": g,
                "system": s,
                "position": p,
                "coords": coords,
                "metal": int(enriched.get("metal") or 0),
                "crystal": int(enriched.get("crystal") or 0),
                "fuel_cells": int(enriched.get("fuel_cells") or 0),
                "total": int(enriched.get("total") or 0),
                "expires_at": float(enriched.get("expires_at") or 0),
                "ttl_remaining_seconds": remaining,
                "recycler_slots_needed": int(enriched.get("recycler_slots_needed") or 0),
                "galaxy_href": href,
                "is_current_system": (
                    current_galaxy is not None
                    and current_system is not None
                    and g == int(current_galaxy)
                    and s == int(current_system)
                ),
                "viewer_engaged": bool(enriched.get("viewer_engaged")),
                "viewer_fleet_status": str(enriched.get("viewer_fleet_status") or ""),
                "viewer_arrival_at": enriched.get("viewer_arrival_at"),
                "viewer_en_route": bool(enriched.get("viewer_en_route")),
                "viewer_harvest_locked": bool(enriched.get("viewer_harvest_locked")),
            }
        )
    entries.sort(
        key=lambda e: (
            0 if e.get("viewer_en_route") else 1 if e.get("viewer_engaged") else 2,
            int(e["expires_at"]),
            int(e["galaxy"]),
            int(e["system"]),
            int(e["position"]),
        )
    )
    return entries


def _reclaimer_cargo() -> int:
    from .fleet_defs import SHIPS

    return max(0, int((SHIPS.get("harvest_reclaimer") or {}).get("cargo") or 0))


def estimate_reclaimer_slots_needed(
    metal: int, crystal: int, fuel_cells: int = 0
) -> int:
    cargo = _reclaimer_cargo()
    total = max(0, int(metal)) + max(0, int(crystal)) + max(0, int(fuel_cells))
    if total <= 0 or cargo <= 0:
        return 0
    return (total + cargo - 1) // cargo


def _roll_loot(asteroid_key: str, *, rng: Optional[random.Random] = None) -> Dict[str, int]:
    """Roll metal/crystal/fuel independently in the catalog resource band.

    Type ``split`` biases which resources land toward the high end of the band
    (still every resource stays within ``resource_range``).
    """
    catalog = ASTEROID_CATALOG.get(str(asteroid_key)) or ASTEROID_CATALOG["mixed_belt"]
    roll = rng or random
    lo, hi = catalog.get("resource_range") or ASTEROID_RESOURCE_RANGE
    lo_i, hi_i = int(lo), int(hi)
    if hi_i < lo_i:
        lo_i, hi_i = hi_i, lo_i
    split = dict(catalog.get("split") or {})
    equal = 1.0 / 3.0
    out: Dict[str, int] = {}
    for key in ("metal", "crystal", "fuel_cells"):
        share = float(split.get(key) or equal)
        # Map share vs equal into [0, 1] bias toward hi for preferred resources.
        bias = max(0.0, min(1.0, 0.5 + (share - equal) * 1.25))
        jitter = roll.uniform(-0.08, 0.08)
        t = max(0.0, min(1.0, bias + jitter))
        span = hi_i - lo_i
        out[key] = int(lo_i + round(span * t))
        out[key] = max(lo_i, min(hi_i, out[key]))
    return out


def _pick_weighted_key(*, rng: Optional[random.Random] = None) -> str:
    roll = rng or random
    keys = list(ASTEROID_CATALOG.keys())
    weights = [int(ASTEROID_CATALOG[k]["spawn_weight"]) for k in keys]
    return str(roll.choices(keys, weights=weights, k=1)[0])


def _row_to_asteroid(row) -> Dict[str, Any]:
    key = str(row["asteroid_key"] or "mixed_belt")
    catalog = ASTEROID_CATALOG.get(key) or {}
    metal = int(row["metal"] or 0)
    crystal = int(row["crystal"] or 0)
    fuel = int(row["fuel_cells"] or 0)
    total = metal + crystal + fuel
    g = int(row["galaxy"])
    s = int(row["system"])
    p = int(row["position"])
    return {
        "id": int(row["id"]),
        "asteroid_key": key,
        "name_key": str(catalog.get("name_key") or "asteroid_type_mixed_belt"),
        "desc_key": str(catalog.get("desc_key") or "asteroid_type_mixed_belt_desc"),
        "galaxy": g,
        "system": s,
        "position": p,
        "coords": f"[{g}:{s}:{p}]",
        "metal": metal,
        "crystal": crystal,
        "fuel_cells": fuel,
        "total": total,
        "status": str(row["status"] or STATUS_ACTIVE),
        "spawned_at": float(row["spawned_at"] or 0),
        "expires_at": float(row["expires_at"] or 0),
        "claimed_at": float(row["claimed_at"]) if row["claimed_at"] is not None else None,
        "claimed_by_player_id": (
            int(row["claimed_by_player_id"])
            if row["claimed_by_player_id"] is not None
            else None
        ),
        "recycler_slots_needed": estimate_reclaimer_slots_needed(metal, crystal, fuel),
        "fleet_deep_link": (
            f"/fleet?mission=recycle"
            f"&target_galaxy={g}&target_system={s}&target_position={p}"
        ),
    }


def list_active_asteroids(
    *,
    conn,
    now: Optional[float] = None,
    limit: int = 64,
) -> List[Dict[str, Any]]:
    if not asteroid_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT * FROM asteroid_fields
        WHERE status = ?
          AND expires_at > ?
        ORDER BY id ASC
        LIMIT ?;
        """,
        (STATUS_ACTIVE, ts, max(1, int(limit))),
    ).fetchall()
    return [_row_to_asteroid(r) for r in rows]


def get_active_asteroid_at(
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not asteroid_schema_ready(conn):
        return None
    ts = float(now if now is not None else _now())
    row = conn.execute(
        """
        SELECT * FROM asteroid_fields
        WHERE status = ?
          AND expires_at > ?
          AND galaxy = ? AND system = ? AND position = ?
        ORDER BY id DESC
        LIMIT 1;
        """,
        (STATUS_ACTIVE, ts, int(galaxy), int(system), int(position)),
    ).fetchone()
    if not row:
        return None
    return _row_to_asteroid(row)


def get_asteroids_for_system(
    galaxy: int,
    system: int,
    *,
    conn,
    now: Optional[float] = None,
    viewer_player_id: Optional[int] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map position → compact asteroid payload for galaxy slot attach."""
    if not asteroid_schema_ready(conn):
        return {}
    ts = float(now if now is not None else _now())
    expire_due_asteroids(conn=conn, now=ts)
    rows = conn.execute(
        """
        SELECT * FROM asteroid_fields
        WHERE status = ?
          AND expires_at > ?
          AND galaxy = ? AND system = ?
        ORDER BY position ASC, id ASC;
        """,
        (STATUS_ACTIVE, ts, int(galaxy), int(system)),
    ).fetchall()
    engaged_ids: Set[int] = set()
    fleet_map: Dict[int, Dict[str, Any]] = {}
    if viewer_player_id is not None and int(viewer_player_id) > 0:
        vid = int(viewer_player_id)
        engaged_ids = player_engaged_asteroid_ids(vid, conn=conn)
        fleet_map = viewer_asteroid_fleet_status_map(vid, conn=conn, now=ts)
        for aid, meta in fleet_map.items():
            if meta.get("engaged"):
                engaged_ids.add(int(aid))
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        payload = enrich_asteroid_viewer_state(
            _row_to_asteroid(row),
            engaged_ids=engaged_ids,
            fleet_map=fleet_map,
            now=ts,
        )
        out[int(payload["position"])] = payload
    return out


def _active_asteroid_coords(
    conn,
    *,
    now: Optional[float] = None,
) -> Set[Tuple[int, int, int]]:
    return {
        (int(a["galaxy"]), int(a["system"]), int(a["position"]))
        for a in list_active_asteroids(conn=conn, now=now, limit=MAX_ACTIVE_ASTEROIDS + 20)
    }


def _ttl_reserved_spawn_coords(conn, *, now: Optional[float] = None) -> Set[Tuple[int, int, int]]:
    """Coords still reserved until original field expires_at (anti-pop after claim)."""
    if not asteroid_schema_ready(conn):
        return set()
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT galaxy, system, position
        FROM asteroid_fields
        WHERE expires_at > ?
          AND status IN (?, ?);
        """,
        (ts, STATUS_CLAIMED, STATUS_EXPIRED),
    ).fetchall()
    out: Set[Tuple[int, int, int]] = set()
    for row in rows:
        try:
            out.add((int(row["galaxy"]), int(row["system"]), int(row["position"])))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _blocked_spawn_coords(conn, *, now: Optional[float] = None) -> Set[Tuple[int, int, int]]:
    blocked = set(_active_asteroid_coords(conn, now=now))
    blocked |= _ttl_reserved_spawn_coords(conn, now=now)
    try:
        from .world_boss import _active_boss_coords

        blocked |= _active_boss_coords(conn, now=now)
    except Exception:
        pass
    return blocked


def _planet_positions_in_system(
    conn,
    galaxy: int,
    system: int,
    *,
    position_min: int,
    position_max: int,
) -> Set[int]:
    return {
        int(r["position"])
        for r in conn.execute(
            """
            SELECT position FROM planets
            WHERE galaxy = ? AND system = ?
              AND position BETWEEN ? AND ?;
            """,
            (int(galaxy), int(system), int(position_min), int(position_max)),
        ).fetchall()
    }


def _free_slots_in_system(
    conn,
    galaxy: int,
    system: int,
    *,
    blocked: Set[Tuple[int, int, int]],
    position_min: int,
    position_max: int,
) -> List[int]:
    occupied = _planet_positions_in_system(
        conn,
        galaxy,
        system,
        position_min=position_min,
        position_max=position_max,
    )
    free: List[int] = []
    for pos in range(int(position_min), int(position_max) + 1):
        if pos in occupied:
            continue
        if (int(galaxy), int(system), int(pos)) in blocked:
            continue
        free.append(int(pos))
    return free


def _dense_systems(conn, *, limit: int = DENSE_SYSTEM_LIMIT) -> List[Tuple[int, int, int]]:
    from .galaxy import POSITION_MAX, POSITION_MIN

    rows = conn.execute(
        """
        SELECT galaxy, system, COUNT(*) AS n
        FROM planets
        WHERE galaxy IS NOT NULL AND system IS NOT NULL
          AND position BETWEEN ? AND ?
        GROUP BY galaxy, system
        ORDER BY n DESC
        LIMIT ?;
        """,
        (POSITION_MIN, POSITION_MAX, max(1, int(limit))),
    ).fetchall()
    return [(int(r["galaxy"]), int(r["system"]), int(r["n"])) for r in rows]


def _spawn_candidate_systems(
    conn, *, limit: int = SPAWN_SEARCH_SYSTEM_LIMIT
) -> List[Tuple[int, int, int]]:
    """Dense systems first, but only those that still have a free classic slot."""
    from .galaxy import POSITION_MAX, POSITION_MIN

    slot_span = int(POSITION_MAX) - int(POSITION_MIN) + 1
    rows = conn.execute(
        """
        SELECT galaxy, system, COUNT(*) AS n
        FROM planets
        WHERE galaxy IS NOT NULL AND system IS NOT NULL
          AND position BETWEEN ? AND ?
        GROUP BY galaxy, system
        HAVING COUNT(*) < ?
        ORDER BY n DESC
        LIMIT ?;
        """,
        (POSITION_MIN, POSITION_MAX, slot_span, max(1, int(limit))),
    ).fetchall()
    out = [(int(r["galaxy"]), int(r["system"]), int(r["n"])) for r in rows]
    if out:
        return out
    # Empty universe / all classic slots full in occupied systems → try [1:1].
    return [(1, 1, 0)]


def expire_due_asteroids(*, conn, now: Optional[float] = None) -> List[int]:
    if not asteroid_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT id FROM asteroid_fields
        WHERE status = ? AND expires_at <= ?;
        """,
        (STATUS_ACTIVE, ts),
    ).fetchall()
    expired_ids: List[int] = []
    for row in rows:
        aid = int(row["id"])
        cur = conn.execute(
            """
            UPDATE asteroid_fields
            SET status = ?
            WHERE id = ? AND status = ?;
            """,
            (STATUS_EXPIRED, aid, STATUS_ACTIVE),
        )
        if cur.rowcount == 1:
            expired_ids.append(aid)
    return expired_ids


def insert_asteroid(
    *,
    conn,
    galaxy: int,
    system: int,
    position: int,
    asteroid_key: Optional[str] = None,
    now: Optional[float] = None,
    rng: Optional[random.Random] = None,
    ttl_seconds: int = TTL_SECONDS,
) -> Dict[str, Any]:
    """Insert one active asteroid at coords (caller enforces uniqueness)."""
    if not asteroid_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}
    ts = float(now if now is not None else _now())
    key = str(asteroid_key or _pick_weighted_key(rng=rng))
    if key not in ASTEROID_CATALOG:
        key = "mixed_belt"
    loot = _roll_loot(key, rng=rng)
    expires = ts + float(ttl_seconds)
    cur = conn.execute(
        """
        INSERT INTO asteroid_fields (
            asteroid_key, galaxy, system, position,
            metal, crystal, fuel_cells, status,
            spawned_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            key,
            int(galaxy),
            int(system),
            int(position),
            float(loot["metal"]),
            float(loot["crystal"]),
            float(loot["fuel_cells"]),
            STATUS_ACTIVE,
            ts,
            expires,
        ),
    )
    aid = int(cur.lastrowid)
    row = conn.execute(
        "SELECT * FROM asteroid_fields WHERE id = ? LIMIT 1;", (aid,)
    ).fetchone()
    return {"ok": True, "asteroid": _row_to_asteroid(row)}


def spawn_asteroid_belt(
    *,
    conn,
    now: Optional[float] = None,
    force: bool = False,
    rng: Optional[random.Random] = None,
    systems_limit: int = BELT_SYSTEMS_PER_WAVE,
    belt_size: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Spawn asteroid belts in the densest systems under the global cap."""
    if not asteroid_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready", "spawned": []}

    from .galaxy import POSITION_MAX, POSITION_MIN

    ts = float(now if now is not None else _now())
    roll = rng or random
    active = list_active_asteroids(conn=conn, now=ts, limit=MAX_ACTIVE_ASTEROIDS + 20)
    room = int(MAX_ACTIVE_ASTEROIDS) - len(active)
    if room <= 0 and not force:
        return {
            "ok": False,
            "error": "concurrent_cap",
            "active_count": len(active),
            "max_concurrent": int(MAX_ACTIVE_ASTEROIDS),
            "spawned": [],
        }

    size_lo, size_hi = belt_size or BELT_SIZE_RANGE
    blocked = _blocked_spawn_coords(conn, now=ts)
    dense = _spawn_candidate_systems(conn, limit=SPAWN_SEARCH_SYSTEM_LIMIT)

    spawned: List[Dict[str, Any]] = []
    systems_used = 0
    for g, s, _n in dense:
        if systems_used >= int(systems_limit):
            break
        if room <= 0 and not force:
            break
        free = _free_slots_in_system(
            conn,
            g,
            s,
            blocked=blocked,
            position_min=POSITION_MIN,
            position_max=POSITION_MAX,
        )
        if not free:
            continue
        want = min(int(roll.randint(int(size_lo), int(size_hi))), len(free), max(0, room) or len(free))
        if want <= 0:
            continue
        chosen = roll.sample(free, k=want)
        belt_spawned = 0
        for pos in chosen:
            if room <= 0 and not force:
                break
            result = insert_asteroid(
                conn=conn,
                galaxy=g,
                system=s,
                position=pos,
                now=ts,
                rng=roll,
            )
            if not result.get("ok"):
                continue
            ast = result["asteroid"]
            spawned.append(ast)
            blocked.add((int(g), int(s), int(pos)))
            room -= 1
            belt_spawned += 1
        if belt_spawned > 0:
            systems_used += 1

    if spawned:
        set_runtime_value(SPAWN_RUNTIME_KEY, str(ts), conn=conn)

    return {
        "ok": bool(spawned),
        "spawned": spawned,
        "systems_used": systems_used,
        "active_count": len(active) + len(spawned),
        "error": None if spawned else "no_free_slots",
    }


def build_schedule_info(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    active = list_active_asteroids(conn=conn, now=ts) if asteroid_schema_ready(conn) else []
    last_spawn: Optional[float] = None
    if asteroid_schema_ready(conn):
        raw = get_runtime_value(SPAWN_RUNTIME_KEY, conn=conn)
        if raw not in (None, ""):
            try:
                last_spawn = float(raw)
            except (TypeError, ValueError):
                last_spawn = None
    if last_spawn is not None and last_spawn > 0:
        next_eligible_at = float(last_spawn) + float(INTER_WAVE_COOLDOWN_SEC)
    else:
        next_eligible_at = ts
    under_cap = len(active) < int(MAX_ACTIVE_ASTEROIDS)
    spawn_ready = bool(under_cap and ts >= next_eligible_at)
    seconds_until_next = max(0, int(next_eligible_at - ts)) if not spawn_ready else 0
    return {
        "inter_wave_cooldown_sec": int(INTER_WAVE_COOLDOWN_SEC),
        "max_concurrent": int(MAX_ACTIVE_ASTEROIDS),
        "ttl_seconds": int(TTL_SECONDS),
        "active_count": len(active),
        "last_spawn_at": last_spawn,
        "next_eligible_at": float(next_eligible_at),
        "seconds_until_next": int(seconds_until_next),
        "spawn_ready": spawn_ready,
        "under_cap": under_cap,
    }


def tick_asteroid_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    if not asteroid_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready", "expired_ids": [], "spawned": []}

    ts = float(now if now is not None else _now())
    expired_ids = expire_due_asteroids(conn=conn, now=ts)
    schedule = build_schedule_info(conn=conn, now=ts)
    spawned: List[Dict[str, Any]] = []
    spawn_result: Optional[Dict[str, Any]] = None
    # Deploy / empty-universe bootstrap: never leave zero active fields waiting on cooldown.
    if int(schedule.get("active_count") or 0) == 0:
        spawn_result = spawn_asteroid_belt(conn=conn, now=ts)
        spawned = list(spawn_result.get("spawned") or [])
    elif schedule.get("spawn_ready"):
        spawn_result = spawn_asteroid_belt(conn=conn, now=ts)
        spawned = list(spawn_result.get("spawned") or [])
    return {
        "ok": True,
        "expired_ids": expired_ids,
        "spawned": spawned,
        "spawn_result": spawn_result,
        "schedule": build_schedule_info(conn=conn, now=ts),
    }


def ensure_asteroids_present(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Galaxy/deploy bootstrap — spawn a belt wave if none are active yet."""
    if not asteroid_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready", "spawned": []}
    ts = float(now if now is not None else _now())
    expire_due_asteroids(conn=conn, now=ts)
    active = list_active_asteroids(conn=conn, now=ts)
    if active:
        return {"ok": True, "spawned": [], "skipped": True, "active_count": len(active)}
    result = spawn_asteroid_belt(conn=conn, now=ts)
    return {
        "ok": bool(result.get("ok")),
        "spawned": list(result.get("spawned") or []),
        "skipped": False,
        "active_count": int(result.get("active_count") or 0),
        "error": result.get("error"),
    }


def maybe_tick_asteroid_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Cron entry — expire due fields and spawn a belt wave when eligible."""
    try:
        return tick_asteroid_schedule(conn=conn, now=now)
    except Exception:
        logger.exception("asteroid schedule tick failed")
        return {"ok": False, "error": "tick_failed", "expired_ids": [], "spawned": []}


def _split_load(pool: Mapping[str, int], cargo_total: int) -> Dict[str, int]:
    """Proportional take up to cargo capacity (same idea as fleet collect load)."""
    metal = max(0, int(pool.get("metal") or 0))
    crystal = max(0, int(pool.get("crystal") or 0))
    fuel = max(0, int(pool.get("fuel_cells") or 0))
    total = metal + crystal + fuel
    cap = max(0, int(cargo_total))
    if total <= 0 or cap <= 0:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    if total <= cap:
        return {"metal": metal, "crystal": crystal, "fuel_cells": fuel}
    # Prefer filling in catalog order metal → crystal → fuel for remainder.
    take_m = int(cap * metal / total)
    take_c = int(cap * crystal / total)
    take_f = max(0, cap - take_m - take_c)
    # Clamp to available
    take_m = min(metal, take_m)
    take_c = min(crystal, take_c)
    take_f = min(fuel, take_f)
    used = take_m + take_c + take_f
    leftover = cap - used
    if leftover > 0:
        for key, avail, current in (
            ("metal", metal, take_m),
            ("crystal", crystal, take_c),
            ("fuel_cells", fuel, take_f),
        ):
            room = avail - current
            if room <= 0:
                continue
            add = min(room, leftover)
            if key == "metal":
                take_m += add
            elif key == "crystal":
                take_c += add
            else:
                take_f += add
            leftover -= add
            if leftover <= 0:
                break
    return {"metal": take_m, "crystal": take_c, "fuel_cells": take_f}


def try_claim_harvest(
    galaxy: int,
    system: int,
    position: int,
    *,
    player_id: int,
    cargo_capacity: int,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Atomically claim an active asteroid and return harvestable cargo.

    Returns ``status``:
    - ``none`` — no asteroid activity at coords
    - ``claimed`` — this player won; ``harvested`` is min(pool, cargo)
    - ``missed`` — asteroid was present but already taken / race lost
    - ``expired`` — field timed out while fleet was en route
    """
    if not asteroid_schema_ready(conn):
        return {"status": "none", "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0}}

    ts = float(now if now is not None else _now())
    g, s, p = int(galaxy), int(system), int(position)

    row = conn.execute(
        """
        SELECT * FROM asteroid_fields
        WHERE galaxy = ? AND system = ? AND position = ?
          AND status = ?
          AND expires_at > ?
        ORDER BY id DESC
        LIMIT 1;
        """,
        (g, s, p, STATUS_ACTIVE, ts),
    ).fetchone()
    if not row:
        # Recently claimed at these coords → miss for late arrivals.
        recent = conn.execute(
            """
            SELECT id FROM asteroid_fields
            WHERE galaxy = ? AND system = ? AND position = ?
              AND status = ?
              AND claimed_at IS NOT NULL
              AND claimed_at >= ?
            ORDER BY claimed_at DESC
            LIMIT 1;
            """,
            (g, s, p, STATUS_CLAIMED, ts - float(TTL_SECONDS)),
        ).fetchone()
        if recent:
            return {
                "status": "missed",
                "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0},
                "asteroid_id": int(recent["id"]),
            }
        # Field expired while fleet was en route.
        expired = conn.execute(
            """
            SELECT id FROM asteroid_fields
            WHERE galaxy = ? AND system = ? AND position = ?
              AND status = ?
              AND expires_at >= ?
            ORDER BY expires_at DESC
            LIMIT 1;
            """,
            (g, s, p, STATUS_EXPIRED, ts - float(TTL_SECONDS)),
        ).fetchone()
        if expired:
            return {
                "status": "expired",
                "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0},
                "asteroid_id": int(expired["id"]),
            }
        return {"status": "none", "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0}}

    aid = int(row["id"])
    pool = {
        "metal": int(row["metal"] or 0),
        "crystal": int(row["crystal"] or 0),
        "fuel_cells": int(row["fuel_cells"] or 0),
    }
    harvested = _split_load(pool, int(cargo_capacity))

    cur = conn.execute(
        """
        UPDATE asteroid_fields
        SET status = ?,
            claimed_at = ?,
            claimed_by_player_id = ?,
            metal = 0,
            crystal = 0,
            fuel_cells = 0
        WHERE id = ? AND status = ?;
        """,
        (STATUS_CLAIMED, ts, int(player_id), aid, STATUS_ACTIVE),
    )
    if cur.rowcount != 1:
        return {
            "status": "missed",
            "harvested": {"metal": 0, "crystal": 0, "fuel_cells": 0},
            "asteroid_id": aid,
        }

    asteroid = _row_to_asteroid(row)
    asteroid["status"] = STATUS_CLAIMED
    asteroid["metal"] = 0
    asteroid["crystal"] = 0
    asteroid["fuel_cells"] = 0
    asteroid["total"] = 0
    return {
        "status": "claimed",
        "harvested": harvested,
        "asteroid_id": aid,
        "asteroid_key": asteroid.get("asteroid_key"),
        "pool": pool,
        "asteroid": asteroid,
    }
