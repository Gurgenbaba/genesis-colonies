"""Pirate bases — spawn, galaxy presence, expire (EPIC-21 / GC-P03).

Attack/destroy combat lands in a follow-up ticket (GC-P04) via ``simulate_battle``.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..db import table_exists
from ..runtime_state import get_runtime_value, set_runtime_value
from .heat import HEAT_THRESHOLDS, get_galaxy_heat, schema_ready as heat_schema_ready
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

logger = logging.getLogger(__name__)

BASES_TABLE = "pirate_bases"
FACTIONS_TABLE = "pirate_faction_defs"

STATUS_ACTIVE = "active"
STATUS_ESCALATING = "escalating"
STATUS_DESTROYED = "destroyed"
STATUS_EXPIRED = "expired"
LIVE_STATUSES = (STATUS_ACTIVE, STATUS_ESCALATING)

BASE_TTL_SECONDS = 48 * 3600
MAX_BASES_PER_GALAXY = 3
MAX_BASES_GLOBAL = 24
SPAWN_RUNTIME_KEY = "pirate_bases_last_spawn_at"
SPAWN_COOLDOWN_SEC = 45 * 60
HEAT_SPAWN_MIN = HEAT_THRESHOLDS["patrol"]  # 150

# Combat (GC-P04)
WAVE_HP_FRACTION = 0.12
MAX_WAVE_HP_FRACTION = 0.35
OVERKILL_LOG_SCALE = 0.15
ATTACK_COOLDOWN_SEC = 120
MAX_WAVES_PER_PLAYER = 40


def _now() -> float:
    return time.time()


def bases_schema_ready(conn) -> bool:
    return table_exists(conn, BASES_TABLE) and table_exists(conn, FACTIONS_TABLE)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def list_faction_defs(conn) -> List[Dict[str, Any]]:
    if not bases_schema_ready(conn):
        return []
    cur = conn.execute(
        """
        SELECT faction_key, name_key, description_key, commander_key,
               aggression_weight, loot_tier, defense_tier,
               fleet_stacks_json, personality_json, sort_order, active
        FROM pirate_faction_defs
        WHERE active = 1
        ORDER BY sort_order ASC;
        """
    )
    out = []
    for row in cur.fetchall():
        out.append(
            {
                "faction_key": row["faction_key"],
                "name_key": row["name_key"],
                "description_key": row["description_key"],
                "commander_key": row["commander_key"],
                "aggression_weight": int(row["aggression_weight"] or 0),
                "loot_tier": row["loot_tier"],
                "defense_tier": row["defense_tier"],
                "fleet_stacks": dict(_json_loads(row["fleet_stacks_json"], {}) or {}),
                "personality": dict(_json_loads(row["personality_json"], {}) or {}),
                "sort_order": int(row["sort_order"] or 0),
            }
        )
    return out


def _row_to_base(row: Mapping[str, Any]) -> Dict[str, Any]:
    strength = int(row["strength"] or 1)
    max_hp = int(row["max_hp"] or 100)
    current_hp = int(row["current_hp"] or 0)
    hp_ratio = (float(current_hp) / float(max_hp)) if max_hp > 0 else 0.0
    g = int(row["galaxy"])
    s = int(row["system"])
    p = int(row["position"])
    return {
        "id": int(row["id"]),
        "base_id": int(row["id"]),
        "faction_key": row["faction_key"],
        "status": row["status"],
        "galaxy": g,
        "system": s,
        "position": p,
        "strength": strength,
        "activity": int(row["activity"] or 0),
        "loot_tier": row["loot_tier"],
        "fleet_stacks": dict(_json_loads(row["fleet_stacks_json"], {}) or {}),
        "max_hp": max_hp,
        "current_hp": current_hp,
        "hp_ratio": hp_ratio,
        "spawned_at": float(row["spawned_at"]),
        "escalates_at": float(row["escalates_at"]) if row["escalates_at"] else None,
        "destroyed_at": float(row["destroyed_at"]) if row["destroyed_at"] else None,
        "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
        "updated_at": float(row["updated_at"]),
        "name_key": f"pirate_faction_{row['faction_key']}",
        "description_key": f"pirate_faction_{row['faction_key']}_desc",
        "commander_key": {
            "crimson_corsairs": "pirate_commander_crimson",
            "iron_collective": "pirate_commander_iron",
            "void_cult": "pirate_commander_void",
            "nomad_swarm": "pirate_commander_nomad",
        }.get(str(row["faction_key"]), "pirate_commander_crimson"),
        "strength_stars": "★" * strength + "☆" * max(0, 5 - strength),
        "coords": f"[{g}:{s}:{p}]",
        "fleet_deep_link": (
            f"/fleet?mission=attack&target_galaxy={g}&target_system={s}&target_position={p}"
        ),
        "wave_cooldown_sec": ATTACK_COOLDOWN_SEC,
    }


def list_live_bases(
    conn,
    *,
    galaxy: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if not bases_schema_ready(conn):
        return []
    limit = max(1, min(int(limit), 500))
    if galaxy is not None:
        cur = conn.execute(
            f"""
            SELECT * FROM pirate_bases
            WHERE status IN (?, ?) AND galaxy = ?
            ORDER BY spawned_at DESC
            LIMIT ?;
            """,
            (STATUS_ACTIVE, STATUS_ESCALATING, int(galaxy), limit),
        )
    else:
        cur = conn.execute(
            f"""
            SELECT * FROM pirate_bases
            WHERE status IN (?, ?)
            ORDER BY spawned_at DESC
            LIMIT ?;
            """,
            (STATUS_ACTIVE, STATUS_ESCALATING, limit),
        )
    return [_row_to_base(r) for r in cur.fetchall()]


def get_bases_for_system(galaxy: int, system: int, *, conn) -> Dict[int, Dict[str, Any]]:
    if not bases_schema_ready(conn):
        return {}
    cur = conn.execute(
        """
        SELECT * FROM pirate_bases
        WHERE status IN (?, ?) AND galaxy = ? AND system = ?;
        """,
        (STATUS_ACTIVE, STATUS_ESCALATING, int(galaxy), int(system)),
    )
    out: Dict[int, Dict[str, Any]] = {}
    for row in cur.fetchall():
        base = _row_to_base(row)
        out[int(base["position"])] = base
    return out


def get_active_base_at(
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not bases_schema_ready(conn):
        return None
    cur = conn.execute(
        """
        SELECT * FROM pirate_bases
        WHERE status IN (?, ?) AND galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (
            STATUS_ACTIVE,
            STATUS_ESCALATING,
            int(galaxy),
            int(system),
            int(position),
        ),
    )
    row = cur.fetchone()
    if not row:
        return None
    base = _row_to_base(row)
    ts = float(now if now is not None else _now())
    expires = base.get("expires_at")
    if expires is not None and float(expires) <= ts:
        return None
    return base


