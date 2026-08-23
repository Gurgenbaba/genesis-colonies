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

# GC-I18N-VISIBLE-ROUND2-001
def test_visible_i18n_round2_planet_evolution_labels_across_all_locales():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    expected = {'de': {'pe_ecology_t1': 'Biomasse-Extraktion', 'pe_event_choice_bribe': 'Bestechen', 'pe_event_choice_shutdown_ai': 'KI abschalten', 'pe_import_deficit': 'Importdefizit', 'pe_policy_archetype': 'Kultur-Archetyp:', 'pe_spec_synergy': 'Passt zu deiner DNA:', 'pe_stat_events': 'Abgeschlossene Events', 'pe_tab_events': 'Ereignisse', 'pe_trait_badge_positive': 'Vorteil', 'pe_warn_energy': 'Energieengpass', 'pe_warn_failure': 'Planet in der Krise'}, 'en': {'pe_ecology_t1': 'Biomass Extraction', 'pe_event_choice_bribe': 'Bribe', 'pe_event_choice_shutdown_ai': 'Shut down AI', 'pe_import_deficit': 'Import deficit', 'pe_policy_archetype': 'Culture archetype:', 'pe_spec_synergy': 'Matches your DNA:', 'pe_stat_events': 'Events completed', 'pe_tab_events': 'Events', 'pe_trait_badge_positive': 'Advantage', 'pe_warn_energy': 'Energy shortage', 'pe_warn_failure': 'Planet in crisis'}, 'fr': {'pe_ecology_t1': 'Extraction de biomasse', 'pe_event_choice_bribe': 'Corrompre', 'pe_event_choice_shutdown_ai': 'Désactiver l’IA', 'pe_import_deficit': 'Déficit d’importation', 'pe_policy_archetype': 'Archétype culturel :', 'pe_spec_synergy': 'Correspond à votre ADN :', 'pe_stat_events': 'Événements terminés', 'pe_tab_events': 'Événements', 'pe_trait_badge_positive': 'Avantage', 'pe_warn_energy': 'Pénurie d’énergie', 'pe_warn_failure': 'Planète en crise'}, 'es': {'pe_ecology_t1': 'Extracción de biomasa', 'pe_event_choice_bribe': 'Sobornar', 'pe_event_choice_shutdown_ai': 'Apagar IA', 'pe_import_deficit': 'Déficit de importación', 'pe_policy_archetype': 'Arquetipo cultural:', 'pe_spec_synergy': 'Coincide con tu ADN:', 'pe_stat_events': 'Eventos completados', 'pe_tab_events': 'Eventos', 'pe_trait_badge_positive': 'Ventaja', 'pe_warn_energy': 'Déficit de energía', 'pe_warn_failure': 'Planeta en crisis'}, 'pl': {'pe_ecology_t1': 'Ekstrakcja biomasy', 'pe_event_choice_bribe': 'Przekup', 'pe_event_choice_shutdown_ai': 'Wyłącz SI', 'pe_import_deficit': 'Deficyt importu', 'pe_policy_archetype': 'Archetyp kultury:', 'pe_spec_synergy': 'Pasuje do twojego DNA:', 'pe_stat_events': 'Ukończone wydarzenia', 'pe_tab_events': 'Wydarzenia', 'pe_trait_badge_positive': 'Zaleta', 'pe_warn_energy': 'Niedobór energii', 'pe_warn_failure': 'Planeta w kryzysie'}, 'tr': {'pe_ecology_t1': 'Biyokütle çıkarımı', 'pe_event_choice_bribe': 'Rüşvet ver', 'pe_event_choice_shutdown_ai': 'YZ’yi kapat', 'pe_import_deficit': 'İthalat açığı', 'pe_policy_archetype': 'Kültür arketipi:', 'pe_spec_synergy': 'DNA’nla uyumlu:', 'pe_stat_events': 'Tamamlanan etkinlikler', 'pe_tab_events': 'Etkinlikler', 'pe_trait_badge_positive': 'Avantaj', 'pe_warn_energy': 'Enerji sıkıntısı', 'pe_warn_failure': 'Gezegen krizde'}, 'ru': {'pe_ecology_t1': 'Добыча биомассы', 'pe_event_choice_bribe': 'Подкупить', 'pe_event_choice_shutdown_ai': 'Отключить ИИ', 'pe_import_deficit': 'Дефицит импорта', 'pe_policy_archetype': 'Культурный архетип:', 'pe_spec_synergy': 'Соответствует вашей ДНК:', 'pe_stat_events': 'События завершены', 'pe_tab_events': 'События', 'pe_trait_badge_positive': 'Преимущество', 'pe_warn_energy': 'Дефицит энергии', 'pe_warn_failure': 'Планета в кризисе'}, 'pt': {'pe_ecology_t1': 'Extração de biomassa', 'pe_event_choice_bribe': 'Subornar', 'pe_event_choice_shutdown_ai': 'Desligar IA', 'pe_import_deficit': 'Déficit de importação', 'pe_policy_archetype': 'Arquétipo cultural:', 'pe_spec_synergy': 'Combina com seu DNA:', 'pe_stat_events': 'Eventos concluídos', 'pe_tab_events': 'Eventos', 'pe_trait_badge_positive': 'Vantagem', 'pe_warn_energy': 'Falta de energia', 'pe_warn_failure': 'Planeta em crise'}}
    for locale, labels in expected.items():
        payload = json.loads((root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        for key, value in labels.items():
            assert payload[key] == value, f"{locale}: {key} = {payload[key]!r}"


def test_visible_i18n_round2_english_global_leaks_are_fixed():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "locales" / "en.json").read_text(encoding="utf-8"))
    expected = {'action_upgrade': 'Start upgrade', 'landing_badge_nop2w': '🚫 No Pay2Win', 'landing_cta_command_center': '🛰 To Command Center', 'landing_cta_logout': 'Log out', 'landing_feature_nop2w_title': 'No Pay2Win', 'landing_label_galaxies': 'Galaxies', 'landing_label_production': 'Production', 'landing_label_start_resources': 'Starting resources', 'landing_label_universe': 'Universe', 'landing_roadmap_defense': 'Defense', 'landing_roadmap_galaxy': 'Galaxy Map', 'landing_section_what_title': 'What awaits you?', 'landing_status_online': 'Online'}
    for key, value in expected.items():
        assert payload[key] == value, f"en: {key} = {payload[key]!r}"


