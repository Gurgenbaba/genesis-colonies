"""GC-I18N-HARDENING regression guards."""

from __future__ import annotations

from pathlib import Path

from scripts.audit_visible_i18n import (
    ROOT,
    _js_findings,
    _placeholder_signature,
    _python_findings,
    _template_findings,
    audit_locale_parity,
)


def test_i18n_all_supported_locales_have_exact_key_and_placeholder_parity():
    failures = audit_locale_parity()
    assert not failures, "\n".join(failures[:30])


def test_i18n_placeholder_signature_tracks_percent_and_brace_names():
    assert _placeholder_signature("%(name)s — {count}") == (("name",), ("count",))
    assert _placeholder_signature("{count} / {count} · %(name)s") == (("name",), ("count",))


def test_i18n_template_scanner_flags_visible_literal_text_and_attributes():
    path = ROOT / "templates" / "_i18n_scanner_fixture.html"
    findings = _template_findings(
        path,
        [
            '<button aria-label="Send fleet">Attack now</button>',
            '<button aria-label="{{ T(\'fleet_send\', \'Senden\') }}">{{ T("fleet_attack", "Angreifen") }}</button>',
        ],
        None,
    )
    rendered = [f.render() for f in findings]
    assert any("Send fleet" in item for item in rendered)
    assert any("Attack now" in item for item in rendered)
    assert not any("fleet_send" in item or "fleet_attack" in item for item in rendered)


def test_i18n_js_scanner_flags_direct_player_copy_but_not_translation_calls():
    path = ROOT / "static" / "_i18n_scanner_fixture.js"
    findings = _js_findings(
        path,
        [
            'button.textContent = "Send fleet";',
            'button.textContent = t("fleet_send");',
            'node.setAttribute("aria-label", "Open research details");',
        ],
        None,
    )
    rendered = [f.render() for f in findings]
    assert any("Send fleet" in item for item in rendered)
    assert any("Open research details" in item for item in rendered)
    assert len(rendered) == 2


def test_i18n_python_scanner_flags_literal_ui_payload_copy():
    path = ROOT / "game" / "_i18n_scanner_fixture.py"
    findings = _python_findings(
        path,
        [
            'payload = {"title": "Planet Evolution", "label_key": "planet_evolution_title"}',
            'payload = {"title_key": "planet_evolution_title"}',
        ],
        None,
    )
    assert len(findings) == 1
    assert findings[0].text == "Planet Evolution"


# GC-PE-CORE-LOCALES-001
def test_planet_evolution_core_labels_are_localized_across_supported_locales():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    expected = {'de': {'pe_homeworld': 'Heimatwelt', 'pe_status_stable': 'Stabil', 'pe_development_stage': 'Entwicklungsstufe', 'pe_planet_type': 'Planetentyp', 'pe_class_terrestrial': 'Felsplanet', 'pe_planet_score': 'Planetenwert', 'pe_economy_short': 'Produktion', 'pe_hero_bonuses_title': 'Planetenboni', 'pe_event_urgent': 'Dringend', 'pe_rarity_epic': 'Episch', 'pe_rarity_rare': 'Selten'}, 'en': {'pe_homeworld': 'Homeworld', 'pe_status_stable': 'Stable', 'pe_development_stage': 'Development stage', 'pe_planet_type': 'Planet type', 'pe_class_terrestrial': 'Rocky planet', 'pe_planet_score': 'Planet score', 'pe_economy_short': 'Production', 'pe_hero_bonuses_title': 'Planet bonuses', 'pe_event_urgent': 'Urgent', 'pe_rarity_epic': 'Epic', 'pe_rarity_rare': 'Rare'}, 'fr': {'pe_homeworld': 'Monde natal', 'pe_status_stable': 'Stable', 'pe_development_stage': 'Stade de développement', 'pe_planet_type': 'Type de planète', 'pe_class_terrestrial': 'Planète rocheuse', 'pe_planet_score': 'Score planétaire', 'pe_economy_short': 'Production', 'pe_hero_bonuses_title': 'Bonus planétaires', 'pe_event_urgent': 'Urgent', 'pe_rarity_epic': 'Épique', 'pe_rarity_rare': 'Rare'}, 'es': {'pe_homeworld': 'Mundo natal', 'pe_status_stable': 'Estable', 'pe_development_stage': 'Etapa de desarrollo', 'pe_planet_type': 'Tipo de planeta', 'pe_class_terrestrial': 'Planeta rocoso', 'pe_planet_score': 'Puntuación del planeta', 'pe_economy_short': 'Producción', 'pe_hero_bonuses_title': 'Bonificaciones del planeta', 'pe_event_urgent': 'Urgente', 'pe_rarity_epic': 'Épico', 'pe_rarity_rare': 'Raro'}, 'pl': {'pe_homeworld': 'Świat macierzysty', 'pe_status_stable': 'Stabilny', 'pe_development_stage': 'Etap rozwoju', 'pe_planet_type': 'Typ planety', 'pe_class_terrestrial': 'Skalista planeta', 'pe_planet_score': 'Punkty planety', 'pe_economy_short': 'Produkcja', 'pe_hero_bonuses_title': 'Bonusy planety', 'pe_event_urgent': 'Pilne', 'pe_rarity_epic': 'Epicki', 'pe_rarity_rare': 'Rzadki'}, 'tr': {'pe_homeworld': 'Ana dünya', 'pe_status_stable': 'Stabil', 'pe_development_stage': 'Gelişim aşaması', 'pe_planet_type': 'Gezegen türü', 'pe_class_terrestrial': 'Kayalık gezegen', 'pe_planet_score': 'Gezegen puanı', 'pe_economy_short': 'Üretim', 'pe_hero_bonuses_title': 'Gezegen bonusları', 'pe_event_urgent': 'Acil', 'pe_rarity_epic': 'Destansı', 'pe_rarity_rare': 'Nadir'}, 'ru': {'pe_homeworld': 'Родной мир', 'pe_status_stable': 'Стабильно', 'pe_development_stage': 'Этап развития', 'pe_planet_type': 'Тип планеты', 'pe_class_terrestrial': 'Каменистая планета', 'pe_planet_score': 'Рейтинг планеты', 'pe_economy_short': 'Производство', 'pe_hero_bonuses_title': 'Бонусы планеты', 'pe_event_urgent': 'Срочно', 'pe_rarity_epic': 'Эпический', 'pe_rarity_rare': 'Редкий'}, 'pt': {'pe_homeworld': 'Mundo natal', 'pe_status_stable': 'Estável', 'pe_development_stage': 'Estágio de desenvolvimento', 'pe_planet_type': 'Tipo de planeta', 'pe_class_terrestrial': 'Planeta rochoso', 'pe_planet_score': 'Pontuação do planeta', 'pe_economy_short': 'Produção', 'pe_hero_bonuses_title': 'Bônus do planeta', 'pe_event_urgent': 'Urgente', 'pe_rarity_epic': 'Épico', 'pe_rarity_rare': 'Raro'}}
    for locale, labels in expected.items():
        payload = json.loads((root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        for key, value in labels.items():
            assert payload[key] == value, f"{locale}: {key} = {payload[key]!r}, expected {value!r}"
