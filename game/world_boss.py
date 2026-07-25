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
# Gap between successive spawns when under the concurrent cap (GC-W13).
INTER_EVENT_COOLDOWN_SEC = 4 * 3600
MAX_CONCURRENT_EVENTS = 3
EXPO_DISCOVERY_CHANCE = 0.055
SCHEDULE_RUNTIME_KEY = "world_boss_last_ended_at"
SPAWN_RUNTIME_KEY = "world_boss_last_spawn_at"
ROTATION_RUNTIME_KEY = "world_boss_rotation_index"

# Raid HP mapping (combat still uses simulate_battle; HP is not raw prestige).
# Even fight full wipe ≈ WAVE_HP_FRACTION of max_hp.
WAVE_HP_FRACTION = 0.02
# Soft overkill: 1 + scale * log2(1 + force_ratio). Mega fleets approach the cap.
OVERKILL_LOG_SCALE = 0.15
# Cap ≈ 8% → solo mega fleet needs ~13 waves (target band 10–20 hits).
MAX_WAVE_HP_FRACTION = 0.08

# Reward tiers → inventory container keys (meta-only, known catalog).
# Amounts are tuned “good but not OP”: participate solid, top tiers rare containers.
REWARD_PARTICIPATE = "container_event_special"
REWARD_TOP10 = "container_void_artifact"
REWARD_TOP1 = "container_mythic"
REWARD_ALLIANCE_TOP = "container_ancient_relic"
# (tier, item_key, amount) — stacked grants, same key sums.
REWARD_TIER_GRANTS: Tuple[Tuple[str, str, int], ...] = (
    ("top1", REWARD_TOP1, 1),
    ("top10", REWARD_TOP10, 1),
    ("top10", REWARD_PARTICIPATE, 1),
    ("alliance_top", REWARD_ALLIANCE_TOP, 1),
    ("discoverer", REWARD_PARTICIPATE, 1),
    ("participate", REWARD_PARTICIPATE, 2),
)


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
            "fleet_deep_link": (
                f"/fleet?mission=attack"
                f"&target_galaxy={int(event['galaxy'])}"
                f"&target_system={int(event['system'])}"
                f"&target_position={int(event['position'])}"
            ),
            "wave_cooldown_sec": int(WAVE_COOLDOWN_SEC),
            "max_waves": int(MAX_WAVES_PER_PLAYER),
        }
    return out


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
    if galaxy is None or system is None or position is None:
        g, s, p = _pick_spawn_coords(conn, prefer_dense=prefer_dense)
    else:
        g, s, p = int(galaxy), int(system), int(position)

    # Avoid stacking on an already-occupied boss slot.
    if get_active_event_at(g, s, p, conn=conn, now=ts) and not force:
        g, s, p = _pick_spawn_coords(conn, prefer_dense=prefer_dense)

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
    """Apply arrival damage/waves. Preserves ``last_attack_at`` from send-time CD."""
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
    if event["status"] not in (STATUS_DEFEATED, STATUS_EXPIRED):
        return {"ok": False, "error": "event_not_claimable"}

    existing = _player_claim_row(int(event_id), int(player_id), conn=conn)
    if existing:
        return {"ok": False, "error": "already_claimed", "claim": existing}

    tiers, meta = compute_claim_tiers(int(event_id), int(player_id), conn=conn)
    if not tiers:
        return {"ok": False, "error": meta.get("error") or "no_contribution"}

    from .inventory import grant_inventory_item

    # Aggregate amounts per item_key across earned tiers.
    amounts: Dict[str, int] = {}
    tier_for_key: Dict[str, str] = {}
    for tier, item_key, amount in REWARD_TIER_GRANTS:
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
                int(player_id), int(event["id"]), conn=conn, now=now
            )
        player_info = {
            "contribution": mine,
            "claim": claim,
            "can_claim": can_claim,
            "can_attack": ok_atk,
            "attack_block_reason": atk_reason if not ok_atk else "",
            "attack_meta": atk_meta,
            "is_discoverer": bool(disc_id and int(disc_id) == int(player_id)),
        }
    return {
        "event": event,
        "contributions": contribs,
        "alliance_board": alliance_board,
        "player": player_info,
        "discoverer_name": discoverer_name,
    }


def build_world_boss_payload(
    player_id: Optional[int] = None,
    *,
    conn,
    event_id: Optional[int] = None,
    now: Optional[float] = None,
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
        "schedule": build_schedule_info(conn=conn, now=ts),
        "server_now": ts,
    }
    if not world_boss_schema_ready(conn):
        return empty

    schedule = build_schedule_info(conn=conn, now=ts)
    active = list_active_events(conn=conn, now=ts, limit=MAX_CONCURRENT_EVENTS + 5)
    cards: List[Dict[str, Any]] = []
    for ev in active:
        cards.append(_event_card_for_player(ev, player_id, conn=conn, now=ts))

    # Recently ended claimable for this player (or latest ended for browse).
    ended_rows = conn.execute(
        """
        SELECT id FROM world_boss_events
        WHERE status IN (?, ?)
        ORDER BY updated_at DESC
        LIMIT 8;
        """,
        (STATUS_DEFEATED, STATUS_EXPIRED),
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
    return {
        "ok": True,
        "ready": True,
        "event": primary["event"] if primary else None,
        "events": cards,
        "contributions": primary["contributions"] if primary else [],
        "alliance_board": primary["alliance_board"] if primary else [],
        "player": primary["player"] if primary else None,
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

    return {
        "ok": True,
        "expired_ids": expired_ids,
        "spawned_event_id": int(spawned["id"]) if spawned else None,
        "active_count": len(list_active_events(conn=conn, now=ts)),
        "active_event_id": int(spawned["id"]) if spawned else (int(active[0]["id"]) if active else None),
    }


def maybe_tick_world_boss_schedule(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Throttled schedule tick for fleet_worker maintenance."""
    try:
        return tick_world_boss_schedule(conn=conn, now=now)
    except Exception:
        logger.exception("world_boss schedule tick failed")
        return {"ok": False, "error": "tick_failed"}
