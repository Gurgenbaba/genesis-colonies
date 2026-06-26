#!/usr/bin/env python3
"""Sync locale gaps and repair obvious German leakage in non-de files."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
sys.path.insert(0, str(ROOT))

from game.i18n import SUPPORTED_LOCALES  # noqa: E402
from scripts.check_locale_keys import collect_used_keys, find_missing  # noqa: E402
from scripts.gc900_translate_locales import (  # noqa: E402
    GERMAN_HINTS,
    is_german,
    translate_batch,
)

# Keys that may legitimately match across locales (proper nouns, placeholders, format-only).
_IDENTICAL_OK = frozenset(
    {
        "nav_trader_hub",
        "trader_hub_title",
        "metal",
        "crystal",
        "energy",
        "resource_metal",
        "resource_crystal",
        "resource_energy",
        "universe_name",
        "referral_apply_placeholder",
        "register_placeholder_referral",
        "buildings_technical_yard_capacity_compact",
        "buildings_technical_yard_compact_with_reduction",
        "building_terraformer",
        "overview_crystal",
        "auction_house_min_bid",
    }
)

_EXPLICIT: dict[str, dict[str, str]] = {
    "trader_hub_subtitle": {
        "de": "Ressourcen tauschen · Schiffe recyceln",
        "en": "Exchange resources · Recycle ships",
        "es": "Intercambiar recursos · Reciclar naves",
        "fr": "Échanger des ressources · Recycler des vaisseaux",
        "pl": "Wymiana zasobów · Recykling statków",
        "pt": "Trocar recursos · Reciclar naves",
        "ru": "Обмен ресурсами · Утилизация кораблей",
        "tr": "Kaynak takası · Gemi geri dönüşümü",
    },
    "status_requirements_missing": {
        "en": "Requirements missing",
        "es": "Requisitos no cumplidos",
        "fr": "Prérequis manquants",
        "pl": "Brak wymagań",
        "pt": "Requisitos em falta",
        "ru": "Требования не выполнены",
        "tr": "Gereksinimler eksik",
    },
    "status_locked": {
        "en": "Locked",
        "es": "Bloqueado",
        "fr": "Verrouillé",
        "pl": "Zablokowane",
        "pt": "Bloqueado",
        "ru": "Заблокировано",
        "tr": "Kilitli",
    },
    "tech_storage": {
        "en": "Storage technology",
        "es": "Tecnología de almacenamiento",
        "fr": "Technologie de stockage",
        "pl": "Technologia magazynowania",
        "pt": "Tecnologia de armazenamento",
        "ru": "Технология хранения",
        "tr": "Depolama teknolojisi",
    },
    "pe_policy_empty": {
        "en": "Free",
        "es": "Libre",
        "fr": "Libre",
        "pl": "Wolne",
        "pt": "Livre",
        "ru": "Свободно",
        "tr": "Boş",
    },
    "pe_policy_wrong_archetype": {
        "pl": "Nie pasuje do kultury tej planety.",
        "ru": "Не соответствует культуре этой планеты.",
    },
    "pe_archetype_frontier_settlers": {
        "en": "Frontier settlers",
        "es": "Colonos de la frontera",
        "fr": "Colons de la frontière",
        "pl": "Osadnicy pogranicza",
        "pt": "Colonos da fronteira",
        "ru": "Поселенцы пограничья",
        "tr": "Sınır yerleşimcileri",
    },
    "pe_archetype_scientific_collective": {
        "en": "Scientific collective",
        "es": "Colectivo científico",
        "fr": "Collectif scientifique",
        "pl": "Naukowy kolektyw",
        "pt": "Coletivo científico",
        "ru": "Научный коллектив",
        "tr": "Bilimsel kolektif",
    },
    "pe_archetype_industrial_union_state": {
        "en": "Industrial union",
        "es": "Unión industrial",
        "fr": "Union industrielle",
        "pl": "Unia przemysłowa",
        "pt": "União industrial",
        "ru": "Промышленный союз",
        "tr": "Sanayi birliği",
    },
    "pe_archetype_isolationists": {
        "en": "Isolationists",
        "es": "Aislamistas",
        "fr": "Isolationnistes",
        "pl": "Izolacjoniści",
        "pt": "Isolationistas",
        "ru": "Изоляционисты",
        "tr": "İzolasyonistler",
    },
    "exchange_rate_ferronite_per_crytite": {
        "pl": "%(rate)s Ferronitu za 1 Crytite",
    },
    "exchange_error_exchange_arbitrage_disabled": {
        "pl": "Kursy wymiany są błędnie skonfigurowane. Skontaktuj się z administratorem.",
    },
    "admin_exchange_crytite_buy_cost_label": {
        "pl": "Koszt Ferronitu za 1 Crytite (kupno)",
    },
    "admin_exchange_crytite_sell_return_label": {
        "pl": "Zwrot Ferronitu za 1 Crytite (sprzedaż)",
    },
    "admin_exchange_arbitrage_help": {
        "pl": "Cena kupna musi być wyższa niż zwrot ze sprzedaży, inaczej możliwy jest arbitraż.",
    },
    "error_exchange_arbitrage_risk": {
        "pl": "Nieprawidłowe kursy: cena kupna Crytite musi być wyższa niż zwrot ze sprzedaży.",
    },
}

_EN_GERMAN_FIXES: dict[str, str] = {
    "header_level": "Level",
    "msg_upgrade_unknown": "This upgrade could not be started.",
    "register_subtitle": "Secure your commander name before someone else does. Your name is recorded in the Genesis Cluster logbook.",
    "pe_level": "Level",
    "pe_level_short": "Level",
    "pe_xp_to_level": "Progress to level",
    "pe_progression_section": "Evolution & unlocks",
    "pe_tab_policies": "Policies",
    "pe_unlock_policy_1": "First policy slot",
    "pe_unlock_policy_2": "Second policy slot",
    "pe_unlock_policy_3": "Third policy slot",
    "pe_req_planet_level": "Planet must reach level %(need)s (current: level %(current)s)",
    "pe_req_trait_none": "Must not have this trait",
    "pe_no_history": "Your planet's history begins with your decisions.",
    "pe_policies_hint": "Policy slots are mechanical rules — not cosmetics.",
    "pe_spec_tier_title_2": "Tier 2 — expansion",
    "pe_spec_lock_level": "Planet level too low",
    "pe_load_error_body": "Evolution data could not be loaded. Please reload the page.",
    "pe_confirm_policy": "Activate policy in this slot?",
    "pe_reload": "Reload page",
    "pe_reason_ok": "Success.",
    "pe_reason_not_owner": "You do not own this planet.",
    "pe_reason_level_too_low": "Planet level too low.",
    "pe_reason_already_chosen": "This choice has already been made.",
    "pe_reason_unknown_policy": "Unknown policy.",
    "pe_reason_archetype_not_allowed": "Policy does not match this planet's culture.",
    "pe_reason_slot_on_cooldown": "Policy slot on cooldown.",
    "policy_automation_directive": "Automation directive",
    "spec_science_nexus": "Science nexus",
}


def _load(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _write(path: Path, data: dict[str, str], key_order: list[str]) -> None:
    ordered = {k: data[k] for k in key_order if k in data}
    for k in sorted(data):
        if k not in ordered:
            ordered[k] = data[k]
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _looks_german(text: str) -> bool:
    if is_german(text):
        return True
    return any(h in text for h in GERMAN_HINTS)


def _sync_missing_keys(data: dict[str, str], locale: str, de: dict[str, str], en: dict[str, str]) -> int:
    changed = 0
    for key in de:
        if key in data:
            continue
        if locale == "de":
            data[key] = de[key]
        else:
            data[key] = en.get(key, de[key])
        changed += 1
    return changed


def _apply_explicit(data: dict[str, str], locale: str) -> int:
    changed = 0
    for key, per_locale in _EXPLICIT.items():
        if locale not in per_locale:
            continue
        val = per_locale[locale]
        if data.get(key) != val:
            data[key] = val
            changed += 1
    return changed


def _fix_en_manual(data: dict[str, str]) -> int:
    changed = 0
    for key, val in _EN_GERMAN_FIXES.items():
        if data.get(key) != val:
            data[key] = val
            changed += 1
    return changed


def _keys_needing_translation(
    data: dict[str, str],
    locale: str,
    de: dict[str, str],
    en: dict[str, str],
) -> list[str]:
    out: list[str] = []
    for key, val in data.items():
        if key in _IDENTICAL_OK or key.startswith("language_name_"):
            continue
        if locale == "en":
            if val == de.get(key) and _looks_german(de.get(key, "")):
                out.append(key)
            elif _looks_german(val) and key not in _EN_GERMAN_FIXES:
                out.append(key)
        elif val == de.get(key) and _looks_german(de.get(key, "")):
            out.append(key)
    return out


_LANG_MAP = {"en": "en", "es": "es", "fr": "fr", "pl": "pl", "pt": "pt", "ru": "ru", "tr": "tr"}


def _translate_keys(
    data: dict[str, str],
    keys: list[str],
    *,
    locale: str,
    de: dict[str, str],
    en: dict[str, str],
    batch_size: int = 30,
) -> int:
    if not keys:
        return 0
    changed = 0
    source_lang = "de" if locale == "en" else "en"
    target_lang = _LANG_MAP[locale]
    for i in range(0, len(keys), batch_size):
        chunk = keys[i : i + batch_size]
        src = de if locale == "en" else en
        texts = [src.get(k, data[k]) for k in chunk]
        translated = translate_batch(texts, source=source_lang, target=target_lang)
        for key, new_val in zip(chunk, translated):
            if new_val and new_val != data.get(key):
                data[key] = new_val
                changed += 1
        time.sleep(0.35)
    return changed


def main() -> int:
    de = _load(LOCALES / "de.json")
    en = _load(LOCALES / "en.json")
    used = collect_used_keys()
    key_order = list(de.keys()) + sorted(set(en) - set(de))
    total_changed = 0

    for locale in SUPPORTED_LOCALES:
        path = LOCALES / f"{locale}.json"
        data = _load(path) if path.exists() else dict(en)
        before = len(data)

        missing_used = find_missing(locale, used)
        synced = _sync_missing_keys(data, locale, de, en)
        explicit = _apply_explicit(data, locale)
        manual_en = _fix_en_manual(data) if locale == "en" else 0

        todo = _keys_needing_translation(data, locale, de, en)
        # Skip keys already fixed explicitly or manually
        skip = set(_EXPLICIT) | set(_EN_GERMAN_FIXES)
        todo = [k for k in todo if k not in skip]
        translated = 0
        if todo and locale != "de":
            print(f"{locale}: translating {len(todo)} leaked keys…", flush=True)
            translated = _translate_keys(data, todo, locale=locale, de=de, en=en)

        _write(path, data, key_order)
        locale_changed = synced + explicit + manual_en + translated
        total_changed += locale_changed
        still_missing = find_missing(locale, used)
        print(
            f"{locale}: +{synced} missing keys, {explicit} explicit, {manual_en} manual-en, "
            f"{translated} translated, entries {before}->{len(data)}, still missing used: {len(still_missing)}"
        )

    print(f"Done. ~{total_changed} value updates across locales.")
    return 0 if all(not find_missing(loc, used) for loc in SUPPORTED_LOCALES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
