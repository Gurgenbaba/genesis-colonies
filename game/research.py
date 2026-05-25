"""
Forschungs-Logik für Genesis Colonies.

- Research-Konfiguration (RESEARCH_TECHS)
- Kosten- und Zeit-Berechnung
- Requirement-Checks
- Research-Queue (Starten)
- Finish-Handling läuft ATOMAR über models.finish_due_research_jobs (inkl. Score Trigger)
- Cache invalidieren nach Finish (ranking.invalidate_player_score_cache)

WICHTIG:
- Dieses Modul enthält keine Flask- oder Template-Logik.
- Multi-User-safe: Finish/Start sind defensiv und robust.
"""

from __future__ import annotations

import time
from typing import Dict, Tuple, List, Any, Optional

from .models import (
    db,
    get_game_settings,
    get_research_levels,
    get_research_queue_rows,
    add_research_job,
    get_homeworld,
    get_planet_buildings,
    try_spend_resources,
    finish_due_research_jobs,  # ✅ atomare Finish-Logik (inkl. Score Trigger)
)
from .ranking import invalidate_player_score_cache  # ✅ Cache invalidieren nach Finish


# ======================================================================
# TECH CONFIG
# ======================================================================

RESEARCH_TECHS: Dict[str, Dict[str, Any]] = {
    "energy_tech": {
        "label": "Energieeffizienz",
        "label_key": "energy_tech",
        "description": "Optimiert die Energieausbeute aller Anlagen.",
        "description_key": "desc_energy_tech",
        "category": "energy",
        "icon": "energieeffizienz.png",
        "base_cost_m": 1000,
        "base_cost_c": 500,
        "base_time": 600,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "mining_tech": {
        "label": "Metallveredelung",
        "label_key": "mining_tech",
        "description": "Steigert die Reinheit und damit die Produktion von Ferronit.",
        "description_key": "desc_mining_tech",
        "category": "metal",
        "icon": "metallveredelung.png",
        "base_cost_m": 1200,
        "base_cost_c": 600,
        "base_time": 650,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "buildtime_tech": {
        "label": "Bauoptimierung",
        "label_key": "buildtime_tech",
        "description": "Reduziert Bauzeiten aller Gebäude.",
        "description_key": "desc_buildtime_tech",
        "category": "construction",
        "icon": "bauoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 800,
        "base_time": 700,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "storage_tech": {
        "label": "Lagertechnik",
        "label_key": "storage_tech",
        "description": "Erhöht die maximale Kapazität aller Lagergebäude.",
        "description_key": "desc_storage_tech",
        "category": "storage",
        "icon": "lagertechnik.png",
        "base_cost_m": 800,
        "base_cost_c": 800,
        "base_time": 550,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "drone_tech": {
        "label": "Drohnenoptimierung",
        "label_key": "research_drones_tech",
        "description": "Verbesserte Drohnen erhöhen die Ausbeute.",
        "description_key": "desc_research_drones_tech",
        "category": "drones",
        "icon": "drohnenoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 900,
        "base_time": 750,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "navigation_tech": {
        "label": "Hyperraum-Navigation",
        "label_key": "research_navigation_tech",
        "description": "Verkürzt Flugzeiten.",
        "description_key": "desc_research_navigation_tech",
        "category": "navigation",
        "icon": "hyperraum-navigation.png",
        "base_cost_m": 2000,
        "base_cost_c": 1500,
        "base_time": 900,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"drone_tech": 2}},
    },
    "engine_tech": {
        "label": "Kryo-Antriebstechnik",
        "label_key": "research_engine_tech",
        "description": "Erhöht Flottengeschwindigkeit.",
        "description_key": "desc_research_engine_tech",
        "category": "engine",
        "icon": "kryo-antriebstechnik.png",
        "base_cost_m": 2200,
        "base_cost_c": 1600,
        "base_time": 950,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"energy_tech": 2}},
    },
    "weapon_tech": {
        "label": "Waffenentwicklung",
        "label_key": "research_weapon_tech",
        "description": "Erhöht Feuerkraft.",
        "description_key": "desc_research_weapon_tech",
        "category": "weapon",
        "icon": "waffenentwicklung.png",
        "base_cost_m": 1800,
        "base_cost_c": 900,
        "base_time": 800,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "armor_tech": {
        "label": "Panzerungstechnik",
        "label_key": "research_armor_tech",
        "description": "Erhöht Hülle.",
        "description_key": "desc_research_armor_tech",
        "category": "armor",
        "icon": "panzerungstechnik.png",
        "base_cost_m": 1900,
        "base_cost_c": 1100,
        "base_time": 850,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}, "research": {"weapon_tech": 1}},
    },
    "shield_tech": {
        "label": "Schildtechnologie",
        "label_key": "research_shield_tech",
        "description": "Erhöht Schildstärke.",
        "description_key": "desc_research_shield_tech",
        "category": "shield",
        "icon": "schildtechnologie.png",
        "base_cost_m": 2200,
        "base_cost_c": 1300,
        "base_time": 950,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"armor_tech": 1}},
    },
}


