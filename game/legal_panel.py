"""Player-facing legal documents (Impressum, Datenschutz, AGB, Widerruf).

Owner for public `/legal` and the ingame imprint special window.
Stammdaten + document bodies live here; locales are synced from LEGAL_PANEL_STRINGS.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# --- Operator stammdaten (single source) ---
OPERATOR_NAME = "Robert Finn"
OPERATOR_STREET = "Winne Siedlung 32"
OPERATOR_POSTAL = "98507"
OPERATOR_CITY = "Breitungen"
OPERATOR_COUNTRY = "Deutschland"
OPERATOR_EMAIL = "r.finn2303@gmail.com"
OPERATOR_ADDRESS_LINE = f"{OPERATOR_STREET}, {OPERATOR_POSTAL} {OPERATOR_CITY}"
LEGAL_TEXT_VERSION = "v1"
LEGAL_STAND = "01.08.2026"

DOC_IMPRINT = "imprint"
DOC_PRIVACY = "privacy"
DOC_TERMS = "terms"
DOC_WITHDRAWAL = "withdrawal"

LEGAL_DOCS: Tuple[Dict[str, Any], ...] = (
    {
        "id": DOC_IMPRINT,
        "tab_key": "legal_tab_imprint",
        "title_key": "legal_imprint_title",
        "sections": (
            {"title_key": "legal_imprint_provider_title", "body_key": "legal_imprint_provider_body", "open": True},
            {"title_key": "legal_imprint_contact_title", "body_key": "legal_imprint_contact_body", "open": True},
            {"title_key": "legal_imprint_offer_title", "body_key": "legal_imprint_offer_body", "open": False},
            {"title_key": "legal_imprint_liability_title", "body_key": "legal_imprint_liability_body", "open": False},
            {"title_key": "legal_imprint_copyright_title", "body_key": "legal_imprint_copyright_body", "open": False},
        ),
    },
    {
        "id": DOC_PRIVACY,
        "tab_key": "legal_tab_privacy",
        "title_key": "legal_privacy_title",
        "sections": (
            {"title_key": "legal_privacy_controller_title", "body_key": "legal_privacy_controller_body", "open": True},
            {"title_key": "legal_privacy_purposes_title", "body_key": "legal_privacy_purposes_body", "open": False},
            {"title_key": "legal_privacy_recipients_title", "body_key": "legal_privacy_recipients_body", "open": False},
            {"title_key": "legal_privacy_rights_title", "body_key": "legal_privacy_rights_body", "open": False},
            {"title_key": "legal_privacy_retention_title", "body_key": "legal_privacy_retention_body", "open": False},
        ),
    },
    {
        "id": DOC_TERMS,
        "tab_key": "legal_tab_terms",
        "title_key": "legal_terms_title",
        "sections": (
            {"title_key": "legal_terms_scope_title", "body_key": "legal_terms_scope_body", "open": True},
            {"title_key": "legal_terms_contract_title", "body_key": "legal_terms_contract_body", "open": False},
            {"title_key": "legal_terms_digital_title", "body_key": "legal_terms_digital_body", "open": False},
            {"title_key": "legal_terms_refund_title", "body_key": "legal_terms_refund_body", "open": False},
            {"title_key": "legal_terms_liability_title", "body_key": "legal_terms_liability_body", "open": False},
            {"title_key": "legal_terms_final_title", "body_key": "legal_terms_final_body", "open": False},
        ),
    },
    {
        "id": DOC_WITHDRAWAL,
        "tab_key": "legal_tab_withdrawal",
        "title_key": "legal_withdrawal_title",
        "sections": (
            {"title_key": "legal_withdrawal_info_title", "body_key": "legal_withdrawal_info_body", "open": True},
            {"title_key": "legal_withdrawal_digital_title", "body_key": "legal_withdrawal_digital_body", "open": True},
            {"title_key": "legal_withdrawal_howto_title", "body_key": "legal_withdrawal_howto_body", "open": False},
            {"title_key": "legal_withdrawal_form_title", "body_key": "legal_withdrawal_form_body", "open": False},
        ),
    },
)


def _de_strings() -> Dict[str, str]:
    email = OPERATOR_EMAIL
    name = OPERATOR_NAME
    addr = OPERATOR_ADDRESS_LINE
    stand = LEGAL_STAND
    return {
        "legal_tab_imprint": "Impressum",
        "legal_tab_privacy": "Datenschutz",
        "legal_tab_terms": "AGB",
        "legal_tab_withdrawal": "Widerruf",
        "legal_page_title": "Rechtliche Hinweise",
        "legal_page_intro": (
            "Anbieterkennzeichnung, Datenschutz, Nutzungsbedingungen und Widerrufsbelehrung "
            "für Genesis Colonies."
        ),
        "legal_provider_block_title": "Anbieter",
        "legal_contact_form_cta": "Kontaktformular öffnen",
        "legal_contact_email_label": "E-Mail",
        "legal_stand_label": f"Stand: {stand} · Textfassung {LEGAL_TEXT_VERSION}",
        "legal_open_public": "Vollständige Fassung öffnen",
        "legal_shop_footer": (
            "Digitale Inhalte · nach Gutschrift kein Widerruf · "
            "Details: AGB / Widerrufsbelehrung"
        ),
        "legal_ack_agb_label": (
            "Ich akzeptiere die AGB und die Widerrufsbelehrung."
        ),
        "legal_ack_digital_label": (
            "Ich verlange die sofortige Ausführung der digitalen Inhalte und weiß, dass ich "
            "mein Widerrufsrecht mit Beginn der Ausführung verliere. Virtuelle Güter werden "
            "nach Gutschrift nicht erstattet (Ausnahme: technische Nichtlieferung)."
        ),
        "legal_ack_required": "Bitte die rechtlichen Hinweise vor dem Kauf bestätigen.",
        "legal_imprint_title": "Impressum",
        "legal_imprint_provider_title": "Anbieterkennzeichnung",
        "legal_imprint_provider_body": (
            f"**Anbieter:** {name}\n\n"
            f"**Anschrift:** {addr}, {OPERATOR_COUNTRY}\n\n"
            f"Verantwortlich für die Inhalte dieses Angebots: {name}."
        ),
        "legal_imprint_contact_title": "Kontakt",
        "legal_imprint_contact_body": (
            f"**E-Mail:** {email}\n\n"
            "Eine Telefonnummer wird nicht angegeben. Stattdessen steht ein "
            "**elektronisches Kontaktformular** (Ingame-Support) zur Verfügung — "
            "nach Login über Support in der Utility-Leiste. Nicht-Spieler erreichen "
            f"den Anbieter jederzeit unter {email}."
        ),
        "legal_imprint_offer_title": "Angebot",
        "legal_imprint_offer_body": (
            "Genesis Colonies ist ein browserbasiertes Strategiespiel. Über den Ingame-Shop "
            "werden **digitale Inhalte / virtuelle Güter** (z. B. Season Pass, Timekeeper, "
            "Boosters, Container, Cosmetics) gegen Entgelt angeboten. Es erfolgt keine "
            "physische Warenlieferung."
        ),
        "legal_imprint_liability_title": "Haftungshinweis",
        "legal_imprint_liability_body": (
            "Inhalte und Spielmechaniken können sich ändern. Für die ständige Verfügbarkeit "
            "des Dienstes wird keine Garantie übernommen. Zwangende gesetzliche "
            "Haftungsvorschriften bleiben unberührt."
        ),
        "legal_imprint_copyright_title": "Urheberrecht",
        "legal_imprint_copyright_body": (
            "Spielcode, Texte, UI und eigene Assets unterliegen dem Urheberrecht des Anbieters, "
            "soweit nicht anders gekennzeichnet. Drittinhalte bleiben Eigentum der jeweiligen "
            "Rechteinhaber."
        ),
        "legal_privacy_title": "Datenschutzerklärung",
        "legal_privacy_controller_title": "Verantwortlicher",
        "legal_privacy_controller_body": (
            f"Verantwortlich für die Verarbeitung personenbezogener Daten:\n\n"
            f"{name}\n{addr}\nE-Mail: {email}"
        ),
        "legal_privacy_purposes_title": "Zwecke und Rechtsgrundlagen",
        "legal_privacy_purposes_body": (
            "Wir verarbeiten Daten zur Bereitstellung des Spiels und der Nutzerkonten "
            "(Vertragserfüllung), zur Betrugs- und Missbrauchsprävention (berechtigtes Interesse), "
            "zur Bearbeitung von Support-Anfragen sowie zur Abwicklung von Käufen digitaler "
            "Inhalte über Zahlungsdienstleister (Vertragserfüllung). Soweit Einwilligungen "
            "erforderlich sind (z. B. optionale Cookies), ist die Einwilligung Rechtsgrundlage."
        ),
        "legal_privacy_recipients_title": "Empfänger / Auftragsverarbeitung",
        "legal_privacy_recipients_body": (
            "Je nach Nutzung können Daten an folgende Kategorien von Empfängern gelangen:\n\n"
            "- **Hosting-Anbieter** (Betrieb der Spielserver)\n"
            "- **PayPal** und ggf. **Stripe** (Zahlungsabwicklung im Shop)\n"
            "- **Discord** (optionaler Login / Support-Benachrichtigungen)\n\n"
            "Eine Übermittlung in Drittländer erfolgt nur, soweit der jeweilige Anbieter dies "
            "technisch vorsieht und geeignete Garantien greifen."
        ),
        "legal_privacy_rights_title": "Ihre Rechte",
        "legal_privacy_rights_body": (
            "Sie haben nach Maßgabe der DSGVO insbesondere Rechte auf Auskunft, Berichtigung, "
            "Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. "
            "Account-Löschung kann in den Spieleinstellungen vorgemerkt werden. Beschwerden "
            "können bei einer Datenschutzaufsichtsbehörde eingereicht werden."
        ),
        "legal_privacy_retention_title": "Speicherdauer",
        "legal_privacy_retention_body": (
            "Kontodaten werden für die Dauer der Mitgliedschaft und danach gemäß gesetzlicher "
            "Aufbewahrungsfristen (z. B. handels-/steuerrechtlich bei Käufen) gespeichert. "
            "Support-Tickets und Bestellnachweise werden so lange aufbewahrt, wie es für "
            "Nachweis und Abwicklung erforderlich ist."
        ),
        "legal_terms_title": "Allgemeine Geschäftsbedingungen",
        "legal_terms_scope_title": "Geltungsbereich",
        "legal_terms_scope_body": (
            f"Diese AGB gelten für den Erwerb digitaler Inhalte im Genesis-Colonies-Shop "
            f"zwischen dem Anbieter ({name}) und dem Kunden (Verbraucher oder Unternehmer). "
            "Ergänzend gelten die Ingame-Spielregeln."
        ),
        "legal_terms_contract_title": "Vertragsschluss und Preise",
        "legal_terms_contract_body": (
            "Das Angebot im Shop ist unverbindlich. Der Vertrag kommt zustande, wenn der Kunde "
            "den Checkout über den Zahlungsdienstleister (PayPal/Stripe) abschließt und die "
            "Zahlung erfolgreich autorisiert wird. Preise verstehen sich in Euro wie im Shop "
            "angezeigt. Es wird keine Umsatzsteuer-Identifikationsnummer ausgewiesen."
        ),
        "legal_terms_digital_title": "Digitale Inhalte / virtuelle Güter",
        "legal_terms_digital_body": (
            "Vertragsgegenstand sind ausschließlich **virtuelle Güter / digitale Inhalte** "
            "(z. B. Freischaltungen, Timekeeper-Zeit, Boosters, Container, Cosmetics). "
            "Eine physische Lieferung findet nicht statt. Die Erfüllung erfolgt durch "
            "**sofortige Gutschrift bzw. Freischaltung** im Spielaccount nach erfolgreicher Zahlung."
        ),
        "legal_terms_refund_title": "Erstattung / Widerruf",
        "legal_terms_refund_body": (
            "Nach Beginn der Ausführung digitaler Inhalte und wirksamer Belehrung "
            "(§ 356 Abs. 5 BGB) besteht **kein Widerrufsrecht**. Nach Gutschrift virtueller "
            "Güter erfolgt **keine freiwillige Erstattung** und kein Rückgängigmachen bereits "
            "genutzter Vorteile.\n\n"
            "**Ausnahme:** Technische Nichtlieferung — Zahlung ist erfolgt, die Leistung wurde "
            "aber nicht gutgeschrieben. In diesem Fall erfolgt Nachgutschrift oder Erstattung "
            "über den Zahlungsanbieter (Support-Kategorie Zahlung/Billing).\n\n"
            "Zwingende gesetzliche Rechte bleiben unberührt."
        ),
        "legal_terms_liability_title": "Haftung",
        "legal_terms_liability_body": (
            "Für Vorsatz und grobe Fahrlässigkeit sowie bei Verletzung von Leben, Körper und "
            "Gesundheit haftet der Anbieter unbeschränkt. Bei leichter Fahrlässigkeit ist die "
            "Haftung auf die Verletzung wesentlicher Vertragspflichten und auf den "
            "vorhersehbaren, vertragstypischen Schaden begrenzt, soweit gesetzlich zulässig. "
            "Die Verfügbarkeit des Spiels kann eingeschränkt sein (Wartung, Störungen)."
        ),
        "legal_terms_final_title": "Schlussbestimmungen",
        "legal_terms_final_body": (
            "Es gilt das Recht der Bundesrepublik Deutschland unter Ausschluss des UN-Kaufrechts, "
            "soweit zwingendes Verbraucherschutzrecht am Wohnsitz des Verbrauchers nicht "
            "entgegensteht. Sollten einzelne Bestimmungen unwirksam sein, bleibt der Rest wirksam."
        ),
        "legal_withdrawal_title": "Widerrufsbelehrung",
        "legal_withdrawal_info_title": "Widerrufsrecht",
        "legal_withdrawal_info_body": (
            "Verbrauchern steht grundsätzlich ein Widerrufsrecht von 14 Tagen zu. Die Frist "
            "beginnt mit Vertragsschluss. Um Ihr Widerrufsrecht auszuüben, müssen Sie uns "
            f"({name}, {addr}, E-Mail: {email}) mittels einer eindeutigen Erklärung informieren."
        ),
        "legal_withdrawal_digital_title": "Erlöschen bei digitalen Inhalten",
        "legal_withdrawal_digital_body": (
            "Das Widerrufsrecht erlischt bei Verträgen über die Lieferung von digitalen Inhalten, "
            "die nicht auf einem körperlichen Datenträger geliefert werden, wenn der Unternehmer "
            "mit der Ausführung des Vertrags begonnen hat, nachdem der Verbraucher "
            "**ausdrücklich zugestimmt** hat, dass der Unternehmer mit der Ausführung vor "
            "Ablauf der Widerrufsfrist beginnt, und der Verbraucher seine Kenntnis davon "
            "bestätigt hat, dass er durch seine Zustimmung mit Beginn der Ausführung "
            "sein Widerrufsrecht verliert (§ 356 Abs. 5 BGB).\n\n"
            "**Praxis Genesis Colonies:** Digitale Inhalte werden unmittelbar nach erfolgreicher "
            "Zahlung gutgeschrieben. Mit der Doppelbestätigung im Checkout und Beginn der "
            "Ausführung erlischt das Widerrufsrecht. Nach Gutschrift erfolgt keine freiwillige "
            "Erstattung virtueller Güter."
        ),
        "legal_withdrawal_howto_title": "Widerruf erklären",
        "legal_withdrawal_howto_body": (
            f"Widerrufserklärungen richten Sie an: {email} oder — nach Login — über das "
            "Ingame-Support-Formular (Kategorie Zahlung/Billing), soweit ein Widerruf "
            "noch nicht nach § 356 Abs. 5 BGB erloschen ist."
        ),
        "legal_withdrawal_form_title": "Muster-Widerrufsformular",
        "legal_withdrawal_form_body": (
            f"An {name}, {addr}, {email}:\n\n"
            "Hiermit widerrufe(n) ich/wir den von mir/uns abgeschlossenen Vertrag über den "
            "Kauf der folgenden digitalen Inhalte: …\n"
            "Bestellt am: …\n"
            "Name des/der Verbraucher(s): …\n"
            "Anschrift des/der Verbraucher(s): …\n"
            "Datum: …"
        ),
    }


def _en_strings() -> Dict[str, str]:
    email = OPERATOR_EMAIL
    name = OPERATOR_NAME
    addr = OPERATOR_ADDRESS_LINE
    stand = LEGAL_STAND
    return {
        "legal_tab_imprint": "Imprint",
        "legal_tab_privacy": "Privacy",
        "legal_tab_terms": "Terms",
        "legal_tab_withdrawal": "Withdrawal",
        "legal_page_title": "Legal notices",
        "legal_page_intro": (
            "Provider identification, privacy policy, terms of service and withdrawal "
            "information for Genesis Colonies."
        ),
        "legal_provider_block_title": "Provider",
        "legal_contact_form_cta": "Open contact form",
        "legal_contact_email_label": "Email",
        "legal_stand_label": f"Updated: {stand} · text version {LEGAL_TEXT_VERSION}",
        "legal_open_public": "Open full version",
        "legal_shop_footer": (
            "Digital content · no withdrawal after credit · "
            "Details: Terms / Withdrawal"
        ),
        "legal_ack_agb_label": "I accept the Terms and the Withdrawal policy.",
        "legal_ack_digital_label": (
            "I request immediate performance of the digital content and acknowledge that I "
            "lose my right of withdrawal when performance begins. Virtual goods are not "
            "refunded after credit (exception: technical non-delivery)."
        ),
        "legal_ack_required": "Please confirm the legal notices before purchase.",
        "legal_imprint_title": "Imprint",
        "legal_imprint_provider_title": "Provider identification",
        "legal_imprint_provider_body": (
            f"**Provider:** {name}\n\n"
            f"**Address:** {addr}, {OPERATOR_COUNTRY}\n\n"
            f"Responsible for the content of this service: {name}."
        ),
        "legal_imprint_contact_title": "Contact",
        "legal_imprint_contact_body": (
            f"**Email:** {email}\n\n"
            "No telephone number is provided. An **electronic contact form** (in-game support) "
            "is available after login via Support in the utility bar. Non-players can always "
            f"reach the provider at {email}."
        ),
        "legal_imprint_offer_title": "Offer",
        "legal_imprint_offer_body": (
            "Genesis Colonies is a browser strategy game. The in-game shop offers "
            "**digital content / virtual goods** (e.g. Season Pass, Timekeeper, boosters, "
            "containers, cosmetics) for a fee. No physical goods are shipped."
        ),
        "legal_imprint_liability_title": "Liability",
        "legal_imprint_liability_body": (
            "Content and game mechanics may change. Continuous availability is not guaranteed. "
            "Mandatory statutory liability remains unaffected."
        ),
        "legal_imprint_copyright_title": "Copyright",
        "legal_imprint_copyright_body": (
            "Game code, texts, UI and original assets are copyrighted by the provider unless "
            "otherwise noted. Third-party content remains the property of its owners."
        ),
        "legal_privacy_title": "Privacy policy",
        "legal_privacy_controller_title": "Controller",
        "legal_privacy_controller_body": (
            f"Controller for personal data processing:\n\n"
            f"{name}\n{addr}\nEmail: {email}"
        ),
        "legal_privacy_purposes_title": "Purposes and legal bases",
        "legal_privacy_purposes_body": (
            "We process data to provide the game and accounts (contract performance), to prevent "
            "fraud and abuse (legitimate interest), to handle support requests, and to process "
            "purchases of digital content via payment providers (contract performance). Where "
            "consent is required (e.g. optional cookies), consent is the legal basis."
        ),
        "legal_privacy_recipients_title": "Recipients / processors",
        "legal_privacy_recipients_body": (
            "Depending on use, data may be shared with:\n\n"
            "- **Hosting provider** (game servers)\n"
            "- **PayPal** and optionally **Stripe** (shop payments)\n"
            "- **Discord** (optional login / support notifications)\n\n"
            "Transfers to third countries occur only as provided by those services with "
            "appropriate safeguards."
        ),
        "legal_privacy_rights_title": "Your rights",
        "legal_privacy_rights_body": (
            "Under the GDPR you have rights of access, rectification, erasure, restriction, "
            "portability and objection. Account deletion can be scheduled in game settings. "
            "You may lodge a complaint with a supervisory authority."
        ),
        "legal_privacy_retention_title": "Retention",
        "legal_privacy_retention_body": (
            "Account data is stored for the membership period and thereafter as required by "
            "statutory retention (e.g. commercial/tax records for purchases). Support tickets "
            "and order records are kept as needed for proof and processing."
        ),
        "legal_terms_title": "Terms of service",
        "legal_terms_scope_title": "Scope",
        "legal_terms_scope_body": (
            f"These Terms apply to purchases of digital content in the Genesis Colonies shop "
            f"between the provider ({name}) and the customer. In-game rules apply in addition."
        ),
        "legal_terms_contract_title": "Contract and prices",
        "legal_terms_contract_body": (
            "Shop listings are non-binding. The contract is formed when the customer completes "
            "checkout via the payment provider (PayPal/Stripe) and payment is authorised. "
            "Prices are shown in euro. No VAT identification number is displayed."
        ),
        "legal_terms_digital_title": "Digital content / virtual goods",
        "legal_terms_digital_body": (
            "The subject matter is exclusively **virtual goods / digital content** "
            "(e.g. unlocks, Timekeeper time, boosters, containers, cosmetics). No physical "
            "delivery. Performance is **immediate credit/unlock** in the game account after "
            "successful payment."
        ),
        "legal_terms_refund_title": "Refunds / withdrawal",
        "legal_terms_refund_body": (
            "After performance of digital content begins and the statutory notice is effective "
            "(§ 356 (5) BGB), there is **no right of withdrawal**. After virtual goods are "
            "credited, there is **no voluntary refund** and no reversal of consumed benefits.\n\n"
            "**Exception:** technical non-delivery — payment succeeded but the reward was not "
            "credited. In that case we re-grant or refund via the payment provider "
            "(support category Billing).\n\n"
            "Mandatory statutory rights remain unaffected."
        ),
        "legal_terms_liability_title": "Liability",
        "legal_terms_liability_body": (
            "Liability for intent, gross negligence, and injury to life, body or health is "
            "unlimited. For slight negligence, liability is limited to breach of essential "
            "contractual duties and foreseeable typical damage where legally permitted. "
            "Game availability may be limited (maintenance, outages)."
        ),
        "legal_terms_final_title": "Final provisions",
        "legal_terms_final_body": (
            "German law applies excluding the UN CISG, without prejudice to mandatory consumer "
            "protection at the consumer's residence. If any clause is invalid, the remainder "
            "stays in force."
        ),
        "legal_withdrawal_title": "Withdrawal information",
        "legal_withdrawal_info_title": "Right of withdrawal",
        "legal_withdrawal_info_body": (
            "Consumers generally have a 14-day right of withdrawal from contract conclusion. "
            f"To withdraw, notify {name}, {addr}, email {email} with a clear statement."
        ),
        "legal_withdrawal_digital_title": "Expiry for digital content",
        "legal_withdrawal_digital_body": (
            "The right of withdrawal expires for digital content not supplied on a tangible "
            "medium if the trader has begun performance after the consumer expressly consented "
            "to begin before the withdrawal period ends and acknowledged that this causes loss "
            "of the withdrawal right (§ 356 (5) BGB).\n\n"
            "**Genesis Colonies practice:** Digital content is credited immediately after "
            "successful payment. With the checkout double acknowledgement and start of "
            "performance, the withdrawal right expires. After credit there is no voluntary "
            "refund of virtual goods."
        ),
        "legal_withdrawal_howto_title": "How to withdraw",
        "legal_withdrawal_howto_body": (
            f"Send withdrawal notices to {email} or — after login — via the in-game support "
            "form (Billing), insofar as withdrawal has not yet expired under § 356 (5) BGB."
        ),
        "legal_withdrawal_form_title": "Model withdrawal form",
        "legal_withdrawal_form_body": (
            f"To {name}, {addr}, {email}:\n\n"
            "I/We hereby withdraw from the contract concluded by me/us for the purchase of "
            "the following digital content: …\n"
            "Ordered on: …\n"
            "Name of consumer(s): …\n"
            "Address of consumer(s): …\n"
            "Date: …"
        ),
    }


LEGAL_PANEL_STRINGS: Dict[str, Dict[str, str]] = {
    "de": _de_strings(),
    "en": _en_strings(),
}

for _loc in ("fr", "es", "pl", "tr", "ru", "pt"):
    LEGAL_PANEL_STRINGS[_loc] = dict(LEGAL_PANEL_STRINGS["en"])


def all_legal_panel_locale_keys() -> Tuple[str, ...]:
    return tuple(sorted(LEGAL_PANEL_STRINGS["de"].keys()))


def legal_panel_template_context() -> Dict[str, Any]:
    return {
        "LEGAL_DOCS": LEGAL_DOCS,
        "LEGAL_TEXT_VERSION": LEGAL_TEXT_VERSION,
        "LEGAL_STAND": LEGAL_STAND,
        "LEGAL_OPERATOR_NAME": OPERATOR_NAME,
        "LEGAL_OPERATOR_STREET": OPERATOR_STREET,
        "LEGAL_OPERATOR_POSTAL": OPERATOR_POSTAL,
        "LEGAL_OPERATOR_CITY": OPERATOR_CITY,
        "LEGAL_OPERATOR_COUNTRY": OPERATOR_COUNTRY,
        "LEGAL_OPERATOR_EMAIL": OPERATOR_EMAIL,
        "LEGAL_OPERATOR_ADDRESS_LINE": OPERATOR_ADDRESS_LINE,
    }


def resolve_doc_id(raw: str | None) -> str:
    key = str(raw or DOC_IMPRINT).strip().lower()
    valid = {d["id"] for d in LEGAL_DOCS}
    return key if key in valid else DOC_IMPRINT


def forbidden_hobby_phrases() -> Tuple[str, ...]:
    """Phrases that must not appear in live legal UI (discoverability regression)."""
    return (
        "nicht kommerziell",
        "nicht-kommerziell",
        "Hobbyprojekt",
        "privates Hobbyprojekt",
        "non-commercial hobby",
    )
