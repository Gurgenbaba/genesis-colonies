"""
GC-541 — Inventory item use & craft (server-authoritative).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import lock_planet_for_update, table_exists
from .inventory_catalog import (
    BOOSTER_TIME_SECONDS,
    CRAFT_RECIPES,
    item_catalog_entry,
    item_is_collectible,
    item_is_craft_material,
    item_is_usable,
    is_known_item_key,
    resolve_item_use_kind,
)
from .inventory import (
    _credit_planet_resources,
    _debit_inventory_item,
    _inventory_amount,
    build_inventory_state,
    grant_inventory_item,
    inventory_schema_ready,
)

Effect = Dict[str, Any]


def unlocks_schema_ready(conn) -> bool:
    return table_exists(conn, "player_unlocks")


def _clamp_amount(amount: int, owned: int, *, max_use: int = 100) -> int:
    return max(1, min(int(amount), int(owned), int(max_use)))


def _effect_message(effect: Effect) -> Dict[str, Any]:
    kind = str(effect.get("kind") or "")
    if kind == "resource":
        key = str(effect.get("resource_key") or "")
        return {
            "message_key": f"inv_effect_resource_{key}" if key else "inv_effect_resource",
            "message_params": {"amount": int(effect.get("amount") or 0)},
        }
    if kind == "time_boost":
        target = str(effect.get("target") or "build")
        sec = int(effect.get("seconds_reduced") or 0)
        minutes = max(1, int(round(sec / 60)))
        return {
            "message_key": f"inv_effect_{target}_boost",
            "message_params": {"minutes": minutes, "seconds": sec},
        }
    if kind == "planet_xp":
        return {
            "message_key": "inv_effect_planet_xp",
            "message_params": {"xp": int(effect.get("xp_gained") or 0)},
        }
    if kind == "production_grant":
        return {
            "message_key": "inv_effect_production_grant",
            "message_params": {
                "metal": int(effect.get("metal") or 0),
                "crystal": int(effect.get("crystal") or 0),
            },
        }
    if kind == "research_instant":
        return {
            "message_key": "inv_effect_research_instant",
            "message_params": {"tech_key": str(effect.get("tech_key") or "")},
        }
    if kind == "blueprint_unlock":
        return {
            "message_key": "inv_effect_blueprint_unlock",
            "message_params": {"unlock_key": str(effect.get("unlock_key") or "")},
        }
    if kind == "craft":
        return {
            "message_key": "inv_effect_craft",
            "message_params": {
                "output_key": str(effect.get("output_key") or ""),
                "amount": int(effect.get("amount") or 0),
            },
        }
    return {"message_key": "inv_effect_generic", "message_params": {}}


def _shift_queue_times(
    conn,
    *,
    table: str,
    id_col: str,
    start_col: str,
    finish_col: str,
    rows: List[Mapping[str, Any]],
    reduction_sec: float,
    now: float,
) -> float:
    """Shift research/shipyard queue head job (and followers) by up to reduction_sec."""
    if not rows or reduction_sec <= 0:
        return 0.0
    first = rows[0]
    finish = float(first[finish_col] or 0)
    if finish <= now:
        return 0.0
    remaining = finish - now
    actual = min(float(reduction_sec), remaining)
    if actual <= 0:
        return 0.0

    cur = conn.cursor()
    new_finish = finish - actual
    cur.execute(
        f"UPDATE {table} SET {finish_col} = ? WHERE {id_col} = ?;",
        (new_finish, int(first[id_col])),
    )
    for row in rows[1:]:
        old_start = float(row[start_col] or 0)
        old_finish = float(row[finish_col] or 0)
        cur.execute(
            f"UPDATE {table} SET {start_col} = ?, {finish_col} = ? WHERE {id_col} = ?;",
            (old_start - actual, old_finish - actual, int(row[id_col])),
        )
    return actual


def apply_build_queue_booster(
    conn,
    user_id: int,
    planet_id: int,
    boost_seconds: int,
    *,
    now: Optional[float] = None,
) -> Optional[Effect]:
    """
    Apply a build-time booster to the full build queue on ``planet_id``.

    Shifts every queued job earlier by ``effective_shift`` where:
      effective_shift = min(boost_seconds, last_finish_time - now)

    The booster is considered fully applied when the queue had jobs; callers
    report ``seconds_reduced`` as the nominal ``boost_seconds`` even when the
    queue had less remaining time than the booster duration.
    """
    from .models import get_build_queue_rows
    from .queue_engine import finish_due_work_once

    ts = float(now if now is not None else time.time())
    pid = int(planet_id)
    uid = int(user_id)
    boost = max(0, int(boost_seconds))
    if boost <= 0:
        return None

    # Use caller conn — never open a parallel writer during inventory mutations.
    finish_due_work_once(
        uid,
        pid,
        conn=conn,
        source="inventory_use",
        dedup=False,
        recalc_ranks=False,
    )
    rows = list(get_build_queue_rows(pid, conn=conn))
    if not rows:
        return None

    last_finish = float(rows[-1]["finish_time"] or 0)
    effective_shift = min(float(boost), max(0.0, last_finish - ts))
    if effective_shift <= 0:
        return None

    cur = conn.cursor()
    for row in rows:
        start = float(row["start_time"] or 0)
        finish = float(row["finish_time"] or 0)
        cur.execute(
            """
            UPDATE build_queue
            SET start_time = ?, finish_time = ?
            WHERE id = ?;
            """,
            (start - effective_shift, finish - effective_shift, int(row["id"])),
        )

    finish_due_work_once(
        uid,
        pid,
        conn=conn,
        source="inventory_use",
        dedup=False,
        recalc_ranks=False,
    )

    return {
        "kind": "time_boost",
        "target": "build",
        "seconds_reduced": boost,
        "seconds_shifted": int(effective_shift),
    }


def _is_build_booster_item(item_key: str) -> bool:
    from .inventory_catalog import BOOSTER_QUEUE_TARGET

    key = str(item_key or "")
    return BOOSTER_QUEUE_TARGET.get(key) == "build"


def _apply_build_time_boost(
    planet_id: int,
    user_id: int,
    seconds: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Effect]:
    return apply_build_queue_booster(
        conn,
        int(user_id),
        int(planet_id),
        int(seconds),
        now=now,
    )


def _apply_research_time_boost(
    user_id: int,
    seconds: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Effect]:
    from .models import get_research_queue_rows
    from .queue_engine import finish_due_work_once

    ts = float(now if now is not None else time.time())
    finish_due_work_once(int(user_id), conn=conn, source="inventory_use")
    rows = get_research_queue_rows(int(user_id), conn=conn)
    if not rows:
        return None
    reduced = _shift_queue_times(
        conn,
        table="research_queue",
        id_col="id",
        start_col="start_at",
        finish_col="finish_at",
        rows=rows,
        reduction_sec=float(seconds),
        now=ts,
    )
    if reduced <= 0:
        return None
    return {"kind": "time_boost", "target": "research", "seconds_reduced": int(reduced)}


def _apply_shipyard_time_boost(
    planet_id: int,
    user_id: int,
    seconds: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Effect]:
    from .queue_engine import finish_active_planet_due_work
    from .shipyard_queue import list_shipyard_queue_rows, shipyard_queue_table_ready

    if not shipyard_queue_table_ready(conn):
        return None
    ts = float(now if now is not None else time.time())
    finish_active_planet_due_work(int(user_id), int(planet_id), conn, source="inventory_use")
    rows = list_shipyard_queue_rows(int(planet_id), conn=conn)
    if not rows:
        return None
    reduced = _shift_queue_times(
        conn,
        table="shipyard_queue",
        id_col="id",
        start_col="started_at",
        finish_col="finish_at",
        rows=rows,
        reduction_sec=float(seconds),
        now=ts,
    )
    if reduced <= 0:
        return None
    return {"kind": "time_boost", "target": "shipyard", "seconds_reduced": int(reduced)}


def _apply_time_boost(
    target: str,
    seconds: int,
    *,
    user_id: int,
    planet_id: int,
    conn,
) -> Optional[Effect]:
    if target == "build":
        return _apply_build_time_boost(planet_id, user_id, seconds, conn=conn)
    if target == "research":
        return _apply_research_time_boost(user_id, seconds, conn=conn)
    if target == "shipyard":
        return _apply_shipyard_time_boost(planet_id, user_id, seconds, conn=conn)
    return None


def _apply_resource_effect(
    planet_id: int,
    effect: Mapping[str, Any],
    *,
    conn,
) -> Effect:
    metal = int(effect.get("metal") or 0)
    crystal = int(effect.get("crystal") or 0)
    fuel = int(effect.get("fuel_cells") or 0)
    _credit_planet_resources(planet_id, metal=metal, crystal=crystal, fuel_cells=fuel, conn=conn)
    if metal > 0:
        return {"kind": "resource", "resource_key": "metal", "amount": metal}
    if crystal > 0:
        return {"kind": "resource", "resource_key": "crystal", "amount": crystal}
    return {"kind": "resource", "resource_key": "fuel_cells", "amount": fuel}


def _apply_planet_xp_effect(
    planet_id: int,
    xp: int,
    *,
    conn,
) -> Effect:
    from .planet_evolution.planet_level import add_planet_xp

    result = add_planet_xp(int(planet_id), int(xp), conn, reason="inventory_item")
    return {
        "kind": "planet_xp",
        "xp_gained": int(result.get("xp_gained") or 0),
        "planet_level": int(result.get("planet_level") or 1),
        "planet_xp": int(result.get("planet_xp") or 0),
    }


def _apply_production_grant(
    user_id: int,
    planet_id: int,
    effect: Mapping[str, Any],
    *,
    conn,
) -> Effect:
    from .logic import get_building_production_per_hour
    from .models import get_planet_buildings, get_research_levels

    pct = float(effect.get("pct") or 0) / 100.0
    hours = float(effect.get("hours") or 1)
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    research = get_research_levels(user_id=int(user_id), conn=conn)
    prod = get_building_production_per_hour(buildings, 1.0, research=research)
    metal_amt = int(prod.get("metal_mine", 0) or 0)
    crystal_amt = int(prod.get("crystal_mine", 0) or 0)
    grant_metal = max(0, int(metal_amt * pct * hours))
    grant_crystal = max(0, int(crystal_amt * pct * hours))
    if grant_metal <= 0 and grant_crystal <= 0:
        grant_metal = max(1000, int(10_000 * pct))
        grant_crystal = max(500, int(5_000 * pct))
    _credit_planet_resources(
        planet_id,
        metal=grant_metal,
        crystal=grant_crystal,
        conn=conn,
    )
    return {
        "kind": "production_grant",
        "metal": grant_metal,
        "crystal": grant_crystal,
        "pct": int(effect.get("pct") or 0),
        "hours": hours,
    }


def _apply_research_instant(user_id: int, *, conn) -> Optional[Effect]:
    from .models import get_research_queue_rows
    from .queue_engine import finish_due_work_once, finish_player_research_jobs

    finish_due_work_once(int(user_id), conn=conn, source="inventory_use")
    rows = get_research_queue_rows(int(user_id), conn=conn)
    if not rows:
        return None
    head = rows[0]
    tech_key = str(head["tech_key"])
    now = time.time()
    finish_at = float(head["finish_at"] or 0)
    if finish_at <= now:
        finish_player_research_jobs(int(user_id), conn, now)
        return {"kind": "research_instant", "tech_key": tech_key}
    cur = conn.cursor()
    cur.execute(
        "UPDATE research_queue SET finish_at = ? WHERE id = ?;",
        (now, int(head["id"])),
    )
    finish_player_research_jobs(int(user_id), conn, now)
    return {"kind": "research_instant", "tech_key": tech_key}


def _apply_blueprint_unlock(
    user_id: int,
    item_key: str,
    spec: Mapping[str, Any],
    *,
    conn,
) -> Optional[Effect]:
    if not unlocks_schema_ready(conn):
        return None
    unlock_key = str(spec.get("unlock_key") or item_key)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM player_unlocks
        WHERE user_id = ? AND unlock_key = ? LIMIT 1;
        """,
        (int(user_id), unlock_key),
    )
    if cur.fetchone():
        return None
    now = float(time.time())
    cur.execute(
        """
        INSERT INTO player_unlocks (user_id, unlock_key, source_item_key, created_at)
        VALUES (?, ?, ?, ?);
        """,
        (int(user_id), unlock_key, str(item_key), now),
    )
    return {"kind": "blueprint_unlock", "unlock_key": unlock_key, "source_item_key": str(item_key)}