def _occupied_positions(conn, galaxy: int, system: int) -> Set[int]:
    occupied: Set[int] = set()
    cur = conn.execute(
        """
        SELECT position FROM planets
        WHERE galaxy = ? AND system = ? AND position IS NOT NULL;
        """,
        (int(galaxy), int(system)),
    )
    for row in cur.fetchall():
        occupied.add(int(row["position"]))
    cur = conn.execute(
        """
        SELECT position FROM pirate_bases
        WHERE status IN (?, ?) AND galaxy = ? AND system = ?;
        """,
        (STATUS_ACTIVE, STATUS_ESCALATING, int(galaxy), int(system)),
    )
    for row in cur.fetchall():
        occupied.add(int(row["position"]))
    try:
        from ..world_boss import get_bosses_for_system

        for pos in get_bosses_for_system(int(galaxy), int(system), conn=conn):
            occupied.add(int(pos))
    except Exception:
        pass
    try:
        from ..asteroids import get_asteroids_for_system

        for pos in get_asteroids_for_system(int(galaxy), int(system), conn=conn):
            occupied.add(int(pos))
    except Exception:
        pass
    return occupied


def _pick_free_slot(
    conn,
    galaxy: int,
    *,
    rng: random.Random,
) -> Optional[Tuple[int, int, int]]:
    """Pick free classic slot in ``galaxy`` (positions 1–15)."""
    systems = list(range(1, 500))
    rng.shuffle(systems)
    for system in systems[:80]:
        occupied = _occupied_positions(conn, galaxy, system)
        free = [p for p in range(1, 16) if p not in occupied]
        if free:
            return (int(galaxy), int(system), int(rng.choice(free)))
    return None


def _strength_from_heat(heat: int) -> int:
    if heat >= HEAT_THRESHOLDS["war"]:
        return 5
    if heat >= HEAT_THRESHOLDS["crisis"]:
        return 4
    if heat >= HEAT_THRESHOLDS["elite"]:
        return 3
    if heat >= HEAT_THRESHOLDS["raids"]:
        return 2
    return 1


def _hp_for_strength(strength: int) -> int:
    return int(50_000 * max(1, strength) ** 1.4)


