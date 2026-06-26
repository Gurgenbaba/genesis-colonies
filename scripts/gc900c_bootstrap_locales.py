#!/usr/bin/env python3
"""GC-900C: Bootstrap complete locale files from de.json key set + en.json values."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

NEW_LOCALES = ("fr", "es", "pl", "tr", "ru", "pt")

# Missing EN keys whose DE source contains German — hand-translated for Phase 1.
EN_BACKFILL: dict[str, str] = {
    "admin_section_start_values": "Starting values for new players",
    "event_forge_reactor_overload": "Reactor overload",
    "event_smuggler_raid": "Authority raid",
    "event_trade_disruption": "Trade disruption",
    "galaxy_sector_overview": "Sector overview",
    "header_next_cost": "Next costs",
    "open_research": "→ Open research",
    "overview_label_score_buildings": "Buildings",
    "overview_warning_vote_available": "Vote available — claim your reward.",
    "pe_archetype_militarized_society": "Militarized society",
    "pe_cat_atmosphere": "Atmosphere",
    "pe_culture_crime": "Crime",
    "pe_culture_loyalty": "Loyalty",
    "pe_culture_stability": "Stability",
    "pe_event_decision_hint": "Your decision changes production, stability, or future events.",
    "pe_next_research": "Next research (locked)",
    "pe_orbital_t2": "Zero-G foundry",
    "pe_pick_spec": "Choose specialization (permanent)",
    "pe_policy_cooldown": "Slot on cooldown — switch available again soon.",
    "pe_rarity_common": "Common",
    "pe_rarity_legendary": "Legendary",
    "pe_rarity_uncommon": "Uncommon",
    "pe_req_building": "Requires building %(building)s (level %(need)s)",
    "pe_req_imperial_research": "Requires empire research %(tech_key)s (level %(need)s)",
    "pe_req_locked_choice": "Requires a previous permanent decision",
    "pe_req_planet_research": "Requires %(tech_label_key)s (level %(need)s)",
    "pe_req_spec": "Requires specialization",
    "pe_req_traits_any": "Requires a matching planet trait",
    "pe_req_unknown": "Requirement not met",
    "pe_spec_active_desc": "This permanent direction shapes production, events, and policy on this planet.",
    "pe_spec_empty": "Choose a permanent specialization to shape the planet.",
    "pe_spec_identity_ai_controlled_world": "This planet is run by automation — efficiency over loyalty.",
    "pe_spec_identity_deep_mining_colony": "This planet drains the core — raw Ferronite at industrial scale.",
    "pe_spec_identity_industrial_megacity": "This planet is an industrial megacity — conversion and output above all.",
    "pe_spec_identity_science_nexus": "This planet becomes a knowledge hub — research, breakthroughs, and experimental risk define everything.",
    "pe_spec_identity_smuggler_colony": "This planet lives in the shadows — smuggling, crime, and high profits.",
    "pe_spec_identity_trade_hub": "This planet becomes a trade hub — routes and markets drive prosperity.",
    "pe_spec_lock_affinity": "DNA affinity too weak",
    "pe_spec_needs_import": "Requires import:",
    "pe_spec_next_tier": "Next tier",
    "pe_spec_section": "Planet identity",
    "pe_spec_t1_ai_controlled_world": "Auto-conversion — machines take over production.",
    "pe_spec_t1_fortress_planet": "Phase crystal export — military baseline supply.",
    "pe_spec_t1_industrial_megacity": "Extra conversion queue — mass processing.",
    "pe_spec_t2_ai_controlled_world": "Loyalty bypass — efficiency without consent.",
    "pe_spec_t2_deep_mining_colony": "Bulk export — raw materials for the empire.",
    "pe_spec_t2_smuggler_colony": "Crime sweet spot — maximum smuggling profit.",
    "pe_spec_t2_trade_hub": "More routes at once — the trade empire grows.",
    "pe_spec_t3_ai_controlled_world": "AI runaway risk — powerful and dangerous.",
    "pe_spec_t3_forge_world": "Mandatory overtime policy — maximum output, higher risk.",
    "pe_spec_t3_fortress_planet": "Defense mechanic — survive sieges.",
    "pe_spec_t3_industrial_megacity": "Stability risk — output vs. control.",
    "pe_spec_t3_science_nexus": "Experimental research — highest potential, highest risk.",
    "pe_spec_t3_smuggler_colony": "Smuggler events — authority vs. black market.",
    "pe_spec_t3_trade_hub": "Market fee mechanic — economic control.",
    "pe_spec_tagline_fortress_planet": "Fortress world — defense and military production.",
    "pe_spec_tagline_science_nexus": "Research world — knowledge, breakthroughs, experiments.",
    "pe_spec_tagline_trade_hub": "Trade hub — routes, markets, prosperity.",
    "pe_spec_tier_title_1": "Tier 1 — core identity",
    "pe_spec_why_generic": "Strong focus for this planet.",
    "pe_stat_industrial": "Industrial capacity",
    "pe_stat_population": "Population",
    "pe_trait_risk_events": "Risk: more frequent crisis events",
    "pe_trait_tooltip": "Planet traits shape research, events, and specializations.",
    "pe_unlock_conversion_queue": "Extra conversion queue",
    "pe_unlock_crime_sweet_spot": "Crime sweet spot for smuggling",
    "pe_unlock_discovery_bonus": "Higher discovery chance",
    "pe_unlock_dna_2": "All DNA traits revealed",
    "pe_unlock_generic": "New opportunity",
    "pe_unlock_loyalty_bypass": "Loyalty mechanic bypassed",
    "pe_unlock_market_fee": "Market fee mechanic",
    "pe_unlock_policy_mandatory_overtime": "Policy: mandatory overtime",
    "pe_unlock_spec_risk": "Increased risk event",
    "pe_unlock_specialization": "Specialization selectable",
    "pe_unlock_stability_risk": "High output, stability risk",
    "pe_warn_crime": "High crime",
    "pe_warn_crime_body": "Loyalty and trade suffer under high crime.",
    "pe_warn_energy_body": "Industrial draw exceeds baseline — overload events possible.",
    "pe_warn_stability_body": "Without countermeasures, rebellion and event risk rise.",
    "pe_xp_tooltip": "Development points from research, events, and planet activity.",
    "policy_mandatory_overtime": "Mandatory overtime",
    "research_panel_active_hint": "Monitor active projects and start new technologies.",
    "research_req_hint": "Progress needs requirements: lab, buildings, or tech level.",
    "tech_cryogenic_drive_desc": "More thrust, fewer losses — especially for large fleets.",
    "tech_hyperspace_navigation_desc": "Shortens flight times through better jump vectors and route calculation.",
    "tech_metal_refining_desc": "Increases Ferronite production by 10% per level through better processes.",
    "tech_shield_tech_desc": "Tougher shields through stronger fields, modulation, and amplifiers.",
    "tech_storage_desc": "Increases storage capacity through compression, stabilization, and logistics.",
    "tech_weapon_tech_desc": "Increases fleet firepower through modern energy and projectile systems.",
    "trait_aetherion_storms": "Aetherion storms",
    "trait_cryogenic_atmosphere": "Cryogenic atmosphere",
    "trait_dark_matter_residue": "Dark matter residue",
}

LANGUAGE_NAMES: dict[str, dict[str, str]] = {
    "de": {
        "de": "Deutsch",
        "en": "Englisch",
        "fr": "Französisch",
        "es": "Spanisch",
        "pl": "Polnisch",
        "tr": "Türkisch",
        "ru": "Russisch",
        "pt": "Portugiesisch",
    },
    "en": {
        "de": "German",
        "en": "English",
        "fr": "French",
        "es": "Spanish",
        "pl": "Polish",
        "tr": "Turkish",
        "ru": "Russian",
        "pt": "Portuguese",
    },
    "fr": {
        "de": "Allemand",
        "en": "Anglais",
        "fr": "Français",
        "es": "Espagnol",
        "pl": "Polonais",
        "tr": "Turc",
        "ru": "Russe",
        "pt": "Portugais",
    },
    "es": {
        "de": "Alemán",
        "en": "Inglés",
        "fr": "Francés",
        "es": "Español",
        "pl": "Polaco",
        "tr": "Turco",
        "ru": "Ruso",
        "pt": "Portugués",
    },
    "pl": {
        "de": "Niemiecki",
        "en": "Angielski",
        "fr": "Francuski",
        "es": "Hiszpański",
        "pl": "Polski",
        "tr": "Turecki",
        "ru": "Rosyjski",
        "pt": "Portugalski",
    },
    "tr": {
        "de": "Almanca",
        "en": "İngilizce",
        "fr": "Fransızca",
        "es": "İspanyolca",
        "pl": "Lehçe",
        "tr": "Türkçe",
        "ru": "Rusça",
        "pt": "Portekizce",
    },
    "ru": {
        "de": "Немецкий",
        "en": "Английский",
        "fr": "Французский",
        "es": "Испанский",
        "pl": "Польский",
        "tr": "Турецкий",
        "ru": "Русский",
        "pt": "Португальский",
    },
    "pt": {
        "de": "Alemão",
        "en": "Inglês",
        "fr": "Francês",
        "es": "Espanhol",
        "pl": "Polonês",
        "tr": "Turco",
        "ru": "Russo",
        "pt": "Português",
    },
}

_GERMAN_CHARS = re.compile(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]")
_FERRONIT = re.compile(r"Ferronit(?!e)")
_FERRONIT_LOWER = re.compile(r"ferronit(?!e)")


def _load(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _canon_en(text: str) -> str:
    out = text.replace("Ferronitee", "Ferronite").replace("ferronitee", "ferronite")
    out = _FERRONIT.sub("Ferronite", out)
    out = _FERRONIT_LOWER.sub("ferronite", out)
    out = out.replace("Roh-Ferronit", "Raw Ferronite").replace("Abbau-Pfad", "Extraction Path")
    return out


def _resolve_en_value(key: str, de: dict[str, str], en: dict[str, str]) -> str:
    if key in en:
        return en[key]
    if key in EN_BACKFILL:
        return EN_BACKFILL[key]
    raw = de.get(key, key)
    if _GERMAN_CHARS.search(raw):
        raise KeyError(f"Missing EN translation for German DE value: {key}")
    return _canon_en(raw)


def _ordered_keys(de: dict[str, str], en: dict[str, str]) -> list[str]:
    de_keys = list(de.keys())
    extra = sorted(set(en) - set(de))
    return de_keys + extra


def _write_locale(path: Path, data: dict[str, str], key_order: list[str]) -> None:
    ordered = {k: data[k] for k in key_order if k in data}
    for k in sorted(data):
        if k not in ordered:
            ordered[k] = data[k]
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inject_language_names(data: dict[str, str], locale: str) -> None:
    names = LANGUAGE_NAMES.get(locale, LANGUAGE_NAMES["en"])
    for code, label in names.items():
        data[f"language_name_{code}"] = label


def build_complete_en(de: dict[str, str], en: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _ordered_keys(de, en):
        val = _resolve_en_value(key, de, en)
        out[key] = _canon_en(val)
    _inject_language_names(out, "en")
    return out


def main() -> int:
    de = _load(LOCALES / "de.json")
    en_raw = _load(LOCALES / "en.json")
    complete_en = build_complete_en(de, en_raw)
    key_order = _ordered_keys(de, complete_en)
    _write_locale(LOCALES / "en.json", complete_en, key_order)
    print(f"en.json: {len(complete_en)} keys")

    for loc in NEW_LOCALES:
        data = dict(complete_en)
        _inject_language_names(data, loc)
        _write_locale(LOCALES / f"{loc}.json", data, key_order)
        print(f"{loc}.json: {len(data)} keys (EN base)")

    de_out = dict(de)
    _inject_language_names(de_out, "de")
    _write_locale(LOCALES / "de.json", de_out, list(de.keys()))
    print(f"de.json: language names updated")

    for loc in ("de", "en", *NEW_LOCALES):
        d = _load(LOCALES / f"{loc}.json")
        missing = set(de) - set(d)
        if missing:
            print(f"ERROR: {loc}.json missing {len(missing)} keys", file=sys.stderr)
            return 1
    print("GC-900C bootstrap OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
