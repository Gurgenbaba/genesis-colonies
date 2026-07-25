"""
EPIC-20 — World Boss Events (server-wide PvE).

Owner of shared-HP events, contribution ledger, schedule, and reward claims.
Combat math stays in ``game/combat.py``; fleet send/arrival orchestration in ``game/fleet.py``.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
STATUS_SCHEDULED = "scheduled"

WAVE_COOLDOWN_SEC = 300
MAX_WAVES_PER_PLAYER = 40
DEFAULT_EVENT_DURATION_SEC = 48 * 3600
INTER_EVENT_COOLDOWN_SEC = 24 * 3600
SCHEDULE_RUNTIME_KEY = "world_boss_last_ended_at"
ROTATION_RUNTIME_KEY = "world_boss_rotation_index"

# Raid HP mapping (combat still uses simulate_battle; HP is not raw prestige).
# Even fight full wipe ≈ WAVE_HP_FRACTION of max_hp; mega fleets scale via log2 overkill.
WAVE_HP_FRACTION = 0.03
# Cap allows a single mega-wave to finish the bar; typical huge overkill lands ~40–60%.
MAX_WAVE_HP_FRACTION = 1.0

# Reward tiers → inventory container keys (meta-only, known catalog).
REWARD_PARTICIPATE = "container_event_special"
REWARD_TOP10 = "container_void_artifact"
REWARD_TOP1 = "container_mythic"
REWARD_ALLIANCE_TOP = "container_ancient_relic"


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
        "name_key": str(defn.get("name_key") or f"wb_boss_{boss_key}"),
        "description_key": str(defn.get("description_key") or ""),
        "loot_pool_key": str(defn.get("loot_pool_key") or REWARD_PARTICIPATE),
    }


def get_active_event(*, conn, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
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
        ORDER BY e.id DESC
        LIMIT 1;
        """,
        (STATUS_ACTIVE, ts, ts),
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
    event = get_active_event(conn=conn, now=now)
    if not event:
        return None
    if (
        int(event["galaxy"]) == int(galaxy)
        and int(event["system"]) == int(system)
        and int(event["position"]) == int(position)
    ):
        return event
    return None


