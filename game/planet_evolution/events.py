"""Planet event engine — spawn, resolve, tick."""

from __future__ import annotations

import hashlib
import random
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from ..exact_math import decimal_text
from ..models import get_game_settings
from .constants import EVENT_COOLDOWN_HOURS
from .definitions import get_event, get_events
from .history import append_history
from .mechanics import compile_planet_mechanics, get_planet_mechanics
from .planet_level import add_planet_xp
from .repository import _json_dumps, _json_loads, get_active_event, get_planet_culture, get_planet_row


EVENT_TIMEOUT_HOURS = 72

# Adapter: map pe_event_definitions.pool_tags + event_key to event_pool:* flag names.
# Canonical tags use pool:{name}; legacy events match by key prefix (e.g. smuggler_* → smuggler).
_EVENT_POOL_TAG_PREFIX = "pool:"


def unlocked_event_pool_names(flags: Dict[str, Any] | None) -> set[str]:
    """Return pool names from compiled planet_mechanics.flags (event_pool:*)."""
    pools: set[str] = set()
    for key, val in (flags or {}).items():
        if not str(key).startswith("event_pool:"):
            continue
        if val:
            pools.add(str(key).split(":", 1)[1])
    return pools


def event_belongs_to_pool(event_key: str, pool_name: str, pool_tags: List[Any]) -> bool:
    pool = str(pool_name or "").strip()
    if not pool:
        return False
    tag = f"{_EVENT_POOL_TAG_PREFIX}{pool}"
    if tag in [str(t) for t in (pool_tags or [])]:
        return True
    key = str(event_key or "")
    if key == pool:
        return True
    if key.startswith(f"{pool}_"):
        return True
    return False


def event_allowed_by_pool_tags(
    event_key: str,
    pool_tags: List[Any],
    *,
    specialization_key: str,
    unlocked_pools: set[str],
) -> bool:
    """Whether an event passes spec/pool gating (unchanged when no pool_tags)."""
    tags = list(pool_tags or [])
    if not tags:
        return True

    spec = str(specialization_key or "")
    spec_match = bool(
        spec and any(str(t).endswith(spec) or t == f"spec:{spec}" for t in tags)
    )
    if spec_match:
        return True

    if unlocked_pools and any(
        event_belongs_to_pool(event_key, pool, tags) for pool in unlocked_pools
    ):
        return True

    # Legacy: planets without specialization were not filtered by pool_tags.
    if not spec:
        return True

    return False


