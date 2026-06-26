#!/usr/bin/env python3
"""Audit German strings in en.json by scope."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
de = json.loads((ROOT / "locales/de.json").read_text(encoding="utf-8"))
en = json.loads((ROOT / "locales/en.json").read_text(encoding="utf-8"))

GERMAN_HINTS = (
    "Produktionskette",
    "Spezialisierung",
    "Forschung",
    "Kolonie",
    "Planetare",
    "Experimentelle",
    "Schmuggler",
    "Tiefbau",
    "Verteidigung",
    "Allianz",
    "Spieler",
    "bannen",
    "Einstellungen",
    "Verifizierungs",
    "Optimiere",
    "Einloggen",
    "erstellen",
    "Drei Schritte",
    "Starte ",
    "Name der",
    "Keine ",
    "Noch ",
    "Ab Stufe",
    "Baue ",
    "Dieser Planet",
    "Mit aktueller",
    "festlegen",
    "ausgebaut",
    "freigeschaltet",
    "Schatten",
    "Rohstoffe",
    "Planetenkern",
    "Feindliche",
    "Kolonie-Scanner",
    "Live-Produktion",
    "Arbeiter",
    "Belagerung",
    "Schwarzmarkt",
    "Quanten",
    "KI-",
    "Ruinen",
    "Syndikat",
    "Unterwelt",
    "Politiken",
    "Aktive ",
    "Handels",
    "freischalten",
    "Orbitaler",
    "Festungs",
    "Meister",
    "Crytite-Produktion",
    "Schmuggelware",
    "Effizienz",
    "Flotten",
    "Urlaub",
    "Kernwerte",
    "Bann ",
    "gebannt",
    "Planetare",
    "Schritte bis",
    "betreten",
    "Scanner",
    "Bastion",
    "Wirtschaft",
    "Vermessung",
    "Konversion",
    "Aufstand",
    "Vorfall",
    "Durchbruch",
    "Boom",
    "Bruch",
    "Output-Bonus",
    "Routen effizienter",
    "Breakthrough-Events",
)


def is_german(val: str) -> bool:
    if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
        return True
    return any(h in val for h in GERMAN_HINTS)


def in_pe_overview(k: str) -> bool:
    return k.startswith(
        (
            "pe_",
            "desc_pe_",
            "spec_",
            "policy_",
            "overview_",
            "trait_",
            "chain_",
            "event_",
            "galaxy_legend",
            "landing_",
            "login_",
            "register_",
            "admin_",
            "alliance_",
            "account_",
        )
    ) or k == "defense_panel_planetary_title"


def in_fleet_defense(k: str) -> bool:
    if k.startswith(("fleet_", "shipyard_", "defense_")):
        return True
    return k in ("shipyard", "fleet_shipyard_title", "nav_shipyard")


pe_hits = sorted(k for k in en if in_pe_overview(k) and is_german(en[k]))
fleet_hits = sorted(k for k in en if in_fleet_defense(k) and is_german(en[k]))
print("pe_overview_german", len(pe_hits))
print("fleet_defense_german", len(fleet_hits))
for k in pe_hits:
    print("PE", k, "|", en[k][:70])
for k in fleet_hits:
    print("FD", k, "|", en[k][:70])

# shipyard canon
for k in ("shipyard", "fleet_shipyard_title", "nav_shipyard", "shipyard_btn_queue_full"):
    if k in en:
        print("CANON", k, "|", en[k])
