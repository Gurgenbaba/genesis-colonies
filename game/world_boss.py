"""
EPIC-20 — World Boss Events (server-wide PvE).

Owner of shared-HP events, contribution ledger, schedule, reward claims,
and instant encounter attacks (``execute_instant_attack``).
Ship combat stats / research mods come from ``game/combat.py`` + ``combat_models``;
legacy arrival resolve remains in ``game/fleet.py`` for in-flight leftovers only.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .db import table_exists
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

WORLD_BOSS_EVENT_TABLE = "world_boss_events"
WORLD_BOSS_DEF_TABLE = "world_boss_definitions"
WORLD_BOSS_CONTRIB_TABLE = "world_boss_contributions"
WORLD_BOSS_CLAIM_TABLE = "world_boss_claims"

STATUS_ACTIVE = "active"
STATUS_DEFEATED = "defeated"
STATUS_EXPIRED = "expired"
STATUS_TAMED = "tamed"
STATUS_SCHEDULED = "scheduled"
# Ended events that unlock (or already paid) contribution rewards.
CLAIMABLE_STATUSES = frozenset({STATUS_DEFEATED, STATUS_EXPIRED, STATUS_TAMED})

WAVE_COOLDOWN_SEC = 300
MAX_WAVES_PER_PLAYER = 40
DEFAULT_EVENT_DURATION_SEC = 48 * 3600
# Gap between successive spawns when under the concurrent cap (GC-W13).
INTER_EVENT_COOLDOWN_SEC = 4 * 3600
MAX_CONCURRENT_EVENTS = 3
EXPO_DISCOVERY_CHANCE = 0.055
SCHEDULE_RUNTIME_KEY = "world_boss_last_ended_at"
SPAWN_RUNTIME_KEY = "world_boss_last_spawn_at"
ROTATION_RUNTIME_KEY = "world_boss_rotation_index"

# Raid HP mapping (instant snapshot + legacy arrival wipe mapping).
# Even fight full wipe ≈ WAVE_HP_FRACTION of max_hp.
WAVE_HP_FRACTION = 0.02
# Soft overkill: 1 + scale * log2(1 + force_ratio). Mega fleets approach the cap.
OVERKILL_LOG_SCALE = 0.15
# Cap ≈ 8% → solo mega fleet needs ~13 waves (target band 10–20 hits).
MAX_WAVE_HP_FRACTION = 0.08

# Instant encounter strike (GC-WB-ATTACK-002) — no ship losses, no flight.
INSTANT_CRIT_CHANCE = 0.12
INSTANT_CRIT_MULT = 1.5
ALLIANCE_SALVO_FRACTION = 0.0  # reserved; visual hook only until LIVEOPS tuning

# Alliance XP from world-boss damage (good, not OP vs donation daily ~150).
# ~1 XP per 40k damage; hard cap per wave so mega fleets cannot dump levels.
ALLIANCE_XP_DAMAGE_DIVISOR = 40_000
ALLIANCE_XP_PER_WAVE_CAP = 40


def alliance_xp_from_boss_damage(damage: int) -> int:
    """Convert one wave's HP damage into alliance XP (0 if below threshold)."""
    dmg = max(0, int(damage))
    if dmg <= 0:
        return 0
    return min(int(ALLIANCE_XP_PER_WAVE_CAP), dmg // int(ALLIANCE_XP_DAMAGE_DIVISOR))


def alliance_xp_reward_preview_row() -> Dict[str, Any]:
    """Server-authored Ally-XP rule for World Boss reward cards."""
    return {
        "tier": "alliance_xp",
        "label_key": "wb_reward_tier_alliance_xp",
        "divisor": int(ALLIANCE_XP_DAMAGE_DIVISOR),
        "wave_cap": int(ALLIANCE_XP_PER_WAVE_CAP),
        "grants": [
            {
                "kind": "alliance_xp",
                "name_key": "wb_reward_alliance_xp_rule",
                "divisor": int(ALLIANCE_XP_DAMAGE_DIVISOR),
                "wave_cap": int(ALLIANCE_XP_PER_WAVE_CAP),
            }
        ],
    }


# Reward tiers → inventory container keys (meta-only, known catalog).
# Amounts are tuned “good but not OP”: participate solid, top tiers rare containers.
# Participate / discoverer / top10-bonus use the boss definition `loot_pool_key`.
REWARD_PARTICIPATE = "container_event_special"
REWARD_TOP10 = "container_void_artifact"
REWARD_TOP1 = "container_mythic"
REWARD_ALLIANCE_TOP = "container_ancient_relic"
REWARD_TIER_ORDER: Tuple[str, ...] = (
    "participate",
    "top10",
    "top1",
    "alliance_top",
    "discoverer",
)


def normalize_loot_pool_key(raw: Any) -> str:
    key = str(raw or REWARD_PARTICIPATE).strip()
    return key or REWARD_PARTICIPATE


def build_reward_tier_grants(
    loot_pool_key: Optional[str] = None,
) -> Tuple[Tuple[str, str, int], ...]:
    """(tier, item_key, amount) — same key stacks within a claim."""
    pool = normalize_loot_pool_key(loot_pool_key)
    return (
        ("top1", REWARD_TOP1, 1),
        ("top10", REWARD_TOP10, 1),
        ("top10", pool, 1),
        ("alliance_top", REWARD_ALLIANCE_TOP, 1),
        ("discoverer", pool, 1),
        ("participate", pool, 2),
    )


# Default catalog (event-special pool) — used by tests / fallbacks.
REWARD_TIER_GRANTS: Tuple[Tuple[str, str, int], ...] = build_reward_tier_grants(
    REWARD_PARTICIPATE
)


def build_rewards_preview(
    loot_pool_key: Optional[str] = None,
    *,
    earned_tiers: Optional[Set[str]] = None,
    alliance_xp_earned: int = 0,
) -> List[Dict[str, Any]]:
    """Server-authored per-boss reward table for World Boss cards."""
    by_tier: Dict[str, Dict[str, int]] = {}
    for tier, item_key, amount in build_reward_tier_grants(loot_pool_key):
        bucket = by_tier.setdefault(str(tier), {})
        bucket[str(item_key)] = bucket.get(str(item_key), 0) + int(amount)
    earned = {str(t) for t in (earned_tiers or set())}
    rows: List[Dict[str, Any]] = []
    for tier in REWARD_TIER_ORDER:
        grants_map = by_tier.get(tier)
        if not grants_map:
            continue
        rows.append(
            {
                "tier": tier,
                "label_key": f"wb_reward_tier_{tier}",
                "earned": tier in earned,
                "grants": [
                    {
                        "item_key": item_key,
                        "amount": int(amount),
                        "name_key": f"inv_{item_key}",
                    }
                    for item_key, amount in grants_map.items()
                ],
            }
        )
    ally_row = alliance_xp_reward_preview_row()
    ally_row["earned"] = int(alliance_xp_earned or 0) > 0
    rows.append(ally_row)
    return rows


def aggregate_reward_grants_for_tiers(
    loot_pool_key: Optional[str],
    tiers: List[str],
) -> List[Dict[str, Any]]:
    """Aggregate inventory grants for the given earned tiers (claim payout shape)."""
    tier_set = {str(t) for t in (tiers or [])}
    amounts: Dict[str, int] = {}
    for tier, item_key, amount in build_reward_tier_grants(loot_pool_key):
        if tier not in tier_set:
            continue
        amounts[item_key] = amounts.get(item_key, 0) + int(amount)
    return [
        {
            "item_key": item_key,
            "amount": int(amount),
            "name_key": f"inv_{item_key}",
        }
        for item_key, amount in amounts.items()
    ]


def build_player_reward_outlook(
    event: Dict[str, Any],
    player_id: Optional[int],
    *,
    conn,
) -> Dict[str, Any]:
    """What this player gets / has unlocked — concrete grants, not just the catalog."""
    empty: Dict[str, Any] = {
        "mode": "none",
        "earned_tiers": [],
        "grants": [],
        "alliance_xp_earned": 0,
        "rank": None,
        "total_players": 0,
    }
    if player_id is None:
        return empty

    claim = _player_claim_row(int(event["id"]), int(player_id), conn=conn)
    ally_xp = 0
    contribs = list_contributions(int(event["id"]), conn=conn, limit=10000)
    mine = next((c for c in contribs if int(c["player_id"]) == int(player_id)), None)
    if mine:
        ally_xp = int(mine.get("alliance_xp") or 0)

    if claim:
        grants = list(claim.get("rewards") or [])
        for entry in grants:
            if isinstance(entry, dict) and entry.get("item_key") and not entry.get("name_key"):
                entry["name_key"] = f"inv_{entry['item_key']}"
        return {
            "mode": "claimed",
            "earned_tiers": list(claim.get("tiers") or []),
            "grants": grants,
            "alliance_xp_earned": ally_xp,
            "rank": None,
            "total_players": len(contribs),
        }

    if not mine or int(mine.get("damage") or 0) <= 0:
        return empty

    tiers, meta = compute_claim_tiers(int(event["id"]), int(player_id), conn=conn)
    if not tiers:
        return empty

    status = str(event.get("status") or "")
    mode = "claimable" if status in CLAIMABLE_STATUSES else "projected"
    return {
        "mode": mode,
        "earned_tiers": list(tiers),
        "grants": aggregate_reward_grants_for_tiers(event.get("loot_pool_key"), tiers),
        "alliance_xp_earned": ally_xp,
        "rank": int(meta.get("rank") or 0) or None,
        "total_players": int(meta.get("total_players") or len(contribs)),
    }


def _now() -> float:
    return float(time.time())


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def world_boss_schema_ready(conn) -> bool:
    return (
        table_exists(conn, WORLD_BOSS_DEF_TABLE)
        and table_exists(conn, WORLD_BOSS_EVENT_TABLE)
        and table_exists(conn, WORLD_BOSS_CONTRIB_TABLE)
        and table_exists(conn, WORLD_BOSS_CLAIM_TABLE)
    )


def get_definition(boss_key: str, *, conn) -> Optional[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT boss_key, name_key, description_key, max_hp, duration_seconds,
               fleet_stacks_json, phases_json, loot_pool_key, spawn_weight, sort_order, active
        FROM world_boss_definitions
        WHERE boss_key = ?
        LIMIT 1;
        """,
        (str(boss_key),),
    ).fetchone()
    if not row:
        return None
    return _definition_from_row(row)


def list_definitions(*, conn, active_only: bool = True) -> List[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return []
    sql = """
        SELECT boss_key, name_key, description_key, max_hp, duration_seconds,
               fleet_stacks_json, phases_json, loot_pool_key, spawn_weight, sort_order, active
        FROM world_boss_definitions
    """
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY sort_order ASC, boss_key ASC;"
    return [_definition_from_row(r) for r in conn.execute(sql).fetchall()]


def _definition_from_row(row) -> Dict[str, Any]:
    return {
        "boss_key": str(row["boss_key"]),
        "name_key": str(row["name_key"] or ""),
        "description_key": str(row["description_key"] or ""),
        "max_hp": int(row["max_hp"]),
        "duration_seconds": int(row["duration_seconds"] or DEFAULT_EVENT_DURATION_SEC),
        "fleet_stacks": dict(_json_loads(row["fleet_stacks_json"], {}) or {}),
        "phases": list(_json_loads(row["phases_json"], []) or []),
        "loot_pool_key": str(row["loot_pool_key"] or REWARD_PARTICIPATE),
        "spawn_weight": int(row["spawn_weight"] or 0),
        "sort_order": int(row["sort_order"] or 0),
        "active": bool(int(row["active"] or 0)),
    }


def _event_from_row(row, *, definition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    max_hp = int(row["max_hp"])
    current_hp = int(row["current_hp"])
    hp_ratio = (float(current_hp) / float(max_hp)) if max_hp > 0 else 0.0
    boss_key = str(row["boss_key"])
    defn = definition or {}
    discovered_by = None
    try:
        keys = row.keys() if hasattr(row, "keys") else ()
        if "discovered_by_player_id" in keys and row["discovered_by_player_id"] is not None:
            discovered_by = int(row["discovered_by_player_id"])
    except (TypeError, ValueError, KeyError):
        discovered_by = None
    return {
        "id": int(row["id"]),
        "boss_key": boss_key,
        "status": str(row["status"]),
        "galaxy": int(row["galaxy"]),
        "system": int(row["system"]),
        "position": int(row["position"]),
        "coords": f"[{int(row['galaxy'])}:{int(row['system'])}:{int(row['position'])}]",
        "max_hp": max_hp,
        "current_hp": current_hp,
        "hp_ratio": round(max(0.0, min(1.0, hp_ratio)), 4),
        "phase_index": int(row["phase_index"] or 0),
        "fleet_stacks": dict(_json_loads(row["fleet_stacks_json"], {}) or {}),
        "starts_at": float(row["starts_at"]),
        "ends_at": float(row["ends_at"]),
        "defeated_at": float(row["defeated_at"]) if row["defeated_at"] is not None else None,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "discovered_by_player_id": discovered_by,
        "name_key": str(defn.get("name_key") or f"wb_boss_{boss_key}"),
        "description_key": str(defn.get("description_key") or ""),
        "loot_pool_key": str(defn.get("loot_pool_key") or REWARD_PARTICIPATE),
    }


def list_active_events(*, conn, now: Optional[float] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """All currently active world boss events (newest first)."""
    if not world_boss_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT e.*, d.name_key, d.description_key, d.loot_pool_key, d.phases_json AS def_phases_json
        FROM world_boss_events e
        LEFT JOIN world_boss_definitions d ON d.boss_key = e.boss_key
        WHERE e.status = ?
          AND e.starts_at <= ?
          AND e.ends_at > ?
        ORDER BY e.id DESC
        LIMIT ?;
        """,
        (STATUS_ACTIVE, ts, ts, max(1, int(limit))),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        defn = {
            "name_key": row["name_key"],
            "description_key": row["description_key"],
            "loot_pool_key": row["loot_pool_key"],
            "phases": _json_loads(row["def_phases_json"], []),
        }
        out.append(_event_from_row(row, definition=defn))
    return out


def get_active_event(*, conn, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Primary active event (newest). Prefer ``list_active_events`` for multi-boss."""
    events = list_active_events(conn=conn, now=now, limit=1)
    return events[0] if events else None


def get_event_by_id(event_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT e.*, d.name_key, d.description_key, d.loot_pool_key
        FROM world_boss_events e
        LEFT JOIN world_boss_definitions d ON d.boss_key = e.boss_key
        WHERE e.id = ?
        LIMIT 1;
        """,
        (int(event_id),),
    ).fetchone()
    if not row:
        return None
    return _event_from_row(
        row,
        definition={
            "name_key": row["name_key"],
            "description_key": row["description_key"],
            "loot_pool_key": row["loot_pool_key"],
        },
    )


def get_active_event_at(
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return None
    ts = float(now if now is not None else _now())
    row = conn.execute(
        """
        SELECT e.*, d.name_key, d.description_key, d.loot_pool_key, d.phases_json AS def_phases_json
        FROM world_boss_events e
        LEFT JOIN world_boss_definitions d ON d.boss_key = e.boss_key
        WHERE e.status = ?
          AND e.starts_at <= ?
          AND e.ends_at > ?
          AND e.galaxy = ? AND e.system = ? AND e.position = ?
        ORDER BY e.id DESC
        LIMIT 1;
        """,
        (STATUS_ACTIVE, ts, ts, int(galaxy), int(system), int(position)),
    ).fetchone()
    if not row:
        return None
    defn = {
        "name_key": row["name_key"],
        "description_key": row["description_key"],
        "loot_pool_key": row["loot_pool_key"],
        "phases": _json_loads(row["def_phases_json"], []),
    }
    return _event_from_row(row, definition=defn)


def get_bosses_for_system(
    galaxy: int,
    system: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map position → compact boss payload for galaxy slot attach."""
    events = list_active_events(conn=conn, now=now, limit=MAX_CONCURRENT_EVENTS + 5)
    out: Dict[int, Dict[str, Any]] = {}
    for event in events:
        if int(event["galaxy"]) != int(galaxy) or int(event["system"]) != int(system):
            continue
        out[int(event["position"])] = {
            "event_id": int(event["id"]),
            "boss_key": event["boss_key"],
            "name_key": event["name_key"],
            "status": event["status"],
            "current_hp": int(event["current_hp"]),
            "max_hp": int(event["max_hp"]),
            "hp_ratio": event["hp_ratio"],
            "ends_at": event["ends_at"],
            "coords": event["coords"],
            "fleet_deep_link": f"/world-boss",
            "encounter_path": "/world-boss",
            "wave_cooldown_sec": int(WAVE_COOLDOWN_SEC),
            "max_waves": int(MAX_WAVES_PER_PLAYER),
        }
    return out


def _active_boss_coords(
    conn,
    *,
    now: Optional[float] = None,
) -> Set[Tuple[int, int, int]]:
    """Active world-boss slots — must stay unique across concurrent events."""
    return {
        (int(e["galaxy"]), int(e["system"]), int(e["position"]))
        for e in list_active_events(conn=conn, now=now, limit=MAX_CONCURRENT_EVENTS + 20)
        if e.get("galaxy") is not None and e.get("system") is not None and e.get("position") is not None
    }


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


def _first_free_classic_slot(
    conn,
    galaxy: int,
    system: int,
    *,
    blocked: Set[Tuple[int, int, int]],
    position_min: int,
    position_max: int,
) -> Optional[int]:
    occupied = _planet_positions_in_system(
        conn,
        galaxy,
        system,
        position_min=position_min,
        position_max=position_max,
    )
    for pos in range(int(position_min), int(position_max) + 1):
        if pos in occupied:
            continue
        if (int(galaxy), int(system), int(pos)) in blocked:
            continue
        return int(pos)
    return None


def _pick_spawn_coords(
    conn,
    *,
    prefer_dense: bool = False,
    blocked: Optional[Set[Tuple[int, int, int]]] = None,
    now: Optional[float] = None,
) -> Tuple[int, int, int]:
    """Pick an empty classic slot (1–15), never overlapping an active boss."""
    from .galaxy import POSITION_MAX, POSITION_MIN

    blocked_slots: Set[Tuple[int, int, int]] = set(blocked or ())
    blocked_slots |= _active_boss_coords(conn, now=now)
    cur = conn.cursor()
    candidates: List[Tuple[int, int]] = []

    if prefer_dense:
        # Prefer densest systems first, then a few runners-up.
        dense_rows = cur.execute(
            """
            SELECT galaxy, system, COUNT(*) AS n
            FROM planets
            WHERE galaxy IS NOT NULL AND system IS NOT NULL
              AND position BETWEEN ? AND ?
            GROUP BY galaxy, system
            ORDER BY n DESC
            LIMIT 8;
            """,
            (POSITION_MIN, POSITION_MAX),
        ).fetchall()
        for drow in dense_rows:
            candidates.append((int(drow["galaxy"]), int(drow["system"])))

    home = cur.execute(
        """
        SELECT galaxy, system, position FROM planets
        WHERE is_homeworld = 1
        ORDER BY id ASC
        LIMIT 1;
        """
    ).fetchone()
    if home:
        hg, hs = int(home["galaxy"]), int(home["system"])
        candidates.append((hg, hs))
        for delta in range(1, 12):
            candidates.append((hg, min(hs + delta, 499)))
            if hs - delta >= 1:
                candidates.append((hg, hs - delta))

    candidates.extend([(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)])

    seen: Set[Tuple[int, int]] = set()
    for g, s in candidates:
        key = (int(g), int(s))
        if key in seen:
            continue
        seen.add(key)
        free = _first_free_classic_slot(
            conn,
            g,
            s,
            blocked=blocked_slots,
            position_min=POSITION_MIN,
            position_max=POSITION_MAX,
        )
        if free is not None:
            return int(g), int(s), int(free)

    # Last resort: walk systems until a free classic slot exists.
    for g in range(1, 6):
        for s in range(1, 50):
            if (g, s) in seen:
                continue
            free = _first_free_classic_slot(
                conn,
                g,
                s,
                blocked=blocked_slots,
                position_min=POSITION_MIN,
                position_max=POSITION_MAX,
            )
            if free is not None:
                return int(g), int(s), int(free)

    # Extremely constrained map: still avoid active bosses even if planets fill slots.
    for g in range(1, 10):
        for s in range(1, 100):
            for pos in range(int(POSITION_MIN), int(POSITION_MAX) + 1):
                if (g, s, pos) not in blocked_slots:
                    return int(g), int(s), int(pos)
    return 1, 1, 8


def _resolve_phase_stacks(
    definition: Mapping[str, Any],
    *,
    current_hp: int,
    max_hp: int,
    current_stacks: Mapping[str, int],
) -> Tuple[int, Dict[str, int]]:
    phases = list(definition.get("phases") or [])
    ratio = (float(current_hp) / float(max_hp)) if max_hp > 0 else 0.0
    phase_index = 0
    chosen_stacks = dict(current_stacks or {})
    for idx, phase in enumerate(phases):
        if not isinstance(phase, Mapping):
            continue
        threshold = float(phase.get("hp_ratio") or 0.0)
        if ratio <= threshold + 1e-9:
            phase_index = idx
            override = phase.get("stacks")
            if isinstance(override, Mapping) and override:
                chosen_stacks = {str(k): max(0, int(v or 0)) for k, v in override.items()}
    if not chosen_stacks:
        chosen_stacks = {
            str(k): max(0, int(v or 0))
            for k, v in dict(definition.get("fleet_stacks") or {}).items()
        }
    # Scale surviving stacks by remaining HP so later waves are weaker.
    scaled: Dict[str, int] = {}
    for key, qty in chosen_stacks.items():
        scaled[key] = max(0, int(round(int(qty) * max(0.05, ratio))))
    return phase_index, scaled


def combat_ships_from_hangar(hangar: Mapping[str, int] | None) -> Dict[str, int]:
    """Combat-role hulls (+ eclipse hybrid) available for WB auto-attack / prefill parity."""
    from .fleet_defs import ship_has_role

    out: Dict[str, int] = {}
    for key, amount in dict(hangar or {}).items():
        qty = int(amount or 0)
        if qty <= 0:
            continue
        sk = str(key)
        if ship_has_role(sk, "combat") or sk == "eclipse_runner":
            out[sk] = qty
    return out


def defender_ships_for_event(event: Mapping[str, Any], *, conn=None) -> Dict[str, int]:
    """Current phase defender stacks for an active world-boss event."""
    definition = get_definition(str(event.get("boss_key") or ""), conn=conn) or {}
    _phase, defender_ships = _resolve_phase_stacks(
        definition,
        current_hp=int(event.get("current_hp") or 0),
        max_hp=int(event.get("max_hp") or 0),
        current_stacks=event.get("fleet_stacks") or {},
    )
    return dict(defender_ships or {})


def _scale_ship_counts(ships: Mapping[str, int], parts: int, *, total_parts: int = 10_000) -> Dict[str, int]:
    """Integer scale ``parts/total_parts`` of each ship count (floor, drop zeros)."""
    p = max(0, int(parts))
    denom = max(1, int(total_parts))
    out: Dict[str, int] = {}
    for key, amount in dict(ships or {}).items():
        qty = int(amount or 0)
        if qty <= 0:
            continue
        scaled = (qty * p) // denom
        if scaled > 0:
            out[str(key)] = int(scaled)
    return out


def estimate_world_boss_wave_damage(
    attacker_ships: Mapping[str, int],
    defender_ships: Mapping[str, int],
    max_hp: int,
    *,
    rng_seed: int,
    conn=None,
) -> int:
    """Deterministic HP-damage estimate for auto-attack trim (plan seed ≠ arrival seed)."""
    import random

    from .combat import attacker_stacks_from_fleet, simulate_battle
    from .combat_models import COMBAT_UNIT_SHIP, stacks_from_counts

    atk = {
        str(k): max(0, int(v or 0))
        for k, v in dict(attacker_ships or {}).items()
        if int(v or 0) > 0
    }
    if not atk:
        return 0
    def_ships = {
        str(k): max(0, int(v or 0))
        for k, v in dict(defender_ships or {}).items()
        if int(v or 0) > 0
    }
    result = simulate_battle(
        attacker_stacks_from_fleet(atk),
        stacks_from_counts(def_ships, unit_type=COMBAT_UNIT_SHIP),
        rng=random.Random(int(rng_seed)),
        attacker_player_id=None,
        defender_player_id=None,
        conn=conn,
    )
    return int(
        compute_world_boss_hp_damage(
            defender_ships_before=def_ships,
            defender_losses=result.defender_losses or {},
            max_hp=int(max_hp),
            attacker_ships_before=atk,
        )
    )


def select_world_boss_auto_attack_ships(
    hangar: Mapping[str, int],
    *,
    defender_ships: Mapping[str, int],
    max_hp: int,
    event_id: int = 0,
    conn=None,
    safety_parts: int = 1_500,
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """
    GC-WB-AUTO-ATTACK-001 — smallest proportional combat fleet matching full-hangar max HP damage.

    Binary-searches a scale of the combat pool so Auto-Attack does not dump the entire hangar
    when a fraction already reaches the player's achievable wave damage (incl. soft overkill cap).
    A small safety margin covers arrival RNG differing from the plan seed.
    """
    pool = combat_ships_from_hangar(hangar)
    pool_count = int(sum(pool.values()))
    meta: Dict[str, Any] = {
        "pool_ships": dict(pool),
        "pool_sent_count": pool_count,
        "ships": {},
        "sent_count": 0,
        "ship_types": 0,
        "trimmed": False,
        "scale_parts": 10_000,
        "damage_full": 0,
        "damage_estimate": 0,
    }
    if pool_count <= 0:
        return {}, meta

    seed = 900_000_000 + int(event_id or 0)
    d_full = estimate_world_boss_wave_damage(
        pool, defender_ships, max_hp, rng_seed=seed, conn=conn
    )
    hp_budget = max(0, int(max_hp))
    damage_cap = int(float(hp_budget) * float(MAX_WAVE_HP_FRACTION)) if hp_budget > 0 else 0
    # Target = boss wave max HP damage (8% cap) when hangar can reach it; else best effort.
    target = int(min(d_full, damage_cap)) if damage_cap > 0 else int(d_full)
    meta["damage_full"] = int(d_full)
    meta["damage_cap"] = int(damage_cap)
    meta["damage_target"] = int(target)
    if d_full <= 0 or target <= 0:
        # Cannot score with the plan seed — still send the combat pool (real arrival may differ).
        meta["ships"] = dict(pool)
        meta["sent_count"] = pool_count
        meta["ship_types"] = len(pool)
        return dict(pool), meta

    total_parts = 10_000
    lo, hi = 1, total_parts
    best_parts = total_parts
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _scale_ship_counts(pool, mid, total_parts=total_parts)
        if not candidate:
            lo = mid + 1
            continue
        dmg = estimate_world_boss_wave_damage(
            candidate, defender_ships, max_hp, rng_seed=seed, conn=conn
        )
        if dmg >= target:
            best_parts = mid
            hi = mid - 1
        else:
            lo = mid + 1

    # Buffer against arrival RNG / phase drift (capped at full pool).
    buffered_parts = min(total_parts, int(best_parts) + max(0, int(safety_parts)))
    selected = _scale_ship_counts(pool, buffered_parts, total_parts=total_parts)
    if not selected:
        selected = dict(pool)
        buffered_parts = total_parts
    d_sel = estimate_world_boss_wave_damage(
        selected, defender_ships, max_hp, rng_seed=seed, conn=conn
    )
    if d_sel < target:
        selected = dict(pool)
        buffered_parts = total_parts
        d_sel = d_full

    meta.update(
        {
            "ships": dict(selected),
            "sent_count": int(sum(selected.values())),
            "ship_types": len(selected),
            "trimmed": int(sum(selected.values())) < pool_count,
            "scale_parts": int(buffered_parts),
            "damage_estimate": int(d_sel),
        }
    )
    return dict(selected), meta


def hp_phase_from_ratio(hp_ratio: float) -> int:
    """UI/combat phase from remaining HP ratio (1 cyan / 2 orange / 3 red / 0 dead)."""
    pct = float(hp_ratio) * 100.0
    if pct <= 0:
        return 0
    if pct <= 25:
        return 3
    if pct <= 50:
        return 2
    return 1


def compute_attack_power(
    ships: Mapping[str, int],
    *,
    player_id: int,
    planet_id: Optional[int] = None,
    conn=None,
) -> int:
    """Sum of effective ship attack × qty (canonical combat stats + research mods)."""
    from .combat import combat_modifiers_for_player
    from .combat_models import combat_stats_for_ship

    mods = combat_modifiers_for_player(
        int(player_id),
        planet_id=int(planet_id) if planet_id is not None else None,
        conn=conn,
    )
    weapon_bonus = max(0.0, float(mods.weapon_bonus))
    total = 0
    for key, amount in dict(ships or {}).items():
        qty = max(0, int(amount or 0))
        if qty <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats is None or int(stats.attack) <= 0:
            continue
        effective = max(0, int(round(int(stats.attack) * (1.0 + weapon_bonus))))
        total += effective * qty
    return int(total)


def compute_instant_hp_damage(
    *,
    ships: Mapping[str, int],
    defender_ships: Mapping[str, int],
    max_hp: int,
    critical: bool = False,
) -> int:
    """
    Map attack snapshot → shared boss HP damage (no simulate_battle / no losses).

    Uses prestige scores of attacker vs wave stacks with the same wipe/overkill/cap
    rules as ``compute_world_boss_hp_damage`` (even fight ≈ 2%, cap 8%).
    """
    from .scoring import compute_destroyed_raw_from_losses

    hp_budget = max(0, int(max_hp))
    if hp_budget <= 0:
        return 0
    atk = {
        str(k): max(0, int(v or 0))
        for k, v in dict(ships or {}).items()
        if int(v or 0) > 0
    }
    wave = {
        str(k): max(0, int(v or 0))
        for k, v in dict(defender_ships or {}).items()
        if int(v or 0) > 0
    }
    if not atk:
        return 0
    atk_score = int(compute_destroyed_raw_from_losses(atk)) if atk else 0
    wave_score = int(compute_destroyed_raw_from_losses(wave)) if wave else 0
    if atk_score <= 0:
        return 0
    if wave_score <= 0:
        # No defender stacks — still allow a capped strike from attacker force.
        wave_score = max(1, atk_score)
    fraction = min(1.0, float(atk_score) / float(wave_score))
    force_ratio = float(atk_score) / float(max(wave_score, 1))
    overkill_mult = max(
        1.0,
        1.0 + float(OVERKILL_LOG_SCALE) * math.log2(max(1.0, force_ratio)),
    )
    base = float(hp_budget) * float(WAVE_HP_FRACTION) * fraction * overkill_mult
    if critical:
        base *= float(INSTANT_CRIT_MULT)
    cap = float(hp_budget) * float(MAX_WAVE_HP_FRACTION)
    damage = int(min(cap, max(0.0, base)))
    if damage <= 0 and atk_score > 0:
        return 1
    return max(0, damage)


def _projectile_profile_for_ships(ships: Mapping[str, int]) -> str:
    from .combat_models import combat_stats_for_ship

    best = 0
    for key, amount in dict(ships or {}).items():
        if int(amount or 0) <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats is None:
            continue
        best = max(best, int(stats.attack or 0))
    if best >= 500:
        return "plasma_heavy"
    if best >= 100:
        return "laser_mid"
    return "kinetic_light"


def _normalize_attack_ships(ships: Mapping[str, int] | None) -> Dict[str, int]:
    from .fleet_defs import canonical_ship_key

    out: Dict[str, int] = {}
    for key, amount in dict(ships or {}).items():
        qty = max(0, int(amount or 0))
        if qty <= 0:
            continue
        ck = canonical_ship_key(str(key))
        if not ck:
            continue
        out[ck] = int(out.get(ck, 0)) + qty
    return out


def _validate_ships_in_hangar(
    ships: Mapping[str, int],
    hangar: Mapping[str, int],
) -> Tuple[bool, str]:
    for key, qty in dict(ships or {}).items():
        need = max(0, int(qty or 0))
        if need <= 0:
            continue
        have = max(0, int(hangar.get(key) or 0))
        if have < need:
            return False, "insufficient_ships"
    if not ships or sum(int(v or 0) for v in ships.values()) <= 0:
        return False, "no_ships_selected"
    return True, ""


def execute_instant_attack(
    player_id: int,
    event_id: int,
    ships: Mapping[str, int] | None,
    *,
    planet_id: int,
    conn,
    now: Optional[float] = None,
    rng: Any = None,
    auto_select: bool = False,
) -> Dict[str, Any]:
    """
    GC-WB-ATTACK-002 — resolve a World Boss strike in-request (no flight, no losses).

    Ships stay in hangar; cooldown and contribution update atomically with HP.
    """
    import random

    from .fleet import get_planet_ships

    ts = float(now if now is not None else _now())
    pid = int(player_id)
    eid = int(event_id)
    origin_id = int(planet_id)

    ok_atk, reason, meta = can_player_attack_boss(
        pid,
        eid,
        conn=conn,
        now=ts,
        enforce_cooldown=True,
        check_inflight=False,
    )
    if not ok_atk:
        return {
            "ok": False,
            "error": reason,
            "attack": None,
            "boss": None,
            "player": None,
            **(meta or {}),
        }

    event = meta.get("event") or get_event_by_id(eid, conn=conn)
    if not event or event["status"] != STATUS_ACTIVE:
        return {"ok": False, "error": "world_boss_inactive", "attack": None, "boss": None, "player": None}

    hangar = get_planet_ships(origin_id, conn=conn)
    selected = _normalize_attack_ships(ships)
    if auto_select or not selected:
        defender_preview = defender_ships_for_event(event, conn=conn)
        selected, pick_meta = select_world_boss_auto_attack_ships(
            hangar,
            defender_ships=defender_preview,
            max_hp=int(event.get("max_hp") or 0),
            event_id=eid,
            conn=conn,
        )
        if not selected:
            return {
                "ok": False,
                "error": "no_combat_ships_available",
                "attack": None,
                "boss": None,
                "player": None,
                "auto_meta": pick_meta,
            }

    ok_ships, ship_reason = _validate_ships_in_hangar(selected, hangar)
    if not ok_ships:
        return {
            "ok": False,
            "error": ship_reason,
            "attack": None,
            "boss": None,
            "player": None,
        }

    definition = get_definition(event["boss_key"], conn=conn) or {}
    phase_index, defender_ships = _resolve_phase_stacks(
        definition,
        current_hp=int(event["current_hp"]),
        max_hp=int(event["max_hp"]),
        current_stacks=event.get("fleet_stacks") or {},
    )

    battle_rng = rng if rng is not None else random.Random(
        int(eid) * 1_000_003 + int(pid) * 97 + int(ts)
    )
    critical = bool(battle_rng.random() < float(INSTANT_CRIT_CHANCE))
    attack_power = compute_attack_power(
        selected, player_id=pid, planet_id=origin_id, conn=conn
    )
    rolled = compute_instant_hp_damage(
        ships=selected,
        defender_ships=defender_ships,
        max_hp=int(event["max_hp"]),
        critical=critical,
    )
    alliance_salvo = 0
    if float(ALLIANCE_SALVO_FRACTION) > 0:
        alliance_salvo = int(rolled * float(ALLIANCE_SALVO_FRACTION))
        rolled += alliance_salvo

    if rolled <= 0:
        return {
            "ok": False,
            "error": "world_boss_no_damage",
            "attack": None,
            "boss": None,
            "player": None,
            "attack_power": attack_power,
        }

    before_hp = int(event["current_hp"])
    max_hp = int(event["max_hp"])
    cur = conn.execute(
        """
        UPDATE world_boss_events
        SET current_hp = MAX(0, current_hp - ?),
            updated_at = ?
        WHERE id = ? AND status = ? AND current_hp > 0;
        """,
        (int(rolled), ts, eid, STATUS_ACTIVE),
    )
    if int(cur.rowcount or 0) <= 0:
        return {
            "ok": False,
            "error": "world_boss_defeated",
            "attack": None,
            "boss": None,
            "player": None,
        }

    updated_row = conn.execute(
        "SELECT current_hp FROM world_boss_events WHERE id = ? LIMIT 1;",
        (eid,),
    ).fetchone()
    new_hp = max(0, int(updated_row["current_hp"] if updated_row else 0))
    applied = max(0, before_hp - new_hp)
    defeated = new_hp <= 0

    new_phase, remaining_def = _resolve_phase_stacks(
        definition,
        current_hp=new_hp,
        max_hp=max_hp,
        current_stacks=defender_ships,
    )
    new_status = STATUS_DEFEATED if defeated else STATUS_ACTIVE
    conn.execute(
        """
        UPDATE world_boss_events
        SET phase_index = ?,
            fleet_stacks_json = ?,
            status = ?,
            defeated_at = CASE WHEN ? THEN ? ELSE defeated_at END,
            updated_at = ?
        WHERE id = ?;
        """,
        (
            int(new_phase),
            _json_dumps(remaining_def),
            new_status,
            1 if defeated else 0,
            ts,
            ts,
            eid,
        ),
    )

    try:
        from .pirates.hooks import safe_record_heat

        safe_record_heat(conn, int(event.get("galaxy") or 0) or None, "world_boss")
    except Exception:
        logger.exception("pirate heat world_boss instant hook failed event_id=%s", eid)

    alliance_id = None
    try:
        from .alliance import get_player_alliance

        membership = get_player_alliance(pid, conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        logger.exception("world_boss alliance lookup failed player=%s", pid)

    note_attack_dispatched(
        pid, eid, conn=conn, now=ts, alliance_id=alliance_id
    )

    wave_xp = 0
    alliance_xp_granted = 0
    if alliance_id is not None and applied > 0:
        wave_xp = alliance_xp_from_boss_damage(int(applied))

    _upsert_contribution(
        event_id=eid,
        player_id=pid,
        alliance_id=alliance_id,
        damage=applied,
        alliance_xp=wave_xp,
        now=ts,
        conn=conn,
    )

    if alliance_id is not None and wave_xp > 0:
        try:
            from .alliance import grant_alliance_xp

            alliance_xp_granted = int(
                grant_alliance_xp(int(alliance_id), wave_xp, conn=conn)
            )
        except Exception:
            logger.exception(
                "world_boss alliance xp failed player=%s alliance=%s",
                pid,
                alliance_id,
            )

    try:
        from .directives.progress import emit_world_boss_damage_event

        # Synthetic movement id: unique per event/player/wave for directive ledger.
        waves_after = int(meta.get("waves") or 0) + 1
        synth_movement = int(eid) * 1_000_000 + (pid % 10_000) * 100 + (waves_after % 100)
        emit_world_boss_damage_event(
            pid,
            movement_id=synth_movement,
            damage=applied,
            event_id=eid,
            conn=conn,
            now=ts,
        )
    except Exception:
        logger.exception("world_boss directive emit failed instant event=%s", eid)

    updated = get_event_by_id(eid, conn=conn)
    if defeated and updated:
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)
        try:
            _announce_defeat(updated, conn=conn)
        except Exception:
            logger.exception("world_boss defeat news failed event=%s", eid)

    cooldown_until = float(ts + WAVE_COOLDOWN_SEC)
    hp_ratio = (float(new_hp) / float(max_hp)) if max_hp > 0 else 0.0
    contrib_row = conn.execute(
        """
        SELECT damage, waves FROM world_boss_contributions
        WHERE event_id = ? AND player_id = ? LIMIT 1;
        """,
        (eid, pid),
    ).fetchone()
    total_damage = int(contrib_row["damage"] or 0) if contrib_row else int(applied)
    waves_done = int(contrib_row["waves"] or 0) if contrib_row else 1

    rank = None
    total_players = None
    try:
        contribs = list_contributions(eid, conn=conn, limit=200)
        total_players = len(contribs)
        for row in contribs:
            if int(row.get("player_id") or 0) == pid:
                rank = int(row.get("rank") or 0)
                break
    except Exception:
        logger.exception("world_boss rank lookup failed")

    hangar_after = get_planet_ships(origin_id, conn=conn)

    return {
        "ok": True,
        "error": "",
        "attack": {
            "damage": int(applied),
            "critical": bool(critical),
            "projectile_profile": _projectile_profile_for_ships(selected),
            "hit_at": int(ts),
            "alliance_salvo": int(alliance_salvo),
            "attack_power": int(attack_power),
            "ships": dict(selected),
        },
        "boss": {
            "event_id": eid,
            "hp": int(new_hp),
            "max_hp": int(max_hp),
            "hp_pct": round(max(0.0, min(100.0, hp_ratio * 100.0)), 2),
            "phase": int(hp_phase_from_ratio(hp_ratio)),
            "phase_index": int(new_phase),
            "defeated": bool(defeated),
            "status": new_status,
            "boss_key": str(event.get("boss_key") or ""),
        },
        "player": {
            "total_damage": int(total_damage),
            "rank": rank,
            "total_players": total_players,
            "cooldown_until": cooldown_until,
            "waves": int(waves_done),
            "max_waves": int(MAX_WAVES_PER_PLAYER),
            "alliance_xp_granted": int(alliance_xp_granted),
        },
        "ships_snapshot": dict(selected),
        "hangar_unchanged": hangar_after == hangar,
        "event": updated,
        "damage": int(applied),
        "defeated": bool(defeated),
    }


def compute_world_boss_hp_damage(
    *,
    defender_ships_before: Mapping[str, int],
    defender_losses: Mapping[str, int],
    max_hp: int,
    attacker_ships_before: Mapping[str, int] | None = None,
) -> int:
    """
    Map battle defender losses → shared boss HP damage.

    Wipe fraction uses combat prestige scores of the wave. Overkill multiplies by
    ``1 + OVERKILL_LOG_SCALE * log2(max(1, attacker_score / wave_score))`` so mega fleets
    deal more than even fights but stay near ``MAX_WAVE_HP_FRACTION`` (≈10–20 solo waves).
    """
    from .scoring import compute_destroyed_raw_from_losses

    hp_budget = max(0, int(max_hp))
    if hp_budget <= 0:
        return 0

    before = {
        str(k): max(0, int(v or 0))
        for k, v in dict(defender_ships_before or {}).items()
        if int(v or 0) > 0
    }
    losses = {
        str(k): max(0, int(v or 0))
        for k, v in dict(defender_losses or {}).items()
        if int(v or 0) > 0
    }
    if not losses:
        return 0

    full_score = int(compute_destroyed_raw_from_losses(before)) if before else 0
    lost_score = int(compute_destroyed_raw_from_losses(losses))
    if full_score <= 0:
        return 1 if lost_score > 0 or losses else 0

    fraction = min(1.0, float(lost_score) / float(full_score))
    atk = {
        str(k): max(0, int(v or 0))
        for k, v in dict(attacker_ships_before or {}).items()
        if int(v or 0) > 0
    }
    attacker_score = int(compute_destroyed_raw_from_losses(atk)) if atk else 0
    force_ratio = float(attacker_score) / float(max(full_score, 1))
    # Even fight (ratio≈1) stays at 1.0; only larger fleets gain soft overkill.
    overkill_mult = max(
        1.0,
        1.0 + float(OVERKILL_LOG_SCALE) * math.log2(max(1.0, force_ratio)),
    )
    base = float(hp_budget) * float(WAVE_HP_FRACTION) * fraction * overkill_mult
    cap = float(hp_budget) * float(MAX_WAVE_HP_FRACTION)
    damage = int(min(cap, max(0.0, base)))
    if damage <= 0 and lost_score > 0:
        return 1
    return max(0, damage)


def spawn_world_boss(
    boss_key: str,
    *,
    conn,
    now: Optional[float] = None,
    galaxy: Optional[int] = None,
    system: Optional[int] = None,
    position: Optional[int] = None,
    announce: bool = True,
    force: bool = False,
    discovered_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Create an active world boss event.

    Without ``force``: refuses when concurrent cap is reached or the same
    ``boss_key`` is already active. With ``force``: expires same-key actives
    and may exceed the soft concurrent cap.
    """
    from .db import column_exists

    if not world_boss_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    definition = get_definition(boss_key, conn=conn)
    if not definition or not definition.get("active"):
        return {"ok": False, "error": "unknown_boss"}

    active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 10)
    same_key = [e for e in active if str(e.get("boss_key")) == str(boss_key)]
    if same_key and not force:
        return {"ok": False, "error": "boss_key_already_active", "event": same_key[0]}
    if same_key and force:
        for ev in same_key:
            _expire_event(int(ev["id"]), conn=conn, now=ts, status=STATUS_EXPIRED)
        active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 10)

    if len(active) >= int(MAX_CONCURRENT_EVENTS) and not force:
        return {
            "ok": False,
            "error": "concurrent_cap",
            "active_count": len(active),
            "max_concurrent": int(MAX_CONCURRENT_EVENTS),
        }

    prefer_dense = str(boss_key) == "planet_eater"
    blocked = _active_boss_coords(conn, now=ts)
    if galaxy is None or system is None or position is None:
        g, s, p = _pick_spawn_coords(
            conn, prefer_dense=prefer_dense, blocked=blocked, now=ts
        )
    else:
        g, s, p = int(galaxy), int(system), int(position)
        if (g, s, p) in blocked:
            return {
                "ok": False,
                "error": "coords_occupied",
                "coords": f"[{g}:{s}:{p}]",
            }

    duration = int(definition["duration_seconds"] or DEFAULT_EVENT_DURATION_SEC)
    stacks = {
        str(k): max(0, int(v or 0))
        for k, v in dict(definition.get("fleet_stacks") or {}).items()
        if int(v or 0) > 0
    }
    max_hp = int(definition["max_hp"])
    disc_id = int(discovered_by) if discovered_by is not None and int(discovered_by) > 0 else None
    has_disc_col = column_exists(conn, WORLD_BOSS_EVENT_TABLE, "discovered_by_player_id")
    cur = conn.cursor()
    if has_disc_col:
        cur.execute(
            """
            INSERT INTO world_boss_events (
                boss_key, status, galaxy, system, position,
                max_hp, current_hp, phase_index, fleet_stacks_json,
                starts_at, ends_at, defeated_at, created_at, updated_at,
                discovered_by_player_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, NULL, ?, ?, ?);
            """,
            (
                str(boss_key),
                STATUS_ACTIVE,
                g,
                s,
                p,
                max_hp,
                max_hp,
                _json_dumps(stacks),
                ts,
                ts + duration,
                ts,
                ts,
                disc_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO world_boss_events (
                boss_key, status, galaxy, system, position,
                max_hp, current_hp, phase_index, fleet_stacks_json,
                starts_at, ends_at, defeated_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, NULL, ?, ?);
            """,
            (
                str(boss_key),
                STATUS_ACTIVE,
                g,
                s,
                p,
                max_hp,
                max_hp,
                _json_dumps(stacks),
                ts,
                ts + duration,
                ts,
                ts,
            ),
        )
    event_id = int(cur.lastrowid)
    event = get_event_by_id(event_id, conn=conn)
    set_runtime_value(SPAWN_RUNTIME_KEY, str(ts), conn=conn)

    if announce and event:
        try:
            _announce_spawn(event, conn=conn)
        except Exception:
            logger.exception("world_boss spawn news failed event_id=%s", event_id)

    return {"ok": True, "event": event}


def _boss_display_name(event: Mapping[str, Any], *, locale: str) -> str:
    from .i18n import tr

    name_key = str(event.get("name_key") or f"wb_boss_{event.get('boss_key')}")
    return tr(name_key, str(event.get("boss_key") or "World Boss"), locale=locale)


def format_world_boss_news(
    event: Mapping[str, Any],
    *,
    kind: str,
    locale: Optional[str] = None,
    discoverer_name: Optional[str] = None,
) -> Dict[str, str]:
    """Build localized title/body for spawn or defeat news (display + persist)."""
    from .i18n import DEFAULT_LOCALE, fmt_int, normalize_locale, tr

    loc = normalize_locale(locale) if locale is not None else DEFAULT_LOCALE
    boss_name = _boss_display_name(event, locale=loc)
    coords = str(event.get("coords") or "")
    if kind == "defeat":
        return {
            "title": tr(
                "wb_news_defeat_title",
                "World Boss besiegt: %(boss)s",
                locale=loc,
                boss=boss_name,
            ),
            "body": tr(
                "wb_news_defeat_body",
                "Der World Boss bei %(coords)s wurde besiegt. Belohnungen auf dem World-Boss-Board abholen.",
                locale=loc,
                coords=coords,
            ),
        }
    if kind == "tame":
        return {
            "title": tr(
                "wb_news_tame_title",
                "World Boss gezähmt: %(boss)s",
                locale=loc,
                boss=boss_name,
            ),
            "body": tr(
                "wb_news_tame_body",
                "Der World Boss bei %(coords)s wurde gezähmt und ist verschwunden. Belohnungen wurden an alle Teilnehmer ausgezahlt.",
                locale=loc,
                coords=coords,
            ),
        }
    if discoverer_name:
        return {
            "title": tr(
                "wb_news_spawn_title",
                "World Boss: %(boss)s",
                locale=loc,
                boss=boss_name,
            ),
            "body": tr(
                "wb_news_spawn_body_discovered",
                "%(player)s hat einen World Boss bei %(coords)s entdeckt (Expedition). HP %(hp)s/%(max_hp)s — für alle angreifbar.",
                locale=loc,
                player=str(discoverer_name),
                coords=coords,
                hp=fmt_int(event.get("current_hp") or 0),
                max_hp=fmt_int(event.get("max_hp") or 0),
            ),
        }
    return {
        "title": tr(
            "wb_news_spawn_title",
            "World Boss: %(boss)s",
            locale=loc,
            boss=boss_name,
        ),
        "body": tr(
            "wb_news_spawn_body",
            "Ein World Boss ist bei %(coords)s erschienen. HP %(hp)s/%(max_hp)s. Angriff über Galaxie oder Flotte.",
            locale=loc,
            coords=coords,
            hp=fmt_int(event.get("current_hp") or 0),
            max_hp=fmt_int(event.get("max_hp") or 0),
        ),
    }


def localize_world_boss_news_entry(
    entry: Mapping[str, Any],
    *,
    locale: Optional[str] = None,
    conn=None,
) -> Dict[str, Any]:
    """Rewrite title/body for world_boss source_ref using the viewer's locale."""
    from .i18n import current_locale, normalize_locale

    ref = str(entry.get("source_ref") or "").strip()
    if not ref.startswith("world_boss:"):
        return dict(entry)

    parts = ref.split(":")
    kind = parts[1] if len(parts) > 1 else "spawn"
    try:
        event_id = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        event_id = 0
    if event_id <= 0:
        return dict(entry)

    own = conn is None
    if own:
        from .db import db as _db

        conn = _db()
    try:
        event = get_event_by_id(event_id, conn=conn)
        if not event:
            return dict(entry)
        loc = normalize_locale(locale) if locale is not None else current_locale()
        copy = format_world_boss_news(event, kind=kind, locale=loc)
        out = dict(entry)
        out["title"] = copy["title"]
        out["body"] = copy["body"]
        return out
    finally:
        if own:
            conn.close()


def _announce_spawn(event: Mapping[str, Any], *, conn) -> None:
    from .i18n import DEFAULT_LOCALE
    from .universe_news import create_news

    discoverer_name = None
    disc_id = event.get("discovered_by_player_id")
    if disc_id:
        discoverer_name = _player_name(int(disc_id), conn=conn)
    copy = format_world_boss_news(
        event,
        kind="spawn",
        locale=DEFAULT_LOCALE,
        discoverer_name=discoverer_name,
    )
    create_news(
        title=copy["title"],
        body=copy["body"],
        category="EVENT",
        badge="EVENT",
        source_ref=f"world_boss:spawn:{int(event['id'])}",
        set_banner=True,
        conn=conn,
    )


def _announce_defeat(event: Mapping[str, Any], *, conn) -> None:
    from .i18n import DEFAULT_LOCALE
    from .universe_news import create_news

    copy = format_world_boss_news(event, kind="defeat", locale=DEFAULT_LOCALE)
    create_news(
        title=copy["title"],
        body=copy["body"],
        category="EVENT",
        badge="EVENT",
        source_ref=f"world_boss:defeat:{int(event['id'])}",
        set_banner=True,
        conn=conn,
    )


def _announce_tame(event: Mapping[str, Any], *, conn) -> None:
    from .i18n import DEFAULT_LOCALE
    from .universe_news import create_news

    copy = format_world_boss_news(event, kind="tame", locale=DEFAULT_LOCALE)
    create_news(
        title=copy["title"],
        body=copy["body"],
        category="EVENT",
        badge="EVENT",
        source_ref=f"world_boss:tame:{int(event['id'])}",
        set_banner=True,
        conn=conn,
    )


def _expire_event(
    event_id: int,
    *,
    conn,
    now: float,
    status: str = STATUS_EXPIRED,
) -> None:
    conn.execute(
        """
        UPDATE world_boss_events
        SET status = ?, updated_at = ?,
            defeated_at = CASE
                WHEN ? IN ('defeated', 'tamed') THEN ?
                ELSE defeated_at
            END
        WHERE id = ? AND status = ?;
        """,
        (status, float(now), status, float(now), int(event_id), STATUS_ACTIVE),
    )
    set_runtime_value(SCHEDULE_RUNTIME_KEY, str(float(now)), conn=conn)


def close_event_as_tamed(
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Remove live boss after successful catch: status tamed, HP 0, stop auto-attack."""
    if not world_boss_schema_ready(conn):
        return None
    ts = float(now if now is not None else _now())
    eid = int(event_id)
    conn.execute(
        """
        UPDATE world_boss_events
        SET status = ?, current_hp = 0, defeated_at = ?, updated_at = ?
        WHERE id = ? AND status = ?;
        """,
        (STATUS_TAMED, ts, ts, eid, STATUS_ACTIVE),
    )
    if _auto_attack_columns_ready(conn):
        conn.execute(
            """
            UPDATE world_boss_contributions
            SET auto_attack_enabled = 0
            WHERE event_id = ? AND auto_attack_enabled = 1;
            """,
            (eid,),
        )
    set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)
    updated = get_event_by_id(eid, conn=conn)
    if updated and str(updated.get("status") or "") == STATUS_TAMED:
        try:
            _announce_tame(updated, conn=conn)
        except Exception:
            logger.exception("world_boss tame news failed event=%s", eid)
    return updated


def auto_distribute_world_boss_rewards(
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Pay every damage contributor via claim_world_boss_rewards (idempotent)."""
    ts = float(now if now is not None else _now())
    eid = int(event_id)
    contribs = list_contributions(eid, conn=conn, limit=10000)
    paid: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for row in contribs:
        pid = int(row.get("player_id") or 0)
        if pid <= 0 or int(row.get("damage") or 0) <= 0:
            continue
        result = claim_world_boss_rewards(pid, eid, conn=conn, now=ts)
        entry = {
            "player_id": pid,
            "ok": bool(result.get("ok")),
            "error": str(result.get("error") or ""),
            "tiers": list(result.get("tiers") or []),
        }
        if result.get("ok"):
            paid.append(entry)
        else:
            skipped.append(entry)
    return {
        "ok": True,
        "event_id": eid,
        "participant_count": len(paid) + len(skipped),
        "claimed_count": len(paid),
        "skipped_count": len(skipped),
        "paid": paid,
        "skipped": skipped,
    }


def has_inflight_world_boss_attack(
    player_id: int,
    event: Mapping[str, Any],
    *,
    conn,
    exclude_movement_id: Optional[int] = None,
) -> bool:
    """True if player already has an outbound attack en route to this boss slot."""
    from .db import table_exists

    if not table_exists(conn, "fleet_movements"):
        return False
    params: List[Any] = [
        int(player_id),
        int(event["galaxy"]),
        int(event["system"]),
        int(event["position"]),
    ]
    exclude_sql = ""
    if exclude_movement_id is not None and int(exclude_movement_id) > 0:
        exclude_sql = " AND id != ?"
        params.append(int(exclude_movement_id))
    row = conn.execute(
        f"""
        SELECT id FROM fleet_movements
        WHERE player_id = ?
          AND mission_type = 'attack'
          AND status = 'outbound'
          AND target_galaxy = ?
          AND target_system = ?
          AND target_position = ?
          {exclude_sql}
        LIMIT 1;
        """,
        tuple(params),
    ).fetchone()
    return row is not None


def note_attack_dispatched(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
    alliance_id: Optional[int] = None,
) -> None:
    """Start wave cooldown at fleet send (no wave/damage yet)."""
    ts = float(now if now is not None else _now())
    if alliance_id is None:
        try:
            from .alliance import get_player_alliance

            membership = get_player_alliance(int(player_id), conn=conn)
            if membership:
                alliance_id = int(membership["alliance_id"])
        except Exception:
            alliance_id = None
    conn.execute(
        """
        INSERT INTO world_boss_contributions (
            event_id, player_id, alliance_id, damage, waves,
            last_attack_at, created_at, updated_at
        ) VALUES (?, ?, ?, 0, 0, ?, ?, ?)
        ON CONFLICT(event_id, player_id) DO UPDATE SET
            last_attack_at = excluded.last_attack_at,
            alliance_id = COALESCE(excluded.alliance_id, alliance_id),
            updated_at = excluded.updated_at;
        """,
        (
            int(event_id),
            int(player_id),
            int(alliance_id) if alliance_id is not None else None,
            ts,
            ts,
            ts,
        ),
    )


def can_player_attack_boss(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
    enforce_cooldown: bool = True,
    check_inflight: bool = True,
    exclude_movement_id: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    ts = float(now if now is not None else _now())
    event = get_event_by_id(int(event_id), conn=conn)
    if not event or event["status"] != STATUS_ACTIVE:
        return False, "world_boss_inactive", {}
    if ts >= float(event["ends_at"]):
        return False, "world_boss_expired", {"event": event}
    if int(event["current_hp"]) <= 0:
        return False, "world_boss_defeated", {"event": event}

    row = conn.execute(
        """
        SELECT waves, last_attack_at FROM world_boss_contributions
        WHERE event_id = ? AND player_id = ?
        LIMIT 1;
        """,
        (int(event_id), int(player_id)),
    ).fetchone()
    waves = int(row["waves"] or 0) if row else 0
    last_at = float(row["last_attack_at"] or 0) if row and row["last_attack_at"] is not None else 0.0
    base_meta: Dict[str, Any] = {
        "waves": waves,
        "max_waves": int(MAX_WAVES_PER_PLAYER),
        "wave_cooldown_sec": int(WAVE_COOLDOWN_SEC),
        "last_attack_at": last_at if last_at > 0 else None,
        "next_attack_at": None,
        "cooldown_until": None,
        "cooldown_remaining": 0,
    }
    if waves >= MAX_WAVES_PER_PLAYER:
        return False, "world_boss_wave_limit", base_meta
    if check_inflight and has_inflight_world_boss_attack(
        int(player_id),
        event,
        conn=conn,
        exclude_movement_id=exclude_movement_id,
    ):
        return False, "world_boss_inflight", base_meta
    if enforce_cooldown and last_at > 0 and (ts - last_at) < WAVE_COOLDOWN_SEC:
        remaining = max(0, int(WAVE_COOLDOWN_SEC - (ts - last_at)))
        next_at = float(last_at + WAVE_COOLDOWN_SEC)
        base_meta["cooldown_remaining"] = remaining
        base_meta["next_attack_at"] = next_at
        base_meta["cooldown_until"] = next_at
        return False, "world_boss_cooldown", base_meta
    base_meta["event"] = event
    return True, "", base_meta


def resolve_attack_arrival(
    *,
    movement: Mapping[str, Any],
    ships: Mapping[str, int],
    player_id: int,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Resolve a world-boss attack on fleet arrival.

    Returns dict with return_ships, combat_result, event, damage, defeated.
    """
    from .combat import (
        attacker_stacks_from_fleet,
        battle_rng_for_movement,
        publish_attack_combat_report,
        remaining_stock,
        simulate_battle,
        spawn_combat_debris_field,
    )

    ts = float(now if now is not None else _now())
    movement_id = int(movement["id"])
    tg = int(movement["target_galaxy"])
    ts_sys = int(movement["target_system"])
    tp = int(movement["target_position"])
    event = get_active_event_at(tg, ts_sys, tp, conn=conn, now=ts)
    if not event:
        return {
            "ok": False,
            "error": "world_boss_inactive",
            "return_ships": dict(ships),
            "combat_result": None,
            "event": None,
            "damage": 0,
            "defeated": False,
        }

    ok_atk, reason, meta = can_player_attack_boss(
        int(player_id),
        int(event["id"]),
        conn=conn,
        now=ts,
        enforce_cooldown=False,
        check_inflight=False,
        exclude_movement_id=movement_id,
    )
    if not ok_atk:
        return {
            "ok": False,
            "error": reason,
            "return_ships": dict(ships),
            "combat_result": None,
            "event": event,
            "damage": 0,
            "defeated": False,
            **meta,
        }

    definition = get_definition(event["boss_key"], conn=conn) or {}
    phase_index, defender_ships = _resolve_phase_stacks(
        definition,
        current_hp=int(event["current_hp"]),
        max_hp=int(event["max_hp"]),
        current_stacks=event.get("fleet_stacks") or {},
    )
    atk_stacks = attacker_stacks_from_fleet(ships)
    from .combat_models import COMBAT_UNIT_SHIP, stacks_from_counts

    def_stacks = stacks_from_counts(defender_ships, unit_type=COMBAT_UNIT_SHIP)
    combat_result = simulate_battle(
        atk_stacks,
        def_stacks,
        rng=battle_rng_for_movement(movement_id),
        attacker_player_id=int(player_id),
        defender_player_id=None,
        conn=conn,
    )
    return_ships = remaining_stock(
        ships,
        combat_result.attacker_losses,
        canonical_ship_keys=True,
    )
    damage = compute_world_boss_hp_damage(
        defender_ships_before=defender_ships,
        defender_losses=combat_result.defender_losses or {},
        max_hp=int(event["max_hp"]),
        attacker_ships_before=ships,
    )

    remaining_def = remaining_stock(defender_ships, combat_result.defender_losses or {})
    new_hp = max(0, int(event["current_hp"]) - damage)
    defeated = new_hp <= 0
    new_status = STATUS_DEFEATED if defeated else STATUS_ACTIVE

    conn.execute(
        """
        UPDATE world_boss_events
        SET current_hp = ?, phase_index = ?, fleet_stacks_json = ?,
            status = ?, defeated_at = CASE WHEN ? THEN ? ELSE defeated_at END,
            updated_at = ?
        WHERE id = ? AND status = ?;
        """,
        (
            new_hp,
            int(phase_index),
            _json_dumps(remaining_def),
            new_status,
            1 if defeated else 0,
            ts,
            ts,
            int(event["id"]),
            STATUS_ACTIVE,
        ),
    )

    try:
        from .pirates.hooks import safe_record_heat

        safe_record_heat(conn, int(event.get("galaxy") or 0) or None, "world_boss")
    except Exception:
        logger.exception("pirate heat world_boss hook failed event_id=%s", event.get("id"))

    alliance_id = None
    try:
        from .alliance import get_player_alliance

        membership = get_player_alliance(int(player_id), conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        logger.exception("world_boss alliance lookup failed player=%s", player_id)

    alliance_xp_granted = 0
    wave_xp = 0
    if alliance_id is not None and int(damage) > 0:
        wave_xp = alliance_xp_from_boss_damage(int(damage))

    _upsert_contribution(
        event_id=int(event["id"]),
        player_id=int(player_id),
        alliance_id=alliance_id,
        damage=damage,
        alliance_xp=wave_xp,
        now=ts,
        conn=conn,
    )

    if alliance_id is not None and wave_xp > 0:
        try:
            from .alliance import grant_alliance_xp

            alliance_xp_granted = int(
                grant_alliance_xp(int(alliance_id), wave_xp, conn=conn)
            )
        except Exception:
            logger.exception(
                "world_boss alliance xp failed player=%s alliance=%s",
                player_id,
                alliance_id,
            )

    try:
        spawn_combat_debris_field(
            galaxy=tg,
            system=ts_sys,
            position=tp,
            attacker_losses=combat_result.attacker_losses or {},
            defender_losses=combat_result.defender_losses or {},
            conn=conn,
        )
    except Exception:
        logger.exception("world_boss debris spawn failed movement=%s", movement_id)

    from .i18n import get_player_locale

    attacker_name = _player_name(int(player_id), conn=conn)
    attacker_locale = get_player_locale(int(player_id), conn=conn)
    boss_label = _boss_display_name(event, locale=attacker_locale)
    try:
        publish_attack_combat_report(
            attacker_id=int(player_id),
            defender_id=0,
            coords=str(event.get("coords") or ""),
            attacker_name=attacker_name,
            defender_name=boss_label,
            attacking_ships=ships,
            defending_ships=defender_ships,
            defending_defense={},
            combat_result=combat_result,
            return_ships=return_ships,
            loot={},
            fleet_id=movement_id,
            origin_coords=None,
            origin_planet_name=None,
            target_planet_name="",
            attacker_planet_id=int(movement.get("origin_planet_id") or 0) or None,
            defender_planet_id=None,
            conn=conn,
            attacker_locale=attacker_locale,
            defender_locale=None,
            combat_kind="world_boss",
            extra_metadata={
                "world_boss_event_id": int(event["id"]),
                "world_boss_damage": int(damage),
                "boss_key": str(event.get("boss_key") or ""),
            },
        )
    except Exception:
        logger.exception("world_boss combat report failed movement=%s", movement_id)

    try:
        from .directives.progress import emit_world_boss_damage_event

        emit_world_boss_damage_event(
            int(player_id),
            movement_id=movement_id,
            damage=damage,
            event_id=int(event["id"]),
            conn=conn,
            now=ts,
        )
    except Exception:
        logger.exception("world_boss directive emit failed movement=%s", movement_id)

    updated = get_event_by_id(int(event["id"]), conn=conn)
    if defeated and updated:
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)
        try:
            _announce_defeat(updated, conn=conn)
        except Exception:
            logger.exception("world_boss defeat news failed event=%s", event["id"])

    return {
        "ok": True,
        "error": "",
        "return_ships": return_ships,
        "combat_result": combat_result,
        "event": updated,
        "damage": damage,
        "defeated": defeated,
        "defender_ships_before": defender_ships,
        "alliance_id": int(alliance_id) if alliance_id is not None else None,
        "alliance_xp_granted": int(alliance_xp_granted),
    }


def _player_name(player_id: int, *, conn) -> str:
    row = conn.execute(
        "SELECT name FROM players WHERE id = ? LIMIT 1;",
        (int(player_id),),
    ).fetchone()
    return str(row["name"] or f"Player {player_id}") if row else f"Player {player_id}"


def _upsert_contribution(
    *,
    event_id: int,
    player_id: int,
    alliance_id: Optional[int],
    damage: int,
    now: float,
    conn,
    alliance_xp: int = 0,
) -> None:
    """Apply arrival damage/waves. Preserves ``last_attack_at`` from send-time CD."""
    from .db import column_exists

    dmg = max(0, int(damage))
    xp = max(0, int(alliance_xp))
    has_xp_col = column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "alliance_xp")
    if has_xp_col:
        conn.execute(
            """
            INSERT INTO world_boss_contributions (
                event_id, player_id, alliance_id, damage, waves, alliance_xp,
                last_attack_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(event_id, player_id) DO UPDATE SET
                damage = damage + excluded.damage,
                waves = waves + 1,
                alliance_xp = alliance_xp + excluded.alliance_xp,
                alliance_id = COALESCE(excluded.alliance_id, alliance_id),
                updated_at = excluded.updated_at;
            """,
            (
                int(event_id),
                int(player_id),
                int(alliance_id) if alliance_id is not None else None,
                dmg,
                xp,
                float(now),
                float(now),
                float(now),
            ),
        )
        return
    conn.execute(
        """
        INSERT INTO world_boss_contributions (
            event_id, player_id, alliance_id, damage, waves,
            last_attack_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(event_id, player_id) DO UPDATE SET
            damage = damage + excluded.damage,
            waves = waves + 1,
            alliance_id = COALESCE(excluded.alliance_id, alliance_id),
            updated_at = excluded.updated_at;
        """,
        (
            int(event_id),
            int(player_id),
            int(alliance_id) if alliance_id is not None else None,
            dmg,
            float(now),
            float(now),
            float(now),
        ),
    )


def list_contributions(
    event_id: int,
    *,
    conn,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return []
    from .db import column_exists

    has_xp_col = column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "alliance_xp")
    xp_select = "c.alliance_xp" if has_xp_col else "0 AS alliance_xp"
    rows = conn.execute(
        f"""
        SELECT c.player_id, c.alliance_id, c.damage, c.waves, {xp_select}, c.last_attack_at,
               p.name AS player_name, a.tag AS alliance_tag
        FROM world_boss_contributions c
        LEFT JOIN players p ON p.id = c.player_id
        LEFT JOIN alliances a ON a.id = c.alliance_id
        WHERE c.event_id = ?
        ORDER BY c.damage DESC, c.updated_at ASC
        LIMIT ?;
        """,
        (int(event_id), max(1, int(limit))),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        out.append(
            {
                "rank": idx,
                "player_id": int(row["player_id"]),
                "player_name": str(row["player_name"] or ""),
                "alliance_id": int(row["alliance_id"]) if row["alliance_id"] is not None else None,
                "alliance_tag": str(row["alliance_tag"] or "") or None,
                "damage": int(row["damage"] or 0),
                "waves": int(row["waves"] or 0),
                "alliance_xp": int(row["alliance_xp"] or 0),
                "last_attack_at": float(row["last_attack_at"]) if row["last_attack_at"] else None,
            }
        )
    return out


def list_alliance_contributions(
    event_id: int,
    *,
    conn,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    if not world_boss_schema_ready(conn):
        return []
    from .db import column_exists

    has_xp_col = column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "alliance_xp")
    xp_sum = "COALESCE(SUM(c.alliance_xp), 0)" if has_xp_col else "0"
    rows = conn.execute(
        f"""
        SELECT c.alliance_id, SUM(c.damage) AS damage, COUNT(*) AS members,
               {xp_sum} AS alliance_xp,
               a.tag AS alliance_tag, a.name AS alliance_name
        FROM world_boss_contributions c
        LEFT JOIN alliances a ON a.id = c.alliance_id
        WHERE c.event_id = ? AND c.alliance_id IS NOT NULL
        GROUP BY c.alliance_id
        ORDER BY damage DESC
        LIMIT ?;
        """,
        (int(event_id), max(1, int(limit))),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        out.append(
            {
                "rank": idx,
                "alliance_id": int(row["alliance_id"]),
                "alliance_tag": str(row["alliance_tag"] or ""),
                "alliance_name": str(row["alliance_name"] or ""),
                "damage": int(row["damage"] or 0),
                "alliance_xp": int(row["alliance_xp"] or 0),
                "members": int(row["members"] or 0),
            }
        )
    return out


def _player_claim_row(event_id: int, player_id: int, *, conn) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, tiers_json, rewards_json, claimed_at
        FROM world_boss_claims
        WHERE event_id = ? AND player_id = ?
        LIMIT 1;
        """,
        (int(event_id), int(player_id)),
    ).fetchone()
    if not row:
        return None
    rewards = list(_json_loads(row["rewards_json"], []) or [])
    for entry in rewards:
        if not isinstance(entry, dict):
            continue
        item_key = str(entry.get("item_key") or "").strip()
        if item_key and not entry.get("name_key"):
            entry["name_key"] = f"inv_{item_key}"
    return {
        "id": int(row["id"]),
        "tiers": list(_json_loads(row["tiers_json"], []) or []),
        "rewards": rewards,
        "claimed_at": float(row["claimed_at"]),
    }


def compute_claim_tiers(
    event_id: int,
    player_id: int,
    *,
    conn,
) -> Tuple[List[str], Dict[str, Any]]:
    contribs = list_contributions(event_id, conn=conn, limit=10000)
    player_row = next((c for c in contribs if int(c["player_id"]) == int(player_id)), None)
    if not player_row or int(player_row["damage"]) <= 0:
        return [], {"error": "no_contribution"}

    tiers: List[str] = ["participate"]
    total = len(contribs)
    rank = int(player_row["rank"])
    if rank == 1:
        tiers.append("top1")
    top10_cut = max(1, int(total * 0.10 + 0.999))
    if rank <= top10_cut:
        tiers.append("top10")

    alliance_board = list_alliance_contributions(event_id, conn=conn, limit=1)
    if alliance_board:
        top_aid = int(alliance_board[0]["alliance_id"])
        if player_row.get("alliance_id") is not None and int(player_row["alliance_id"]) == top_aid:
            tiers.append("alliance_top")

    event = get_event_by_id(int(event_id), conn=conn)
    disc = event.get("discovered_by_player_id") if event else None
    if disc is not None and int(disc) == int(player_id):
        tiers.append("discoverer")

    return tiers, {"rank": rank, "damage": int(player_row["damage"]), "total_players": total}


def claim_world_boss_rewards(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    if not world_boss_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    event = get_event_by_id(int(event_id), conn=conn)
    if not event:
        return {"ok": False, "error": "event_not_found"}
    if event["status"] not in CLAIMABLE_STATUSES:
        return {"ok": False, "error": "event_not_claimable"}

    existing = _player_claim_row(int(event_id), int(player_id), conn=conn)
    if existing:
        return {"ok": False, "error": "already_claimed", "claim": existing}

    tiers, meta = compute_claim_tiers(int(event_id), int(player_id), conn=conn)
    if not tiers:
        return {"ok": False, "error": meta.get("error") or "no_contribution"}

    from .inventory import grant_inventory_item

    # Aggregate amounts per item_key across earned tiers (boss loot_pool_key).
    amounts: Dict[str, int] = {}
    tier_for_key: Dict[str, str] = {}
    for tier, item_key, amount in build_reward_tier_grants(event.get("loot_pool_key")):
        if tier not in tiers:
            continue
        amounts[item_key] = amounts.get(item_key, 0) + int(amount)
        tier_for_key.setdefault(item_key, tier)

    granted: List[Dict[str, Any]] = []
    for item_key, amount in amounts.items():
        ok = grant_inventory_item(
            int(player_id),
            item_key,
            int(amount),
            conn=conn,
            metadata={
                "source": "world_boss",
                "event_id": int(event_id),
                "tier": tier_for_key.get(item_key, "participate"),
            },
        )
        if ok:
            granted.append(
                {
                    "tier": tier_for_key.get(item_key, "participate"),
                    "item_key": item_key,
                    "amount": int(amount),
                    "name_key": f"inv_{item_key}",
                }
            )

    if not granted:
        return {"ok": False, "error": "grant_failed", "tiers": tiers}

    conn.execute(
        """
        INSERT INTO world_boss_claims (event_id, player_id, tiers_json, rewards_json, claimed_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (
            int(event_id),
            int(player_id),
            _json_dumps(tiers),
            _json_dumps(granted),
            ts,
        ),
    )
    return {
        "ok": True,
        "event_id": int(event_id),
        "tiers": tiers,
        "rewards": granted,
        "meta": meta,
    }


def _pick_weighted_boss_key(
    definitions: List[Dict[str, Any]],
    *,
    exclude_keys: set[str],
) -> Optional[str]:
    import random

    pool = [
        d
        for d in definitions
        if str(d.get("boss_key") or "") not in exclude_keys and int(d.get("spawn_weight") or 0) > 0
    ]
    if not pool:
        return None
    weights = [max(1, int(d.get("spawn_weight") or 1)) for d in pool]
    pick = random.choices(pool, weights=weights, k=1)[0]
    return str(pick["boss_key"])


def try_discover_world_boss_from_expedition(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
    rng: Any = None,
) -> Dict[str, Any]:
    """Rare expo discovery → spawn one boss if under concurrent cap."""
    import random as _random

    ts = float(now if now is not None else _now())
    roller = rng if rng is not None else _random.Random()
    if float(roller.random()) >= float(EXPO_DISCOVERY_CHANCE):
        return {"ok": False, "error": "no_roll"}
    active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 5)
    if len(active) >= int(MAX_CONCURRENT_EVENTS):
        return {"ok": False, "error": "concurrent_cap"}
    exclude = {str(e.get("boss_key") or "") for e in active}
    defs = list_definitions(conn=conn, active_only=True)
    boss_key = _pick_weighted_boss_key(defs, exclude_keys=exclude)
    if not boss_key:
        return {"ok": False, "error": "no_boss_available"}
    result = spawn_world_boss(
        boss_key,
        conn=conn,
        now=ts,
        announce=True,
        force=False,
        discovered_by=int(player_id),
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "spawn_failed"}
    event = result.get("event") or {}
    return {
        "ok": True,
        "event_id": int(event.get("id") or 0),
        "boss_key": str(event.get("boss_key") or boss_key),
        "coords": str(event.get("coords") or ""),
        "galaxy": int(event.get("galaxy") or 0),
        "system": int(event.get("system") or 0),
        "position": int(event.get("position") or 0),
        "discovered_by": int(player_id),
    }


def build_schedule_info(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Server-side spawn ETA for the World Boss panel."""
    ts = float(now if now is not None else _now())
    active = list_active_events(conn=conn, now=ts) if world_boss_schema_ready(conn) else []
    last_spawn: Optional[float] = None
    last_ended: Optional[float] = None
    if world_boss_schema_ready(conn):
        for key, dest in (
            (SPAWN_RUNTIME_KEY, "spawn"),
            (SCHEDULE_RUNTIME_KEY, "ended"),
        ):
            raw = get_runtime_value(key, conn=conn)
            if raw in (None, ""):
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if dest == "spawn":
                last_spawn = val
            else:
                last_ended = val
    anchor = last_spawn if last_spawn is not None and last_spawn > 0 else last_ended
    if anchor is not None and anchor > 0:
        next_eligible_at = float(anchor) + float(INTER_EVENT_COOLDOWN_SEC)
    else:
        next_eligible_at = ts
    under_cap = len(active) < int(MAX_CONCURRENT_EVENTS)
    spawn_ready = bool(under_cap and ts >= next_eligible_at)
    return {
        "inter_event_cooldown_sec": int(INTER_EVENT_COOLDOWN_SEC),
        "max_concurrent": int(MAX_CONCURRENT_EVENTS),
        "active_count": len(active),
        "last_ended_at": last_ended,
        "last_spawn_at": last_spawn,
        "next_eligible_at": float(next_eligible_at),
        "spawn_ready": spawn_ready,
        "has_active": bool(active),
    }


def formation_preview_from_hangar(
    hangar: Mapping[str, int] | None,
    *,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Top combat hulls for Encounter Stage formation (max ``limit`` types)."""
    combat = combat_ships_from_hangar(hangar)
    items = sorted(
        ((str(k), int(v)) for k, v in combat.items() if int(v) > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )[: max(0, int(limit))]
    return [{"ship_key": key, "count": qty} for key, qty in items]


def _event_card_for_player(
    event: Dict[str, Any],
    player_id: Optional[int],
    *,
    conn,
    now: float,
) -> Dict[str, Any]:
    contribs = list_contributions(int(event["id"]), conn=conn, limit=100)
    alliance_board = list_alliance_contributions(int(event["id"]), conn=conn, limit=50)
    discoverer_name = None
    disc_id = event.get("discovered_by_player_id")
    if disc_id:
        discoverer_name = _player_name(int(disc_id), conn=conn)
    player_info = None
    outlook: Dict[str, Any] = {
        "mode": "none",
        "earned_tiers": [],
        "grants": [],
        "alliance_xp_earned": 0,
        "rank": None,
        "total_players": 0,
    }
    if player_id is not None:
        mine = next((c for c in contribs if int(c["player_id"]) == int(player_id)), None)
        claim = _player_claim_row(int(event["id"]), int(player_id), conn=conn)
        can_claim = (
            event["status"] in CLAIMABLE_STATUSES
            and mine is not None
            and int(mine["damage"]) > 0
            and claim is None
        )
        ok_atk, atk_reason, atk_meta = (False, "inactive", {})
        if event["status"] == STATUS_ACTIVE:
            ok_atk, atk_reason, atk_meta = can_player_attack_boss(
                int(player_id), int(event["id"]), conn=conn, now=now
            )
        outlook = build_player_reward_outlook(event, int(player_id), conn=conn)
        formation: List[Dict[str, Any]] = []
        auto_enabled = False
        try:
            from .fleet import get_planet_ships
            from .planet_evolution.repository import get_context_planet

            planet = get_context_planet(int(player_id), conn=conn)
            if planet:
                hangar = get_planet_ships(int(planet["id"]), conn=conn)
                formation = formation_preview_from_hangar(hangar, limit=4)
        except Exception:
            logger.exception("world_boss formation preview failed player=%s", player_id)
        if _auto_attack_columns_ready(conn):
            auto_row = conn.execute(
                """
                SELECT auto_attack_enabled FROM world_boss_contributions
                WHERE event_id = ? AND player_id = ? LIMIT 1;
                """,
                (int(event["id"]), int(player_id)),
            ).fetchone()
            auto_enabled = bool(auto_row and int(auto_row["auto_attack_enabled"] or 0))
        player_info = {
            "contribution": mine,
            "claim": claim,
            "can_claim": can_claim,
            "can_attack": ok_atk,
            "attack_block_reason": atk_reason if not ok_atk else "",
            "attack_meta": atk_meta,
            "is_discoverer": bool(disc_id and int(disc_id) == int(player_id)),
            "alliance_xp_earned": int((mine or {}).get("alliance_xp") or 0),
            "reward_outlook": outlook,
            "formation": formation,
            "auto_attack_enabled": auto_enabled,
            "catch": None,
        }
        try:
            from .world_boss_companions import build_catch_info_for_event

            player_info["catch"] = build_catch_info_for_event(
                int(player_id), event, conn=conn, now=now
            )
        except Exception:
            logger.exception("world_boss catch info failed player=%s", player_id)
    earned_tiers = set(outlook.get("earned_tiers") or [])
    return {
        "event": event,
        "contributions": contribs,
        "alliance_board": alliance_board,
        "player": player_info,
        "discoverer_name": discoverer_name,
        "rewards_preview": build_rewards_preview(
            event.get("loot_pool_key"),
            earned_tiers=earned_tiers,
            alliance_xp_earned=int(outlook.get("alliance_xp_earned") or 0),
        ),
        "reward_outlook": outlook,
    }


def build_world_boss_payload(
    player_id: Optional[int] = None,
    *,
    conn,
    event_id: Optional[int] = None,
    now: Optional[float] = None,
    flush_auto: bool = True,
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    empty = {
        "ok": True,
        "ready": False,
        "event": None,
        "events": [],
        "contributions": [],
        "alliance_board": [],
        "player": None,
        "definitions": [],
        "companions": {"ready": False, "slots": [], "owned_count": 0},
        "schedule": build_schedule_info(conn=conn, now=ts),
        "server_now": ts,
        "flushed_attacks": [],
    }
    if not world_boss_schema_ready(conn):
        return empty

    # Opportunistic auto-fire so "Auto aktiv + CD frei" works without waiting on fleet_worker.
    flushed_attacks: List[Dict[str, Any]] = []
    if flush_auto and player_id is not None:
        try:
            flush_res = flush_ready_auto_attacks_for_player(int(player_id), conn=conn, now=ts)
            raw_hits = flush_res.get("attacks") if isinstance(flush_res, dict) else None
            if isinstance(raw_hits, list):
                flushed_attacks = [h for h in raw_hits if isinstance(h, dict) and h.get("attack")]
        except Exception:
            logger.exception("world_boss opportunistic auto flush failed player=%s", player_id)

    schedule = build_schedule_info(conn=conn, now=ts)
    active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 5)
    cards: List[Dict[str, Any]] = []
    for ev in active:
        cards.append(_event_card_for_player(ev, player_id, conn=conn, now=ts))

    # Recently ended claimable for this player (or latest ended for browse).
    ended_rows = conn.execute(
        """
        SELECT id FROM world_boss_events
        WHERE status IN (?, ?, ?)
        ORDER BY updated_at DESC
        LIMIT 8;
        """,
        (STATUS_DEFEATED, STATUS_EXPIRED, STATUS_TAMED),
    ).fetchall()
    active_ids = {int(c["event"]["id"]) for c in cards}
    for row in ended_rows:
        eid = int(row["id"])
        if eid in active_ids:
            continue
        ev = get_event_by_id(eid, conn=conn)
        if not ev:
            continue
        card = _event_card_for_player(ev, player_id, conn=conn, now=ts)
        # Keep ended cards that the player can claim, or when browsing a specific id.
        if player_id is not None and not (card.get("player") or {}).get("can_claim"):
            if event_id is None or int(event_id) != eid:
                continue
        cards.append(card)

    if event_id is not None:
        preferred = next((c for c in cards if int(c["event"]["id"]) == int(event_id)), None)
        if preferred is None:
            ev = get_event_by_id(int(event_id), conn=conn)
            if ev:
                preferred = _event_card_for_player(ev, player_id, conn=conn, now=ts)
                cards.insert(0, preferred)

    primary = cards[0] if cards else None
    companions: Dict[str, Any] = {"ready": False, "slots": [], "owned_count": 0}
    if player_id is not None:
        try:
            from .world_boss_companions import build_overview_companions

            companions = build_overview_companions(int(player_id), conn=conn, now=ts)
        except Exception:
            logger.exception("world_boss companions payload failed player=%s", player_id)
    return {
        "ok": True,
        "ready": True,
        "event": primary["event"] if primary else None,
        "events": cards,
        "contributions": primary["contributions"] if primary else [],
        "alliance_board": primary["alliance_board"] if primary else [],
        "player": primary["player"] if primary else None,
        "definitions": list_definitions(conn=conn),
        "companions": companions,
        "schedule": schedule,
        "server_now": ts,
        "flushed_attacks": flushed_attacks,
    }


def _auto_attack_columns_ready(conn) -> bool:
    from .db import column_exists

    return bool(
        column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "auto_attack_enabled")
        and column_exists(conn, WORLD_BOSS_CONTRIB_TABLE, "auto_attack_ships_json")
    )


def _clear_auto_attack(event_id: int, player_id: int, *, conn) -> None:
    if not _auto_attack_columns_ready(conn):
        return
    conn.execute(
        """
        UPDATE world_boss_contributions
        SET auto_attack_enabled = 0,
            auto_attack_ships_json = '{}',
            updated_at = ?
        WHERE event_id = ? AND player_id = ?;
        """,
        (_now(), int(event_id), int(player_id)),
    )


def maybe_fire_ready_auto_attack(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
    ships: Mapping[str, int] | None = None,
    planet_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fire one instant strike when auto-attack is enabled and cooldown is free.

    Shared by fleet_worker ticks and opportunistic WB payload flush.
    Clears the flag on terminal failures (defeated / invalid hangar / wave limit).
    """
    if not world_boss_schema_ready(conn) or not _auto_attack_columns_ready(conn):
        return {"ok": False, "fired": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    pid = int(player_id)
    eid = int(event_id)

    row = conn.execute(
        """
        SELECT c.auto_attack_enabled, c.auto_attack_ships_json, c.auto_attack_planet_id,
               c.waves, e.status, e.ends_at, e.current_hp
        FROM world_boss_contributions c
        JOIN world_boss_events e ON e.id = c.event_id
        WHERE c.event_id = ? AND c.player_id = ?
        LIMIT 1;
        """,
        (eid, pid),
    ).fetchone()
    if not row or not int(row["auto_attack_enabled"] or 0):
        return {"ok": True, "fired": False, "error": "auto_disabled"}

    status = str(row["status"] or "")
    ends_at = float(row["ends_at"] or 0)
    hp = int(row["current_hp"] or 0)
    waves = int(row["waves"] or 0)
    if (
        status != STATUS_ACTIVE
        or hp <= 0
        or (ends_at > 0 and ts >= ends_at)
        or waves >= MAX_WAVES_PER_PLAYER
    ):
        _clear_auto_attack(eid, pid, conn=conn)
        return {"ok": True, "fired": False, "stopped": True, "error": "auto_stopped"}

    ok_atk, atk_reason, _meta = can_player_attack_boss(
        pid,
        eid,
        conn=conn,
        now=ts,
        enforce_cooldown=True,
        check_inflight=False,
    )
    if not ok_atk:
        out: Dict[str, Any] = {"ok": True, "fired": False, "error": atk_reason or "blocked"}
        if atk_reason == "world_boss_cooldown" and _meta.get("cooldown_until") is not None:
            out["cooldown_until"] = float(_meta["cooldown_until"])
        return out

    selected = _normalize_attack_ships(ships if ships is not None else _json_loads(row["auto_attack_ships_json"], {}))
    origin_id = int(planet_id if planet_id is not None else (row["auto_attack_planet_id"] or 0))
    if origin_id <= 0:
        try:
            from .planet_evolution.repository import get_context_planet

            planet = get_context_planet(pid, conn=conn)
            origin_id = int(planet["id"]) if planet else 0
        except Exception:
            origin_id = 0
    if origin_id <= 0 or not selected:
        _clear_auto_attack(eid, pid, conn=conn)
        return {"ok": True, "fired": False, "stopped": True, "error": "no_ships_selected"}

    result = execute_instant_attack(
        pid,
        eid,
        selected,
        planet_id=origin_id,
        conn=conn,
        now=ts,
        auto_select=False,
    )
    if result.get("ok"):
        if result.get("defeated"):
            _clear_auto_attack(eid, pid, conn=conn)
        return {
            "ok": True,
            "fired": True,
            "stopped": bool(result.get("defeated")),
            "attack": result.get("attack"),
            "boss": result.get("boss"),
            "player": result.get("player"),
            "damage": result.get("damage"),
        }

    err = str(result.get("error") or "")
    if err in (
        "world_boss_defeated",
        "world_boss_inactive",
        "world_boss_expired",
        "world_boss_wave_limit",
        "insufficient_ships",
        "no_ships_selected",
        "no_combat_ships_available",
    ):
        _clear_auto_attack(eid, pid, conn=conn)
        return {"ok": True, "fired": False, "stopped": True, "error": err}
    return {"ok": True, "fired": False, "error": err or "world_boss_attack_failed"}


def flush_ready_auto_attacks_for_player(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Opportunistic auto-fire for one player across active events (WB page/API)."""
    if not world_boss_schema_ready(conn) or not _auto_attack_columns_ready(conn):
        return {"ok": True, "fired": 0, "stopped": 0}

    ts = float(now if now is not None else _now())
    pid = int(player_id)
    rows = conn.execute(
        """
        SELECT c.event_id
        FROM world_boss_contributions c
        JOIN world_boss_events e ON e.id = c.event_id
        WHERE c.player_id = ? AND c.auto_attack_enabled = 1 AND e.status = ?;
        """,
        (pid, STATUS_ACTIVE),
    ).fetchall()

    fired = 0
    stopped = 0
    attacks: List[Dict[str, Any]] = []
    for row in rows:
        res = maybe_fire_ready_auto_attack(pid, int(row["event_id"]), conn=conn, now=ts)
        if res.get("fired"):
            fired += 1
            if res.get("attack"):
                attacks.append(
                    {
                        "event_id": int(row["event_id"]),
                        "attack": res.get("attack"),
                        "boss": res.get("boss"),
                        "player": res.get("player"),
                    }
                )
        if res.get("stopped"):
            stopped += 1
    return {
        "ok": True,
        "fired": int(fired),
        "stopped": int(stopped),
        "candidates": len(rows),
        "attacks": attacks,
    }


def set_world_boss_auto_attack(
    player_id: int,
    event_id: int,
    *,
    enabled: bool,
    planet_id: int,
    ships: Mapping[str, int] | None = None,
    conn,
    now: Optional[float] = None,
    auto_select: bool = True,
) -> Dict[str, Any]:
    """GC-WB-AUTO-004 — enable/disable server-owned auto-attack for one event."""
    if not world_boss_schema_ready(conn) or not _auto_attack_columns_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    pid = int(player_id)
    eid = int(event_id)
    origin_id = int(planet_id)

    event = get_event_by_id(eid, conn=conn)
    if not event or event["status"] != STATUS_ACTIVE:
        return {"ok": False, "error": "world_boss_inactive"}

    if not enabled:
        _clear_auto_attack(eid, pid, conn=conn)
        return {
            "ok": True,
            "enabled": False,
            "event_id": eid,
            "ships": {},
        }

    from .fleet import get_planet_ships

    hangar = get_planet_ships(origin_id, conn=conn)
    selected = _normalize_attack_ships(ships)
    if auto_select or not selected:
        defender = defender_ships_for_event(event, conn=conn)
        selected, _meta = select_world_boss_auto_attack_ships(
            hangar,
            defender_ships=defender,
            max_hp=int(event.get("max_hp") or 0),
            event_id=eid,
            conn=conn,
        )
    ok_ships, ship_reason = _validate_ships_in_hangar(selected, hangar)
    if not ok_ships:
        return {"ok": False, "error": ship_reason or "no_combat_ships_available"}

    alliance_id = None
    try:
        from .alliance import get_player_alliance

        membership = get_player_alliance(pid, conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        alliance_id = None

    ships_json = _json_dumps(selected)
    conn.execute(
        """
        INSERT INTO world_boss_contributions (
            event_id, player_id, alliance_id, damage, waves,
            last_attack_at, created_at, updated_at,
            auto_attack_enabled, auto_attack_ships_json, auto_attack_planet_id
        ) VALUES (?, ?, ?, 0, 0, NULL, ?, ?, 1, ?, ?)
        ON CONFLICT(event_id, player_id) DO UPDATE SET
            alliance_id = COALESCE(excluded.alliance_id, alliance_id),
            auto_attack_enabled = 1,
            auto_attack_ships_json = excluded.auto_attack_ships_json,
            auto_attack_planet_id = excluded.auto_attack_planet_id,
            updated_at = excluded.updated_at;
        """,
        (
            eid,
            pid,
            int(alliance_id) if alliance_id is not None else None,
            ts,
            ts,
            ships_json,
            origin_id,
        ),
    )

    # Immediate strike on enable when cooldown is free; follow-ups stay tick-owned.
    out: Dict[str, Any] = {
        "ok": True,
        "enabled": True,
        "event_id": eid,
        "ships": dict(selected),
        "planet_id": origin_id,
        "fired": False,
        "attack": None,
        "boss": None,
        "player": None,
    }
    ok_atk, atk_reason, _atk_meta = can_player_attack_boss(
        pid,
        eid,
        conn=conn,
        now=ts,
        enforce_cooldown=True,
        check_inflight=False,
    )
    if ok_atk:
        strike = execute_instant_attack(
            pid,
            eid,
            selected,
            planet_id=origin_id,
            conn=conn,
            now=ts,
            auto_select=False,
        )
        if strike.get("ok"):
            out["fired"] = True
            out["attack"] = strike.get("attack")
            out["boss"] = strike.get("boss")
            out["player"] = strike.get("player")
        else:
            out["immediate_error"] = strike.get("error") or "world_boss_attack_failed"
    elif atk_reason == "world_boss_cooldown":
        out["on_cooldown"] = True
        if _atk_meta.get("cooldown_until") is not None:
            out["cooldown_until"] = float(_atk_meta["cooldown_until"])
    return out


def tick_world_boss_auto_attacks(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """
    Server-owned auto-attack fire: one instant strike per ready flagged player.

    Stops (clears flag) on defeat/expire, invalid hangar, wave limit, or inactive event.
    """
    if not world_boss_schema_ready(conn) or not _auto_attack_columns_ready(conn):
        return {"ok": True, "fired": 0, "stopped": 0}

    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT c.event_id, c.player_id
        FROM world_boss_contributions c
        JOIN world_boss_events e ON e.id = c.event_id
        WHERE c.auto_attack_enabled = 1;
        """
    ).fetchall()

    fired = 0
    stopped = 0
    for row in rows:
        res = maybe_fire_ready_auto_attack(
            int(row["player_id"]),
            int(row["event_id"]),
            conn=conn,
            now=ts,
        )
        if res.get("fired"):
            fired += 1
        if res.get("stopped"):
            stopped += 1

    return {"ok": True, "fired": int(fired), "stopped": int(stopped), "candidates": len(rows)}


def tick_world_boss_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Expire due events and optionally spawn the next boss (cron piggyback)."""
    if not world_boss_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    expired_ids: List[int] = []
    rows = conn.execute(
        """
        SELECT id FROM world_boss_events
        WHERE status = ? AND ends_at <= ?;
        """,
        (STATUS_ACTIVE, ts),
    ).fetchall()
    for row in rows:
        eid = int(row["id"])
        _expire_event(eid, conn=conn, now=ts, status=STATUS_EXPIRED)
        expired_ids.append(eid)

    active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 5)
    spawned = None
    if len(active) < int(MAX_CONCURRENT_EVENTS):
        schedule = build_schedule_info(conn=conn, now=ts)
        if schedule.get("spawn_ready"):
            exclude = {str(e.get("boss_key") or "") for e in active}
            defs = list_definitions(conn=conn, active_only=True)
            boss_key = _pick_weighted_boss_key(defs, exclude_keys=exclude)
            if boss_key:
                result = spawn_world_boss(boss_key, conn=conn, now=ts, announce=True)
                if result.get("ok"):
                    spawned = result.get("event")

    auto_tick = tick_world_boss_auto_attacks(conn=conn, now=ts)

    return {
        "ok": True,
        "expired_ids": expired_ids,
        "spawned_event_id": int(spawned["id"]) if spawned else None,
        "active_count": len(list_active_events(conn=conn, now=ts)),
        "active_event_id": int(spawned["id"]) if spawned else (int(active[0]["id"]) if active else None),
        "auto_attack": auto_tick,
    }


def maybe_tick_world_boss_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Throttled schedule tick for fleet_worker maintenance (spawn/expire + auto-attack)."""
    try:
        return tick_world_boss_schedule(conn=conn, now=now)
    except Exception:
        logger.exception("world_boss schedule tick failed")
        return {"ok": False, "error": "tick_failed"}
