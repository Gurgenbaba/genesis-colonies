"""Dashboard payload builder for Planet Evolution UI (player-facing UX)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional

from ..models import get_planet_buildings
from .constants import LEVEL_UNLOCKS, MAX_PLANET_LEVEL, SPECIALIZATION_UNLOCK_LEVEL, IDENTITY_TEASER_MIN_LEVEL
from .expansion_gates import build_expansion_unlock_block
from .definitions import get_event, get_policy, get_policies as get_policy_definitions, get_research_def, get_trait
from .specialization import list_specialization_options
from .dna import all_trait_keys
from .history import get_history
from .planet_level import xp_threshold_for_level
from .ascension import get_ascension_status
from .planet_research import compute_planet_research_cost, compute_planet_research_time
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
from ..activity_xp import get_activity_xp_dashboard
from .scoring import compute_single_planet_score
from .ux_copy import (
    category_label_key,
    event_state_label_key,
    humanize_requirements,
    level_unlock_label_key,
    planet_class_label_key,
    planet_research_icon,
    planet_research_icon_fallback,
    polarity_label_key,
    trait_effect_lines,
)


def _pct(current: float, cap: float) -> int:
    if cap <= 0:
        return 0
    return max(0, min(100, int(round(100.0 * float(current) / float(cap)))))


def _planet_location_display(planet: Dict[str, Any]) -> Dict[str, Any]:
    from game.galaxy import get_planet_coordinates

    coords = get_planet_coordinates(planet)
    return {
        "galaxy": coords["galaxy"],
        "system": coords["system"],
        "position": coords["position"],
        "display": coords["formatted"],
    }


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
    """Trait cards for PE — DNA hidden until establishment (reveal tier 0)."""
    if int(reveal or 0) <= 0:
        return []
    cards: List[Dict[str, Any]] = []
    for key in all_trait_keys(dna, reveal_tier=int(reveal)):
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
                "effect_lines": trait_effect_lines(tdef),
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


def _enrich_research_card(
    *,
    tech: Dict[str, Any],
    cfg: Dict[str, Any],
    planet_id: int,
    planet: Dict[str, Any],
    planet_level: int,
    queue_has_room: bool,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    tech_key = str(tech.get("tech_key") or "")
    current = int(tech.get("level") or 0)
    q_count = int(tech.get("queue_count") or 0)
    max_level = int(tech.get("max_level") or 1)
    target = current + q_count + 1

    cost_m, cost_c = compute_planet_research_cost(tech_key, target)
    duration_seconds = int(compute_planet_research_time(planet_id, tech_key, target, conn))

    metal = float(planet.get("metal") or 0)
    crystal = float(planet.get("crystal") or 0)
    missing_resources: List[Dict[str, Any]] = []
    if metal < cost_m:
        missing_resources.append(
            {
                "resource_key": "metal",
                "label_key": "resource_metal",
                "have": int(metal),
                "need": int(cost_m),
                "deficit": int(cost_m - metal),
            }
        )
    if crystal < cost_c:
        missing_resources.append(
            {
                "resource_key": "crystal",
                "label_key": "resource_crystal",
                "have": int(crystal),
                "need": int(cost_c),
                "deficit": int(cost_c - crystal),
            }
        )
    can_afford = not missing_resources

    unavailable_reason_key: Optional[str] = None
    can_start = False
    if tech.get("is_active"):
        unavailable_reason_key = "already_running"
    elif not tech.get("requirements_met"):
        unavailable_reason_key = "research_locked"
    elif tech.get("choice_group") and not tech.get("choice_made"):
        unavailable_reason_key = "choice_required"
    elif target > max_level:
        unavailable_reason_key = "max_level"
    elif not queue_has_room:
        unavailable_reason_key = "queue_full"
    elif not can_afford:
        unavailable_reason_key = "not_enough_resources"
    else:
        can_start = True

    return {
        "tech_key": tech_key,
        "icon": planet_research_icon(tech_key, cfg.get("category")),
        "icon_fallback": planet_research_icon_fallback(tech_key, cfg.get("category")),
        "label_key": tech.get("label_key") or tech_key,
        "unlock_key": tech.get("description_key") or cfg.get("description_key"),
        "tier": tech.get("tier"),
        "target_level": target,
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
        "duration_seconds": duration_seconds,
        "can_afford": can_afford,
        "can_start": can_start,
        "missing_resources": missing_resources,
        "unavailable_reason_key": unavailable_reason_key,
        "requirements_met": bool(tech.get("requirements_met")),
        "missing_human": humanize_requirements(
            tech.get("missing_requirements") or [],
            planet_level=planet_level,
        ),
        "choice_group": tech.get("choice_group"),
        "choice_options": tech.get("choice_options"),
        "choice_made": tech.get("choice_made"),
    }


def _attach_queue_job_to_pe_card(card: Dict[str, Any], jobs_by_key: Mapping[str, Any]) -> None:
    from ..queue_card import card_queue_job_for_item

    tech_key = str(card.get("tech_key") or "")
    qj = card_queue_job_for_item(jobs_by_key, tech_key) if tech_key else None
    if qj:
        card["queue_job"] = dict(qj)
    elif "queue_job" in card:
        del card["queue_job"]


def _research_ux(
    research_status: Dict[str, Any],
    planet_level: int,
    *,
    planet_id: int,
    planet: Dict[str, Any],
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    now = time.time()
    queue = research_status.get("queue") or []
    techs = research_status.get("techs") or []
    queue_limit = int(research_status.get("queue_limit") or 2)
    queue_count = len(queue)

    from ..queue_card import group_card_jobs_by_owner_key, map_planet_research_queue_to_card_jobs

    card_jobs_by_owner = research_status.get("card_jobs_by_owner")
    if not isinstance(card_jobs_by_owner, dict):
        card_jobs = map_planet_research_queue_to_card_jobs(research_status, now=now)
        card_jobs_by_owner = group_card_jobs_by_owner_key(card_jobs)

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
                "icon": planet_research_icon(tech_key, cfg.get("category")),
                "icon_fallback": planet_research_icon_fallback(tech_key, cfg.get("category")),
                "label_key": cfg.get("label_key") or tech_key,
                "unlock_key": cfg.get("description_key"),
                "progress_pct": int(round(100.0 * elapsed / span)),
                "seconds_remaining": max(0, int(finish - now)),
                "start_at": start,
                "finish_at": finish,
                "total_seconds": int(span),
            }
        )

    queue_cards: List[Dict[str, Any]] = []
    recommended: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []
    queue_has_room = queue_count < queue_limit
    seen_queue_keys: set[str] = set()

    for tech in techs:
        tech_key = str(tech.get("tech_key") or "")
        cfg = get_research_def(tech_key) or {}
        level = int(tech.get("level") or 0)
        max_level = int(tech.get("max_level") or 1)
        q_count = int(tech.get("queue_count") or 0)

        card = _enrich_research_card(
            tech=tech,
            cfg=cfg,
            planet_id=planet_id,
            planet=planet,
            planet_level=planet_level,
            queue_has_room=queue_has_room,
            conn=conn,
        )
        _attach_queue_job_to_pe_card(card, card_jobs_by_owner)

        if (tech.get("is_active") or q_count > 0) and tech_key not in seen_queue_keys:
            queue_cards.append(card)
            seen_queue_keys.add(tech_key)
            continue

        if level >= max_level or tech.get("is_active"):
            continue

        if tech.get("requirements_met") and len(recommended) < 3:
            recommended.append(card)
        elif not tech.get("requirements_met") and len(locked) < 6:
            locked.append(card)

    return {
        "active": active,
        "queue_cards": queue_cards,
        "recommended": recommended,
        "locked": locked,
        "queue_count": queue_count,
        "queue_limit": queue_limit,
        "queue_has_room": queue_has_room,
        "card_jobs_by_owner": card_jobs_by_owner,
    }


def _ascension_ux(planet_id: int, *, conn: sqlite3.Connection) -> Dict[str, Any]:
    return get_ascension_status(planet_id, conn=conn)


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
    establishment: Optional[Dict[str, Any]] = None,
    expansion_unlock: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    def _cta(
        *,
        priority: str,
        title_key: str,
        body_key: str,
        cta_label_key: str,
        cta_target: str,
        cta_action: str = "focus",
        cta_highlight: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        return {
            "priority": priority,
            "title_key": title_key,
            "body_key": body_key,
            "cta_label_key": cta_label_key,
            "cta_target": cta_target,
            "cta_action": cta_action,
            "cta_highlight": cta_highlight,
            **extra,
        }

    if active_event:
        return _cta(
            priority="event",
            title_key="pe_action_event_title",
            body_key="pe_action_event_body",
            cta_label_key="pe_action_event_cta",
            cta_target="events",
            cta_action="focus_tab",
            cta_highlight="pe-event-decision",
            event_label_key=active_event.get("label_key"),
        )

    if establishment and establishment.get("visible") and not establishment.get("complete"):
        unmet = [
            m
            for m in (establishment.get("milestones") or [])
            if not m.get("met") and m.get("required", True)
        ]
        first = unmet[0] if unmet else None
        return _cta(
            priority="establishment",
            title_key="pe_action_establishment_title",
            body_key="pe_action_establishment_body",
            cta_label_key="pe_action_establishment_cta",
            cta_target="establishment",
            cta_action="focus_section",
            cta_highlight="pe-section-establishment",
            milestone_label_key=str(first.get("label_key") or "") if first else "",
            met_count=int(establishment.get("met_count") or 0),
            required_count=int(establishment.get("required_count") or 0),
        )

    if bool(planet.get("is_homeworld")) and expansion_unlock:
        checklist = expansion_unlock.get("launch_checklist") or {}
        items = {str(i.get("key") or ""): i for i in (checklist.get("items") or [])}
        if items.get("interstellar_expansion") and not items["interstellar_expansion"].get("met"):
            return _cta(
                priority="expansion_research",
                title_key="pe_action_expansion_research_title",
                body_key="pe_action_expansion_research_body",
                cta_label_key="pe_action_expansion_research_cta",
                cta_target="research",
                cta_action="navigate",
                cta_highlight="research",
                tech_key="interstellar_expansion",
            )
        if items.get("genesis_ark_level") and not items["genesis_ark_level"].get("met"):
            return _cta(
                priority="expansion_progression",
                title_key="pe_action_expansion_progress_title",
                body_key="pe_action_expansion_progress_body",
                cta_label_key="pe_action_expansion_progress_cta",
                cta_target="progression",
                cta_action="focus_section",
                cta_highlight="pe-section-expansion-gate",
            )
        if checklist.get("can_launch"):
            return _cta(
                priority="expansion_ready",
                title_key="pe_colonize_new_world_cta",
                body_key="pe_colonize_new_world_hint",
                cta_label_key="pe_colonize_new_world_cta",
                cta_target="command_map",
                cta_action="navigate",
                cta_href="/galaxy?view=command_map&action=colonize",
                cta_highlight="pe-section-expansion-gate",
            )
        if items.get("seed_ark") and not items["seed_ark"].get("met"):
            return _cta(
                priority="expansion_seed_ark",
                title_key="pe_action_expansion_seed_ark_title",
                body_key="pe_action_expansion_seed_ark_body",
                cta_label_key="pe_action_expansion_seed_ark_cta",
                cta_target="fleet",
                cta_action="navigate",
                cta_highlight="fleet",
            )

    if planet.get("failure_state"):
        return _cta(
            priority="crisis",
            title_key="pe_action_crisis_title",
            body_key="pe_action_crisis_body",
            cta_label_key="pe_action_crisis_cta",
            cta_target="events",
            cta_action="focus_tab",
            cta_highlight="pe-event-decision",
        )

    if not planet.get("specialization_key") and level >= SPECIALIZATION_UNLOCK_LEVEL and eligible_specs:
        return _cta(
            priority="specialization",
            title_key="pe_action_spec_title",
            body_key="pe_action_spec_body",
            cta_label_key="pe_action_spec_cta",
            cta_target="specialization",
            cta_action="focus_section",
            cta_highlight="pe-spec-picker",
        )

    if level < SPECIALIZATION_UNLOCK_LEVEL and not planet.get("specialization_key"):
        return _cta(
            priority="progression",
            title_key="pe_action_spec_soon_title",
            body_key="pe_action_spec_soon_body",
            cta_label_key="pe_action_progression_cta",
            cta_target="progression",
            cta_action="focus_section",
            cta_highlight="pe-section-progression",
            unlock_level=SPECIALIZATION_UNLOCK_LEVEL,
        )

    rec = research_ux.get("recommended") or []
    if rec and research_ux.get("queue_has_room"):
        first = rec[0]
        tech_key = str(first.get("tech_key") or "")
        return _cta(
            priority="research",
            title_key="pe_action_research_title",
            body_key="pe_action_research_body",
            cta_label_key="pe_action_research_cta",
            cta_target="research",
            cta_action="focus_tab",
            cta_highlight=f"pe-research-card-{tech_key}" if tech_key else "pe-section-research",
            tech_key=tech_key,
            tech_label_key=first.get("label_key"),
        )

    if research_ux.get("active"):
        job = research_ux["active"][0]
        tech_key = str(job.get("tech_key") or "")
        return _cta(
            priority="research_running",
            title_key="pe_action_research_running_title",
            body_key="pe_action_research_running_body",
            cta_label_key="pe_action_research_running_cta",
            cta_target="research",
            cta_action="focus_tab",
            cta_highlight="pe-planet-research-active",
            tech_label_key=job.get("label_key"),
            progress_pct=job.get("progress_pct"),
        )

    deficits = mechanics.get("import_deficits") or []
    if deficits:
        return _cta(
            priority="economy",
            title_key="pe_action_economy_title",
            body_key="pe_action_economy_body",
            cta_label_key="pe_action_economy_cta",
            cta_target="economy",
            cta_action="focus_section",
            cta_highlight="pe-section-economy",
        )

    if any(w.get("key") == "stability" for w in warnings):
        return _cta(
            priority="stability",
            title_key="pe_action_stability_title",
            body_key="pe_action_stability_body",
            cta_label_key="pe_action_stability_cta",
            cta_target="policies",
            cta_action="focus_tab",
            cta_highlight="pe-section-policies",
        )

    return _cta(
        priority="explore",
        title_key="pe_action_explore_title",
        body_key="pe_action_explore_body",
        cta_label_key="pe_action_explore_cta",
        cta_target="traits",
        cta_action="focus_section",
        cta_highlight="pe-section-traits",
    )


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


def build_identity_teaser(
    *,
    planet: Dict[str, Any],
    eligible_specs: List[str],
    xp_pct: int = 0,
    planet_score: int = 0,
) -> Dict[str, Any]:
    """Compact identity progress payload for Overview widget and PE banners."""
    level = int(planet.get("planet_level") or 1)
    spec_key = planet.get("specialization_key")
    spec_tier = int(planet.get("specialization_tier") or 0)
    unlock = SPECIALIZATION_UNLOCK_LEVEL

    if not spec_key and level < IDENTITY_TEASER_MIN_LEVEL:
        return {"visible": False}

    if spec_key:
        status = "active"
        title_key = "pe_identity_teaser_active_title"
        body_key = "pe_identity_teaser_active_body"
        cta_label_key = "pe_identity_teaser_view_cta"
    elif level >= unlock:
        if eligible_specs:
            status = "ready"
            title_key = "pe_identity_teaser_ready_title"
            body_key = "pe_identity_teaser_ready_body"
            cta_label_key = "pe_identity_teaser_pick_cta"
        else:
            status = "waiting"
            title_key = "pe_identity_teaser_waiting_title"
            body_key = "pe_identity_teaser_waiting_body"
            cta_label_key = "pe_identity_teaser_view_cta"
    else:
        status = "countdown"
        title_key = "pe_identity_teaser_countdown_title"
        body_key = "pe_identity_teaser_countdown_body"
        cta_label_key = "pe_identity_teaser_view_cta"

    levels_remaining = max(0, unlock - level)
    progress_to_unlock_pct = min(100, int(round(100.0 * level / max(1, unlock)))) if level < unlock else 100

    next_unlock_level = None
    next_unlock_label_key = None
    for unlock_level in sorted(LEVEL_UNLOCKS.keys()):
        if unlock_level <= level:
            continue
        next_unlock_level = unlock_level
        next_unlock_label_key = level_unlock_label_key(unlock_level, LEVEL_UNLOCKS[unlock_level])
        break

    return {
        "visible": True,
        "status": status,
        "title_key": title_key,
        "body_key": body_key,
        "cta_label_key": cta_label_key,
        "planet_level": level,
        "max_level": MAX_PLANET_LEVEL,
        "unlock_level": unlock,
        "levels_remaining": levels_remaining,
        "progress_to_unlock_pct": progress_to_unlock_pct,
        "xp_pct": int(xp_pct),
        "planet_score": int(planet_score),
        "spec_key": spec_key,
        "spec_label_key": f"spec_{spec_key}" if spec_key else None,
        "spec_tier": spec_tier,
        "eligible_count": len(eligible_specs or []),
        "next_unlock_level": next_unlock_level,
        "next_unlock_label_key": next_unlock_label_key,
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
    raw_level = planet.get("planet_level")
    level = int(raw_level) if raw_level is not None else 1
    xp = int(planet.get("planet_xp") or 0)
    next_threshold = xp_threshold_for_level(level + 1) if level < MAX_PLANET_LEVEL else xp
    prev_threshold = xp_threshold_for_level(level)
    xp_in_level = max(0, xp - prev_threshold)
    xp_span = max(1, next_threshold - prev_threshold)
    rarity = str(dna.get("rarity_tier") or "common")

    eligible = list(eligible_specializations or [])
    research_ux = _research_ux(research, level, planet_id=planet_id, planet=planet, conn=conn)

    expansion_unlock: Dict[str, Any] = {"visible": False}
    establishment: Dict[str, Any] = {"visible": False}
    expansion_lifecycle: Dict[str, Any] = {}
    player_id = int(planet.get("player_id") or 0)
    is_homeworld = bool(planet.get("is_homeworld"))
    if player_id:
        expansion_unlock = build_expansion_unlock_block(
            player_id,
            conn=conn,
            viewing_homeworld=is_homeworld,
        )
        if not is_homeworld:
            from .expansion_phase import resolve_expansion_phase

            resolved = resolve_expansion_phase(
                player_id=player_id,
                planet_id=int(planet_id),
                conn=conn,
            )
            expansion_lifecycle = {
                "phase": str(resolved.get("phase") or ""),
                "phase_label_key": str(resolved.get("phase_label_key") or ""),
                "is_outpost": bool(resolved.get("is_outpost")),
                "is_colony": bool(resolved.get("is_colony")),
            }
            if bool(resolved.get("is_outpost")):
                milestones = list(resolved.get("requirements") or [])
                required = [m for m in milestones if m.get("required", True)]
                met = sum(1 for m in required if m.get("met"))
                establishment = {
                    "visible": True,
                    "phase_label_key": str(resolved.get("phase_label_key") or ""),
                    "milestones": milestones,
                    "complete": bool(resolved.get("is_colony")),
                    "met_count": int(met),
                    "required_count": len(required),
                }

    warnings = _warnings(planet, culture, mechanics, active_event)
    if establishment.get("visible") and not establishment.get("complete"):
        warnings.insert(
            0,
            {
                "key": "establishment",
                "label_key": "pe_warn_establishment",
                "body_key": "pe_warn_establishment_body",
                "severity": "warn",
                "action_target": "establishment",
            },
        )
    status = _planet_status(planet, culture, warnings)
    economy = _economy_flow(planet_id, mechanics, conn)

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM planet_events WHERE planet_id = ? AND state IN ('pending','active');",
        (int(planet_id),),
    )
    open_events = int(cur.fetchone()["c"])

    dna_hidden = int(reveal or 0) <= 0 and not is_homeworld and bool(
        str(planet.get("world_key") or planet.get("origin_world_key") or "").strip()
    )

    return {
        "header": {
            "xp_in_level": xp_in_level,
            "xp_span": xp_span,
            "xp_pct": _pct(xp_in_level, xp_span),
            "xp_remaining": max(0, xp_span - xp_in_level),
            "stability": float(culture.get("stability") or 0),
            "loyalty": float(culture.get("loyalty") or 0),
            "is_homeworld": is_homeworld,
            "is_outpost": bool(establishment.get("visible")),
            "dna_hidden": bool(dna_hidden),
            "rarity": rarity if not dna_hidden else "unknown",
            "rarity_label_key": f"pe_rarity_{rarity}" if not dna_hidden else "pe_dna_unknown",
            "status": status,
            "planet_class_label_key": (
                planet_class_label_key(planet.get("planet_class") or "terrestrial")
                if not dna_hidden
                else "pe_world_class_unknown"
            ),
            "level_label_key": (
                "pe_development_stage_outpost"
                if bool(establishment.get("visible"))
                else "pe_development_stage"
            ),
        },
        "location": _planet_location_display(planet),
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
        "ascension_ux": _ascension_ux(planet_id, conn=conn),
        "spec_recommendations": _spec_recommendations(eligible, dna, reveal, conn, planet_id),
        "next_action": _next_action(
            planet=planet,
            level=level,
            active_event=active_event,
            eligible_specs=eligible,
            research_ux=research_ux,
            warnings=warnings,
            mechanics=mechanics,
            establishment=establishment,
            expansion_unlock=expansion_unlock,
        ),
        "policies_active": _policy_rows(planet_id, conn),
        "policy_ux": _policy_ux(planet_id, planet=planet, culture=culture, conn=conn),
        "policy_slots_max": _policy_slots_max(level),
        "warnings": warnings,
        "events_feed": _events_feed(planet_id, conn),
        "open_events_count": open_events,
        "history": get_history(planet_id, limit=20, conn=conn),
        "identity_teaser": build_identity_teaser(
            planet=planet,
            eligible_specs=eligible,
            xp_pct=_pct(xp_in_level, xp_span),
            planet_score=compute_single_planet_score(planet_id, conn=conn),
        ),
        "expansion_unlock": expansion_unlock,
        "establishment": establishment,
        "expansion_lifecycle": expansion_lifecycle,
        "dna_reveal_tier": int(reveal),
        "activity_xp": get_activity_xp_dashboard(
            int(player_id),
            int(planet_id),
            conn=conn,
        ) if player_id else {"visible": False},
    }