def _scale_stacks(stacks: Mapping[str, Any], strength: int) -> Dict[str, int]:
    mult = 0.5 + 0.5 * max(1, strength)
    out: Dict[str, int] = {}
    for k, v in dict(stacks or {}).items():
        n = int(max(0, round(int(v or 0) * mult)))
        if n > 0:
            out[str(k)] = n
    return out


def spawn_pirate_base(
    conn,
    *,
    galaxy: int,
    faction_key: Optional[str] = None,
    now: Optional[float] = None,
    announce: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    if not bases_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}
    if not force and not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled"}

    ts = float(now if now is not None else _now())
    heat_snap = get_galaxy_heat(conn, int(galaxy)) if heat_schema_ready(conn) else {"heat": 0}
    heat = int(heat_snap.get("heat") or 0)
    if not force and heat < HEAT_SPAWN_MIN:
        return {"ok": False, "error": "heat_too_low", "heat": heat}

    live_g = list_live_bases(conn, galaxy=int(galaxy), limit=50)
    if not force and len(live_g) >= MAX_BASES_PER_GALAXY:
        return {"ok": False, "error": "galaxy_cap"}

    live_all = list_live_bases(conn, limit=MAX_BASES_GLOBAL + 5)
    if not force and len(live_all) >= MAX_BASES_GLOBAL:
        return {"ok": False, "error": "global_cap"}

    factions = list_faction_defs(conn)
    if not factions:
        return {"ok": False, "error": "no_factions"}

    if faction_key:
        faction = next((f for f in factions if f["faction_key"] == faction_key), None)
        if not faction:
            return {"ok": False, "error": "unknown_faction"}
    else:
        weights = [max(1, int(f["aggression_weight"])) for f in factions]
        faction = random.choices(factions, weights=weights, k=1)[0]

    coords = _pick_free_slot(conn, int(galaxy), rng=random.Random(int(ts) ^ int(galaxy)))
    if not coords:
        return {"ok": False, "error": "no_free_slot"}
    g, s, p = coords

    strength = _strength_from_heat(heat)
    stacks = _scale_stacks(faction["fleet_stacks"], strength)
    max_hp = _hp_for_strength(strength)
    expires_at = ts + BASE_TTL_SECONDS
    escalates_at = ts + 6 * 3600

    cur = conn.execute(
        """
        INSERT INTO pirate_bases (
            faction_key, status, galaxy, system, position,
            strength, activity, loot_tier, fleet_stacks_json,
            max_hp, current_hp, spawned_at, escalates_at, expires_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            faction["faction_key"],
            STATUS_ACTIVE,
            g,
            s,
            p,
            strength,
            10,
            faction["loot_tier"],
            _json_dumps(stacks),
            max_hp,
            max_hp,
            ts,
            escalates_at,
            expires_at,
            ts,
        ),
    )
    base_id = int(cur.lastrowid)

    log_pirate_action(
        conn,
        kind="base_spawn",
        faction_key=faction["faction_key"],
        base_id=base_id,
        galaxy_id=g,
        message=f"base spawned [{g}:{s}:{p}] strength={strength}",
        payload={"system": s, "position": p, "strength": strength, "heat": heat},
    )

    if announce:
        try:
            from ..i18n import DEFAULT_LOCALE, tr
            from ..universe_news import create_news

            title = tr(
                "pirate_news_base_discovered",
                "Pirate base discovered",
                locale=DEFAULT_LOCALE,
            )
            body = tr(
                "pirate_news_base_discovered_body",
                "A %(faction)s hideout appeared at [%(g)s:%(s)s:%(p)s] (strength %(stars)s).",
                locale=DEFAULT_LOCALE,
                faction=tr(faction["name_key"], faction["faction_key"], locale=DEFAULT_LOCALE),
                g=g,
                s=s,
                p=p,
                stars=strength,
            )
            create_news(
                title=title,
                body=body,
                category="EVENT",
                badge="EVENT",
                source_ref=f"pirate_base:spawn:{base_id}",
                set_banner=False,
                conn=conn,
            )
        except Exception:
            logger.exception("pirate base news failed base_id=%s", base_id)

    base = get_active_base_at(g, s, p, conn=conn, now=ts)
    return {"ok": True, "base": base, "base_id": base_id}


def expire_due_bases(conn, *, now: Optional[float] = None) -> List[int]:
    if not bases_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        """
        SELECT id FROM pirate_bases
        WHERE status IN (?, ?) AND expires_at IS NOT NULL AND expires_at <= ?;
        """,
        (STATUS_ACTIVE, STATUS_ESCALATING, ts),
    )
    ids = [int(r["id"]) for r in cur.fetchall()]
    if not ids:
        return []
    conn.execute(
        f"""
        UPDATE pirate_bases
        SET status = ?, updated_at = ?
        WHERE id IN ({",".join("?" * len(ids))}) AND status IN (?, ?);
        """,
        (STATUS_EXPIRED, ts, *ids, STATUS_ACTIVE, STATUS_ESCALATING),
    )
    for bid in ids:
        log_pirate_action(
            conn,
            kind="base_expired",
            base_id=bid,
            message=f"base expired id={bid}",
        )
    return ids


def escalate_due_bases(conn, *, now: Optional[float] = None) -> List[int]:
    if not bases_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        """
        SELECT * FROM pirate_bases
        WHERE status = ? AND escalates_at IS NOT NULL AND escalates_at <= ?;
        """,
        (STATUS_ACTIVE, ts),
    )
    rows = cur.fetchall()
    escalated: List[int] = []
    for row in rows:
        strength = min(5, int(row["strength"] or 1) + 1)
        activity = min(100, int(row["activity"] or 0) + 25)
        stacks = _scale_stacks(_json_loads(row["fleet_stacks_json"], {}), strength)
        max_hp = _hp_for_strength(strength)
        # Keep current HP ratio when escalating.
        old_max = max(1, int(row["max_hp"] or 1))
        ratio = float(row["current_hp"] or 0) / float(old_max)
        new_hp = max(1, int(max_hp * ratio))
        conn.execute(
            """
            UPDATE pirate_bases
            SET status = ?, strength = ?, activity = ?, fleet_stacks_json = ?,
                max_hp = ?, current_hp = ?, escalates_at = ?, updated_at = ?
            WHERE id = ? AND status = ?;
            """,
            (
                STATUS_ESCALATING,
                strength,
                activity,
                _json_dumps(stacks),
                max_hp,
                new_hp,
                ts + 6 * 3600,
                ts,
                int(row["id"]),
                STATUS_ACTIVE,
            ),
        )
        escalated.append(int(row["id"]))
        log_pirate_action(
            conn,
            kind="base_escalate",
            base_id=int(row["id"]),
            faction_key=row["faction_key"],
            galaxy_id=int(row["galaxy"]),
            message=f"base escalated strength={strength}",
            payload={"strength": strength, "activity": activity},
            severity="warn",
        )
    return escalated


def destroy_base(conn, base_id: int, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Mark base destroyed (GC-P04 will call after combat wipe)."""
    if not bases_schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        """
        UPDATE pirate_bases
        SET status = ?, current_hp = 0, destroyed_at = ?, updated_at = ?
        WHERE id = ? AND status IN (?, ?);
        """,
        (STATUS_DESTROYED, ts, ts, int(base_id), STATUS_ACTIVE, STATUS_ESCALATING),
    )
    if cur.rowcount != 1:
        return {"ok": False, "error": "not_found_or_dead"}
    faction_key = None
    try:
        row = conn.execute(
            "SELECT faction_key, galaxy FROM pirate_bases WHERE id = ? LIMIT 1;",
            (int(base_id),),
        ).fetchone()
        if row:
            faction_key = row["faction_key"]
            log_pirate_action(
                conn,
                kind="base_destroyed",
                base_id=int(base_id),
                faction_key=str(faction_key),
                galaxy_id=int(row["galaxy"]) if row["galaxy"] is not None else None,
                message=f"base destroyed id={base_id}",
                severity="warn",
            )
    except Exception:
        log_pirate_action(
            conn,
            kind="base_destroyed",
            base_id=int(base_id),
            message=f"base destroyed id={base_id}",
            severity="warn",
        )
    if faction_key:
        try:
            from .ambush import panic_recall_faction_fleets

            panic_recall_faction_fleets(
                conn, faction_key=str(faction_key), reason="base_destroyed"
            )
        except Exception:
            logger.exception("fleet-save on destroy failed base=%s", base_id)
    return {"ok": True, "base_id": int(base_id)}


