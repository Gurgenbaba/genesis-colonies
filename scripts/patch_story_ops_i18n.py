"""Patch Story Ops i18n keys into all locale files (GC-2502/2503)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"

# English source of truth; other locales get English fallbacks unless overridden.
EN = {
    "nav_story": "Story Ops",
    "nav_badge_story_aria": "Story transmission awaiting response",
    "story_eyebrow": "TRANSMISSION CHANNEL",
    "story_hint": "Authorized arcs and side ops from the Ark signal net. Progress through real gameplay.",
    "story_unavailable": "Story Ops are currently unavailable.",
    "story_status_live": "LIVE CHANNEL",
    "story_contact_ark": "Genesis Ark",
    "story_contact_androgyn": "Androgyn Echo",
    "story_idle_title": "Channel quiet",
    "story_idle_body": "No active transmission. Side ops unlock as your Imperium grows.",
    "story_waiting_gameplay": "Complete the objective through normal gameplay.",
    "story_arcs_title": "Active & completed ops",
    "story_no_arcs": "No arcs yet.",
    "story_lore_title": "Unlocked fragments",
    "story_kind_main": "Main",
    "story_kind_side": "Side",
    "story_cta_continue": "Continue",
    "story_cta_acknowledge": "Acknowledge",
    "story_cta_listen": "Open channel",
    "story_cta_accept": "Accept directive",
    "story_action_fail": "Transmission failed.",
    "codex_unlock_story_flag": "Complete the related Story Ops transmission to unlock this topic.",
    "story_ark_main_title": "Ark Signal",
    "story_ark_main_intro_title": "First handshake",
    "story_ark_main_intro_body": "Genesis Ark carrier wave locked.\nYour Imperium is online. Expand infrastructure, then ping the void with a fleet — so the Ark can map your signature.",
    "story_ark_main_build_title": "Raise the colony spine",
    "story_ark_main_build_body": "Complete one building upgrade on any world. The Ark reads structural heat signatures as proof of life.",
    "story_ark_main_fleet_title": "Mark the void",
    "story_ark_main_fleet_body": "Launch any fleet mission. Even a short hop proves the channel can carry command intent.",
    "story_ark_main_reveal_title": "Ark Origin fragment",
    "story_ark_main_reveal_body": "The Genesis Ark is not a slot — it is the seat of your Imperium. Colonies grow around it. The signal remembers every world you claim.",
    "story_ark_main_notify_subject": "Ark Signal — archive sealed",
    "story_ark_main_notify_body": "Main transmission complete. Side channels may now open.",
    "story_androgyn_title": "Androgyn Echo",
    "story_androgyn_contact_title": "Unlabeled carrier",
    "story_androgyn_contact_body": "A second voice rides the Ark lattice — neither gendered nor faction-tagged. It speaks as if it already knows your command cadence.",
    "story_androgyn_choice_title": "How do you answer?",
    "story_androgyn_choice_body": "Pursue the echo into deeper bands, or archive the contact for later analysis.",
    "story_androgyn_choice_pursue": "Pursue the echo",
    "story_androgyn_choice_archive": "Archive and seal",
    "story_androgyn_notify_subject": "Androgyn Echo — logged",
    "story_androgyn_notify_body": "The unlabeled contact is stored in your Story Ops archive.",
    "story_void_patrol_title": "Void Patrol",
    "story_void_patrol_brief_title": "Expedition brief",
    "story_void_patrol_brief_body": "High Command wants a probe into unknown space. Launch an expedition — pirate heat and lost colonies leave footprints the Ark can read.",
    "story_void_patrol_obj_title": "Launch an expedition",
    "story_void_patrol_obj_body": "Send a fleet on an expedition mission.",
    "story_void_patrol_notify_subject": "Void Patrol — complete",
    "story_void_patrol_notify_body": "Expedition signature logged. Patrol fragment unlocked.",
    "story_codex_codex_ark_signal_title": "Genesis Ark Signal",
    "story_codex_codex_ark_signal_body": "The Ark is the permanent seat of every Imperium — government, research, and evolution orbit this origin.",
    "story_codex_codex_androgyn_echo_title": "Androgyn Echo",
    "story_codex_codex_androgyn_echo_body": "A gender-neutral contact on the Ark lattice. It does not claim a faction — only a conversation.",
    "story_codex_codex_void_patrol_title": "Void Patrol",
    "story_codex_codex_void_patrol_body": "Expedition footprints feed the Ark's map of living threats and lost colonies.",
}

DE = {
    **EN,
    "nav_story": "Story Ops",
    "story_eyebrow": "ÜBERTRAGUNGSKANAL",
    "story_hint": "Autorisierte Arcs und Side Ops aus dem Ark-Signalnetz. Fortschritt entsteht durch echtes Gameplay.",
    "story_unavailable": "Story Ops sind derzeit nicht verfügbar.",
    "story_contact_ark": "Genesis Ark",
    "story_contact_androgyn": "Androgyn-Echo",
    "story_idle_title": "Kanal ruhig",
    "story_idle_body": "Keine aktive Übertragung. Side Ops öffnen sich, wenn dein Imperium wächst.",
    "story_waiting_gameplay": "Erfülle das Ziel durch normales Spielen.",
    "story_arcs_title": "Aktive & abgeschlossene Ops",
    "story_no_arcs": "Noch keine Arcs.",
    "story_lore_title": "Freigeschaltete Fragmente",
    "story_kind_main": "Haupt",
    "story_kind_side": "Neben",
    "story_cta_continue": "Weiter",
    "story_cta_acknowledge": "Bestätigen",
    "story_cta_listen": "Kanal öffnen",
    "story_cta_accept": "Befehl annehmen",
    "story_action_fail": "Übertragung fehlgeschlagen.",
    "codex_unlock_story_flag": "Schließe die zugehörige Story-Ops-Übertragung ab, um dieses Thema freizuschalten.",
    "story_ark_main_title": "Ark-Signal",
    "story_ark_main_intro_title": "Erster Handshake",
    "story_ark_main_intro_body": "Genesis-Ark-Trägerwelle gesichert.\nDein Imperium ist online. Baue Infrastruktur aus und sende dann eine Flotte — damit die Ark deine Signatur kartieren kann.",
    "story_ark_main_build_title": "Kolonie-Rückgrat stärken",
    "story_ark_main_build_body": "Schließe ein Gebäude-Upgrade auf einer Welt ab. Die Ark liest strukturelle Wärmesignaturen als Lebenszeichen.",
    "story_ark_main_fleet_title": "Die Leere markieren",
    "story_ark_main_fleet_body": "Starte eine beliebige Flottenmission. Schon ein kurzer Sprung beweist, dass der Kanal Befehlsabsicht trägt.",
    "story_ark_main_reveal_title": "Ark-Ursprungsfragment",
    "story_ark_main_reveal_body": "Die Genesis Ark ist kein Slot — sie ist der Sitz deines Imperiums. Kolonien wachsen um sie. Das Signal erinnert jede Welt, die du beanspruchst.",
    "story_ark_main_notify_subject": "Ark-Signal — Archiv versiegelt",
    "story_ark_main_notify_body": "Hauptübertragung abgeschlossen. Nebenkanäle können sich öffnen.",
    "story_androgyn_title": "Androgyn-Echo",
    "story_androgyn_contact_title": "Unmarkierter Träger",
    "story_androgyn_contact_body": "Eine zweite Stimme reitet auf dem Ark-Gitter — weder gegendert noch fraktionsmarkiert. Sie spricht, als kenne sie bereits deinen Befehlstakt.",
    "story_androgyn_choice_title": "Wie antwortest du?",
    "story_androgyn_choice_body": "Verfolge das Echo in tiefere Bänder oder archiviere den Kontakt für spätere Analyse.",
    "story_androgyn_choice_pursue": "Echo verfolgen",
    "story_androgyn_choice_archive": "Archivieren und versiegeln",
    "story_androgyn_notify_subject": "Androgyn-Echo — protokolliert",
    "story_androgyn_notify_body": "Der unmarkierte Kontakt liegt in deinem Story-Ops-Archiv.",
    "story_void_patrol_title": "Void-Patrol",
    "story_void_patrol_brief_title": "Expeditionsbriefing",
    "story_void_patrol_brief_body": "High Command will eine Sonde in unbekannten Raum. Starte eine Expedition — Piratenhitze und verlorene Kolonien hinterlassen Spuren, die die Ark lesen kann.",
    "story_void_patrol_obj_title": "Expedition starten",
    "story_void_patrol_obj_body": "Sende eine Flotte auf eine Expeditionsmission.",
    "story_void_patrol_notify_subject": "Void-Patrol — abgeschlossen",
    "story_void_patrol_notify_body": "Expeditionssignatur protokolliert. Patrol-Fragment freigeschaltet.",
    "story_codex_codex_ark_signal_title": "Genesis-Ark-Signal",
    "story_codex_codex_ark_signal_body": "Die Ark ist der permanente Sitz jedes Imperiums — Regierung, Forschung und Evolution kreisen um diesen Ursprung.",
    "story_codex_codex_androgyn_echo_title": "Androgyn-Echo",
    "story_codex_codex_androgyn_echo_body": "Ein gender-neutraler Kontakt auf dem Ark-Gitter. Keine Fraktion — nur ein Gespräch.",
    "story_codex_codex_void_patrol_title": "Void-Patrol",
    "story_codex_codex_void_patrol_body": "Expeditionsspuren speisen die Ark-Karte lebender Bedrohungen und verlorener Kolonien.",
}

BY_LOCALE = {
    "en": EN,
    "de": DE,
    "es": EN,
    "fr": EN,
    "pl": EN,
    "pt": EN,
    "ru": EN,
    "tr": EN,
}


def main() -> None:
    for loc, keys in BY_LOCALE.items():
        path = LOCALES / f"{loc}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(keys)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"patched {path.name} (+{len(keys)} keys)")


if __name__ == "__main__":
    main()