# ======================================================================
# COSTS & TIME
# ======================================================================

def get_research_cost(tech_key: str, level: int) -> Tuple[int, int]:
    cfg = RESEARCH_TECHS.get(tech_key)
    if not cfg:
        return 0, 0

    base_m = float(cfg.get("base_cost_m", 1000))
    base_c = float(cfg.get("base_cost_c", 500))
    cost_factor = float(cfg.get("cost_factor", 1.6))

    lvl = max(1, int(level))
    factor = cost_factor ** (lvl - 1)

    return int(base_m * factor), int(base_c * factor)


def get_research_time(
    tech_key: str,
    level: int,
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
) -> int:
    cfg = RESEARCH_TECHS.get(tech_key)
    if not cfg:
        return 0

    base_time = float(cfg.get("base_time", 600))
    cost_factor = float(cfg.get("cost_factor", 1.6))

    lvl = max(1, int(level))
    factor = cost_factor ** (lvl - 1)
    raw = float(base_time * factor)

    # Gebäude (Lab-Level) laden falls nicht übergeben
    if buildings is None:
        planet = get_homeworld(player_id=int(user_id))
        buildings = get_planet_buildings(int(planet["id"]))

    lab_level = int(buildings.get("research_lab", 0) or 0)
    lab_bonus = 1.0 + max(0, lab_level - 1) * 0.10

    # NOTE: build_time_speed kommt aus research modifiers (siehe game/logic.py)
    # Hier bleiben wir kompatibel: wir rechnen build_time_speed als 1.0, wenn du später zentral ziehst.
    build_time_speed = 1.0

    settings = get_game_settings()
    build_speed = float(settings.get("build_speed", 1.0) or 1.0)
    research_speed = float(settings.get("research_speed", 1.0) or 1.0)

    effective_speed = max(0.1, build_speed * research_speed * lab_bonus * build_time_speed)
    raw /= effective_speed

    return max(5, int(raw))


# ======================================================================
# REQUIREMENTS
# ======================================================================