def test_i18n_research_config_has_no_display_literals():
    source = (ROOT / "game" / "research.py").read_text(encoding="utf-8")
    start = source.index("RESEARCH_TECHS: Dict[str, Dict[str, Any]] = {")
    end = source.index("# Account-wide parallel fleet movements", start)
    config = source[start:end]

    raw_fields = [
        line.strip()
        for line in config.splitlines()
        if line.strip().startswith(('"label":', '"description":'))
    ]
    assert not raw_fields, raw_fields
    assert source.count('tr(str(cfg.get("label_key") or tech))') == 2
    assert source.count('tr(str(cfg.get("description_key") or f"desc_{tech}"))') == 2


def test_i18n_phase3_support_player_ui_uses_locale_ssot():
    support_py = (ROOT / "game" / "support.py").read_text(encoding="utf-8")
    support_tpl = (ROOT / "templates" / "partials" / "special_panel.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")

    for literal in ("Offen", "In Bearbeitung", "Geschlossen", "Niedrig", "Allgemein"):
        assert literal not in support_py
    assert 'from .i18n import tr' in support_py
    assert 'tr("support_sender_you")' in support_py
    assert 'tr("support_sender_player")' in support_py

    for literal in (
        "Neues Support-Ticket erstellen.",
        ">Betreff<",
        ">Kategorie<",
        ">Prioritaet<",
        ">Ticket senden<",
        ">Meine Tickets<",
        ">Ticketliste<",
        ">Aktualisieren<",
        "Noch keine Tickets vorhanden.",
    ):
        assert literal not in support_tpl
    assert "T('support_my_tickets')" in support_tpl
    assert "T('support_message_placeholder')" in support_tpl

    for literal in ('"Antwort schreiben..."', '"Antwort senden"', '"Ticket schliessen"', "'Antwort schreiben...'", "'Antwort senden'", "'Ticket schliessen'"):
        assert literal not in main_js
    assert 'tf("support_message_meta"' in main_js
    assert 't("support_reply_placeholder")' in main_js
    assert 't("support_reply_send")' in main_js
    assert 't("support_close_ticket")' in main_js


def test_world_boss_help_uses_true_document_top_layer():
    template = (ROOT / "templates" / "world_boss.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "world_boss_help_modal.css").read_text(encoding="utf-8")
    portal = (ROOT / "static" / "js" / "pages" / "world_boss_help.js").read_text(encoding="utf-8")

    assert "GC_ASSET_VERSION }}-wbhelp3" in template
    assert "world_boss_help.js" in template
    assert "z-index: 20000" in css
    assert "document.body.appendChild(modal)" in portal
    assert "restoreModal(modal)" in portal

