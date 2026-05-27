"""Dashboard payload builder for Planet Evolution UI (player-facing UX)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import get_planet_buildings
from .constants import LEVEL_UNLOCKS, MAX_PLANET_LEVEL
from .definitions import get_event, get_policy, get_policies as get_policy_definitions, get_research_def, get_trait
from .specialization import list_specialization_options
from .dna import all_trait_keys
from .history import get_history
from .planet_level import xp_threshold_for_level
from .repository import (
    get_discoveries,
    get_legacy_tags,
    get_planet_culture,
    get_planet_dna,
    get_planet_research_levels,
    get_planet_row,
    get_policies,
    get_production_chains,
    get_special_resources,
    get_trade_routes,
)
from .scoring import compute_single_planet_score
from .ux_copy import (
    category_label_key,
    event_state_label_key,
    humanize_requirements,
    level_unlock_label_key,
    planet_class_label_key,
    polarity_label_key,
)


def _pct(current: float, cap: float) -> int:
    if cap <= 0:
        return 0
    return max(0, min(100, int(round(100.0 * float(current) / float(cap)))))


def _planet_status(
    planet: Dict[str, Any],
    culture: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if planet.get("failure_state"):
        return {"key": "crisis", "label_key": "pe_status_crisis"}
    stability = float(culture.get("stability") or 0)
    if stability < 35 or any(w.get("severity") == "critical" for w in warnings):
        return {"key": "pressure", "label_key": "pe_status_pressure"}
    if stability < 60 or warnings:
        return {"key": "pressure", "label_key": "pe_status_pressure"}
    return {"key": "stable", "label_key": "pe_status_stable"}


def _trait_cards(dna: Dict[str, Any], reveal: int) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
    for key in all_trait_keys(dna, reveal_tier=max(reveal, 1)):
        tdef = get_trait(key) or {}
        rarity = str(tdef.get("rarity") or "common")
        effects = tdef.get("effects") or {}
        risk = tdef.get("risk_json") or tdef.get("risk") or {}
        if isinstance(risk, str):
            risk = {}

        polarity = "neutral"
        if effects.get("unlocks") or (effects.get("affinity") if isinstance(effects.get("affinity"), dict) else None):
            polarity = "positive"
        if risk.get("event_rate_mult", 1.0) and float(risk.get("event_rate_mult", 1.0)) > 1.05:
            polarity = "negative"
        if tdef.get("blocks") or effects.get("blocks"):
            polarity = "negative"
        if rarity in ("rare", "epic", "legendary") and tdef.get("category") == "anomaly":
            polarity = "rare"

        risk_key = None
        if float(risk.get("event_rate_mult", 1.0) or 1.0) > 1.05:
            risk_key = "pe_trait_risk_events"
        elif effects.get("blocks"):
            risk_key = "pe_trait_risk_blocks"

        cards.append(
            {
                "key": key,
                "label_key": f"trait_{key}",
                "effect_key": f"trait_effect_{key}",
                "risk_key": risk_key,
                "rarity": rarity,
                "category": tdef.get("category") or "geology",
                "category_label_key": category_label_key(tdef.get("category") or "geology"),
                "polarity": polarity,
                "polarity_label_key": polarity_label_key(polarity),
            }
        )
    return cards


def _progression_milestones(level: int) -> List[Dict[str, Any]]:
    milestones = []
    for unlock_level in sorted(LEVEL_UNLOCKS.keys()):
        if unlock_level <= level:
            continue
        if len(milestones) >= 3:
            break
        unlock = LEVEL_UNLOCKS[unlock_level]
        milestones.append(
            {
                "level": unlock_level,
                "label_key": level_unlock_label_key(unlock_level, unlock),
                "reached": False,
            }
        )
    return milestones


def _economy_flow(planet_id: int, mechanics: Dict[str, Any], conn: sqlite3.Connection) -> Dict[str, Any]:
    exports = []
    for ex in mechanics.get("export_slots") or []:
        exports.append(
            {
                "resource_key": ex,
                "label_key": f"resource_{ex}",
                "status": "active",
            }
        )

    chains = []
    for chain_key in mechanics.get("active_chains") or []:
        chains.append(
            {
                "chain_key": chain_key,
                "label_key": f"chain_{chain_key}",
                "status": "active",
            }
        )

    deficits = []
    for d in mechanics.get("import_deficits") or []:
        received = float(d.get("received") or 0)
        required = float(d.get("required") or 0)
        pct = int(round(100.0 * received / required)) if required > 0 else 0
        deficits.append(
            {
                "resource_key": d.get("resource_key"),
                "label_key": f"resource_{d.get('resource_key')}",
                "received": received,
                "required": required,
                "pct": min(100, pct),
                "status": "critical" if pct < 50 else "warn",
            }
        )

    return {"exports": exports, "chains": chains, "deficits": deficits}


def _research_ux(research_status: Dict[str, Any], planet_level: int) -> Dict[str, Any]:
    now = time.time()
    queue = research_status.get("queue") or []
    techs = research_status.get("techs") or []
    queue_limit = int(research_status.get("queue_limit") or 2)
    queue_count = len(queue)

    active: List[Dict[str, Any]] = []
    for job in queue:
        tech_key = str(job.get("tech_key") or "")
        cfg = get_research_def(tech_key) or {}
        start = float(job.get("start_at") or now)
        finish = float(job.get("finish_at") or now)
        span = max(1.0, finish - start)
        elapsed = max(0.0, min(span, now - start))
        active.append(
            {
                "job_id": job.get("id"),
                "tech_key": tech_key,
                "label_key": cfg.get("label_key") or tech_key,
                "unlock_key": cfg.get("description_key"),
                "progress_pct": int(round(100.0 * elapsed / span)),
                "seconds_remaining": max(0, int(finish - now)),
                "start_at": start,
                "finish_at": finish,
                "total_seconds": int(span),
            }
        )

    recommended: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []

    for tech in techs:
        tech_key = str(tech.get("tech_key") or "")
        cfg = get_research_def(tech_key) or {}
        level = int(tech.get("level") or 0)
        max_level = int(tech.get("max_level") or 1)
        if level >= max_level or tech.get("is_active"):
            continue

        card = {
            "tech_key": tech_key,
            "label_key": tech.get("label_key") or tech_key,
            "unlock_key": tech.get("description_key") or cfg.get("description_key"),
            "tier": tech.get("tier"),
            "requirements_met": bool(tech.get("requirements_met")),
            "missing_human": humanize_requirements(
                tech.get("missing_requirements") or [],
                planet_level=planet_level,
            ),
            "choice_group": tech.get("choice_group"),
            "choice_options": tech.get("choice_options"),
            "choice_made": tech.get("choice_made"),
        }

        if tech.get("requirements_met") and len(recommended) < 3:
            recommended.append(card)
        elif not tech.get("requirements_met") and len(locked) < 6:
            locked.append(card)

    return {
        "active": active,
        "recommended": recommended,
        "locked": locked,
        "queue_count": queue_count,
        "queue_limit": queue_limit,
        "queue_has_room": queue_count < queue_limit,
    }


def _spec_recommendations(
    eligible: List[str],
    dna: Dict[str, Any],
    reveal: int,
    conn: sqlite3.Connection,
    planet_id: int,
) -> List[Dict[str, Any]]:
    options = [o for o in list_specialization_options(planet_id, conn) if o.get("eligible")]
    if not options and eligible:
        options = [o for o in list_specialization_options(planet_id, conn) if o["spec_key"] in eligible]
    return options[:6]


def _warnings(
    planet: Dict[str, Any],
    culture: Dict[str, Any],
    mechanics: Dict[str, Any],
    active_event: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    for d in mechanics.get("import_deficits") or []:
        res = d.get("resource_key") or "resource"
        warnings.append(
            {
                "key": "import_deficit",
                "label_key": "pe_warn_import_deficit",
                "body_key": "pe_warn_import_deficit_body",
                "severity": "warn",
                "action_target": "economy",
                "resource_key": res,
            }
        )
        break

    if float(culture.get("stability") or 100) < 35:
        warnings.append(
            {
                "key": "stability",
                "label_key": "pe_warn_stability",
                "body_key": "pe_warn_stability_body",
                "severity": "critical",
                "action_target": "policies",
            }
        )
    if float(culture.get("crime") or 0) > 75:
        warnings.append(
            {
                "key": "crime",
                "label_key": "pe_warn_crime",
                "body_key": "pe_warn_crime_body",
                "severity": "warn",
                "action_target": "policies",
            }
        )
    if planet.get("failure_state"):
        warnings.append(
            {
                "key": "failure",
                "label_key": "pe_warn_failure",
                "body_key": "pe_warn_failure_body",
                "severity": "critical",
                "action_target": "events",
            }
        )
    if active_event:
        warnings.append(
            {
                "key": "active_event",
                "label_key": active_event.get("label_key") or "pe_active_event",
                "body_key": "pe_warn_active_event_body",
                "severity": "warn",
                "action_target": "events",
            }
        )
    if float(culture.get("industrial_pressure") or 0) > 65:
        warnings.append(
            {
                "key": "energy",
                "label_key": "pe_warn_energy",
                "body_key": "pe_warn_energy_body",
                "severity": "warn",
                "action_target": "economy",
            }
        )
    return warnings


def _next_action(
    *,
    planet: Dict[str, Any],
    level: int,
    active_event: Optional[Dict[str, Any]],
    eligible_specs: List[str],
    research_ux: Dict[str, Any],
    warnings: List[Dict[str, Any]],
    mechanics: Dict[str, Any],
) -> Dict[str, Any]:
    if active_event:
        return {
            "priority": "event",
            "title_key": "pe_action_event_title",
            "body_key": "pe_action_event_body",
            "cta_label_key": "pe_action_event_cta",
            "cta_target": "events",
            "event_label_key": active_event.get("label_key"),
        }

    if planet.get("failure_state"):
        return {
            "priority": "crisis",
            "title_key": "pe_action_crisis_title",
            "body_key": "pe_action_crisis_body",
            "cta_label_key": "pe_action_crisis_cta",
            "cta_target": "events",
        }

    if not planet.get("specialization_key") and level >= 8 and eligible_specs:
        return {
            "priority": "specialization",
            "title_key": "pe_action_spec_title",
            "body_key": "pe_action_spec_body",
            "cta_label_key": "pe_action_spec_cta",
            "cta_target": "specialization",
        }

    if level < 8 and not planet.get("specialization_key"):
        return {
            "priority": "progression",
            "title_key": "pe_action_spec_soon_title",
            "body_key": "pe_action_spec_soon_body",
            "cta_label_key": "pe_action_progression_cta",
            "cta_target": "progression",
            "unlock_level": 8,
        }

    rec = research_ux.get("recommended") or []
    if rec and research_ux.get("queue_has_room"):
        first = rec[0]
        return {
            "priority": "research",
            "title_key": "pe_action_research_title",
            "body_key": "pe_action_research_body",
            "cta_label_key": "pe_action_research_cta",
            "cta_target": "research",
            "tech_key": first.get("tech_key"),
            "tech_label_key": first.get("label_key"),
        }

    if research_ux.get("active"):
        job = research_ux["active"][0]
        return {
            "priority": "research_running",
            "title_key": "pe_action_research_running_title",
            "body_key": "pe_action_research_running_body",
            "cta_label_key": "pe_action_research_running_cta",
            "cta_target": "research",
            "tech_label_key": job.get("label_key"),
            "progress_pct": job.get("progress_pct"),
        }

    deficits = mechanics.get("import_deficits") or []
    if deficits:
        return {
            "priority": "economy",
            "title_key": "pe_action_economy_title",
            "body_key": "pe_action_economy_body",
            "cta_label_key": "pe_action_economy_cta",
            "cta_target": "economy",
        }

    if any(w.get("key") == "stability" for w in warnings):
        return {
            "priority": "stability",
            "title_key": "pe_action_stability_title",
            "body_key": "pe_action_stability_body",
            "cta_label_key": "pe_action_stability_cta",
            "cta_target": "policies",
        }

    return {
        "priority": "explore",
        "title_key": "pe_action_explore_title",
        "body_key": "pe_action_explore_body",
        "cta_label_key": "pe_action_explore_cta",
        "cta_target": "traits",
    }


def _events_feed(planet_id: int, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM planet_events
        WHERE planet_id = ?
        ORDER BY started_at DESC
        LIMIT 12;
        """,
        (int(planet_id),),
    )
    feed = []
    for row in cur.fetchall():
        ev = dict(row)
        edef = get_event(str(ev.get("event_key") or "")) or {}
        ev["label_key"] = edef.get("label_key") or ev.get("event_key")
        ev["state_label_key"] = event_state_label_key(str(ev.get("state") or ""))
        ev["choices"] = edef.get("choices") or []
        feed.append(ev)
    return feed


