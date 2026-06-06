#!/usr/bin/env python3
"""Apply GC-537 missing locale keys (explicit translations only — no source scraping)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "locales"

DE_ADDITIONS: dict[str, str] = {
    "action_cancel": "Abbrechen",
    "action_queue_upgrade": "Upgrade (anreihen)",
    "admin_balance_btn_preset_b": "Preset B anwenden",
    "admin_balance_btn_recalc": "Ranking neu berechnen",
    "admin_balance_btn_save": "Speichern",
    "admin_balance_hint": "Pacing, Queues, Score-Gewichte und Tauschhub — nur whitelisted Keys.",
    "admin_balance_players": "Spieler",
    "admin_balance_preset_applied": "Preset angewendet.",
    "admin_balance_queue_note": "3. Forschungs-Slot ab research_lab Level 4 (Code-Regel).",
    "admin_balance_recalc_ok": "Ranking neu berechnet.",
    "admin_balance_saved": "Balance-Einstellungen gespeichert.",
    "admin_balance_saving": "Speichern…",
    "admin_balance_score_buildings": "Gebäude",
    "admin_balance_score_fleet": "Flotte",
    "admin_balance_score_research": "Forschung",
    "admin_balance_section_queues": "Warteschlangen",
    "admin_balance_section_scores": "Score-Gewichte",
    "admin_balance_section_speed": "Geschwindigkeiten",
    "admin_balance_section_start": "Startressourcen",
    "admin_balance_title": "Balance",
    "admin_btn_refresh": "Aktualisieren",
    "admin_no": "Nein",
    "admin_request_timeout": "Zeitüberschreitung — Server antwortet nicht.",
    "admin_support_col_player": "Spieler",
    "admin_support_col_status": "Status",
    "admin_support_col_subject": "Betreff",
    "admin_support_col_updated": "Aktualisiert",
    "admin_support_empty": "Keine Tickets.",
    "admin_support_hint": "Alle Spieler-Tickets – antworten und Status setzen.",
    "admin_support_no_messages": "Keine Nachrichten.",
    "admin_support_reply_btn": "Antwort senden",
    "admin_support_reply_empty": "Antwort eingeben.",
    "admin_support_reply_label": "Antwort an Spieler",
    "admin_support_reply_ok": "Antwort gesendet.",
    "admin_support_select_hint": "Ticket aus der Liste wählen.",
    "admin_support_status_btn": "Status setzen",
    "admin_support_status_closed": "Geschlossen",
    "admin_support_status_ok": "Status aktualisiert.",
    "admin_support_status_open": "Offen",
    "admin_support_status_progress": "In Bearbeitung",
    "admin_support_title": "Support-Tickets",
    "admin_tick_derived_sync": "Derived sync",
    "admin_yes": "Ja",
    "build_queue_compact_active": "%(count)s Bauaufträge aktiv",
    "build_queue_compact_idle": "Keine Bauaufträge",
    "defense_queue_compact_active": "%(count)s Verteidigungsaufträge aktiv",
    "defense_queue_compact_idle": "Keine Verteidigungsaufträge",
    "err_password2_short": "Bitte Passwort wiederholen (min. 8 Zeichen).",
    "err_password_mismatch": "Passwörter stimmen nicht überein.",
    "err_password_short": "Passwort ist zu kurz.",
    "err_username_long": "Benutzername ist zu lang (max. 24 Zeichen).",
    "err_username_short": "Benutzername ist zu kurz (min. 3 Zeichen).",
    "err_username_spaces": "Commander-Name darf keine Leerzeichen enthalten.",
    "fleet_deploy_report": "Stationierung bei %(coords)s (%(target)s) abgeschlossen. Stationiert: %(ships)s. Ressourcen: %(cargo)s.",
    "fleet_deploy_report_ships_empty": "keine Schiffe",
    "fleet_deploy_report_subject": "Stationierungsbericht %(coords)s",
    "fleet_hold_report_body": "Deine Flotte hält Position bei %(coords)s (%(target)s) bis %(until)s.",
    "fleet_hold_report_subject": "Flotte hält %(coords)s",
    "fleet_recycle_report": "Recycler bei %(coords)s: %(cargo)s geladen. Flotte kehrt nach %(origin)s zurück.",
    "fleet_recycle_report_empty": "Recycler bei %(coords)s — kein Trümmerfeld gesammelt. Flotte kehrt nach %(origin)s zurück.",
    "fleet_recycle_report_subject": "Recycler-Bericht %(coords)s",
    "fleet_spy_report_defense_empty": "Keine Verteidigungsanlagen erkannt",
    "fleet_spy_report_defense_total": "Verteidigungseinheiten: %(count)s",
    "fuel_efficiency": "Brennzellen-Optimierung",
    "galaxy_debris_field": "Trümmerfeld",
    "galaxy_legend_debris": "Trümmerfeld",
    "header_planet_limit": "Planeten",
    "imprint": "Impressum",
    "loading": "Lädt…",
    "login_btn": "Zum Login",
    "messages_no_subject": "Ohne Betreff",
    "messages_sender_logistics": "Logistikbericht",
    "motd": "Nachricht des Tages",
    "msg_action_forbidden": "Aktion nicht erlaubt.",
    "msg_job_not_found": "Auftrag nicht gefunden.",
    "msg_status_refresh_failed": "Seite konnte nicht geladen werden. Bitte erneut versuchen.",
    "pe_ascension_completed": "Vollendet",
    "pe_ascension_duration": "Dauer: %(days)s Tage",
    "pe_ascension_phase": "Phase %(n)s",
    "pe_ascension_queue_compact_active": "%(count)s Ascension-Aufträge",
    "pe_ascension_queue_compact_idle": "Keine Ascension-Aufträge",
    "pe_ascension_ready": "Bereit",
    "pe_planet_tech_queue_compact_active": "%(count)s Planet-Tech-Aufträge",
    "pe_planet_tech_queue_compact_idle": "Keine Planet-Tech-Aufträge",
    "queue_card_status_active": "AKTIV",
    "queue_card_status_queued": "QUEUE #%(n)s",
    "research_armor_tech": "Panzerungstechnik",
    "research_drones_tech": "Drohnenoptimierung",
    "research_engine_tech": "Kryo-Antriebstechnik",
    "research_navigation_tech": "Hyperraum-Navigation",
    "research_queue_compact_active": "%(count)s Forschungen aktiv",
    "research_queue_compact_idle": "Keine Forschungen aktiv",
    "research_requirements_met": "Voraussetzungen erfüllt",
    "research_shield_tech": "Schildtechnologie",
    "research_weapon_tech": "Waffenentwicklung",
    "rules": "Regeln",
    "shipyard_queue_compact_active": "%(count)s Werftaufträge aktiv",
    "shipyard_queue_compact_idle": "Keine Werftaufträge",
    "special_nav": "Sondernavigation",
    "support": "Support",
    "techtree_empty_buildings": "Keine Gebäude-Daten vorhanden (Tech-Tree Nodes prüfen).",
    "techtree_empty_research": "Keine Forschungs-Daten vorhanden (Tech-Tree Nodes prüfen).",
    "wiki_title": "Wiki",
}

EN_ADDITIONS: dict[str, str] = {
    "action_cancel": "Cancel",
    "action_queue_upgrade": "Upgrade (queue)",
    "admin_balance_btn_preset_b": "Apply preset B",
    "admin_balance_btn_recalc": "Recalculate ranking",
    "admin_balance_btn_save": "Save",
    "admin_balance_hint": "Pacing, queues, score weights, and exchange hub — whitelisted keys only.",
    "admin_balance_players": "Players",
    "admin_balance_preset_applied": "Preset applied.",
    "admin_balance_queue_note": "3rd research slot from research_lab level 4 (code rule).",
    "admin_balance_recalc_ok": "Ranking recalculated.",
    "admin_balance_saved": "Balance settings saved.",
    "admin_balance_saving": "Saving…",
    "admin_balance_score_buildings": "Buildings",
    "admin_balance_score_fleet": "Fleet",
    "admin_balance_score_research": "Research",
    "admin_balance_section_queues": "Queues",
    "admin_balance_section_scores": "Score weights",
    "admin_balance_section_speed": "Speeds",
    "admin_balance_section_start": "Starting resources",
    "admin_balance_title": "Balance",
    "admin_btn_refresh": "Refresh",
    "admin_no": "No",
    "admin_request_timeout": "Timeout — server did not respond.",
    "admin_support_col_player": "Player",
    "admin_support_col_status": "Status",
    "admin_support_col_subject": "Subject",
    "admin_support_col_updated": "Updated",
    "admin_support_empty": "No tickets.",
    "admin_support_hint": "All player tickets — reply and set status.",
    "admin_support_no_messages": "No messages.",
    "admin_support_reply_btn": "Send reply",
    "admin_support_reply_empty": "Enter a reply.",
    "admin_support_reply_label": "Reply to player",
    "admin_support_reply_ok": "Reply sent.",
    "admin_support_select_hint": "Select a ticket from the list.",
    "admin_support_status_btn": "Set status",
    "admin_support_status_closed": "Closed",
    "admin_support_status_ok": "Status updated.",
    "admin_support_status_open": "Open",
    "admin_support_status_progress": "In progress",
    "admin_support_title": "Support tickets",
    "admin_tick_derived_sync": "Derived sync",
    "admin_yes": "Yes",
    "build_queue_compact_active": "%(count)s build jobs active",
    "build_queue_compact_idle": "No build jobs",
    "defense_queue_compact_active": "%(count)s defense jobs active",
    "defense_queue_compact_idle": "No defense jobs",
    "err_password2_short": "Please repeat password (min. 8 characters).",
    "err_password_mismatch": "Passwords do not match.",
    "err_password_short": "Password is too short.",
    "err_username_long": "Username is too long (max. 24 characters).",
    "err_username_short": "Username is too short (min. 3 characters).",
    "err_username_spaces": "Commander name must not contain spaces.",
    "fleet_deploy_report": "Deploy at %(coords)s (%(target)s) completed. Stationed: %(ships)s. Resources: %(cargo)s.",
    "fleet_deploy_report_ships_empty": "no ships",
    "fleet_deploy_report_subject": "Deploy report %(coords)s",
    "fleet_hold_report_body": "Your fleet is holding position at %(coords)s (%(target)s) until %(until)s.",
    "fleet_hold_report_subject": "Fleet holding %(coords)s",
    "fleet_recycle_report": "Recycle at %(coords)s: %(cargo)s loaded. Fleet returning to %(origin)s.",
    "fleet_recycle_report_empty": "Recycle at %(coords)s — no debris collected. Fleet returning to %(origin)s.",
    "fleet_recycle_report_subject": "Recycle report %(coords)s",
    "fleet_spy_report_defense_empty": "No defensive structures detected",
    "fleet_spy_report_defense_total": "Defense units: %(count)s",
    "fuel_efficiency": "Fuel Cell Optimization",
    "galaxy_debris_field": "Debris field",
    "galaxy_legend_debris": "Debris field",
    "header_planet_limit": "Planets",
    "imprint": "Imprint",
    "loading": "Loading…",
    "login_btn": "Go to login",
    "messages_no_subject": "No subject",
    "messages_sender_logistics": "Logistics report",
    "motd": "Message of the day",
    "msg_action_forbidden": "Action not allowed.",
    "msg_job_not_found": "Job not found.",
    "msg_status_refresh_failed": "Could not load page. Please try again.",
    "pe_ascension_completed": "Completed",
    "pe_ascension_duration": "Duration: %(days)s days",
    "pe_ascension_phase": "Phase %(n)s",
    "pe_ascension_queue_compact_active": "%(count)s ascension jobs",
    "pe_ascension_queue_compact_idle": "No ascension jobs",
    "pe_ascension_ready": "Ready",
    "pe_planet_tech_queue_compact_active": "%(count)s planet tech jobs",
    "pe_planet_tech_queue_compact_idle": "No planet tech jobs",
    "queue_card_status_active": "ACTIVE",
    "queue_card_status_queued": "QUEUE #%(n)s",
    "research_armor_tech": "Armor Technology",
    "research_drones_tech": "Drone Optimization",
    "research_engine_tech": "Cryo Drive Technology",
    "research_navigation_tech": "Hyperspace Navigation",
    "research_queue_compact_active": "%(count)s research jobs active",
    "research_queue_compact_idle": "No active research",
    "research_requirements_met": "Requirements met",
    "research_shield_tech": "Shield Technology",
    "research_weapon_tech": "Weapons Development",
    "rules": "Rules",
    "shipyard_queue_compact_active": "%(count)s shipyard jobs active",
    "shipyard_queue_compact_idle": "No shipyard jobs",
    "special_nav": "Special navigation",
    "support": "Support",
    "techtree_empty_buildings": "No building data (check tech-tree nodes).",
    "techtree_empty_research": "No research data (check tech-tree nodes).",
    "wiki_title": "Wiki",
}


def _load(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return {str(k): str(v) for k, v in json.load(fh).items()}


def _save(path: Path, data: dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from scripts.check_locale_keys import collect_used_keys, find_missing

    used = collect_used_keys()
    de = _load(LOCALES_DIR / "de.json")
    en = _load(LOCALES_DIR / "en.json")

    for key, val in DE_ADDITIONS.items():
        if key in used and key not in de:
            de[key] = val

    for key in find_missing("en", used):
        if key in EN_ADDITIONS:
            en[key] = EN_ADDITIONS[key]
        elif key in de:
            en[key] = de[key]

    _save(LOCALES_DIR / "de.json", de)
    _save(LOCALES_DIR / "en.json", en)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