def _check_requirements(
    base_requirements: Dict[str, Any],
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> bool:
    if not base_requirements:
        return True

    for b_key, need_lvl in (base_requirements.get("buildings") or {}).items():
        if int(buildings.get(b_key, 0) or 0) < int(need_lvl):
            return False

    for r_key, need_lvl in (base_requirements.get("research") or {}).items():
        if int(research_levels.get(r_key, 0) or 0) < int(need_lvl):
            return False

    return True


def has_research_requirements(
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
    tech_key: str,
) -> bool:
    cfg = RESEARCH_TECHS.get(tech_key)
    if not cfg:
        return False
    req = cfg.get("requirements") or {}
    return _check_requirements(req, buildings, research_levels)


# ======================================================================
# FINISH (ATOMAR, CONN-SAFE)
# ======================================================================

def complete_finished_research(user_id: int, conn=None) -> bool:
    """
    ✅ Conn-safe:
    - Wenn conn übergeben: KEIN eigenes BEGIN/COMMIT, nur finish_due_research_jobs() in derselben Tx.
    - Wenn conn None: eigene Connection + Transaction.
    - Danach Score-Cache invalidieren (nur wenn wirklich finished).
    - Rückgabe: True wenn mindestens ein Job gefinished wurde.
    """
    uid = int(user_id)
    now = time.time()

    from .models import db as _db
    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    finished_any = False
    try:
        if own_conn:
            conn.execute("BEGIN IMMEDIATE")

        finished_any = finish_due_research_jobs(
            user_id=uid,
            now=now,
            conn=conn,
        )

        if own_conn:
            conn.commit()

    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    if finished_any:
        invalidate_player_score_cache(uid)

    return bool(finished_any)


RESEARCH_QUEUE_LIMIT = 3


# ======================================================================
# QUEUE START
# ======================================================================

def queue_research(player: dict, tech_key: str, user_id: Optional[int] = None):
    if tech_key not in RESEARCH_TECHS:
        return False, "unknown_tech", None

    if user_id is None:
        pid = player.get("id")
        if pid is None:
            raise RuntimeError("queue_research: player hat kein 'id'")
        uid = int(pid)
    else:
        uid = int(user_id)

    complete_finished_research(uid)

    planet = get_homeworld(player_id=uid)
    buildings = get_planet_buildings(int(planet["id"]))
    levels = get_research_levels(uid)

    if int(buildings.get("research_lab", 0) or 0) <= 0:
        return False, "no_research_lab", None

    if not has_research_requirements(buildings, levels, tech_key):
        return False, "requirements", None

    rows = get_research_queue_rows(uid)
    if len(rows) >= RESEARCH_QUEUE_LIMIT:
        return False, "research_queue_full", {
            "queue_count": len(rows),
            "queue_limit": RESEARCH_QUEUE_LIMIT,
        }

    queued_same = sum(1 for r in rows if str(r["tech_key"]) == tech_key)
    current = int(levels.get(tech_key, 0) or 0)
    target = current + queued_same + 1

    cost_m, cost_c = get_research_cost(tech_key, target)

    if float(planet["metal"]) < float(cost_m) or float(planet["crystal"]) < float(cost_c):
        return False, "not_enough_resources", (int(cost_m), int(cost_c))

    duration = get_research_time(tech_key, target, user_id=uid, buildings=buildings)
    now = time.time()
    last_finish = max(float(r["finish_at"]) for r in rows) if rows else now
    start_at = max(now, last_finish)
    finish_at = start_at + float(duration)

    if not try_spend_resources(int(planet["id"]), int(cost_m), int(cost_c)):
        return False, "not_enough_resources", (int(cost_m), int(cost_c))

    add_research_job(uid, tech_key, float(start_at), float(finish_at))
    return True, "ok", {
        "seconds": int(duration),
        "level": int(target),
        "queued": len(rows) > 0,
    }


# ======================================================================
# STATUS FOR UI
# ======================================================================

def get_research_status(
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
) -> dict:
    # ✅ UI soll immer frisch sein — ggf. mehrfach abschließen wenn fällig
    complete_finished_research(int(user_id))

    if buildings is None:
        planet = get_homeworld(player_id=int(user_id))
        buildings = get_planet_buildings(int(planet["id"]))

    levels = get_research_levels(int(user_id))
    queue = get_research_queue_rows(int(user_id))
    now = time.time()

    # Nachziehen: Job kann „0s“ anzeigen, finish_at aber knapp in der Zukunft liegen
    for _ in range(3):
        if not queue:
            break
        if float(queue[0]["finish_at"]) > now:
            break
        if not complete_finished_research(int(user_id)):
            break
        queue = get_research_queue_rows(int(user_id))
        levels = get_research_levels(int(user_id))

    queue_list: List[Dict[str, Any]] = []
    pending: Dict[str, int] = {}

    for i, job in enumerate(queue):
        tech = str(job["tech_key"])
        cfg = RESEARCH_TECHS.get(tech, {})
        pending[tech] = pending.get(tech, 0) + 1

        curr = int(levels.get(tech, 0) or 0)
        targ = curr + pending[tech]

        finish_at = float(job["finish_at"])
        start_raw = job["start_at"] if "start_at" in job.keys() else None
        if start_raw is not None and float(start_raw or 0) > 0:
            start_at = float(start_raw)
        elif i > 0:
            start_at = float(queue[i - 1]["finish_at"])
        else:
            start_at = finish_at - float(get_research_time(tech, targ, user_id=int(user_id), buildings=buildings))

        total = max(1, int(finish_at - start_at))
        remain = max(0, int(finish_at - now))

        queue_list.append({
            "id": int(job["id"]),
            "tech_key": tech,
            "key": tech,
            "label": cfg.get("label", tech),
            "label_key": cfg.get("label_key"),
            "description": cfg.get("description", ""),
            "description_key": cfg.get("description_key"),
            "current_level": curr,
            "target_level": int(targ),
            "remaining": int(remain),
            "total_seconds": int(total),
            "total": int(total),
            "finish_at": finish_at,
            "start_at": start_at,
            "icon": cfg.get("icon"),
            "position": i + 1,
        })

    active = queue_list[0] if queue_list else None

    queue_keys: Dict[str, int] = {}
    for item in queue_list:
        k = str(item["tech_key"])
        queue_keys[k] = queue_keys.get(k, 0) + 1

    techs: List[Dict[str, Any]] = []
    for tech, cfg in RESEARCH_TECHS.items():
        curr = int(levels.get(tech, 0) or 0)
        targ = curr + 1

        cost_m, cost_c = get_research_cost(tech, targ)
        t_sec = get_research_time(tech, targ, user_id=int(user_id), buildings=buildings)

        req = cfg.get("requirements") or {}
        req_met = _check_requirements(req, buildings, levels)

        q_count = int(queue_keys.get(tech, 0) or 0)
        is_active = bool(active and str(active.get("tech_key")) == tech and q_count > 0)
        in_queue = q_count > 0

        techs.append({
            "key": tech,
            "label": cfg.get("label", tech),
            "label_key": cfg.get("label_key"),
            "description": cfg.get("description", ""),
            "description_key": cfg.get("description_key"),
            "level": curr,
            "cost_metal": int(cost_m),
            "cost_crystal": int(cost_c),
            "time_seconds": int(t_sec),
            "requirements_met": bool(req_met),
            "icon": cfg.get("icon"),
            "queue_count": q_count,
            "is_active": is_active,
            "in_queue": in_queue,
        })

    summary = {
        "count": len(queue_list),
        "limit": RESEARCH_QUEUE_LIMIT,
        "has_queue": bool(queue_list),
        "first_finish_in": int(queue_list[0]["remaining"]) if queue_list else 0,
    }

    return {
        "active": active,
        "queue": queue_list,
        "summary": summary,
        "techs": techs,
        "lab_level": int(buildings.get("research_lab", 0) or 0),
    }


# ======================================================================
# VALIDATION
# ======================================================================

def _validate_research_config() -> None:
    for tech_key, cfg in RESEARCH_TECHS.items():
        req = cfg.get("requirements") or {}
        for r_key in (req.get("research") or {}).keys():
            if r_key not in RESEARCH_TECHS:
                raise RuntimeError(
                    f"RESEARCH_CONFIG: Requirements von '{tech_key}' verweisen auf unbekannte Forschung '{r_key}'"
                )

_validate_research_config()

# ============================================================================
# Modifiers (used by buildings/resources)
# ============================================================================
from typing import Optional, Dict, Any

def _get_level(levels: Dict[str, Any], key: str) -> int:
    try:
        return int(levels.get(key, 0) or 0)
    except Exception:
        return 0

def get_research_modifiers(player_id: int, conn=None) -> dict:
    """
    Gibt ein Modifier-Dict zurück, das in resources.update_planet_resources genutzt wird.

    Wichtig:
    - Muss conn optional akzeptieren, weil resources.py mit conn=... aufruft.
    - Fallback: falls get_research_levels() in deiner models.py noch kein conn akzeptiert.
    """

    # --- Research-Levels laden (conn optional) ---
    try:
        levels = get_research_levels(player_id, conn=conn)  # type: ignore[arg-type]
    except TypeError:
        # ältere Signatur ohne conn
        levels = get_research_levels(player_id)

    if not isinstance(levels, dict):
        levels = {}

    # --- Default Modifier (sehr defensive) ---
    mods = {
        # Produktion/Ökonomie
        "prod_multiplier": 1.0,          # allgemeiner Produktions-Multiplikator
        "storage_multiplier": 1.0,       # Lagerkapazität
        "energy_efficiency": 1.0,        # optional, falls du es separat nutzt

        # Zeiten
        "build_time_multiplier": 1.0,    # Bauzeit-Multiplikator
        "research_time_multiplier": 1.0, # Forschungszeit-Multiplikator

        # Combat/Meta (für später / UI)
        "weapon_bonus": 0.0,
        "armor_bonus": 0.0,
        "shield_bonus": 0.0,

        # Galaxy/Fleet (für später)
        "scan_range": 0,
        "fleet_speed_multiplier": 1.0,
        "cargo_multiplier": 1.0,
    }

    # --- Modifiers ableiten (sanft, keine Hardcore-Balance hier) ---
    def lvl(key: str) -> int:
        try:
            return int(levels.get(key, 0) or 0)
        except Exception:
            return 0

    # Beispiel-Keys (passen wir später 1:1 an deine RESEARCH_TECHS an)
    # -> Diese Implementierung crasht NICHT, auch wenn Keys fehlen.

    # Energie-/Produktionseffizienz
    le = lvl("energy_efficiency")
    if le > 0:
        mods["energy_efficiency"] *= (1.0 + 0.02 * le)
        mods["prod_multiplier"] *= (1.0 + 0.01 * le)

    # Drohnenoptimierung (kleiner Produktionsboost)
    ld = lvl("drones_optimization")
    if ld > 0:
        mods["prod_multiplier"] *= (1.0 + 0.01 * ld)

    # Bauoptimierung (Bauzeit runter)
    lb = lvl("build_optimization")
    if lb > 0:
        mods["build_time_multiplier"] *= max(0.40, 1.0 - 0.03 * lb)

    # Forschung (Forschungszeit runter)
    lr = lvl("research_optimization")
    if lr > 0:
        mods["research_time_multiplier"] *= max(0.45, 1.0 - 0.03 * lr)

    # Lagertechnik (Cap hoch)
    ls = lvl("storage_tech")
    if ls > 0:
        mods["storage_multiplier"] *= (1.0 + 0.05 * ls)

    # Scanner / Radar (Range hoch)
    lscan = lvl("scanner_tech")
    if lscan > 0:
        mods["scan_range"] += lscan

    # Combat Tech (für später)
    lw = lvl("weapons_development")
    if lw > 0:
        mods["weapon_bonus"] += 0.05 * lw

    la = lvl("armor_tech")
    if la > 0:
        mods["armor_bonus"] += 0.05 * la

    lsh = lvl("shield_tech")
    if lsh > 0:
        mods["shield_bonus"] += 0.05 * lsh

    # Fleet Speed (für später)
    lhn = lvl("hyper_navigation")
    if lhn > 0:
        mods["fleet_speed_multiplier"] *= (1.0 + 0.03 * lhn)

    lcryo = lvl("cryo_engine")
    if lcryo > 0:
        mods["fleet_speed_multiplier"] *= (1.0 + 0.02 * lcryo)

    return mods
