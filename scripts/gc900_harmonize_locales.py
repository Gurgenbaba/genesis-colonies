#!/usr/bin/env python3
"""GC-900: Apply terminology harmonization to locale JSON files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

# Player-facing EN strings that were still German (Phase 7).
EN_OVERRIDES: dict[str, str] = {
    "admin_btn_apply_resources": "Apply resources (ignore storage cap)",
    "admin_resources_hint": "Distribute resources directly. Storage caps are ignored (overflow allowed). Empty player ID = you · set player ID = that player · “All” ignores player ID.",
    "admin_section_resources_tools": "Resource tools (overflow)",
    "admin_section_wipe": "Reset universe (wipe)",
    "admin_wipe_confirm": "I understand: this wipe is permanent.",
    "admin_wipe_execute": "Run wipe",
    "admin_wipe_hint": "Deletes planets, queues, and fleets. Accounts remain. Homeworlds are recreated.",
    "admin_wipe_research": "Reset research levels",
    "admin_wipe_resources": "Reset resources to starting values",
    "alliance_dip_board_sub": "Internal forum / message board for strategy and announcements",
    "alliance_dip_board_title": "Alliance board",
    "alliance_dip_broadcast_sub": "Alliance-wide orders and announcements",
    "alliance_dip_matrix_sub": "Manage alliances, NAPs, and war declarations",
    "alliance_diplomacy_hint": "Interface for alliances, wars, and internal commander communication.",
    "alliance_feature_economy_sub": "Shared resource pools and bonuses",
    "alliance_feature_economy_title": "Alliance economy",
    "alliance_feature_identity_title": "Alliance identity",
    "alliance_feature_members_sub": "Ranks, permissions, join requests, and kicks",
    "alliance_hint": "Alliances, communication, and future cluster warfare.",
    "alliance_note_diplomacy": "Currently disabled — alliance and diplomacy features unlock in a later development step once fleets and combat logic are live.",
    "alliance_note_own": "In a future update you can found and manage alliances here as alliance commander. Until then this page is a UI prototype.",
    "alliance_pill_create": "Found alliance",
    "alliance_pill_events": "Alliance events",
    "alliance_placeholder_intro": "Planned core features for your alliance:",
    "alliance_status_hint": "Everything about your alliance will be bundled here later.",
    "alliance_status_title": "Alliance status",
    "auth_back_to": "Back to",
    "buildings_tabs": "Building categories",
    "close": "Close",
    "defense_panel_mechanics_subtitle": "Defense will later tie directly into radar, fleets, and combat reports.",
    "defense_panel_mechanics_title": "Upcoming mechanics",
    "defense_panel_planetary_subtitle": "This area will become the control hub for defense structures — from light lasers to heavy orbital batteries.",
    "defense_planned_item_build_buttons": "Build and upgrade buttons for lasers, missiles, shields, and turrets",
    "defense_planned_item_overview": "Overview of all defense structures per colony",
    "defense_planned_item_power_score": "Compact estimate of total defensive strength (score / bar)",
    "defense_roadmap_repair": "Possible auto-repair after battles (depends on research)",
    "defense_roadmap_reports": "Links to combat reports and fleet log view",
    "defense_roadmap_synergy": "Synergies with shield generator and radar array (early warning and bonus values)",
    "defense_tag_turrets": "Turrets",
    "desc_pe_industry_t1_automation": "Unlocks the conversion queue.",
    "desc_pe_industry_t2_mining_path": "Orbital extraction or deep core — permanent choice.",
    "desc_pe_industry_t3_mantle": "Production chain: Mantle Alloy (deep core).",
    "desc_pe_industry_t3_orbital": "Production chain: Refined Ferronite (orbital).",
    "desc_pe_industry_t4_foundry": "Larger conversion batches.",
    "desc_pe_industry_t5_overdrive": "Overdrive policy — increased reactor risk.",
    "desc_tech_cryogenic_drive": "More thrust, fewer losses — especially for large fleets.",
    "desc_tech_energy_efficiency": "Optimizes systems and reduces mine energy use by 5% per level.",
    "desc_tech_hyperspace_navigation": "Shortens flight times through better jump vectors and route calculation.",
    "desc_tech_shield_tech": "Tougher shields through stronger fields, modulation, and amplifiers.",
    "desc_tech_storage": "Increases storage capacity through compression, stabilization, and logistics.",
    "desc_tech_weapon_tech": "Increases fleet firepower through modern energy and projectile systems.",
    "landing_feature_tech_text": "Research unlocks new buildings, ships, and bonuses.",
    "landing_footnote": "Free to play · Browser game · Your colony keeps working while you are offline",
    "landing_step_1": "Build a Ferronite mine and solar collectors",
    "landing_step_3": "Level up storage and plan your next upgrade",
    "login_btn_loading": "Checking access…",
    "login_footer_back": "Back to homepage",
    "login_hint_no_reset": "Keep your login details safe — there is currently no password reset system.",
    "login_subtitle": "Sign in with your commander account and take the helm of your colony again.",
    "msg_upgrade_fail_resources": "Not enough resources: need %(metal)s more Ferronite and %(crystal)s more Crytite.",
    "pe_choice_deep_core": "Deep core extraction",
    "pe_choice_orbital_mining": "Orbital extraction",
    "pe_confirm_choice": "This choice is permanent and cannot be undone.",
    "pe_event_choice_contain": "Contain",
    "pe_event_choice_fight": "Fight",
    "pe_event_choice_fortify": "Fortify",
    "pe_event_choice_overload": "Overload",
    "pe_event_choice_publish": "Publish",
    "pe_event_choice_push": "Push through",
    "pe_legacy_ai_incident_resolved": "AI incident resolved",
    "pe_legacy_quantum_breach_survived": "Survived quantum breach",
    "pe_legacy_siege_survived": "Survived siege",
    "pe_legacy_survived_raid": "Survived raid",
    "pe_legacy_survived_reactor_overload": "Survived reactor overload",
    "pe_legacy_survived_rebellion": "Survived rebellion",
    "pe_legacy_trade_disruption_handled": "Trade disruption handled",
    "pe_load_error_title": "Planet data unavailable",
    "pe_no_events": "Quiet phase for now — use the time to build up.",
    "pe_reason_cannot_upgrade": "Upgrade not available right now.",
    "pe_reason_invalid_payload": "Invalid request.",
    "pe_reason_missing_spec_key": "No specialization selected.",
    "pe_reason_missing_tech_key": "No research selected.",
    "pe_reason_no_specialization": "No specialization chosen yet.",
    "pe_reason_schema_missing": "Evolution system not installed — run migrations.",
    "pe_reason_slot_too_low": "Policy requires a higher slot.",
    "pe_spec_locked": "From level 8 you can set your planet's identity.",
    "pe_spec_pick_intro": "Choose your planet's permanent future. This decision cannot be undone.",
    "pe_spec_upgrade_need_level": "Requires planet level %s (current: %s)",
    "register_feature_1": "Build your own colony",
    "register_feature_3": "Prepare legendary fleets",
    "register_placeholder_password2": "Enter again to confirm",
    "research_msg_active": "Research is already in progress.",
    "research_msg_no_lab": "You need a research lab first.",
    "research_msg_not_enough": "Not enough resources: need %(metal)s more Ferronite and %(crystal)s more Crytite.",
    "research_msg_requirements": "Requirements are not met yet.",
    "research_msg_unknown": "This research is unknown or unavailable.",
    "resources": "Resources",
    "status_building": "In progress",
    # Planet evolution titles (missing or German in EN)
    "pe_industry_t1_automation": "Industry automation",
    "pe_industry_t2_mining_path": "Choose extraction path",
    "pe_industry_t3_orbital": "Orbital refinery",
    "pe_industry_t3_mantle": "Mantle tapping",
    "pe_industry_t4_foundry": "Mass foundry",
    "pe_industry_t5_overdrive": "Industry overdrive",
    "pe_dev_path": "Planetary focus",
    "pe_dev_path_hint": "Permanent decisions and specializations",
    # Research display names & effects (canon)
    "mining_tech": "Ferronite Refinement",
    "desc_mining_tech": "Increases empire-wide Ferronite production by 10% and Crytite production by 4% per level. Stacks with Drone Optimization.",
    "desc_drone_tech": "Increases Ferronite and Crytite production by 3% per level. Stacks with Ferronite Refinement.",
    "desc_storage_tech": "Increases Ferronite and Crytite storage capacity by 25% per level. Stacks with storage buildings and the Terraformer.",
    "research_effect_metal_prod": "Ferronite production",
    "metal": "Ferronite",
    "resource_metal": "Ferronite",
    "admin_label_metal_delta": "Ferronite delta",
    "admin_label_start_metal": "Starting Ferronite",
    "building_academy": "Genesis Academy",
    "building_barracks": "Orbital Barracks",
    "building_command_center": "Command Center",
    "building_crystal_mine": "Crytite Extractor",
    "building_crystal_storage": "Crytite Silo",
    "building_metal_mine": "Ferronite Mine",
    "building_metal_storage": "Ferronite Depot",
    "building_nanofactory": "Nanofactory",
    "building_radar_array": "Deep-Space Radar Array",
    "building_research_lab": "Research Lab",
    "building_shield_generator": "Planetary Shield Generator",
    "building_solar_plant": "Solar Collector Field",
    "buildings_btn_active": "Active",
    "buildings_techtree_link": "View tech tree",
    "build_queue_title": "Build queue",
    "build_queue_hint": "{count} orders · Next completion: {eta}",
    "build_queue_remaining": "Remaining",
    "build_queue_time": "Build time",
    "build_queue_target": "Target",
    "build_queue_level_short": "L",
    "hud_storage_almost_full": "Storage almost full",
    "hud_storage_full": "Storage full",
    "label_buildings": "Buildings",
    "label_level": "Level",
    "msg_build_not_enough_resources_short": "Not enough Ferronite or Crytite.",
    "btn_research": "Start Research",
    "label_research": "Research",
    "overview_label_score_research": "Research",
    "overview_panel_research_hint": "Active projects and core technologies at a glance.",
    "overview_research_none": "No research active right now.",
    "research_active_header": "Active Research",
    "research_no_active": "No active research.",
    "research_panel_tech_hint": "All core technologies for this colony.",
    "research_msg_error": "An error occurred while starting research.",
    "research_msg_started": "Started research level %(level)s. Remaining: %(seconds)s seconds.",
    "research_msg_started_fmt": "Started research level {level}. Remaining: {seconds} seconds.",
    "desc_tech_construction_optimization": "Reduces building and research times through standard modules and automation.",
    "tech_construction_optimization_desc": "Reduces building and research times through standard modules and automation.",
    "tech_energy_efficiency_desc": "Optimizes systems and reduces mine energy use by 5% per level. The effect scales with every additional research level.",
    "tech_metal_refining": "Ferronite Refinement",
    "tech_weapon_tech": "Weapon Development",
    "tech_armor_tech": "Armor Technology",
    "tech_shield_tech": "Shield Technology",
    "shipyard": "Orbital Shipyard",
    "fleet_shipyard_title": "Orbital Shipyard",
    "nav_shipyard": "Orbital Shipyard",
    "shipyard_btn_queue_full": "Orbital shipyard queue full",
    "defense_panel_planetary_title": "Planetary Defense",
    "pe_spec_tagline_industrial_megacity": "Industrial megacity — conversion and mass output.",
    "pe_unlock_auto_conversion": "Automatic resource conversion",
    "overview_label_colony": "Colony",
    "pe_policy_wrong_archetype": "Does not match this planet's culture.",
    "fleet_mission_hint_recycle_ready": "Debris field: %(metal)s Ferronite, %(crystal)s Crytite — %(ships)s reclaimer(s) assigned.",
    "fleet_preview_debris_amounts": "Ferronite %(metal)s · Crytite %(crystal)s",
    "trader_hub_footer_note": "All transactions are final. Ferronite and Crytite output is limited by storage capacity on the active colony.",
    "exchange_metal_to_fuel_cells": "Ferronite to Fuel Cells",
    "fuel_exchange_hint": "Premium purchase — both Ferronite and Crytite per unit.",
    "pe_legacy_rare_metal_found": "Rare Ferronite vein found",
    "strategic_world_promise_mining_world": "Rich ore veins beneath the crust — a springboard for Ferronite expansion.",
    "strategic_world_reward_mining_world": "+20% Ferronite potential (hint)",
    "desc_tech_metal_refining": "Increases Ferronite production by 10% per level through better processes.",
}

DE_OVERRIDES: dict[str, str] = {
    "pe_industry_t2_mining_path": "Extraktionspfad wählen",
    "desc_pe_industry_t2_mining_path": "Orbitale Extraktion oder Tiefkern — permanente Entscheidung.",
    "pe_choice_orbital_mining": "Orbitale Extraktion",
    "pe_dev_path": "Planetarer Fokus",
    "pe_dev_path_hint": "Permanente Entscheidungen und Spezialisierungen",
    "mining_tech": "Ferronit-Veredelung",
    "desc_mining_tech": "Erhöht die Ferronit-Produktion im Imperium um 10 % und die Crytite-Produktion um 4 % pro Stufe. Stapelt mit Drohnenoptimierung.",
    "desc_drone_tech": "Erhöht Ferronit- und Crytite-Produktion um 3 % pro Stufe. Stapelt mit Ferronit-Veredelung.",
    "desc_storage_tech": "Erhöht Ferronit- und Crytite-Lagerkapazität um 25 % pro Stufe. Stapelt mit Lagergebäuden und Terraformer.",
    "desc_pe_industry_t3_orbital": "Produktionskette: Veredeltes Ferronit (orbital).",
    "shipyard": "Orbitalwerft",
    "fleet_shipyard_title": "Orbitalwerft",
    "nav_shipyard": "Orbitalwerft",
}

EN_GLOBAL_REPLACEMENTS = (
    (re.compile(r"Ferronit(?!e)"), "Ferronite"),
    (re.compile(r"ferronit(?!e)"), "ferronite"),
    (re.compile(r"\bfuel cells\b"), "Fuel Cells"),
)

DE_GLOBAL_REPLACEMENTS = (
    ("Abbau-Pfad", "Extraktionspfad"),
    ("Mining Path", "Extraktionspfad"),
    ("Resource Path", "Extraktionspfad"),
    ("Orbitalabbau", "Orbitale Extraktion"),
)

_GERMAN_CHARS = re.compile(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]")


def _apply_replacements(text: str, pairs: tuple) -> str:
    out = text
    for old, new in pairs:
        if isinstance(old, re.Pattern):
            out = old.sub(new, out)
        else:
            out = out.replace(old, new)
    return out


def _harmonize_file(path: Path, overrides: dict[str, str], global_pairs: tuple) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for key, override in overrides.items():
        if data.get(key) != override:
            data[key] = override
            changed += 1
    for key in list(data.keys()):
        val = data[key]
        if not isinstance(val, str):
            continue
        repaired = val.replace("Ferronitee", "Ferronite").replace("ferronitee", "ferronite")
        new_val = _apply_replacements(repaired, global_pairs)
        if new_val != val:
            data[key] = new_val
            changed += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    en_changed = _harmonize_file(LOCALES / "en.json", EN_OVERRIDES, EN_GLOBAL_REPLACEMENTS)
    de_changed = _harmonize_file(LOCALES / "de.json", DE_OVERRIDES, DE_GLOBAL_REPLACEMENTS)
    print(f"GC-900 harmonize: en.json ~{en_changed} updates, de.json ~{de_changed} updates")

    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    german_left = [k for k, v in en.items() if isinstance(v, str) and _GERMAN_CHARS.search(v)]
    if german_left:
        print(f"WARNING: {len(german_left)} EN keys still contain German characters", file=sys.stderr)
        for k in german_left[:10]:
            print(f"  - {k}", file=sys.stderr)
        return 1
    ferronit_left = [
        k
        for k, v in en.items()
        if isinstance(v, str) and re.search(r"Ferronit(?!e)", v)
    ]
    if ferronit_left:
        print(f"WARNING: {len(ferronit_left)} EN keys still contain 'Ferronit'", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