def _resolve_use_spec(item_key: str) -> Tuple[Optional[str], Dict[str, Any]]:
    key = str(item_key)
    if item_is_collectible(key) or item_is_craft_material(key):
        return None, {}
    meta = item_catalog_entry(key)
    kind = resolve_item_use_kind(key)
    if not kind or kind == "collectible" or kind == "craft_material":
        return None, {}
    effect = dict(meta.get("use_effect") or {})
    if key in BOOSTER_TIME_SECONDS:
        kind = "time_boost"
        from .inventory_catalog import BOOSTER_QUEUE_TARGET

        effect = {
            "target": BOOSTER_QUEUE_TARGET.get(key, "build"),
            "seconds": int(BOOSTER_TIME_SECONDS[key]),
        }
    return kind, effect


def _apply_single_use(
    user_id: int,
    planet_id: int,
    item_key: str,
    *,
    conn,
) -> Optional[Effect]:
    kind, effect = _resolve_use_spec(item_key)
    if not kind:
        return None
    spec = (item_catalog_entry(item_key).get("use_effect") or {}) if kind != "time_boost" else effect

    if kind == "resource":
        return _apply_resource_effect(planet_id, effect, conn=conn)
    if kind == "planet_xp":
        return _apply_planet_xp_effect(planet_id, int(effect.get("xp") or 0), conn=conn)
    if kind == "time_boost":
        target = str(effect.get("target") or "build")
        seconds = int(effect.get("seconds") or 0)
        return _apply_time_boost(target, seconds, user_id=user_id, planet_id=planet_id, conn=conn)
    if kind == "production_grant":
        return _apply_production_grant(user_id, planet_id, effect, conn=conn)
    if kind == "research_instant":
        return _apply_research_instant(user_id, conn=conn)
    if kind == "blueprint":
        full_spec = dict(ITEM_CATALOG.get(item_key) or {})
        return _apply_blueprint_unlock(user_id, item_key, full_spec, conn=conn)
    return None