# Default outcome payloads keyed by outcome id (extend via admin later).
_OUTCOME_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "shutdown": {"culture_delta": {"stability": 5, "industrial_pressure": -5}, "history_tag": "reactor_shutdown"},
    "overload": {"culture_delta": {"stability": -15, "industrial_pressure": 10}, "add_failure": "reactor_degraded", "history_tag": "reactor_overloaded"},
    "invest": {"culture_delta": {"stability": 2, "prosperity": -3}, "grant_special_resource": {"refined_ferronit": 2000}, "history_tag": "reactor_investment"},
    "exploit": {"grant_special_resource": {"mantle_alloy": 1500}, "culture_delta": {"industrial_pressure": 8}, "history_tag": "rare_metal_found"},
    "survey": {"culture_delta": {"science_focus": 5}, "history_tag": "rare_metal_found"},
    "negotiate": {"culture_delta": {"stability": 8, "loyalty": 5}, "history_tag": "survived_rebellion"},
    "crackdown": {"culture_delta": {"stability": -5, "loyalty": -10, "crime": -8}, "history_tag": "survived_rebellion"},
    "contain": {"culture_delta": {"stability": 3, "science_focus": 2}, "history_tag": "quantum_breach_survived"},
    "push": {"culture_delta": {"science_focus": 10, "stability": -12}, "add_failure": "research_containment_breach", "history_tag": "quantum_breach_survived"},
    "publish": {"culture_delta": {"prosperity": 5, "science_focus": 8}, "history_tag": "breakthrough_achieved"},
    "classify": {"culture_delta": {"loyalty": 5, "science_focus": 3}, "history_tag": "breakthrough_achieved"},
    "shutdown_ai": {"culture_delta": {"loyalty": -5, "stability": 5}, "history_tag": "ai_incident_resolved"},
    "integrate": {"culture_delta": {"science_focus": 12, "loyalty": -8}, "add_failure": "ai_runaway", "history_tag": "ai_incident_resolved"},
    "bribe": {"culture_delta": {"crime": 5, "prosperity": -4}, "history_tag": "survived_raid"},
    "hide": {"culture_delta": {"crime": -3, "stability": -4}, "history_tag": "survived_raid"},
    "fight": {"culture_delta": {"militarization": 8, "stability": -6}, "add_failure": "smuggling_crackdown", "history_tag": "survived_raid"},
    "expand": {"culture_delta": {"crime": 8, "prosperity": 10}, "grant_special_resource": {"contraband": 500}, "history_tag": "black_market_expanded"},
    "consolidate": {"culture_delta": {"crime": -5, "prosperity": 3}, "history_tag": "black_market_expanded"},
    "fortify": {"culture_delta": {"militarization": 10, "prosperity": -2}, "history_tag": "siege_survived"},
    "evacuate_exports": {"culture_delta": {"stability": 5, "prosperity": -5}, "history_tag": "siege_survived"},
    "reroute": {"culture_delta": {"prosperity": -2}, "history_tag": "trade_disruption_handled"},
    "escort": {"culture_delta": {"militarization": 5, "prosperity": -3}, "history_tag": "trade_disruption_handled"},
    "worst_neutral": {"culture_delta": {"stability": -8, "loyalty": -5}, "history_tag": "event_timeout"},
}


def _stable_roll(planet_id: int, event_key: str, day_bucket: int) -> float:
    raw = f"{planet_id}|{event_key}|{day_bucket}|events"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def preview_event_choice(edef: Dict[str, Any], choice_key: str) -> Optional[Dict[str, Any]]:
    """Return the exact outcome payload resolve_choice() would apply."""
    outcome_key = PlanetEventEngine._map_choice_to_outcome(edef, choice_key)
    if not outcome_key:
        return None
    return {
        "outcome_key": outcome_key,
        "outcome": dict(_OUTCOME_DEFAULTS.get(outcome_key, {})),
    }