def maybe_tick_pirate_bases(conn, *, now: Optional[float] = None) -> Dict[str, Any]:
    """fleet_worker piggyback: expire, escalate, spawn when heat + AI enabled."""
    ts = float(now if now is not None else _now())
    expired = expire_due_bases(conn, now=ts)
    escalated = escalate_due_bases(conn, now=ts)
    spawned: List[int] = []

    if not is_pirates_ai_enabled(conn=conn):
        log_pirate_action(
            conn,
            kind="ai_disabled",
            message="tick skipped — AI off",
            severity="info",
        )
        return {
            "expired_ids": expired,
            "escalated_ids": escalated,
            "spawned": spawned,
            "ai_enabled": False,
            "raids": [],
            "spies": [],
            "recycles": [],
        }

    try:
        from .accounts import bootstrap_faction_bots

        result_bots = bootstrap_faction_bots(conn=conn)
    except Exception:
        logger.exception("pirate bot bootstrap failed")
        result_bots = []

    raw = get_runtime_value(SPAWN_RUNTIME_KEY, conn=conn)
    last = float(raw) if raw not in (None, "") else 0.0
    on_cooldown = ts - last < SPAWN_COOLDOWN_SEC

    if not on_cooldown:
        # Spawn in galaxies with heat >= patrol and under cap.
        if heat_schema_ready(conn):
            cur = conn.execute(
                """
                SELECT galaxy_id, heat FROM galaxy_heat
                WHERE heat >= ?
                ORDER BY heat DESC
                LIMIT 12;
                """,
                (HEAT_SPAWN_MIN,),
            )
            for row in cur.fetchall():
                res = spawn_pirate_base(conn, galaxy=int(row["galaxy_id"]), now=ts, announce=True)
                if res.get("ok") and res.get("base_id"):
                    spawned.append(int(res["base_id"]))
                if len(spawned) >= 2:
                    break
        set_runtime_value(SPAWN_RUNTIME_KEY, str(ts), conn=conn)

    result: Dict[str, Any] = {
        "expired_ids": expired,
        "escalated_ids": escalated,
        "spawned": spawned,
        "ai_enabled": True,
        "cooldown": on_cooldown,
        "bots": len(result_bots),
    }
    try:
        from .crisis import maybe_sync_pirate_war

        result["pirate_war"] = maybe_sync_pirate_war(conn, now=ts)
    except Exception:
        logger.exception("pirate_war sync failed")
        result["pirate_war"] = {}
    try:
        from .infiltration import expire_due_infiltrations

        result["infiltrations_expired"] = expire_due_infiltrations(conn, now=ts)
    except Exception:
        logger.exception("infiltration expire failed")
        result["infiltrations_expired"] = []
    try:
        from .smugglers import expire_due_smugglers, maybe_spawn_smugglers

        result["smugglers_expired"] = expire_due_smugglers(conn, now=ts)
        result["smugglers_spawned"] = maybe_spawn_smugglers(conn, now=ts)
    except Exception:
        logger.exception("smuggler tick failed")
        result["smugglers_expired"] = []
        result["smugglers_spawned"] = []
    try:
        from .brain import (
            run_colonize_brain_tick,
            run_patrol_brain_tick,
            run_raid_brain_tick,
            run_recycle_brain_tick,
        )

        patrol = run_patrol_brain_tick(conn, now=ts)
        result["spies"] = patrol.get("spies") or []
        brain = run_raid_brain_tick(conn, now=ts)
        result["raids"] = brain.get("raids") or []
        recycle = run_recycle_brain_tick(conn, now=ts)
        result["recycles"] = recycle.get("recycles") or []
        colonize = run_colonize_brain_tick(conn, now=ts)
        result["colonizes"] = colonize.get("colonizes") or []
    except Exception:
        logger.exception("pirate brain tick failed")
        result["spies"] = []
        result["raids"] = []
        result["recycles"] = []
        result["colonizes"] = []
    return result


