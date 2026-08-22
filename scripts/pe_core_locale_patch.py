"""One-shot helper for GC-PE-CORE-LOCALES-001. Removed before merge."""
from __future__ import annotations

import json
from pathlib import Path

KEYS = [
    "pe_title",
    "pe_homeworld",
    "pe_development_stage",
    "pe_planet_type",
    "pe_planet_score",
    "pe_economy_short",
    "pe_hero_bonuses_title",
    "pe_status_stable",
    "pe_status_pressure",
    "pe_status_crisis",
    "pe_event_urgent",
    "pe_class_barren",
    "pe_class_gas_moon",
    "pe_class_ice",
    "pe_class_oceanic",
    "pe_class_ruin",
    "pe_class_terrestrial",
    "pe_class_volcanic",
    "pe_rarity_common",
    "pe_rarity_uncommon",
    "pe_rarity_rare",
    "pe_rarity_epic",
    "pe_rarity_legendary",
    "pe_expansion_visual_hint",
    "pe_research_remaining",
    "pe_spec_best_match",
    "pe_view_details",
    "pe_xp",
    "pe_xp_remaining",
    "pe_event_state_active",
    "pe_event_state_expired",
    "pe_event_state_pending",
    "pe_event_state_resolved",
    "pe_event_state_unknown",
    "pe_experimental_t1",
    "pe_gov_t1",
    "pe_military_t2",
    "pe_science_t1",
    "pe_trade_t2",
]

VALUES = {
    "de": [
        "Planet-Entwicklung", "Heimatwelt", "Entwicklungsstufe", "Planetentyp", "Planetenwert", "Produktion", "Planetenboni",
        "Stabil", "Unter Druck", "In Krise", "Dringend",
        "Kargwelt", "Gasriesen-Mond", "Eiswelt", "Ozeanwelt", "Ruinenwelt", "Felsplanet", "Vulkanwelt",
        "Gewöhnlich", "Ungewöhnlich", "Selten", "Episch", "Legendär",
        "Expansionsdetails", "Verbleibend", "Beste DNA-Passung", "Details anzeigen", "Entwicklungspunkte", "Fehlende Punkte",
        "Aktiv", "Abgelaufen", "Ausstehend", "Abgeschlossen", "Unbekannt",
        "Dunkle Materie", "Zivilverwaltung", "Befestigung", "Feld-Labore", "Markt-Protokolle",
    ],
    "en": [
        "Planet Evolution", "Homeworld", "Development stage", "Planet type", "Planet score", "Production", "Planet bonuses",
        "Stable", "Under pressure", "In crisis", "Urgent",
        "Barren world", "Gas giant moon", "Ice world", "Ocean world", "Ruin world", "Rocky planet", "Volcanic world",
        "Common", "Uncommon", "Rare", "Epic", "Legendary",
        "Expansion details", "Remaining", "Best DNA match", "View details", "Development points", "Points remaining",
        "Active", "Expired", "Pending", "Resolved", "Unknown",
        "Dark Matter", "Civil Administration", "Fortification", "Field Labs", "Market Protocols",
    ],
    "fr": [
        "Évolution planétaire", "Monde natal", "Stade de développement", "Type de planète", "Score planétaire", "Production", "Bonus planétaires",
        "Stable", "Sous pression", "En crise", "Urgent",
        "Monde aride", "Lune de géante gazeuse", "Monde glacé", "Monde océanique", "Monde en ruine", "Planète rocheuse", "Monde volcanique",
        "Commun", "Peu commun", "Rare", "Épique", "Légendaire",
        "Détails de l’expansion", "Restant", "Meilleure compatibilité ADN", "Voir les détails", "Points d’évolution", "Points restants",
        "Actif", "Expiré", "En attente", "Résolu", "Inconnu",
        "Matière noire", "Administration civile", "Fortification", "Laboratoires de terrain", "Protocoles de marché",
    ],
    "es": [
        "Evolución planetaria", "Mundo natal", "Etapa de desarrollo", "Tipo de planeta", "Puntuación del planeta", "Producción", "Bonificaciones del planeta",
        "Estable", "Bajo presión", "En crisis", "Urgente",
        "Mundo árido", "Luna de gigante gaseoso", "Mundo helado", "Mundo oceánico", "Mundo en ruinas", "Planeta rocoso", "Mundo volcánico",
        "Común", "Poco común", "Raro", "Épico", "Legendario",
        "Detalles de expansión", "Restante", "Mejor coincidencia de ADN", "Ver detalles", "Puntos de evolución", "Puntos restantes",
        "Activo", "Expirado", "Pendiente", "Resuelto", "Desconocido",
        "Materia oscura", "Administración civil", "Fortificación", "Laboratorios de campo", "Protocolos de mercado",
    ],
    "pl": [
        "Ewolucja planety", "Świat macierzysty", "Etap rozwoju", "Typ planety", "Punkty planety", "Produkcja", "Bonusy planety",
        "Stabilny", "Pod presją", "W kryzysie", "Pilne",
        "Jałowy świat", "Księżyc gazowego olbrzyma", "Lodowy świat", "Oceaniczny świat", "Świat ruin", "Skalista planeta", "Wulkaniczny świat",
        "Pospolity", "Niepospolity", "Rzadki", "Epicki", "Legendarny",
        "Szczegóły ekspansji", "Pozostało", "Najlepsze dopasowanie DNA", "Zobacz szczegóły", "Punkty ewolucji", "Pozostałe punkty",
        "Aktywne", "Wygasło", "Oczekujące", "Rozwiązane", "Nieznane",
        "Ciemna materia", "Administracja cywilna", "Fortyfikacja", "Laboratoria terenowe", "Protokoły rynkowe",
    ],
    "tr": [
        "Gezegen Evrimi", "Ana dünya", "Gelişim aşaması", "Gezegen türü", "Gezegen puanı", "Üretim", "Gezegen bonusları",
        "Stabil", "Baskı altında", "Krizde", "Acil",
        "Çorak dünya", "Gaz devi uydusu", "Buz dünyası", "Okyanus dünyası", "Harabe dünya", "Kayalık gezegen", "Volkanik dünya",
        "Yaygın", "Sıra dışı", "Nadir", "Destansı", "Efsanevi",
        "Genişleme ayrıntıları", "Kalan", "En iyi DNA eşleşmesi", "Ayrıntıları görüntüle", "Gelişim puanları", "Kalan puan",
        "Aktif", "Süresi doldu", "Beklemede", "Çözüldü", "Bilinmiyor",
        "Karanlık madde", "Sivil Yönetim", "Tahkimat", "Saha Laboratuvarları", "Pazar Protokolleri",
    ],
    "ru": [
        "Эволюция планеты", "Родной мир", "Этап развития", "Тип планеты", "Рейтинг планеты", "Производство", "Бонусы планеты",
        "Стабильно", "Под давлением", "В кризисе", "Срочно",
        "Безжизненный мир", "Спутник газового гиганта", "Ледяной мир", "Океанический мир", "Мир руин", "Каменистая планета", "Вулканический мир",
        "Обычный", "Необычный", "Редкий", "Эпический", "Легендарный",
        "Подробности экспансии", "Осталось", "Лучшее соответствие ДНК", "Подробнее", "Очки развития", "Осталось очков",
        "Активно", "Истекло", "Ожидает", "Завершено", "Неизвестно",
        "Тёмная материя", "Гражданская администрация", "Укрепления", "Полевые лаборатории", "Рыночные протоколы",
    ],
    "pt": [
        "Evolução planetária", "Mundo natal", "Estágio de desenvolvimento", "Tipo de planeta", "Pontuação do planeta", "Produção", "Bônus do planeta",
        "Estável", "Sob pressão", "Em crise", "Urgente",
        "Mundo árido", "Lua de gigante gasoso", "Mundo gelado", "Mundo oceânico", "Mundo em ruínas", "Planeta rochoso", "Mundo vulcânico",
        "Comum", "Incomum", "Raro", "Épico", "Lendário",
        "Detalhes da expansão", "Restante", "Melhor correspondência de DNA", "Ver detalhes", "Pontos de evolução", "Pontos restantes",
        "Ativo", "Expirado", "Pendente", "Resolvido", "Desconhecido",
        "Matéria escura", "Administração civil", "Fortificação", "Laboratórios de campo", "Protocolos de mercado",
    ],
}

