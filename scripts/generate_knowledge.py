#!/usr/bin/env python3
"""GC-950B: Generate codex catalog, locale keys, and Discord exports from Master Docs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
GENERATED = ROOT / "generated" / "codex"
DOCS_EXPORT = ROOT / "docs" / "export" / "discord"

# UI chrome — all supported locales (article body: de + en, others fall back to en via i18n)
CODEX_UI: dict[str, dict[str, str]] = {
    "codex_title": {
        "de": "Genesis Codex",
        "en": "Genesis Codex",
        "fr": "Codex Genesis",
        "es": "Códice Genesis",
        "pl": "Kodeks Genesis",
        "tr": "Genesis Codex",
        "ru": "Кодекс Genesis",
        "pt": "Codex Genesis",
    },
    "codex_short": {
        "de": "Codex",
        "en": "Codex",
        "fr": "Codex",
        "es": "Códice",
        "pl": "Kodeks",
        "tr": "Codex",
        "ru": "Кодекс",
        "pt": "Codex",
    },
    "codex_intro": {
        "de": "Wissen über dein Imperium — freigeschaltet, wenn es relevant wird.",
        "en": "Knowledge about your empire — unlocked when it matters.",
        "fr": "Connaissances sur votre empire — débloquées quand c'est pertinent.",
        "es": "Conocimiento de tu imperio — desbloqueado cuando importa.",
        "pl": "Wiedza o imperium — odblokowana, gdy ma znaczenie.",
        "tr": "İmparatorluğun hakkında bilgi — gerektiğinde açılır.",
        "ru": "Знания об империи — открываются, когда это важно.",
        "pt": "Conhecimento do império — desbloqueado quando importa.",
    },
    "codex_learn_more": {
        "de": "Mehr erfahren",
        "en": "Learn more",
        "fr": "En savoir plus",
        "es": "Más información",
        "pl": "Dowiedz się więcej",
        "tr": "Daha fazla",
        "ru": "Подробнее",
        "pt": "Saiba mais",
    },
    "codex_locked": {
        "de": "Gesperrt",
        "en": "Locked",
        "fr": "Verrouillé",
        "es": "Bloqueado",
        "pl": "Zablokowane",
        "tr": "Kilitli",
        "ru": "Закрыто",
        "pt": "Bloqueado",
    },
    "codex_locked_preview_title": {
        "de": "Kurzüberblick",
        "en": "Quick overview",
        "fr": "Aperçu",
        "es": "Resumen rápido",
        "pl": "Krótki przegląd",
        "tr": "Kısa özet",
        "ru": "Краткий обзор",
        "pt": "Visão rápida",
    },
    "codex_related_title": {
        "de": "Verwandte Systeme",
        "en": "Related systems",
        "fr": "Systèmes liés",
        "es": "Sistemas relacionados",
        "pl": "Powiązane systemy",
        "tr": "İlgili sistemler",
        "ru": "Связанные системы",
        "pt": "Sistemas relacionados",
    },
    "codex_faq_title": {
        "de": "Häufige Fragen",
        "en": "FAQ",
        "fr": "FAQ",
        "es": "Preguntas frecuentes",
        "pl": "FAQ",
        "tr": "SSS",
        "ru": "FAQ",
        "pt": "FAQ",
    },
    "codex_commander_tip_title": {
        "de": "Commander-Tipp",
        "en": "Commander tip",
        "fr": "Conseil du commandant",
        "es": "Consejo del comandante",
        "pl": "Wskazówka dowódcy",
        "tr": "Komutan ipucu",
        "ru": "Совет командера",
        "pt": "Dica do comandante",
    },
    "codex_commander_tip_new": {
        "de": "Neu",
        "en": "New",
        "fr": "Nouveau",
        "es": "Nuevo",
        "pl": "Nowy",
        "tr": "Yeni",
        "ru": "Новое",
        "pt": "Novo",
    },
    "codex_band_I": {
        "de": "Erste Stunde",
        "en": "First hour",
        "fr": "Première heure",
        "es": "Primera hora",
        "pl": "Pierwsza godzina",
        "tr": "İlk saat",
        "ru": "Первый час",
        "pt": "Primeira hora",
    },
    "codex_band_II": {
        "de": "Frühes Imperium",
        "en": "Early empire",
        "fr": "Empire naissant",
        "es": "Imperio temprano",
        "pl": "Wczesne imperium",
        "tr": "Erken imparatorluk",
        "ru": "Раннее империя",
        "pt": "Império inicial",
    },
    "codex_band_III": {
        "de": "Operative Systeme",
        "en": "Operations",
        "fr": "Opérations",
        "es": "Operaciones",
        "pl": "Operacje",
        "tr": "Operasyonlar",
        "ru": "Операции",
        "pt": "Operações",
    },
    "codex_band_IV": {
        "de": "Endgame",
        "en": "Endgame",
        "fr": "Endgame",
        "es": "Endgame",
        "pl": "Endgame",
        "tr": "Son oyun",
        "ru": "Эндгейм",
        "pt": "Endgame",
    },
    "codex_context_help": {
        "de": "Hilfe",
        "en": "Help",
        "fr": "Aide",
        "es": "Ayuda",
        "pl": "Pomoc",
        "tr": "Yardım",
        "ru": "Помощь",
        "pt": "Ajuda",
    },
    "codex_section_summary": {
        "de": "Kurzfassung",
        "en": "Summary",
        "fr": "Résumé",
        "es": "Resumen",
        "pl": "Podsumowanie",
        "tr": "Özet",
        "ru": "Кратко",
        "pt": "Resumo",
    },
    "codex_section_why": {
        "de": "Warum wichtig",
        "en": "Why it matters",
        "fr": "Pourquoi c'est important",
        "es": "Por qué importa",
        "pl": "Dlaczego to ważne",
        "tr": "Neden önemli",
        "ru": "Зачем это",
        "pt": "Por que importa",
    },
    "codex_section_how": {
        "de": "Wie es funktioniert",
        "en": "How it works",
        "fr": "Comment ça marche",
        "es": "Cómo funciona",
        "pl": "Jak to działa",
        "tr": "Nasıl çalışır",
        "ru": "Как это работает",
        "pt": "Como funciona",
    },
    "codex_article_unavailable": {
        "de": "Dieser Codex-Eintrag ist noch nicht verfügbar.",
        "en": "This codex entry is not available yet.",
        "fr": "Cette entrée du codex n'est pas encore disponible.",
        "es": "Esta entrada del códice aún no está disponible.",
        "pl": "Ten wpis kodeksu nie jest jeszcze dostępny.",
        "tr": "Bu codex girişi henüz kullanılamıyor.",
        "ru": "Эта записи кодекса ещё недоступна.",
        "pt": "Esta entrada do codex ainda não está disponível.",
    },
    "codex_unlock_generic": {
        "de": "Schalte weiteres Imperium-Fortschritt frei, um dieses Thema zu öffnen.",
        "en": "Progress further in your empire to unlock this topic.",
        "fr": "Progressez dans votre empire pour débloquer ce sujet.",
        "es": "Progresa en tu imperio para desbloquear este tema.",
        "pl": "Rozwijaj imperium, aby odblokować ten temat.",
        "tr": "Bu konuyu açmak için imparatorluğunda ilerle.",
        "ru": "Развивайте империю, чтобы открыть эту тему.",
        "pt": "Progrida no império para desbloquear este tópico.",
    },
    "codex_unlock_building": {
        "de": "Baue das erforderliche Gebäude auf der aktiven Welt.",
        "en": "Build the required building on your active world.",
        "fr": "Construisez le bâtiment requis sur votre monde actif.",
        "es": "Construye el edificio requerido en tu mundo activo.",
        "pl": "Zbuduj wymagany budynek na aktywnym świecie.",
        "tr": "Gerekli binayı aktif dünyanda inşa et.",
        "ru": "Постройте нужное здание на активном мире.",
        "pt": "Construa o edifício necessário no mundo ativo.",
    },
    "codex_unlock_route_visit": {
        "de": "Besuche die zugehörige Spielseite, um dieses Thema freizuschalten.",
        "en": "Visit the related game page to unlock this topic.",
        "fr": "Visitez la page de jeu associée pour débloquer ce sujet.",
        "es": "Visita la página del juego relacionada para desbloquear este tema.",
        "pl": "Odwiedź powiązaną stronę gry, aby odblokować ten temat.",
        "tr": "Bu konuyu açmak için ilgili oyun sayfasını ziyaret et.",
        "ru": "Посетите связанную страницу игры, чтобы открыть тему.",
        "pt": "Visite a página do jogo relacionada para desbloquear este tópico.",
    },
    "codex_unlock_first_fleet": {
        "de": "Sende deine erste Flotte, um dieses Thema freizuschalten.",
        "en": "Send your first fleet to unlock this topic.",
        "fr": "Envoyez votre première flotte pour débloquer ce sujet.",
        "es": "Envía tu primera flota para desbloquear este tema.",
        "pl": "Wyślij pierwszą flotę, aby odblokować ten temat.",
        "tr": "Bu konuyu açmak için ilk filonu gönder.",
        "ru": "Отправьте первый флот, чтобы открыть тему.",
        "pt": "Envie sua primeira frota para desbloquear este tópico.",
    },
    "codex_unlock_expansion_teaser": {
        "de": "Schalte die erste Expansion Site frei (Entwicklungsstufe 5).",
        "en": "Unlock the first Expansion Site (development stage 5).",
        "fr": "Débloquez le premier site d'expansion (stade 5).",
        "es": "Desbloquea el primer sitio de expansión (etapa 5).",
        "pl": "Odblokuj pierwszy placówkę ekspansji (poziom 5).",
        "tr": "İlk genişleme alanını aç (gelişim aşaması 5).",
        "ru": "Откройте первый узел расширения (стадия 5).",
        "pt": "Desbloqueie o primeiro site de expansão (estágio 5).",
    },
    "codex_unlock_fleet_teaser": {
        "de": "Baue eine Orbitalwerft, um Flotten zu entsenden.",
        "en": "Build an orbital shipyard to send fleets.",
        "fr": "Construisez une chantier orbital pour envoyer des flottes.",
        "es": "Construye una astillero orbital para enviar flotas.",
        "pl": "Zbuduj orbitalną stocznię, aby wysłać floty.",
        "tr": "Filo göndermek için orbital tersane inşa et.",
        "ru": "Постройте орбитальный док для флотов.",
        "pt": "Construa uma estaleiro orbital para enviar frotas.",
    },
    "codex_unlock_defense_teaser": {
        "de": "Baue eine Verteidigungsfabrik, um Abwehr zu errichten.",
        "en": "Build a defense factory to construct defenses.",
        "fr": "Construisez une usine de défense.",
        "es": "Construye una fábrica de defensa.",
        "pl": "Zbuduj fabrykę obrony.",
        "tr": "Savunma fabrikası inşa et.",
        "ru": "Постройте фабрику обороны.",
        "pt": "Construa uma fábrica de defesa.",
    },
    "codex_unlock_combat_teaser": {
        "de": "Sende deine erste Flotte — dann öffnet sich der Kampf-Guide.",
        "en": "Send your first fleet to unlock the combat guide.",
        "fr": "Envoyez votre première flotte pour le guide de combat.",
        "es": "Envía tu primera flota para el guía de combate.",
        "pl": "Wyślij pierwszą flotę, aby odblokować przewodnik walki.",
        "tr": "İlk filonu gönder — savaş rehberi açılır.",
        "ru": "Отправьте первый флот — откроется гид боя.",
        "pt": "Envie sua primeira frota para o guia de combate.",
    },
    "codex_unlock_trader_teaser": {
        "de": "Besuche den Trader Hub, um den Tausch zu entdecken.",
        "en": "Visit the Trader Hub to discover exchange.",
        "fr": "Visitez le Trader Hub pour l'échange.",
        "es": "Visita el Trader Hub para el intercambio.",
        "pl": "Odwiedź Trader Hub, aby odkryć wymianę.",
        "tr": "Takas için Trader Hub'ı ziyaret et.",
        "ru": "Посетите Trader Hub для обмена.",
        "pt": "Visite o Trader Hub para trocar.",
    },
    "codex_unlock_ascension_teaser": {
        "de": "Erreiche Entwicklungsstufe 15 auf der Genesis Ark.",
        "en": "Reach development stage 15 on the Genesis Ark.",
        "fr": "Atteignez le stade 15 sur la Genesis Ark.",
        "es": "Alcanza etapa 15 en la Genesis Ark.",
        "pl": "Osiągnij poziom 15 na Genesis Ark.",
        "tr": "Genesis Ark'ta gelişim aşaması 15'e ulaş.",
        "ru": "Достигните стадии 15 на Genesis Ark.",
        "pt": "Alcance estágio 15 na Genesis Ark.",
    },
    "codex_unlock_command_map_teaser": {
        "de": "Erreiche Entwicklungsstufe 5 auf der Genesis Ark für die Command Map.",
        "en": "Reach development stage 5 on the Genesis Ark for the Command Map.",
        "fr": "Atteignez le stade 5 pour la Command Map.",
        "es": "Alcanza etapa 5 para la Command Map.",
        "pl": "Osiągnij poziom 5, aby odblokować Command Map.",
        "tr": "Command Map için Genesis Ark gelişim aşaması 5.",
        "ru": "Достигните стадии 5 для Command Map.",
        "pt": "Alcance estágio 5 para a Command Map.",
    },
    "codex_unlock_expeditions_teaser": {
        "de": "Erreiche Entwicklungsstufe 10 auf der Genesis Ark für Expeditionen.",
        "en": "Reach development stage 10 on the Genesis Ark for expeditions.",
        "fr": "Atteignez le stade 10 pour les expéditions.",
        "es": "Alcanza etapa 10 para expediciones.",
        "pl": "Osiągnij poziom 10, aby odblokować ekspedycje.",
        "tr": "Keşifler için Genesis Ark gelişim aşaması 10.",
        "ru": "Достигните стадии 10 для экспедиций.",
        "pt": "Alcance estágio 10 para expedições.",
    },
    "codex_unlock_logistics_teaser": {
        "de": "Baue eine Orbitalwerft, um Logistik freizuschalten.",
        "en": "Build an orbital shipyard to unlock logistics.",
        "fr": "Construisez un chantier orbital pour la logistique.",
        "es": "Construye un astillero orbital para logística.",
        "pl": "Zbuduj orbitalną stocznię, aby odblokować logistykę.",
        "tr": "Lojistik için orbital tersane inşa et.",
        "ru": "Постройте орбитальный док для логистики.",
        "pt": "Construa um estaleiro orbital para logística.",
    },
    "codex_unlock_strategic_worlds_teaser": {
        "de": "Erreiche Entwicklungsstufe 15 für Strategic Worlds.",
        "en": "Reach development stage 15 for Strategic Worlds.",
        "fr": "Atteignez le stade 15 pour les Strategic Worlds.",
        "es": "Alcanza etapa 15 para Strategic Worlds.",
        "pl": "Osiągnij poziom 15 dla Strategic Worlds.",
        "tr": "Strategic Worlds için gelişim aşaması 15.",
        "ru": "Достигните стадии 15 для Strategic Worlds.",
        "pt": "Alcance estágio 15 para Strategic Worlds.",
    },
    "codex_unlock_diplomacy_teaser": {
        "de": "Besuche Galactic Politics, um Diplomatie freizuschalten.",
        "en": "Visit Galactic Politics to unlock diplomacy.",
        "fr": "Visitez Galactic Politics pour la diplomatie.",
        "es": "Visita Galactic Politics para desbloquear diplomacia.",
        "pl": "Odwiedź Galactic Politics, aby odblokować dyplomację.",
        "tr": "Diplomasi için Galactic Politics'i ziyaret et.",
        "ru": "Посетите Galactic Politics, чтобы открыть дипломатию.",
        "pt": "Visite Galactic Politics para desbloquear diplomacia.",
    },
    "codex_unlock_imperial_directives_teaser": {
        "de": "Besuche Imperial Directives, um High-Command-Befehle freizuschalten.",
        "en": "Visit Imperial Directives to unlock High Command orders.",
        "fr": "Visitez Imperial Directives pour les ordres du High Command.",
        "es": "Visita Imperial Directives para desbloquear órdenes.",
        "pl": "Odwiedź Imperial Directives, aby odblokować rozkazy.",
        "tr": "High Command emirleri için Imperial Directives'i ziyaret et.",
        "ru": "Посетите Imperial Directives, чтобы открыть приказы.",
        "pt": "Visite Imperial Directives para desbloquear ordens.",
    },
    "codex_unlock_ranking_teaser": {
        "de": "Besuche das Ranking, um diesen Codex freizuschalten.",
        "en": "Visit Ranking to unlock this Codex entry.",
        "fr": "Visitez le classement pour débloquer cette entrée.",
        "es": "Visita el ranking para desbloquear esta entrada.",
        "pl": "Odwiedź ranking, aby odblokować ten wpis.",
        "tr": "Bu Codex için Ranking'i ziyaret et.",
        "ru": "Посетите рейтинг, чтобы открыть эту запись.",
        "pt": "Visite o ranking para desbloquear esta entrada.",
    },
    "codex_unlock_auction_teaser": {
        "de": "Besuche das Auktionshaus, um diesen Codex freizuschalten.",
        "en": "Visit the Auction House to unlock this Codex entry.",
        "fr": "Visitez la maison d'enchères pour débloquer cette entrée.",
        "es": "Visita la casa de subastas para desbloquear esta entrada.",
        "pl": "Odwiedź dom aukcyjny, aby odblokować ten wpis.",
        "tr": "Bu Codex için Müzayede Evini ziyaret et.",
        "ru": "Посетите аукционный дом, чтобы открыть эту запись.",
        "pt": "Visite o leilão para desbloquear esta entrada.",
    },
    "codex_unlock_referrals_teaser": {
        "de": "Besuche Referrals, um diesen Codex freizuschalten.",
        "en": "Visit Referrals to unlock this Codex entry.",
        "fr": "Visitez Referrals pour débloquer cette entrée.",
        "es": "Visita Referrals para desbloquear esta entrada.",
        "pl": "Odwiedź Referrals, aby odblokować ten wpis.",
        "tr": "Bu Codex için Referrals'ı ziyaret et.",
        "ru": "Посетите Referrals, чтобы открыть эту запись.",
        "pt": "Visite Referrals para desbloquear esta entrada.",
    },
    "codex_unlock_influence_teaser": {
        "de": "Erreiche Entwicklungsstufe 10 auf der Genesis Ark für Einfluss.",
        "en": "Reach development stage 10 on the Genesis Ark for Influence.",
        "fr": "Atteignez le stade 10 pour l'Influence.",
        "es": "Alcanza etapa 10 para Influencia.",
        "pl": "Osiągnij poziom 10, aby odblokować Influence.",
        "tr": "Etki için Genesis Ark gelişim aşaması 10.",
        "ru": "Достигните стадии 10 для Influence.",
        "pt": "Alcance estágio 10 para Influence.",
    },
}

# Shared locale keys outside codex generator (navigation, research aliases).
LOCALE_CORE_PATCHES: dict[str, dict[str, str]] = {
    "back": {
        "de": "Zurück",
        "en": "Back",
        "fr": "Retour",
        "es": "Volver",
        "pl": "Wstecz",
        "tr": "Geri",
        "ru": "Назад",
        "pt": "Voltar",
    },
    "interstellar_expansion": {
        "de": "Interstellar Expansion",
        "en": "Interstellar Expansion",
        "fr": "Expansion interstellaire",
        "es": "Expansión interestelar",
        "pl": "Ekspansja międzygwiezdna",
        "tr": "Yıldızlararası Genişleme",
        "ru": "Межзвёздная экспансия",
        "pt": "Expansão interestelar",
    },
    "options_game_rules_link": {
        "de": "Spielregeln",
        "en": "Game rules",
        "fr": "Règles du jeu",
        "es": "Reglas del juego",
        "pl": "Zasady gry",
        "tr": "Oyun kuralları",
        "ru": "Правила игры",
        "pt": "Regras do jogo",
    },
}

# Legacy building keys still referenced in templates — alias to building_* in DE.
DE_BUILDING_ALIASES: dict[str, str] = {
    "academy": "building_academy",
    "barracks": "building_barracks",
    "command_center": "building_command_center",
    "crystal_mine": "building_crystal_mine",
    "crystal_storage": "building_crystal_storage",
    "defense_factory": "building_defense_factory",
    "geothermal_nexus": "building_geothermal_nexus",
    "metal_mine": "building_metal_mine",
    "metal_storage": "building_metal_storage",
    "nanofactory": "building_nanofactory",
    "planet_core_nexus": "building_planet_core_nexus",
    "radar_array": "building_radar_array",
    "shield_generator": "building_shield_generator",
    "solar_plant": "building_solar_plant",
    "terraformer": "building_terraformer",
    "login_hint": "Melde dich an und übernimm die Kontrolle über deine Kolonie im Genesis-Cluster.",
    "login_password": "Passwort",
    "login_username": "Benutzername",
    "register_btn": "Registrieren",
    "register_hint": "Starte eine neue Kolonie im Genesis-Cluster.",
}

CODEX_UI_KEYS = frozenset(CODEX_UI.keys())
CODEX_ARTICLE_LOCALES = ("fr", "es", "pl", "tr", "ru", "pt")
CODEX_TRANSLATE_LANG = {"fr": "fr", "es": "es", "pl": "pl", "tr": "tr", "ru": "ru", "pt": "pt"}


def _merge_locale_file(locale: str, updates: dict[str, str]) -> int:
    path = LOCALES / f"{locale}.json"
    data: dict[str, str] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    changed = 0
    for key, value in updates.items():
        if data.get(key) != value:
            data[key] = value
            changed += 1
    # Keep wiki_short as alias for codex in utility bar
    if "codex_short" in updates and locale == "de":
        data["wiki_short"] = updates["codex_short"]
    if "codex_title" in updates and locale == "de":
        data["wiki_title"] = updates["codex_title"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return changed


def _apply_locale_core_patches() -> int:
    changed = 0
    for key, per_locale in LOCALE_CORE_PATCHES.items():
        for loc, value in per_locale.items():
            changed += _merge_locale_file(loc, {key: value})
    de_data: dict[str, str] = {}
    de_path = LOCALES / "de.json"
    if de_path.exists():
        with open(de_path, encoding="utf-8") as fh:
            de_data = json.load(fh)
    de_updates: dict[str, str] = {}
    for alias, source in DE_BUILDING_ALIASES.items():
        if alias in de_data:
            continue
        if source in de_data:
            de_updates[alias] = de_data[source]
        elif source in LOCALE_CORE_PATCHES:
            de_updates[alias] = LOCALE_CORE_PATCHES[source]["de"]
    changed += _merge_locale_file("de", de_updates)
    return changed


def _codex_article_keys(en: dict[str, str]) -> list[str]:
    return sorted(k for k in en if k.startswith("codex_") and k not in CODEX_UI_KEYS)


def translate_codex_articles(*, batch_size: int = 20) -> dict[str, int]:
    """Translate codex article body keys from EN into fr/es/pl/pt/ru/tr."""
    from scripts.gc900_translate_locales import translate_batch

    en_path = LOCALES / "en.json"
    with open(en_path, encoding="utf-8") as fh:
        en = json.load(fh)
    keys = _codex_article_keys(en)
    stats: dict[str, int] = {}

    for loc in CODEX_ARTICLE_LOCALES:
        path = LOCALES / f"{loc}.json"
        with open(path, encoding="utf-8") as fh:
            target = json.load(fh)
        for k, v in en.items():
            if k not in target:
                target[k] = v
        changed = 0
        todo = [k for k in keys if k in en]
        print(f"codex translate {loc}: {len(todo)} keys", flush=True)
        for i in range(0, len(todo), batch_size):
            chunk = todo[i : i + batch_size]
            src_texts = [en[k] for k in chunk]
            translated = translate_batch(
                src_texts,
                source="en",
                target=CODEX_TRANSLATE_LANG[loc],
            )
            if len(translated) != len(chunk):
                raise RuntimeError(f"{loc} batch size mismatch: {len(translated)} != {len(chunk)}")
            for key, new_val in zip(chunk, translated):
                if not new_val:
                    continue
                if target.get(key) != new_val:
                    target[key] = new_val
                    changed += 1
            print(
                f"  {loc} batch {i // batch_size + 1}/{(len(todo) + batch_size - 1) // batch_size}",
                flush=True,
            )
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(target, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        stats[loc] = changed
        print(f"  {loc}: {changed} updates", flush=True)
    return stats


def main() -> int:
    sys.path.insert(0, str(ROOT))
    translate_only = "--translate-only" in sys.argv
    skip_translate = "--no-translate" in sys.argv
    if translate_only and skip_translate:
        print("ERROR: --translate-only and --no-translate are mutually exclusive")
        return 1

    if translate_only:
        patch_total = _apply_locale_core_patches()
        translate_stats = translate_codex_articles()
        print(f"GC-950B: codex article translation only, {patch_total} core patches")
        if translate_stats:
            print("Codex article translations:", translate_stats)
        return 0

    from game.knowledge_parser import (
        build_catalog,
        build_locale_map,
        load_player_articles_from_docs,
    )
    from scripts.codex_en_content import en_locale_keys

    articles = load_player_articles_from_docs()
    if not articles:
        print("ERROR: no player articles found")
        return 1

    catalog = build_catalog(articles)
    de_keys = build_locale_map(articles)
    en_keys = en_locale_keys()

    GENERATED.mkdir(parents=True, exist_ok=True)
    DOCS_EXPORT.mkdir(parents=True, exist_ok=True)

    with open(GENERATED / "catalog.json", "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    # Discord exports
    for article in articles:
        codex_id = str((article.get("meta") or {}).get("codex_id") or "")
        discord = (article.get("sections") or {}).get("discord_summary")
        if codex_id and discord:
            (DOCS_EXPORT / f"{codex_id}.md").write_text(str(discord), encoding="utf-8")

    locales = ("de", "en", "fr", "es", "pl", "tr", "ru", "pt")
    total = 0
    for loc in locales:
        ui = {k: v[loc] for k, v in CODEX_UI.items()}
        if loc == "de":
            merged = {**ui, **de_keys}
        elif loc == "en":
            merged = {**ui, **en_keys}
        else:
            # Article bodies: keep locale file + translate_codex_articles(); only sync UI chrome here.
            merged = ui
        total += _merge_locale_file(loc, merged)

    patch_total = _apply_locale_core_patches()
    translate_stats: dict[str, int] = {}
    if not skip_translate:
        translate_stats = translate_codex_articles()

    print(
        f"GC-950B: {len(catalog['articles'])} articles, catalog.json written, "
        f"~{total} codex merges, {patch_total} core patches"
    )
    if translate_stats:
        print("Codex article translations:", translate_stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
