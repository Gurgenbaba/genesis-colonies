"""Player-facing rules panel (bottom utility bar) — content keys synced to locales.

Master doc: docs/GAME_RULES.md (dev/support). Player UI uses ``rules_panel_*`` i18n keys only — not Codex.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

RULES_PANEL_VERSION = "2026-06-27 · v1.2"

# Section order in the Regeln special window (bottom nav).
RULES_PANEL_SECTIONS: Tuple[Dict[str, Any], ...] = (
    {"id": "general", "title_key": "rules_panel_general_title", "body_key": "rules_panel_general_body", "open": True},
    {"id": "accounts", "title_key": "rules_panel_accounts_title", "body_key": "rules_panel_accounts_body", "open": False},
    {"id": "combat", "title_key": "rules_panel_combat_title", "body_key": "rules_panel_combat_body", "open": False},
    {"id": "push", "title_key": "rules_panel_push_title", "body_key": "rules_panel_push_body", "open": False},
    {"id": "economy", "title_key": "rules_panel_economy_title", "body_key": "rules_panel_economy_body", "open": False},
    {"id": "vacation", "title_key": "rules_panel_vacation_title", "body_key": "rules_panel_vacation_body", "open": False},
    {"id": "empire", "title_key": "rules_panel_empire_title", "body_key": "rules_panel_empire_body", "open": False},
    {"id": "community", "title_key": "rules_panel_community_title", "body_key": "rules_panel_community_body", "open": False},
    {"id": "sanctions", "title_key": "rules_panel_sanctions_title", "body_key": "rules_panel_sanctions_body", "open": False},
)

RULES_PANEL_FAQ: Tuple[Dict[str, str], ...] = (
    {"q_key": "rules_panel_faq_0_q", "a_key": "rules_panel_faq_0_a"},
    {"q_key": "rules_panel_faq_1_q", "a_key": "rules_panel_faq_1_a"},
    {"q_key": "rules_panel_faq_2_q", "a_key": "rules_panel_faq_2_a"},
    {"q_key": "rules_panel_faq_3_q", "a_key": "rules_panel_faq_3_a"},
    {"q_key": "rules_panel_faq_4_q", "a_key": "rules_panel_faq_4_a"},
    {"q_key": "rules_panel_faq_5_q", "a_key": "rules_panel_faq_5_a"},
    {"q_key": "rules_panel_faq_6_q", "a_key": "rules_panel_faq_6_a"},
)

INTRO_KEY = "rules_panel_intro"
FAQ_TITLE_KEY = "rules_panel_faq_title"
VERSION_KEY = "rules_panel_version"
SUPPORT_CTA_KEY = "rules_panel_support_cta"

# Synced into locales/*.json via scripts/sync_rules_panel_locales.py
RULES_PANEL_STRINGS: Dict[str, Dict[str, str]] = {
    "de": {
        "rules_panel_intro": (
            "Offizielles Regelwerk von Genesis Colonies — OGame-vertraut, auf unsere Mechaniken zugeschnitten. "
            "Technische Limits setzt der Server durch; Verhaltensregeln prüft das Team. Bei Zweifeln entscheidet das Genesis-Team."
        ),
        "rules_panel_version": "Stand: 27.06.2026 · Regelwerk v1.2",
        "rules_panel_faq_title": "Häufige Fragen",
        "rules_panel_support_cta": "Support kontaktieren",
        "rules_panel_general_title": "Allgemein & Fair Play",
        "rules_panel_general_body": (
            "Respektvoller Umgang — keine Beleidigungen, Diskriminierung, Hassrede oder Drohungen.\n\n"
            "Bugs **melden** (Support/Ticket), nicht ausnutzen. Bewusstes Exploiten kann bestraft werden — "
            "auch ohne explizite Regelzeile.\n\n"
            "Keine Bots, Makros, Clicker oder Automatisierung. Kein Echtgeldhandel (RMT) mit Accounts oder Ressourcen.\n\n"
            "Das Spiel rechnet auf dem Server — die UI zeigt nur Serverdaten.\n\n"
            "Alles, was offensichtlich Mechaniken umgeht, kann sanktioniert werden — auch wenn es nicht wortwörtlich hier steht."
        ),
        "rules_panel_accounts_title": "Accounts",
        "rules_panel_accounts_body": (
            "**Ein Account pro Person pro Universum.** Keine Farmaccounts, Spionage-Alts oder Ranking-Manipulation.\n\n"
            "**Account-Sharing** dauerhaft verboten — Ausnahme: **Sitting** (max. **48 Stunden**, keine Ressourcenweitergabe).\n\n"
            "**Accountübernahme** gegen Echtgeld oder externe Gegenleistung verboten."
        ),
        "rules_panel_combat_title": "Kämpfe",
        "rules_panel_combat_body": (
            "**Bash:** Maximal **5 Angriffe** auf dieselbe **Ziel-Welt** innerhalb von **24 Stunden** (rollierend). "
            "Gilt pro Angreifer-Konto und Ziel-Welt — **nicht** pro Abgangswelt. "
            "Beispiel: 3 Angriffe von Welt A + 2 von Welt B auf **dieselbe** Ziel-Welt = Limit voll.\n\n"
            "**Noobschutz:** Angriffe nur im **5×-Korridor** um deinen Imperiumswert — außer das Ziel ist **länger als 3 Tage inaktiv**.\n\n"
            "**Spionage:** Unbegrenzt (Ziel im Urlaub ausgenommen).\n\n"
            "**Expeditionen & Recycler:** Unbegrenzt (außer du bist selbst im Urlaub).\n\n"
            "**Halteflüge:** Erlaubt. **Gemeinsame Angriffe (ACS):** geplant — bis dahin gelten Bash/Noob pro Einzelangriff.\n\n"
            "**Keine Monde** in Genesis Colonies."
        ),
        "rules_panel_push_title": "Push — Definition",
        "rules_panel_push_body": (
            "**Push** = absichtlich unfairen Vorteil verschaffen — nicht durch normale, marktgerechte Mechaniken.\n\n"
            "**Verboten:** großzügiges Schenken ohne Gegenleistung · absichtlich Flotten verlieren für Beute · "
            "Transportketten A→B→C · extrem einseitiger „Handel“ · Schrottfeld-Tricks · Auktions-Scheingebote.\n\n"
            "**Erlaubt:** fairer Trader-Hub-Tausch · Beute aus Kämpfen · Logistics zwischen **eigenen** Welten · "
            "Allianzhilfe über erlaubte Mechaniken zu marktnahen Konditionen."
        ),
        "rules_panel_economy_title": "Wirtschaft",
        "rules_panel_economy_body": (
            "**Trader Hub:** Markttausch innerhalb deines **täglichen Limits** (accountweit). "
            "Rundtrip-Gewinne werden serverseitig blockiert.\n\n"
            "**Logistics:** Nur zwischen **eigenen** Welten — Missbrauch zugunsten Dritter melden.\n\n"
            "Auktionshaus und Inventar sind separate Systeme — Push über Scheingebote verboten."
        ),
        "rules_panel_vacation_title": "Urlaubsmodus",
        "rules_panel_vacation_body": (
            "**48 Stunden Mindestdauer** nach Aktivierung.\n\n"
            "Währenddessen: **keine Flotten**, **kein Trader Hub**, Schutz vor Angriffen und Spionage.\n\n"
            "Produktion, Forschung und Bauqueues laufen weiter (Ist-Stand).\n\n"
            "Aktivierung erst möglich ohne aktive Flotten, Auktionsgebote oder offene Queues."
        ),
        "rules_panel_empire_title": "Imperium (Genesis-spezifisch)",
        "rules_panel_empire_body": (
            "Kein Missbrauch von **Planet Evolution** (DNA, Traits, Events) · **Command Map** / Kolonisierung · "
            "**Galactic Directives** (Abstimmung) · **Imperial Directives** · Expeditions-Event-Bugs · "
            "Legendary Discoveries oder Establishment-Exploits."
        ),
        "rules_panel_community_title": "Community & Chat",
        "rules_panel_community_body": (
            "**Chat:** Kein Spam, Werbung, RMT-Angebote, NSFW, politische/extremistische Inhalte, Beleidigungen.\n\n"
            "**Namen:** Keine beleidigenden, rassistischen oder irreführenden Team-/Admin-Namen.\n\n"
            "**Allianz:** Koordination erlaubt — kein Multiaccount-Support, kein Push, kein dauerhaftes Account-Sharing.\n\n"
            "**Discord:** Gleiche Fair-Play-Standards; der offizielle Discord kann zusätzliche Regeln haben."
        ),
        "rules_panel_sanctions_title": "Sanktionen & Support",
        "rules_panel_sanctions_body": (
            "Je nach Schwere: Verwarnung · temporäre Sperre · permanente Sperre · Ressourcen-/Flottenentzug · Rollback · Löschung.\n\n"
            "**Eigene Fehler:** Kein Anspruch auf Wiederherstellung verlorener Flotten oder Ressourcen.\n\n"
            "**Serverfehler:** Nach Nachweis prüft das Team Einzelfälle — Entscheidung ist final.\n\n"
            "Regeln können sich weiterentwickeln — Änderungen werden bekannt gegeben."
        ),
        "rules_panel_faq_0_q": "Wie viele Angriffe darf ich auf eine Welt starten?",
        "rules_panel_faq_0_a": "Maximal 5 innerhalb von 24 Stunden auf dieselbe Ziel-Welt — egal von welcher deiner Welten.",
        "rules_panel_faq_1_q": "Warum kann ich jemanden nicht angreifen?",
        "rules_panel_faq_1_a": "Häufig: Noobschutz (Punkte zu weit auseinander), Ziel im Urlaub, oder Bash-Limit erreicht.",
        "rules_panel_faq_2_q": "Was ist Push?",
        "rules_panel_faq_2_a": "Absichtlich unfairen Vorteil verschaffen — z. B. Schenken, absichtlich verlorene Flotten, Schrottfeld-Tricks.",
        "rules_panel_faq_3_q": "Was passiert im Urlaubsmodus?",
        "rules_panel_faq_3_a": "Keine Flotten, kein Trader Hub, Schutz vor Angriff/Spionage. Mindestdauer 48 Stunden.",
        "rules_panel_faq_4_q": "Darf ich zwei Accounts spielen?",
        "rules_panel_faq_4_a": "Nein — ein Account pro Person pro Universum.",
        "rules_panel_faq_5_q": "Was passiert, wenn ich einen Bug finde?",
        "rules_panel_faq_5_a": "Melden — nicht farmen. Bewusstes Ausnutzen kann zu Sanktionen führen.",
        "rules_panel_faq_6_q": "Gibt es Monde?",
        "rules_panel_faq_6_a": "Nein — Genesis Colonies hat kein Mond-System.",
    },
    "en": {
        "rules_panel_intro": (
            "Official rules of Genesis Colonies — familiar to OGame players, tailored to our mechanics. "
            "Technical limits are enforced by the server; behaviour rules are reviewed by the team. "
            "When in doubt, the Genesis team decides."
        ),
        "rules_panel_version": "As of 2026-06-27 · Rules v1.2",
        "rules_panel_faq_title": "FAQ",
        "rules_panel_support_cta": "Contact support",
        "rules_panel_general_title": "General & fair play",
        "rules_panel_general_body": (
            "Respectful conduct — no insults, discrimination, hate speech, or threats.\n\n"
            "Report bugs (support/ticket) — do not exploit them. Deliberate exploiting can be punished even without an explicit rule.\n\n"
            "No bots, macros, clickers, or automation. No real-money trading (RMT) of accounts or resources.\n\n"
            "The game runs on the server — the UI shows server data only.\n\n"
            "Anything that obviously bypasses mechanics can be sanctioned — even if not listed here."
        ),
        "rules_panel_accounts_title": "Accounts",
        "rules_panel_accounts_body": (
            "**One account per person per universe.** No farm accounts, spy alts, or ranking manipulation.\n\n"
            "**Permanent account sharing** forbidden — exception: **sitting** (max **48 hours**, no resource transfers).\n\n"
            "**Account sale/trade** for real money or external compensation forbidden."
        ),
        "rules_panel_combat_title": "Combat",
        "rules_panel_combat_body": (
            "**Bash:** At most **5 attacks** on the same **target world** within **24 hours** (rolling). "
            "Per attacker account and target world — **not** per origin world. "
            "Example: 3 from world A + 2 from world B on the **same** target = limit reached.\n\n"
            "**Noob protection:** Attacks only within the **5× score corridor** — unless target **inactive > 3 days**.\n\n"
            "**Espionage:** Unlimited (except vacation targets).\n\n"
            "**Expeditions & recycler:** Unlimited (except while you are in vacation).\n\n"
            "**Hold missions:** Allowed. **Combined attacks (ACS):** planned — until then bash/noob per single attack.\n\n"
            "**No moons** in Genesis Colonies."
        ),
        "rules_panel_push_title": "Push — definition",
        "rules_panel_push_body": (
            "**Push** = intentionally gaining an unfair advantage — not through normal, market-fair mechanics.\n\n"
            "**Forbidden:** large gifts without return · losing fleets on purpose for loot · A→B→C transport chains · "
            "extremely one-sided trade · wreck-field tricks · auction shill bids.\n\n"
            "**Allowed:** fair Trader Hub exchange · combat loot · logistics between **your own** worlds · "
            "alliance help via allowed mechanics at market-near rates."
        ),
        "rules_panel_economy_title": "Economy",
        "rules_panel_economy_body": (
            "**Trader Hub:** Exchange within your **daily limit** (account-wide). Round-trip profit blocked server-side.\n\n"
            "**Logistics:** Between **your own** worlds only — report abuse benefiting third parties.\n\n"
            "Auction house and inventory are separate — push via shill bids forbidden."
        ),
        "rules_panel_vacation_title": "Vacation mode",
        "rules_panel_vacation_body": (
            "**48-hour minimum** after activation.\n\n"
            "While active: **no fleets**, **no Trader Hub**, protection from attacks and espionage.\n\n"
            "Production, research, and build queues continue (current behaviour).\n\n"
            "Activation only with no active fleets, auction bids, or open queues."
        ),
        "rules_panel_empire_title": "Empire (Genesis-specific)",
        "rules_panel_empire_body": (
            "No abuse of **Planet Evolution** (DNA, traits, events) · **Command Map** / colonization · "
            "**Galactic Directives** (voting) · **Imperial Directives** · expedition event bugs · "
            "legendary discoveries or establishment exploits."
        ),
        "rules_panel_community_title": "Community & chat",
        "rules_panel_community_body": (
            "**Chat:** No spam, ads, RMT offers, NSFW, political/extremist content, insults.\n\n"
            "**Names:** No offensive, racist, or misleading team/admin names.\n\n"
            "**Alliance:** Coordination allowed — no multiaccount support, no push, no permanent sharing.\n\n"
            "**Discord:** Same fair-play standards; official Discord may have extra rules."
        ),
        "rules_panel_sanctions_title": "Sanctions & support",
        "rules_panel_sanctions_body": (
            "Depending on severity: warning · temporary ban · permanent ban · resource/fleet removal · rollback · deletion.\n\n"
            "**Your mistakes:** No claim to restore lost fleets or resources.\n\n"
            "**Server bugs:** Team reviews proven cases — decision is final.\n\n"
            "Rules may evolve — changes will be announced."
        ),
        "rules_panel_faq_0_q": "How many attacks may I launch on one world?",
        "rules_panel_faq_0_a": "At most 5 within 24 hours on the same target world — no matter which of your worlds attacks.",
        "rules_panel_faq_1_q": "Why can't I attack someone?",
        "rules_panel_faq_1_a": "Common: noob protection (scores too far apart), target in vacation, or bash limit reached.",
        "rules_panel_faq_2_q": "What is push?",
        "rules_panel_faq_2_a": "Intentionally gaining an unfair advantage — e.g. gifting, losing fleets on purpose, wreck tricks.",
        "rules_panel_faq_3_q": "What happens in vacation mode?",
        "rules_panel_faq_3_a": "No fleets, no Trader Hub, protected from attack/spy. Minimum 48 hours.",
        "rules_panel_faq_4_q": "May I play two accounts?",
        "rules_panel_faq_4_a": "No — one account per person per universe.",
        "rules_panel_faq_5_q": "What if I find a bug?",
        "rules_panel_faq_5_a": "Report it — do not farm it. Deliberate abuse can lead to sanctions.",
        "rules_panel_faq_6_q": "Are there moons?",
        "rules_panel_faq_6_a": "No — Genesis Colonies has no moon system.",
    },
}


def _fill_locale_from_en(locale: str, base: Dict[str, str]) -> Dict[str, str]:
    """Use EN strings for locales without a full custom translation yet."""
    en = RULES_PANEL_STRINGS["en"]
    out = dict(en)
    out.update(base)
    return out


# fr/es/pl/tr/ru/pt: partial overrides + EN fallback for new keys
RULES_PANEL_STRINGS["fr"] = _fill_locale_from_en(
    "fr",
    {
        "rules_panel_intro": (
            "Règles officielles de Genesis Colonies — familières aux joueurs d'OGame. "
            "Limites techniques appliquées par le serveur. En cas de doute, l'équipe Genesis décide."
        ),
        "rules_panel_version": "Version du 27.06.2026 · règles v1.2",
        "rules_panel_faq_title": "FAQ",
        "rules_panel_support_cta": "Contacter le support",
        "rules_panel_general_title": "Général & fair-play",
        "rules_panel_push_title": "Push — définition",
        "rules_panel_community_title": "Communauté & chat",
    },
)
RULES_PANEL_STRINGS["es"] = _fill_locale_from_en(
    "es",
    {
        "rules_panel_intro": "Reglas oficiales de Genesis Colonies. Ante la duda, decide el equipo Genesis.",
        "rules_panel_version": "27.06.2026 · reglas v1.2",
        "rules_panel_faq_title": "Preguntas frecuentes",
        "rules_panel_support_cta": "Contactar soporte",
        "rules_panel_push_title": "Push — definición",
        "rules_panel_community_title": "Comunidad y chat",
    },
)
for loc in ("pl", "tr", "ru", "pt"):
    RULES_PANEL_STRINGS[loc] = dict(RULES_PANEL_STRINGS["en"])


def all_rules_panel_locale_keys() -> Tuple[str, ...]:
    keys = {INTRO_KEY, FAQ_TITLE_KEY, VERSION_KEY, SUPPORT_CTA_KEY}
    for section in RULES_PANEL_SECTIONS:
        keys.add(str(section["title_key"]))
        keys.add(str(section["body_key"]))
    for item in RULES_PANEL_FAQ:
        keys.add(str(item["q_key"]))
        keys.add(str(item["a_key"]))
    return tuple(sorted(keys))


def rules_panel_template_context() -> Dict[str, Any]:
    return {
        "RULES_PANEL_SECTIONS": RULES_PANEL_SECTIONS,
        "RULES_PANEL_FAQ": RULES_PANEL_FAQ,
        "RULES_PANEL_INTRO_KEY": INTRO_KEY,
        "RULES_PANEL_FAQ_TITLE_KEY": FAQ_TITLE_KEY,
        "RULES_PANEL_VERSION_KEY": VERSION_KEY,
        "RULES_PANEL_SUPPORT_CTA_KEY": SUPPORT_CTA_KEY,
    }