assert all(len(values) == len(KEYS) for values in VALUES.values())
PATCHES = {locale: dict(zip(KEYS, values)) for locale, values in VALUES.items()}

for locale, updates in PATCHES.items():
    path = Path("locales") / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in updates if key not in data]
    if missing:
        raise SystemExit(f"{locale}: missing keys: {missing}")
    data.update(updates)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# Regression-lock the screenshot-critical hero labels for every supported locale.
CRITICAL_KEYS = [
    "pe_homeworld", "pe_status_stable", "pe_development_stage", "pe_planet_type",
    "pe_class_terrestrial", "pe_planet_score", "pe_economy_short", "pe_hero_bonuses_title",
    "pe_event_urgent", "pe_rarity_epic", "pe_rarity_rare",
]
expected = {
    locale: {key: PATCHES[locale][key] for key in CRITICAL_KEYS}
    for locale in VALUES
}

test_path = Path("tests/test_i18n_hardening.py")
marker = "# GC-PE-CORE-LOCALES-001"
text = test_path.read_text(encoding="utf-8")
if marker not in text:
    block = f'''\n\n{marker}\ndef test_planet_evolution_core_labels_are_localized_across_supported_locales():\n    import json\n    from pathlib import Path\n\n    root = Path(__file__).resolve().parents[1]\n    expected = {expected!r}\n    for locale, labels in expected.items():\n        payload = json.loads((root / "locales" / f"{{locale}}.json").read_text(encoding="utf-8"))\n        for key, value in labels.items():\n            assert payload[key] == value, f"{{locale}}: {{key}} = {{payload[key]!r}}, expected {{value!r}}"\n'''
    test_path.write_text(text + block, encoding="utf-8")