# Late import to avoid circular ref in blueprint branch
from .inventory_catalog import ITEM_CATALOG  # noqa: E402


def use_inventory_item(
    user_id: int,
    planet_id: int,
    item_key: str,
    amount: int = 1,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    key = str(item_key or "").strip()
    if not is_known_item_key(key):
        return False, "invalid_item", None
    if not item_is_usable(key):
        return False, "item_not_usable", None

    owned = _inventory_amount(user_id, key, conn=conn)
    use_count = _clamp_amount(amount, owned)
    if use_count <= 0 or owned < use_count:
        return False, "insufficient_items", None

    lock_planet_for_update(conn, int(planet_id))
    effects: List[Effect] = []
    consumed = 0

    for _ in range(use_count):
        effect = _apply_single_use(user_id, planet_id, key, conn=conn)
        if effect is None:
            break
        if not _debit_inventory_item(user_id, key, 1, conn=conn):
            break
        consumed += 1
        effects.append(effect)

    if consumed <= 0:
        fail_reason = "no_effect_target"
        if _is_build_booster_item(key):
            fail_reason = "no_build_queue"
        return False, fail_reason, None

    merged = _merge_effects(effects)
    inventory = build_inventory_state(user_id, conn=conn)
    return True, "item_use_ok", {
        "item_key": key,
        "consumed": consumed,
        "effects": effects,
        "effect": merged,
        "inventory": inventory,
    }


def _merge_effects(effects: List[Effect]) -> Effect:
    if not effects:
        return {}
    if len(effects) == 1:
        out = dict(effects[0])
        out.update(_effect_message(out))
        return out
    kind = str(effects[0].get("kind") or "")
    if kind == "time_boost":
        total = sum(int(e.get("seconds_reduced") or 0) for e in effects)
        out = {
            "kind": "time_boost",
            "target": str(effects[0].get("target") or "build"),
            "seconds_reduced": total,
            "count": len(effects),
        }
        out.update(_effect_message(out))
        return out
    if kind == "resource":
        out = dict(effects[-1])
        out["amount"] = sum(int(e.get("amount") or 0) for e in effects)
        out["count"] = len(effects)
        out.update(_effect_message(out))
        return out
    if kind == "planet_xp":
        out = dict(effects[-1])
        out["xp_gained"] = sum(int(e.get("xp_gained") or 0) for e in effects)
        out["count"] = len(effects)
        out.update(_effect_message(out))
        return out
    out = dict(effects[-1])
    out["count"] = len(effects)
    out.update(_effect_message(out))
    return out


def craft_inventory_item(
    user_id: int,
    recipe_key: str,
    amount: int = 1,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    rkey = str(recipe_key or "").strip()
    recipe = CRAFT_RECIPES.get(rkey)
    if not recipe:
        return False, "invalid_recipe", None

    craft_count = max(1, min(int(amount), 100))
    requires = dict(recipe.get("requires") or {})
    output_key = str(recipe.get("output_key") or rkey)
    output_each = int(recipe.get("output_amount") or 1)

    for mat_key, per_craft in requires.items():
        needed = int(per_craft) * craft_count
        owned = _inventory_amount(user_id, mat_key, conn=conn)
        if owned < needed:
            return False, "insufficient_materials", None

    for mat_key, per_craft in requires.items():
        needed = int(per_craft) * craft_count
        if not _debit_inventory_item(user_id, mat_key, needed, conn=conn):
            return False, "insufficient_materials", None

    total_out = output_each * craft_count
    grant_inventory_item(user_id, output_key, total_out, conn=conn)

    effect: Effect = {
        "kind": "craft",
        "recipe_key": rkey,
        "output_key": output_key,
        "amount": total_out,
    }
    effect.update(_effect_message(effect))
    inventory = build_inventory_state(user_id, conn=conn)
    return True, "craft_ok", {
        "recipe_key": rkey,
        "crafted": craft_count,
        "output_key": output_key,
        "output_amount": total_out,
        "effect": effect,
        "inventory": inventory,
    }


def enrich_inventory_item_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Attach use/craft/collectible metadata for UI."""
    out = dict(row)
    key = str(out.get("item_key") or "")
    owned = int(out.get("amount") or 0)
    out["collectible"] = item_is_collectible(key)
    out["craft_material"] = item_is_craft_material(key)
    out["usable"] = item_is_usable(key)
    use_kind = resolve_item_use_kind(key)
    if use_kind:
        out["use_kind"] = use_kind

    from .inventory_catalog import craft_recipes_for_material

    recipes = craft_recipes_for_material(key)
    if recipes:
        progress: List[Dict[str, Any]] = []
        for rec in recipes:
            progress.append(
                {
                    "recipe_key": rec["recipe_key"],
                    "output_key": rec["output_key"],
                    "name_key": rec["name_key"],
                    "owned": owned,
                    "required": int(rec["required_amount"]),
                    "can_craft": owned >= int(rec["required_amount"]),
                }
            )
        out["craft_progress"] = progress
        out["can_craft"] = any(p["can_craft"] for p in progress)

    return out
