"""One-off helper: merge collector offer i18n keys into all locale files."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

UI_EN = {
    "collector_missing_fragments": "Missing fragments",
    "collector_offer_details": "Details",
}

UI_DE = {
    "collector_missing_fragments": "Fehlende Fragmente",
    "collector_offer_details": "Details",
}

OFFERS = {
    "xeno_dna_common_research_booster": {
        "en": ("Research Rush", "Trade common DNA fragments for a short research boost.", "Research Booster (30 min)"),
        "de": ("Forschungs-Schub", "Tausche gewöhnliche DNA-Fragmente gegen einen kurzen Forschungs-Boost.", "Forschungs-Booster (30 Min.)"),
    },
    "xeno_dna_common_research_pct": {
        "en": ("Research Efficiency", "Common DNA for a lasting research speed bonus.", "Research Speed (+2%, 24 h)"),
        "de": ("Forschungs-Effizienz", "Gewöhnliche DNA gegen dauerhaften Forschungs-Tempo-Bonus.", "Forschungs-Tempo (+2 %, 24 h)"),
    },
    "xeno_dna_common_planet_xp": {
        "en": ("Evolution Spark", "Convert common DNA into planet evolution progress.", "Evolution Core (+250 XP)"),
        "de": ("Evolutions-Funken", "Wandle gewöhnliche DNA in Planeten-Evolutions-Fortschritt um.", "Evolutions-Kern (+250 EP)"),
    },
    "xeno_dna_common_dna_capsule": {
        "en": ("DNA Capsule", "Bundle common fragments into a usable DNA core.", "DNA Core"),
        "de": ("DNA-Kapsel", "Bündle gewöhnliche Fragmente zu einem nutzbaren DNA-Kern.", "DNA-Kern"),
    },
    "xeno_dna_rare_research_bundle": {
        "en": ("Rare Research Bundle", "Rare DNA fragments unlock extended research time.", "Research Booster (6 h)"),
        "de": ("Seltenes Forschungs-Paket", "Seltene DNA-Fragmente für verlängerte Forschungszeit.", "Forschungs-Booster (6 h)"),
    },
    "xeno_dna_rare_evo_xp": {
        "en": ("Rare Evolution Core", "Rare DNA traded for major evolution progress.", "Evolution Core (+5,000 XP)"),
        "de": ("Seltener Evolutions-Kern", "Seltene DNA gegen großen Evolutions-Fortschritt.", "Evolutions-Kern (+5.000 EP)"),
    },
    "xeno_dna_rare_research_crate": {
        "en": ("Research Cache", "Rare DNA exchanged for a research container.", "Research Cache"),
        "de": ("Forschungs-Cache", "Seltene DNA gegen einen Forschungs-Container.", "Forschungs-Cache"),
    },
    "xeno_dna_rare_random_module": {
        "en": ("Random Data Module", "Rare DNA yields a random research data core.", "Random Data Core"),
        "de": ("Zufalls-Datenmodul", "Seltene DNA liefert einen zufälligen Forschungs-Datenkern.", "Zufälliger Datenkern"),
    },
    "xeno_dna_epic_research_24h": {
        "en": ("Epic Research Surge", "Epic DNA for a full-day research boost.", "Research Booster (24 h)"),
        "de": ("Epischer Forschungs-Schub", "Epische DNA für einen ganztägigen Forschungs-Boost.", "Forschungs-Booster (24 h)"),
    },
    "xeno_dna_epic_planet_xp_big": {
        "en": ("Epic Evolution Leap", "Epic DNA for massive planet evolution progress.", "Evolution Core (+50,000 XP)"),
        "de": ("Epischer Evolutions-Sprung", "Epische DNA für massiven Planeten-Evolutions-Fortschritt.", "Evolutions-Kern (+50.000 EP)"),
    },
    "xeno_alien_scanner": {
        "en": ("Alien Scanner", "Alien fragments power a deep-space scanner.", "Alien Scanner"),
        "de": ("Alien-Scanner", "Alien-Fragmente für einen Tiefraum-Scanner.", "Alien-Scanner"),
    },
    "xeno_alien_expo_booster": {
        "en": ("Expedition Loot Boost", "Alien fragments improve expedition yields.", "Expedition Loot (+25%, 24 h)"),
        "de": ("Expeditions-Beute-Boost", "Alien-Fragmente verbessern Expeditions-Erträge.", "Expeditions-Beute (+25 %, 24 h)"),
    },
    "xeno_alien_loot_booster": {
        "en": ("Container Luck", "Alien fragments boost container luck.", "Container Luck (24 h)"),
        "de": ("Container-Glück", "Alien-Fragmente erhöhen Container-Glück.", "Container-Glück (24 h)"),
    },
    "scrap_hull_shipyard_15m": {
        "en": ("Quick Shipyard Rush", "Wreck hulls for short shipyard boosts.", "Shipyard Booster (15 min) ×2"),
        "de": ("Schiffswerft-Kurzboost", "Wrack-Rümpfe für kurze Werft-Boosts.", "Werft-Booster (15 Min.) ×2"),
    },
    "scrap_hull_shipyard_1h": {
        "en": ("Shipyard Hour", "Wreck hulls traded for a solid shipyard boost.", "Shipyard Booster (1 h)"),
        "de": ("Werft-Stunde", "Wrack-Rümpfe gegen soliden Werft-Boost.", "Werft-Booster (1 h)"),
    },
    "scrap_hull_repair_drones": {
        "en": ("Repair Drones", "Salvaged hulls rebuilt into repair drones.", "Repair Drone ×3"),
        "de": ("Reparatur-Drohnen", "Geborgene Rümpfe zu Reparatur-Drohnen.", "Reparatur-Drohne ×3"),
    },
    "scrap_hull_random_ship_small": {
        "en": ("Small Hull Lottery", "Wreck hulls may yield a small ship batch.", "Random small ships"),
        "de": ("Kleine Rumpf-Lotterie", "Wrack-Rümpfe können kleine Schiffslieferungen bringen.", "Zufällige kleine Schiffe"),
    },
    "scrap_reactor_defense_booster": {
        "en": ("Defense & Build Pack", "Reactor salvage for build and shipyard boosts.", "Build Booster (1 h) + Shipyard (15 min)"),
        "de": ("Verteidigungs- & Bau-Paket", "Reaktor-Schrott für Bau- und Werft-Boosts.", "Bau-Booster (1 h) + Werft (15 Min.)"),
    },
    "scrap_reactor_fuel_cells": {
        "en": ("Fuel Cell Pack", "Reactor fragments converted to fuel cells.", "Fuel Cell Pack ×2"),
        "de": ("Brennzellen-Paket", "Reaktor-Fragmente zu Brennzellen.", "Brennzellen-Paket ×2"),
    },
    "scrap_computer_fleet_slot": {
        "en": ("Fleet Queue Upgrade", "Fleet computers unlock an extra fleet slot.", "Fleet Queue +1 (24 h)"),
        "de": ("Flotten-Warteschlangen-Upgrade", "Flotten-Computer für einen extra Flotten-Slot.", "Flotten-Warteschlange +1 (24 h)"),
    },
    "scrap_hull_reconstruction": {
        "en": ("Hull Reconstruction", "Mass hull salvage rebuilt into warships.", "Random medium/large ships"),
        "de": ("Rumpf-Rekonstruktion", "Massen-Rumpf-Salvage zu Kriegsschiffen.", "Zufällige mittlere/große Schiffe"),
    },
    "energy_core_production_25": {
        "en": ("Energy Production +25%", "Energy data cores boost production.", "Production Booster (+25%)"),
        "de": ("Energie-Produktion +25 %", "Energie-Datenkerne boosten Produktion.", "Produktions-Booster (+25 %)"),
    },
    "energy_core_production_50": {
        "en": ("Energy Production +50%", "More energy cores for stronger production.", "Production Booster (+50%)"),
        "de": ("Energie-Produktion +50 %", "Mehr Energie-Kerne für stärkere Produktion.", "Produktions-Booster (+50 %)"),
    },
    "energy_core_energy_surge": {
        "en": ("Solar Energy Surge", "Energy cores trigger a solar surge.", "Energy Surge (+10% Solar, 24 h)"),
        "de": ("Solar-Energie-Schub", "Energie-Kerne lösen einen Solar-Schub aus.", "Energie-Schub (+10 % Solar, 24 h)"),
    },
    "energy_core_planet_xp": {
        "en": ("Energy Evolution Core", "Energy data traded for evolution progress.", "Evolution Core (+500 XP)"),
        "de": ("Energie-Evolutions-Kern", "Energie-Daten gegen Evolutions-Fortschritt.", "Evolutions-Kern (+500 EP)"),
    },
    "energy_mining_production": {
        "en": ("Mining Production Boost", "Mining data cores boost output.", "Production Booster (+25%)"),
        "de": ("Abbau-Produktions-Boost", "Abbau-Datenkerne boosten Output.", "Produktions-Booster (+25 %)"),
    },
    "energy_weapons_build": {
        "en": ("Weapons Build Rush", "Weapons data for faster construction.", "Build Booster (1 h)"),
        "de": ("Waffen-Bau-Schub", "Waffen-Daten für schnelleren Bau.", "Bau-Booster (1 h)"),
    },
    "hyper_fleet_speed_25": {
        "en": ("Fleet Speed +25%", "Hyperdrive modules increase fleet speed.", "Fleet Speed (+25%, 24 h)"),
        "de": ("Flotten-Tempo +25 %", "Hyperantriebs-Module erhöhen Flottengeschwindigkeit.", "Flotten-Tempo (+25 %, 24 h)"),
    },
    "hyper_instant_recall": {
        "en": ("Instant Fleet Recall", "Hyperdrive modules for emergency recall.", "Instant Fleet Recall"),
        "de": ("Sofort-Rückruf", "Hyperantriebs-Module für Notfall-Rückruf.", "Sofort-Flotten-Rückruf"),
    },
    "hyper_legendary_crate": {
        "en": ("Legendary Relic Crate", "Premium hyperdrive trade for a relic container.", "Relic Container"),
        "de": ("Legendärer Relikt-Container", "Premium-Hyperantrieb-Tausch für Relikt-Container.", "Relikt-Container"),
    },
    "hyper_nav_expo_bundle": {
        "en": ("Navigation Expo Bundle", "Nav chips plus expedition loot boost.", "Expedition Loot (+25%, 24 h) + Star Chart"),
        "de": ("Navigations-Expeditions-Paket", "Nav-Chips plus Expeditions-Beute-Boost.", "Expeditions-Beute (+25 %, 24 h) + Sternkarte"),
    },
    "hyper_pirate_scanner": {
        "en": ("Pirate Scanner", "Alien fragments fund a pirate scanner.", "Pirate Scanner"),
        "de": ("Piraten-Scanner", "Alien-Fragmente finanzieren einen Piraten-Scanner.", "Piraten-Scanner"),
    },
    "hyper_anomaly_scanner": {
        "en": ("Anomaly Scanner", "Artifact fragments unlock anomaly scanning.", "Anomaly Scanner"),
        "de": ("Anomalie-Scanner", "Artefakt-Fragmente für Anomalie-Scanning.", "Anomalie-Scanner"),
    },
}

INVENTORY_ITEM_KEYS = [
    "fragment_dna_common",
    "fragment_dna_rare",
    "fragment_dna_epic",
    "fragment_alien",
    "fragment_artifact_alpha",
    "fragment_wreck_hull",
    "fragment_wreck_reactor",
    "fleet_computer",
    "fleet_hyperdrive_module",
    "fleet_nav_chip",
    "research_data_energy",
    "research_data_mining",
    "research_data_weapons",
    "booster_research_30m",
    "booster_research_pct_2_24h",
    "booster_research_6h",
    "booster_research_24h",
    "booster_production_25",
    "booster_production_50",
    "booster_energy_surge_24h",
    "booster_build_1h",
    "booster_shipyard_15m",
    "booster_shipyard_1h",
    "booster_fleet_speed_25_24h",
    "booster_expedition_loot_25_24h",
    "booster_container_luck_24h",
    "evo_planet_xp_250",
    "evo_planet_xp_500",
    "evo_planet_xp_5000",
    "evo_planet_xp_50000",
    "dna_core_common",
    "container_research_cache",
    "container_relic",
    "utility_repair_drone",
    "utility_fleet_instant_recall",
    "utility_alien_scanner",
    "utility_pirate_scanner",
    "utility_anomaly_scanner",
    "utility_fleet_queue_plus_1",
    "resource_pack_fuel",
    "expo_star_chart",
]


def build_patch(lang: str) -> dict[str, str]:
    patch: dict[str, str] = {}
    patch.update(UI_EN if lang == "en" else UI_DE if lang == "de" else UI_EN)
    for offer_key, texts in OFFERS.items():
        title, desc, reward = texts.get(lang, texts["en"])
        patch[f"collector_offer_{offer_key}_title"] = title
        patch[f"collector_offer_{offer_key}_desc"] = desc
        patch[f"collector_offer_{offer_key}_reward"] = reward
    return patch


def mirror_inventory_items(data: dict[str, str]) -> None:
    for key in INVENTORY_ITEM_KEYS:
        inv_key = f"inv_{key}"
        name_key = f"inventory_item_{key}_name"
        desc_key = f"inventory_item_{key}_desc"
        if inv_key in data and name_key not in data:
            data[name_key] = data[inv_key]
        if name_key in data and desc_key not in data:
            data[desc_key] = data.get(f"{inv_key}_desc", data[name_key])


def merge_locale(path: Path, lang: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    patch = build_patch(lang if lang in ("en", "de") else "en")
    data.update(patch)
    mirror_inventory_items(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    for path in sorted(LOCALES.glob("*.json")):
        lang = path.stem
        merge_locale(path, lang)
        print(f"merged {path.name}")


if __name__ == "__main__":
    main()