def get_bosses_for_system(
    galaxy: int,
    system: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map position → compact boss payload for galaxy slot attach."""
    event = get_active_event(conn=conn, now=now)
    if not event:
        return {}
    if int(event["galaxy"]) != int(galaxy) or int(event["system"]) != int(system):
        return {}
    return {
        int(event["position"]): {
            "event_id": int(event["id"]),
            "boss_key": event["boss_key"],
            "name_key": event["name_key"],
            "status": event["status"],
            "current_hp": int(event["current_hp"]),
            "max_hp": int(event["max_hp"]),
            "hp_ratio": event["hp_ratio"],
            "ends_at": event["ends_at"],
            "coords": event["coords"],
            "fleet_deep_link": (
                f"/fleet?mission=attack"
                f"&target_galaxy={int(event['galaxy'])}"
                f"&target_system={int(event['system'])}"
                f"&target_position={int(event['position'])}"
            ),
            "wave_cooldown_sec": int(WAVE_COOLDOWN_SEC),
            "max_waves": int(MAX_WAVES_PER_PLAYER),
        }
    }


def _pick_spawn_coords(conn, *, prefer_dense: bool = False) -> Tuple[int, int, int]:
    """Pick an empty classic slot (1–15). Prefer denser systems for planet_eater."""
    from .galaxy import POSITION_MAX, POSITION_MIN

    cur = conn.cursor()
    if prefer_dense:
        row = cur.execute(
            """
            SELECT galaxy, system, COUNT(*) AS n
            FROM planets
            WHERE galaxy IS NOT NULL AND system IS NOT NULL
              AND position BETWEEN ? AND ?
            GROUP BY galaxy, system
            ORDER BY n DESC
            LIMIT 1;
            """,
            (POSITION_MIN, POSITION_MAX),
        ).fetchone()
        if row:
            g, s = int(row["galaxy"]), int(row["system"])
            occupied = {
                int(r["position"])
                for r in cur.execute(
                    """
                    SELECT position FROM planets
                    WHERE galaxy = ? AND system = ?
                      AND position BETWEEN ? AND ?;
                    """,
                    (g, s, POSITION_MIN, POSITION_MAX),
                ).fetchall()
            }
            for pos in range(POSITION_MIN, POSITION_MAX + 1):
                if pos not in occupied:
                    return g, s, pos

    # Fallback: first empty-ish homeworld neighborhood or 1:1:empty
    home = cur.execute(
        """
        SELECT galaxy, system, position FROM planets
        WHERE is_homeworld = 1
        ORDER BY id ASC
        LIMIT 1;
        """
    ).fetchone()
    if home:
        g, s = int(home["galaxy"]), int(home["system"])
        occupied = {
            int(r["position"])
            for r in cur.execute(
                """
                SELECT position FROM planets
                WHERE galaxy = ? AND system = ?
                  AND position BETWEEN ? AND ?;
                """,
                (g, s, POSITION_MIN, POSITION_MAX),
            ).fetchall()
        }
        for pos in range(POSITION_MIN, POSITION_MAX + 1):
            if pos not in occupied:
                return g, s, pos
        # All full — use next system empty slot 8
        return g, min(s + 1, 499), 8
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
    ``log2(1 + attacker_score / wave_score)`` so mega fleets scale while even fights
    stay near ``WAVE_HP_FRACTION`` of ``max_hp`` (capped at ``MAX_WAVE_HP_FRACTION``).
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
    overkill_mult = max(1.0, math.log2(1.0 + force_ratio))
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
) -> Dict[str, Any]:
    """Create an active world boss event. Fails if another active event exists (unless force)."""
    if not world_boss_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}

    ts = float(now if now is not None else _now())
    definition = get_definition(boss_key, conn=conn)
    if not definition or not definition.get("active"):
        return {"ok": False, "error": "unknown_boss"}

    existing = get_active_event(conn=conn, now=ts)
    if existing and not force:
        return {"ok": False, "error": "event_already_active", "event": existing}
    if existing and force:
        _expire_event(int(existing["id"]), conn=conn, now=ts, status=STATUS_EXPIRED)

    prefer_dense = str(boss_key) == "planet_eater"
    if galaxy is None or system is None or position is None:
        g, s, p = _pick_spawn_coords(conn, prefer_dense=prefer_dense)
    else:
        g, s, p = int(galaxy), int(system), int(position)

    duration = int(definition["duration_seconds"] or DEFAULT_EVENT_DURATION_SEC)
    stacks = {
        str(k): max(0, int(v or 0))
        for k, v in dict(definition.get("fleet_stacks") or {}).items()
        if int(v or 0) > 0
    }
    max_hp = int(definition["max_hp"])
    cur = conn.cursor()
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

    copy = format_world_boss_news(event, kind="spawn", locale=DEFAULT_LOCALE)
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
            defeated_at = CASE WHEN ? = 'defeated' THEN ? ELSE defeated_at END
        WHERE id = ? AND status = ?;
        """,
        (status, float(now), status, float(now), int(event_id), STATUS_ACTIVE),
    )
    set_runtime_value(SCHEDULE_RUNTIME_KEY, str(float(now)), conn=conn)