def _policy_rows(planet_id: int, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = []
    for pol in get_policies(planet_id, conn=conn):
        pdef = get_policy(str(pol.get("policy_key") or "")) or {}
        rows.append(
            {
                "slot": pol.get("slot"),
                "policy_key": pol.get("policy_key"),
                "label_key": pdef.get("label_key") or f"policy_{pol.get('policy_key')}",
            }
        )
    return rows


def _policy_slots_max(level: int) -> int:
    if level >= 18:
        return 3
    if level >= 5:
        return 2
    return 1


def _policy_ux(
    planet_id: int,
    *,
    planet: Dict[str, Any],
    culture: Dict[str, Any],
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    level = int(planet.get("planet_level") or 1)
    slots_max = _policy_slots_max(level)
    archetype = str(culture.get("archetype_key") or "")
    now = time.time()
    active_by_slot: Dict[int, Dict[str, Any]] = {}
    for pol in get_policies(planet_id, conn=conn):
        active_by_slot[int(pol["slot"])] = dict(pol)

    slots: List[Dict[str, Any]] = []
    for slot in range(1, slots_max + 1):
        active = active_by_slot.get(slot)
        active_payload = None
        on_cooldown = False
        if active:
            pdef = get_policy(str(active.get("policy_key") or "")) or {}
            cooldown_until = float(active.get("cooldown_until") or 0)
            on_cooldown = cooldown_until > now
            active_payload = {
                "policy_key": active.get("policy_key"),
                "label_key": pdef.get("label_key") or f"policy_{active.get('policy_key')}",
                "cooldown_until": cooldown_until if on_cooldown else None,
            }

        options: List[Dict[str, Any]] = []
        for policy_key, pdef in get_policy_definitions().items():
            min_slot = int(pdef.get("tier") or 1)
            if min_slot > slot:
                continue
            allowed = pdef.get("archetype_allow") or []
            eligible = not allowed or archetype in [str(a) for a in allowed]
            locked_reason_key = None
            if not eligible:
                locked_reason_key = "pe_policy_wrong_archetype"
            options.append(
                {
                    "policy_key": policy_key,
                    "label_key": pdef.get("label_key") or f"policy_{policy_key}",
                    "eligible": eligible,
                    "locked_reason_key": locked_reason_key,
                    "min_slot": min_slot,
                }
            )
        options.sort(key=lambda o: (not o["eligible"], o["label_key"]))

        slots.append(
            {
                "slot": slot,
                "active": active_payload,
                "on_cooldown": on_cooldown,
                "options": options,
            }
        )

    return {
        "slots_max": slots_max,
        "archetype_key": archetype,
        "archetype_label_key": f"pe_archetype_{archetype}" if archetype else "pe_archetype_unknown",
        "slots": slots,
    }


def build_dashboard_extras(
    planet_id: int,
    *,
    planet: Dict[str, Any],
    dna: Dict[str, Any],
    culture: Dict[str, Any],
    mechanics: Dict[str, Any],
    research: Dict[str, Any],
    active_event: Optional[Dict[str, Any]],
    eligible_specializations: Optional[List[str]] = None,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    reveal = int(planet.get("dna_reveal_tier") or 0)
    level = int(planet.get("planet_level") or 1)
    xp = int(planet.get("planet_xp") or 0)
    next_threshold = xp_threshold_for_level(level + 1) if level < MAX_PLANET_LEVEL else xp
    prev_threshold = xp_threshold_for_level(level)
    xp_in_level = max(0, xp - prev_threshold)
    xp_span = max(1, next_threshold - prev_threshold)
    rarity = str(dna.get("rarity_tier") or "common")

    eligible = list(eligible_specializations or [])
    research_ux = _research_ux(research, level)
    warnings = _warnings(planet, culture, mechanics, active_event)
    status = _planet_status(planet, culture, warnings)
    economy = _economy_flow(planet_id, mechanics, conn)

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM planet_events WHERE planet_id = ? AND state IN ('pending','active');",
        (int(planet_id),),
    )
    open_events = int(cur.fetchone()["c"])

    return {
        "header": {
            "xp_in_level": xp_in_level,
            "xp_span": xp_span,
            "xp_pct": _pct(xp_in_level, xp_span),
            "xp_remaining": max(0, xp_span - xp_in_level),
            "stability": float(culture.get("stability") or 0),
            "loyalty": float(culture.get("loyalty") or 0),
            "is_homeworld": bool(planet.get("is_homeworld")),
            "rarity": rarity,
            "rarity_label_key": f"pe_rarity_{rarity}",
            "status": status,
            "planet_class_label_key": planet_class_label_key(planet.get("planet_class") or "terrestrial"),
        },
        "location": {
            "galaxy": int(planet.get("galaxy") or 1),
            "system": planet.get("system"),
            "position": planet.get("position"),
            "display": f"G{int(planet.get('galaxy') or 1)} · Sektor {planet.get('system') or '?'} · Position {planet.get('position') or '?'}",
        },
        "planet_score": compute_single_planet_score(planet_id, conn=conn),
        "traits": _trait_cards(dna, reveal),
        "progression": {
            "level": level,
            "max_level": MAX_PLANET_LEVEL,
            "xp_in_level": xp_in_level,
            "xp_span": xp_span,
            "xp_pct": _pct(xp_in_level, xp_span),
            "xp_remaining": max(0, xp_span - xp_in_level),
            "next_level": level + 1 if level < MAX_PLANET_LEVEL else None,
            "milestones": _progression_milestones(level),
        },
        "economy": economy,
        "research_ux": research_ux,
        "spec_recommendations": _spec_recommendations(eligible, dna, reveal, conn, planet_id),
        "next_action": _next_action(
            planet=planet,
            level=level,
            active_event=active_event,
            eligible_specs=eligible,
            research_ux=research_ux,
            warnings=warnings,
            mechanics=mechanics,
        ),
        "policies_active": _policy_rows(planet_id, conn),
        "policy_ux": _policy_ux(planet_id, planet=planet, culture=culture, conn=conn),
        "policy_slots_max": _policy_slots_max(level),
        "warnings": warnings,
        "events_feed": _events_feed(planet_id, conn),
        "open_events_count": open_events,
        "history": get_history(planet_id, limit=20, conn=conn),
    }