class PlanetEventEngine:
    """Server-authoritative planet events."""

    @staticmethod
    def tick_planet(conn: sqlite3.Connection, planet_id: int, now: float) -> Dict[str, Any]:
        expired = PlanetEventEngine._expire_timeouts(conn, planet_id, now)
        if get_active_event(planet_id, conn=conn):
            return {"spawned": None, "expired": expired}

        planet = get_planet_row(planet_id, conn=conn) or {}
        if float(planet.get("event_cooldown_until") or 0) > float(now):
            return {"spawned": None, "expired": expired, "cooldown": True}

        spawned = PlanetEventEngine.spawn_event(conn, planet_id, now=now)
        return {"spawned": spawned, "expired": expired}

    @staticmethod
    def spawn_event(
        conn: sqlite3.Connection,
        planet_id: int,
        *,
        event_key: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        ts = float(now if now is not None else time.time())
        if get_active_event(planet_id, conn=conn):
            return None

        planet = get_planet_row(planet_id, conn=conn) or {}
        picked = event_key or PlanetEventEngine._pick_event_key(planet_id, planet, conn, ts)
        if not picked:
            return None

        edef = get_event(picked) or {}
        resolve_by = ts + EVENT_TIMEOUT_HOURS * 3600
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_events (
                planet_id, event_key, state, severity, started_at, resolve_by, payload_json
            ) VALUES (?, ?, 'active', ?, ?, ?, ?);
            """,
            (
                int(planet_id),
                str(picked),
                str(edef.get("severity") or "normal"),
                ts,
                resolve_by,
                _json_dumps({"spawned_at": ts}),
            ),
        )
        event_id = int(cur.lastrowid)
        append_history(
            planet_id,
            "event_spawn",
            str(edef.get("label_key") or picked),
            payload={"event_key": picked, "event_id": event_id},
            history_tag=edef.get("history_tag"),
            conn=conn,
        )
        return {"event_id": event_id, "event_key": picked, "resolve_by": resolve_by}

    @staticmethod
    def resolve_choice(
        conn: sqlite3.Connection,
        planet_id: int,
        event_id: int,
        choice_key: str,
        *,
        now: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ts = float(now if now is not None else time.time())
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM planet_events
            WHERE id = ? AND planet_id = ? AND state IN ('pending','active')
            LIMIT 1;
            """,
            (int(event_id), int(planet_id)),
        )
        row = cur.fetchone()
        if not row:
            return False, "event_not_found", None

        event = dict(row)
        edef = get_event(str(event["event_key"])) or {}
        preview = preview_event_choice(edef, choice_key)
        if not preview:
            return False, "invalid_choice", None

        outcome_key = str(preview["outcome_key"])
        outcome = dict(preview["outcome"])
        PlanetEventEngine._apply_outcome(conn, planet_id, outcome, str(event["event_key"]), edef)
        cur.execute(
            """
            UPDATE planet_events SET
                state = 'resolved',
                player_choice_key = ?,
                outcome_key = ?
            WHERE id = ?;
            """,
            (str(choice_key), str(outcome_key), int(event_id)),
        )
        cur.execute(
            "UPDATE planets SET event_cooldown_until = ? WHERE id = ?;",
            (ts + EVENT_COOLDOWN_HOURS * 3600, int(planet_id)),
        )
        add_planet_xp(planet_id, 10, conn, reason=f"event:{event['event_key']}")
        return True, "ok", {"outcome_key": outcome_key, "outcome": outcome}

    @staticmethod
    def _expire_timeouts(conn: sqlite3.Connection, planet_id: int, now: float) -> int:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM planet_events
            WHERE planet_id = ? AND state = 'active' AND resolve_by IS NOT NULL AND resolve_by <= ?;
            """,
            (int(planet_id), float(now)),
        )
        rows = cur.fetchall()
        count = 0
        for row in rows:
            event = dict(row)
            edef = get_event(str(event["event_key"])) or {}
            outcome = dict(_OUTCOME_DEFAULTS.get("worst_neutral", {}))
            failure = edef.get("failure_link")
            if failure:
                outcome["add_failure"] = str(failure)
            PlanetEventEngine._apply_outcome(conn, planet_id, outcome, str(event["event_key"]), edef)
            cur.execute(
                """
                UPDATE planet_events SET state = 'expired', outcome_key = 'worst_neutral'
                WHERE id = ?;
                """,
                (int(event["id"]),),
            )
            count += 1
        return count

    @staticmethod
    def _pick_event_key(
        planet_id: int,
        planet: Dict[str, Any],
        conn: sqlite3.Connection,
        now: float,
    ) -> Optional[str]:
        try:
            settings = get_game_settings(conn=conn)
            base_chance = float(settings.get("planet_event_base_chance", 0.001))
        except Exception:
            base_chance = 0.001

        day_bucket = int(now // 86400)
        spec = str(planet.get("specialization_key") or "")
        culture = get_planet_culture(planet_id, conn=conn)
        mechanics = get_planet_mechanics(planet_id, conn=conn) or {}
        unlocked_pools = unlocked_event_pool_names(mechanics.get("flags"))

        candidates: List[Tuple[str, float]] = []
        for key, edef in get_events().items():
            if not PlanetEventEngine._trigger_matches(planet_id, planet, culture, edef, conn):
                continue
            trigger = edef.get("trigger") or {}
            chance = float(trigger.get("base_chance_per_day") or base_chance)
            roll = _stable_roll(planet_id, key, day_bucket)
            pool_tags = edef.get("pool_tags") or []
            if not event_allowed_by_pool_tags(
                key,
                pool_tags,
                specialization_key=spec,
                unlocked_pools=unlocked_pools,
            ):
                continue
            if roll < chance:
                candidates.append((key, chance))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    @staticmethod
    def _trigger_matches(
        planet_id: int,
        planet: Dict[str, Any],
        culture: Dict[str, Any],
        edef: Dict[str, Any],
        conn: sqlite3.Connection,
    ) -> bool:
        trigger = edef.get("trigger") or {}
        from .failures import active_failure_keys

        blocked = trigger.get("blocked_if_failure") or []
        active = active_failure_keys(planet_id, conn)
        if blocked and any(str(b) in active for b in blocked):
            return False

        req_culture = trigger.get("requires_culture") or {}
        for key, val in req_culture.items():
            if key.endswith("_lt"):
                stat = key[:-3]
                if float(culture.get(stat, 0) or 0) >= float(val):
                    return False
            elif key.endswith("_gt"):
                stat = key[:-3]
                if float(culture.get(stat, 0) or 0) <= float(val):
                    return False
            elif key.endswith("_range") and isinstance(val, (list, tuple)) and len(val) == 2:
                stat = key[:-6]
                cur_val = float(culture.get(stat, 0) or 0)
                if cur_val < float(val[0]) or cur_val > float(val[1]):
                    return False

        specs = trigger.get("requires_spec_any") or []
        if specs and str(planet.get("specialization_key") or "") not in [str(s) for s in specs]:
            return False

        return True

    @staticmethod
    def _map_choice_to_outcome(edef: Dict[str, Any], choice_key: str) -> Optional[str]:
        for choice in edef.get("choices") or []:
            if isinstance(choice, dict) and str(choice.get("key")) == str(choice_key):
                return str(choice.get("outcome") or choice_key)
        return None

    @staticmethod
    def _apply_outcome(
        conn: sqlite3.Connection,
        planet_id: int,
        outcome: Dict[str, Any],
        event_key: str,
        edef: Dict[str, Any],
    ) -> None:
        from .economy import ensure_special_resource_row
        from .failures import apply_failure

        culture_delta = outcome.get("culture_delta") or {}
        if culture_delta:
            cur = conn.cursor()
            culture = get_planet_culture(planet_id, conn=conn)
            updates = []
            params: List[Any] = []
            for stat, delta in culture_delta.items():
                if stat in culture:
                    updates.append(f"{stat} = ?")
                    params.append(max(0.0, min(100.0, float(culture.get(stat, 0) or 0) + float(delta))))
            if updates:
                params.append(int(planet_id))
                cur.execute(
                    f"UPDATE planet_culture SET {', '.join(updates)} WHERE planet_id = ?;",
                    params,
                )

        grants = outcome.get("grant_special_resource") or {}
        for res_key, amount in grants.items():
            ensure_special_resource_row(planet_id, str(res_key), conn)
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE planet_special_resources
                SET amount = MIN(cap, amount + CAST(? AS NUMERIC))
                WHERE planet_id = ? AND resource_key = ?;
                """,
                (decimal_text(amount), int(planet_id), str(res_key)),
            )

        failure_key = outcome.get("add_failure")
        if failure_key:
            apply_failure(planet_id, str(failure_key), conn)

        history_tag = outcome.get("history_tag") or edef.get("history_tag")
        if history_tag:
            append_history(
                planet_id,
                "event_outcome",
                str(edef.get("label_key") or event_key),
                history_tag=str(history_tag),
                payload={"event_key": event_key, "outcome": outcome},
                conn=conn,
            )

        compile_planet_mechanics(planet_id, conn)

        follow = outcome.get("follow_up_event")
        if isinstance(follow, dict) and follow.get("key"):
            delay_h = float(follow.get("delay_hours") or 0)
            chance = float(follow.get("chance") or 1.0)
            if random.random() < chance:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE planets SET event_cooldown_until = ? WHERE id = ?;",
                    (time.time() + delay_h * 3600, int(planet_id)),
                )