def can_player_attack_boss(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
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
        "cooldown_remaining": 0,
    }
    if waves >= MAX_WAVES_PER_PLAYER:
        return False, "world_boss_wave_limit", base_meta
    if last_at > 0 and (ts - last_at) < WAVE_COOLDOWN_SEC:
        remaining = max(0, int(WAVE_COOLDOWN_SEC - (ts - last_at)))
        base_meta["cooldown_remaining"] = remaining
        base_meta["next_attack_at"] = float(last_at + WAVE_COOLDOWN_SEC)
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
        int(player_id), int(event["id"]), conn=conn, now=ts
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

    alliance_id = None
    try:
        from .alliance import get_player_alliance

        membership = get_player_alliance(int(player_id), conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        logger.exception("world_boss alliance lookup failed player=%s", player_id)

    _upsert_contribution(
        event_id=int(event["id"]),
        player_id=int(player_id),
        alliance_id=alliance_id,
        damage=damage,
        now=ts,
        conn=conn,
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
    boss_label = str(event.get("boss_key") or "World Boss")
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
            target_planet_name=boss_label,
            attacker_planet_id=int(movement.get("origin_planet_id") or 0) or None,
            defender_planet_id=None,
            conn=conn,
            attacker_locale=get_player_locale(int(player_id), conn=conn),
            defender_locale=None,
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
) -> None:
    dmg = max(0, int(damage))
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
            last_attack_at = excluded.last_attack_at,
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
    rows = conn.execute(
        """
        SELECT c.player_id, c.alliance_id, c.damage, c.waves, c.last_attack_at,
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
    rows = conn.execute(
        """
        SELECT c.alliance_id, SUM(c.damage) AS damage, COUNT(*) AS members,
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
    return {
        "id": int(row["id"]),
        "tiers": list(_json_loads(row["tiers_json"], []) or []),
        "rewards": list(_json_loads(row["rewards_json"], []) or []),
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
    if event["status"] not in (STATUS_DEFEATED, STATUS_EXPIRED):
        return {"ok": False, "error": "event_not_claimable"}

    existing = _player_claim_row(int(event_id), int(player_id), conn=conn)
    if existing:
        return {"ok": False, "error": "already_claimed", "claim": existing}

    tiers, meta = compute_claim_tiers(int(event_id), int(player_id), conn=conn)
    if not tiers:
        return {"ok": False, "error": meta.get("error") or "no_contribution"}

    from .inventory import grant_inventory_item

    reward_map = {
        "participate": REWARD_PARTICIPATE,
        "top10": REWARD_TOP10,
        "top1": REWARD_TOP1,
        "alliance_top": REWARD_ALLIANCE_TOP,
    }
    # Prefer unique containers; skip duplicate keys across tiers.
    ordered_tiers = [t for t in ("top1", "top10", "alliance_top", "participate") if t in tiers]
    granted: List[Dict[str, Any]] = []
    seen_keys = set()
    for tier in ordered_tiers:
        item_key = reward_map.get(tier)
        if not item_key or item_key in seen_keys:
            continue
        ok = grant_inventory_item(
            int(player_id),
            item_key,
            1,
            conn=conn,
            metadata={"source": "world_boss", "event_id": int(event_id), "tier": tier},
        )
        if ok:
            seen_keys.add(item_key)
            granted.append({"tier": tier, "item_key": item_key, "amount": 1})

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


def build_schedule_info(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Server-side spawn ETA for the World Boss idle panel."""
    ts = float(now if now is not None else _now())
    active = get_active_event(conn=conn, now=ts) if world_boss_schema_ready(conn) else None
    last_ended: Optional[float] = None
    if world_boss_schema_ready(conn):
        raw = get_runtime_value(SCHEDULE_RUNTIME_KEY, conn=conn)
        if raw not in (None, ""):
            try:
                last_ended = float(raw)
            except (TypeError, ValueError):
                last_ended = None
    if last_ended is not None and last_ended > 0:
        next_eligible_at = float(last_ended) + float(INTER_EVENT_COOLDOWN_SEC)
    else:
        next_eligible_at = ts
    spawn_ready = bool(active is None and ts >= next_eligible_at)
    return {
        "inter_event_cooldown_sec": int(INTER_EVENT_COOLDOWN_SEC),
        "last_ended_at": last_ended,
        "next_eligible_at": float(next_eligible_at),
        "spawn_ready": spawn_ready,
        "has_active": bool(active is not None),
    }


def build_world_boss_payload(
    player_id: Optional[int] = None,
    *,
    conn,
    event_id: Optional[int] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    if not world_boss_schema_ready(conn):
        return {
            "ok": True,
            "ready": False,
            "event": None,
            "contributions": [],
            "alliance_board": [],
            "player": None,
            "definitions": [],
            "schedule": build_schedule_info(conn=conn, now=ts),
            "server_now": ts,
        }

    schedule = build_schedule_info(conn=conn, now=ts)
    event = None
    if event_id is not None:
        event = get_event_by_id(int(event_id), conn=conn)
    if event is None:
        event = get_active_event(conn=conn, now=ts)
    if event is None:
        # Fall back to most recent ended event for board/claim.
        row = conn.execute(
            """
            SELECT id FROM world_boss_events
            WHERE status IN (?, ?)
            ORDER BY updated_at DESC
            LIMIT 1;
            """,
            (STATUS_DEFEATED, STATUS_EXPIRED),
        ).fetchone()
        if row:
            event = get_event_by_id(int(row["id"]), conn=conn)

    if not event:
        return {
            "ok": True,
            "ready": True,
            "event": None,
            "contributions": [],
            "alliance_board": [],
            "player": None,
            "definitions": list_definitions(conn=conn),
            "schedule": schedule,
            "server_now": ts,
        }

    contribs = list_contributions(int(event["id"]), conn=conn, limit=100)
    alliance_board = list_alliance_contributions(int(event["id"]), conn=conn, limit=50)
    player_info = None
    if player_id is not None:
        mine = next((c for c in contribs if int(c["player_id"]) == int(player_id)), None)
        claim = _player_claim_row(int(event["id"]), int(player_id), conn=conn)
        can_claim = (
            event["status"] in (STATUS_DEFEATED, STATUS_EXPIRED)
            and mine is not None
            and int(mine["damage"]) > 0
            and claim is None
        )
        ok_atk, atk_reason, atk_meta = (False, "inactive", {})
        if event["status"] == STATUS_ACTIVE:
            ok_atk, atk_reason, atk_meta = can_player_attack_boss(
                int(player_id), int(event["id"]), conn=conn, now=ts
            )
        player_info = {
            "contribution": mine,
            "claim": claim,
            "can_claim": can_claim,
            "can_attack": ok_atk,
            "attack_block_reason": atk_reason if not ok_atk else "",
            "attack_meta": atk_meta,
        }

    return {
        "ok": True,
        "ready": True,
        "event": event,
        "contributions": contribs,
        "alliance_board": alliance_board,
        "player": player_info,
        "definitions": list_definitions(conn=conn),
        "schedule": schedule,
        "server_now": ts,
    }


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

    active = get_active_event(conn=conn, now=ts)
    spawned = None
    if active is None:
        last_ended_raw = get_runtime_value(SCHEDULE_RUNTIME_KEY, conn=conn)
        last_ended = float(last_ended_raw) if last_ended_raw not in (None, "") else 0.0
        # First-ever spawn: allow immediately when no history.
        cooldown_ok = last_ended <= 0 or (ts - last_ended) >= INTER_EVENT_COOLDOWN_SEC
        if cooldown_ok:
            defs = list_definitions(conn=conn, active_only=True)
            if defs:
                rot_raw = get_runtime_value(ROTATION_RUNTIME_KEY, conn=conn)
                try:
                    rot = int(rot_raw or 0)
                except (TypeError, ValueError):
                    rot = 0
                boss = defs[rot % len(defs)]
                result = spawn_world_boss(boss["boss_key"], conn=conn, now=ts, announce=True)
                if result.get("ok"):
                    spawned = result.get("event")
                    set_runtime_value(ROTATION_RUNTIME_KEY, str(rot + 1), conn=conn)

    return {
        "ok": True,
        "expired_ids": expired_ids,
        "spawned_event_id": int(spawned["id"]) if spawned else None,
        "active_event_id": int(active["id"]) if active else (int(spawned["id"]) if spawned else None),
    }


def maybe_tick_world_boss_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Throttled schedule tick for fleet_worker maintenance."""
    try:
        return tick_world_boss_schedule(conn=conn, now=now)
    except Exception:
        logger.exception("world_boss schedule tick failed")
        return {"ok": False, "error": "tick_failed"}