# --- GC-P04 combat -----------------------------------------------------------


def get_base_by_id(base_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not bases_schema_ready(conn):
        return None
    cur = conn.execute("SELECT * FROM pirate_bases WHERE id = ? LIMIT 1;", (int(base_id),))
    row = cur.fetchone()
    return _row_to_base(row) if row else None


def compute_base_hp_damage(
    *,
    defender_ships_before: Mapping[str, int],
    defender_losses: Mapping[str, int],
    max_hp: int,
    attacker_ships_before: Mapping[str, int],
) -> int:
    import math

    from ..scoring import compute_destroyed_raw_from_losses

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
        return 1 if lost_score > 0 else 0
    fraction = min(1.0, float(lost_score) / float(full_score))
    atk = {
        str(k): max(0, int(v or 0))
        for k, v in dict(attacker_ships_before or {}).items()
        if int(v or 0) > 0
    }
    attacker_score = int(compute_destroyed_raw_from_losses(atk)) if atk else 0
    force_ratio = float(attacker_score) / float(max(full_score, 1))
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


def _upsert_contribution(
    *,
    base_id: int,
    player_id: int,
    alliance_id: Optional[int],
    damage: int,
    now: float,
    conn,
) -> None:
    conn.execute(
        """
        INSERT INTO pirate_base_contributions (
            base_id, player_id, alliance_id, damage, waves, last_attack_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(base_id, player_id) DO UPDATE SET
            damage = pirate_base_contributions.damage + excluded.damage,
            waves = pirate_base_contributions.waves + 1,
            alliance_id = COALESCE(excluded.alliance_id, pirate_base_contributions.alliance_id),
            last_attack_at = excluded.last_attack_at,
            updated_at = excluded.updated_at;
        """,
        (
            int(base_id),
            int(player_id),
            alliance_id,
            max(0, int(damage)),
            float(now),
            float(now),
            float(now),
        ),
    )


def can_player_attack_base(
    player_id: int,
    base_id: int,
    *,
    conn,
    now: Optional[float] = None,
    enforce_cooldown: bool = True,
    check_inflight: bool = True,
    exclude_movement_id: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    ts = float(now if now is not None else _now())
    base = get_base_by_id(int(base_id), conn=conn)
    meta: Dict[str, Any] = {"base": base, "wave_cooldown_sec": ATTACK_COOLDOWN_SEC}
    if not base or base["status"] not in LIVE_STATUSES:
        return False, "pirate_base_inactive", meta
    cur = conn.execute(
        """
        SELECT damage, waves, last_attack_at
        FROM pirate_base_contributions
        WHERE base_id = ? AND player_id = ?
        LIMIT 1;
        """,
        (int(base_id), int(player_id)),
    )
    row = cur.fetchone()
    waves = int(row["waves"] or 0) if row else 0
    last_atk = float(row["last_attack_at"]) if row and row["last_attack_at"] else None
    meta["waves"] = waves
    if waves >= MAX_WAVES_PER_PLAYER:
        return False, "pirate_base_wave_limit", meta
    if enforce_cooldown and last_atk is not None:
        next_at = last_atk + ATTACK_COOLDOWN_SEC
        meta["next_attack_at"] = next_at
        if ts < next_at:
            return False, "pirate_base_cooldown", meta
    if check_inflight:
        cur = conn.execute(
            """
            SELECT id FROM fleet_movements
            WHERE player_id = ?
              AND status = 'outbound'
              AND mission_type = 'attack'
              AND target_galaxy = ? AND target_system = ? AND target_position = ?
              AND (? IS NULL OR id != ?)
            LIMIT 1;
            """,
            (
                int(player_id),
                int(base["galaxy"]),
                int(base["system"]),
                int(base["position"]),
                exclude_movement_id,
                exclude_movement_id,
            ),
        )
        if cur.fetchone():
            return False, "pirate_base_inflight", meta
    return True, "", meta


def note_attack_dispatched(
    player_id: int,
    base_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """Start wave cooldown on send (does not count as a combat wave)."""
    ts = float(now if now is not None else _now())
    alliance_id = None
    try:
        from ..alliance import get_player_alliance

        membership = get_player_alliance(int(player_id), conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        pass
    cur = conn.execute(
        """
        SELECT id FROM pirate_base_contributions
        WHERE base_id = ? AND player_id = ?
        LIMIT 1;
        """,
        (int(base_id), int(player_id)),
    )
    if cur.fetchone():
        conn.execute(
            """
            UPDATE pirate_base_contributions
            SET last_attack_at = ?, updated_at = ?,
                alliance_id = COALESCE(?, alliance_id)
            WHERE base_id = ? AND player_id = ?;
            """,
            (ts, ts, alliance_id, int(base_id), int(player_id)),
        )
    else:
        conn.execute(
            """
            INSERT INTO pirate_base_contributions (
                base_id, player_id, alliance_id, damage, waves, last_attack_at, created_at, updated_at
            ) VALUES (?, ?, ?, 0, 0, ?, ?, ?);
            """,
            (int(base_id), int(player_id), alliance_id, ts, ts, ts),
        )


def _grant_destroy_rewards(conn, base: Mapping[str, Any], *, now: float) -> None:
    """Auto-grant resource loot to contributors on destroy (homeworld)."""
    from ..models import get_planets_by_player
    from ..resources import apply_resource_delta_unbounded

    base_id = int(base["id"])
    strength = max(1, int(base.get("strength") or 1))
    pool_metal = 250_000 * strength
    pool_crystal = 150_000 * strength
    cur = conn.execute(
        """
        SELECT player_id, damage FROM pirate_base_contributions
        WHERE base_id = ? AND damage > 0
        ORDER BY damage DESC;
        """,
        (base_id,),
    )
    rows = cur.fetchall()
    total_dmg = sum(int(r["damage"] or 0) for r in rows) or 1
    for row in rows:
        pid = int(row["player_id"])
        share = float(row["damage"] or 0) / float(total_dmg)
        metal = int(pool_metal * share)
        crystal = int(pool_crystal * share)
        if metal <= 0 and crystal <= 0:
            continue
        # Idempotent claim marker
        claim_cur = conn.execute(
            """
            INSERT OR IGNORE INTO pirate_base_claims (base_id, player_id, tier_key, claimed_at)
            VALUES (?, ?, 'destroy_share', ?);
            """,
            (base_id, pid, now),
        )
        if claim_cur.rowcount != 1:
            continue
        planets = get_planets_by_player(pid, conn=conn) or []
        if not planets:
            continue
        home = dict(planets[0])
        apply_resource_delta_unbounded(home, delta_metal=metal, delta_crystal=crystal)
        conn.execute(
            """
            UPDATE planets SET metal = ?, crystal = ?
            WHERE id = ?;
            """,
            (int(home["metal"]), int(home["crystal"]), int(home["id"])),
        )
        try:
            from .bounty import add_player_bounty, bounty_for_destroy

            credits = bounty_for_destroy(strength, share=share)
            add_player_bounty(
                conn,
                pid,
                str(base.get("faction_key") or ""),
                credits=credits,
                kills=1,
                now=now,
            )
        except Exception:
            logger.exception("pirate destroy bounty failed base=%s player=%s", base_id, pid)
        log_pirate_action(
            conn,
            kind="base_reward",
            base_id=base_id,
            target_player_id=pid,
            galaxy_id=int(base["galaxy"]),
            message=f"destroy share M{metal} C{crystal}",
            payload={"metal": metal, "crystal": crystal, "share": share},
        )


def resolve_attack_arrival(
    *,
    movement: Mapping[str, Any],
    ships: Mapping[str, int],
    player_id: int,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve pirate-base attack on fleet arrival via ``simulate_battle``."""
    from ..combat import (
        attacker_stacks_from_fleet,
        battle_rng_for_movement,
        publish_attack_combat_report,
        remaining_stock,
        simulate_battle,
        spawn_combat_debris_field,
    )
    from ..combat_models import COMBAT_UNIT_SHIP, stacks_from_counts
    from ..i18n import get_player_locale, tr

    ts = float(now if now is not None else _now())
    movement_id = int(movement["id"])
    tg = int(movement["target_galaxy"])
    ts_sys = int(movement["target_system"])
    tp = int(movement["target_position"])
    base = get_active_base_at(tg, ts_sys, tp, conn=conn, now=ts)
    if not base:
        return {
            "ok": False,
            "error": "pirate_base_inactive",
            "return_ships": dict(ships),
            "combat_result": None,
            "base": None,
            "damage": 0,
            "destroyed": False,
        }

    ok_atk, reason, meta = can_player_attack_base(
        int(player_id),
        int(base["id"]),
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
            "base": base,
            "damage": 0,
            "destroyed": False,
            **meta,
        }

    defender_ships = {
        str(k): max(0, int(v or 0))
        for k, v in dict(base.get("fleet_stacks") or {}).items()
        if int(v or 0) > 0
    }
    if not defender_ships:
        # Empty garrison → finish the base.
        destroy_base(conn, int(base["id"]), now=ts)
        refreshed = get_base_by_id(int(base["id"]), conn=conn)
        if refreshed:
            _grant_destroy_rewards(conn, refreshed, now=ts)
        try:
            from .hooks import safe_record_heat

            safe_record_heat(conn, tg, "pirate_base_destroyed")
        except Exception:
            pass
        return {
            "ok": True,
            "return_ships": dict(ships),
            "combat_result": None,
            "base": refreshed or base,
            "damage": int(base.get("current_hp") or 0),
            "destroyed": True,
        }

    atk_stacks = attacker_stacks_from_fleet(ships)
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
    damage = compute_base_hp_damage(
        defender_ships_before=defender_ships,
        defender_losses=combat_result.defender_losses or {},
        max_hp=int(base["max_hp"]),
        attacker_ships_before=ships,
    )
    remaining_def = remaining_stock(defender_ships, combat_result.defender_losses or {})
    new_hp = max(0, int(base["current_hp"]) - damage)
    wiped = not any(int(v or 0) > 0 for v in remaining_def.values())
    destroyed = new_hp <= 0 or wiped
    if destroyed:
        new_hp = 0

    alliance_id = None
    try:
        from ..alliance import get_player_alliance

        membership = get_player_alliance(int(player_id), conn=conn)
        if membership:
            alliance_id = int(membership["alliance_id"])
    except Exception:
        pass

    if destroyed:
        conn.execute(
            """
            UPDATE pirate_bases
            SET status = ?, current_hp = 0, fleet_stacks_json = ?,
                destroyed_at = ?, updated_at = ?
            WHERE id = ? AND status IN (?, ?);
            """,
            (
                STATUS_DESTROYED,
                _json_dumps({}),
                ts,
                ts,
                int(base["id"]),
                STATUS_ACTIVE,
                STATUS_ESCALATING,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE pirate_bases
            SET current_hp = ?, fleet_stacks_json = ?, updated_at = ?
            WHERE id = ? AND status IN (?, ?);
            """,
            (
                new_hp,
                _json_dumps(remaining_def),
                ts,
                int(base["id"]),
                STATUS_ACTIVE,
                STATUS_ESCALATING,
            ),
        )

    _upsert_contribution(
        base_id=int(base["id"]),
        player_id=int(player_id),
        alliance_id=alliance_id,
        damage=max(1, damage) if damage > 0 else damage,
        now=ts,
        conn=conn,
    )
    if damage > 0:
        try:
            from .bounty import add_player_bounty, bounty_for_damage

            b_cred = bounty_for_damage(damage)
            if b_cred > 0:
                add_player_bounty(
                    conn,
                    int(player_id),
                    str(base.get("faction_key") or ""),
                    credits=b_cred,
                    now=ts,
                )
        except Exception:
            logger.exception(
                "pirate damage bounty failed base=%s player=%s",
                base.get("id"),
                player_id,
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
        logger.exception("pirate base debris failed movement=%s", movement_id)

    locale = get_player_locale(int(player_id), conn=conn)
    defender_name = tr(
        base.get("name_key") or "pirate_faction_crimson_corsairs",
        str(base.get("faction_key") or "Pirate Base"),
        locale=locale,
    )
    try:
        cur = conn.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
        prow = cur.fetchone()
        attacker_name = str((prow["name"] if prow else "") or f"Player {player_id}")
    except Exception:
        attacker_name = f"Player {player_id}"

    coords = f"[{tg}:{ts_sys}:{tp}]"
    try:
        publish_attack_combat_report(
            attacker_id=int(player_id),
            defender_id=0,
            coords=coords,
            attacker_name=attacker_name,
            defender_name=defender_name,
            attacking_ships=ships,
            defending_ships=defender_ships,
            defending_defense={},
            combat_result=combat_result,
            return_ships=return_ships,
            loot={},
            fleet_id=movement_id,
            origin_coords=None,
            attacker_locale=locale,
            conn=conn,
            combat_kind="pirate_base",
            extra_metadata={"pirate_base_id": int(base["id"])},
        )
    except Exception:
        logger.exception("pirate base combat report failed movement=%s", movement_id)

    log_pirate_action(
        conn,
        kind="base_attack",
        faction_key=str(base.get("faction_key") or ""),
        base_id=int(base["id"]),
        galaxy_id=tg,
        target_player_id=int(player_id),
        message=f"wave dmg={damage} destroyed={destroyed}",
        payload={"damage": damage, "destroyed": destroyed, "new_hp": new_hp},
        severity="warn" if destroyed else "info",
    )

    if destroyed:
        refreshed = get_base_by_id(int(base["id"]), conn=conn) or base
        _grant_destroy_rewards(conn, refreshed, now=ts)
        try:
            from .hooks import safe_record_heat

            safe_record_heat(conn, tg, "pirate_base_destroyed")
        except Exception:
            pass
        try:
            from ..universe_news import create_news
            from ..i18n import DEFAULT_LOCALE

            create_news(
                title=tr(
                    "pirate_news_base_destroyed",
                    "Pirate base destroyed",
                    locale=DEFAULT_LOCALE,
                ),
                body=tr(
                    "pirate_news_base_destroyed_body",
                    "%(faction)s hideout at %(coords)s has been wiped out.",
                    locale=DEFAULT_LOCALE,
                    faction=defender_name,
                    coords=coords,
                ),
                category="EVENT",
                badge="EVENT",
                source_ref=f"pirate_base:destroy:{int(base['id'])}",
                set_banner=False,
                conn=conn,
            )
        except Exception:
            logger.exception("pirate destroy news failed base=%s", base.get("id"))

    return {
        "ok": True,
        "return_ships": return_ships,
        "combat_result": combat_result,
        "base": get_base_by_id(int(base["id"]), conn=conn) or base,
        "damage": damage,
        "destroyed": destroyed,
    }
