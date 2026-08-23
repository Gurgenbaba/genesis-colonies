from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, *, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} occurrence(s), found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def append_locale_keys(path: Path, mapping: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    existing = [key for key in mapping if key in data]
    if existing:
        raise SystemExit(f"{path}: keys already exist: {existing}")
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise SystemExit(f"{path}: expected JSON object")
    lines = []
    for key, value in mapping.items():
        lines.append(
            "  "
            + json.dumps(key, ensure_ascii=False)
            + ": "
            + json.dumps(value, ensure_ascii=False)
        )
    body = stripped[:-1].rstrip()
    if data:
        body += ","
    body += "\n" + ",\n".join(lines) + "\n}\n"
    json.loads(body)
    path.write_text(body, encoding="utf-8")


LOCALE_KEYS: dict[str, dict[str, str]] = {
    "en": {
        "server_event_preset_weekend_prod_expo": "Resource Production / Expedition Event",
        "server_event_preset_double_production_24h": "Double Production",
        "server_event_preset_expedition_rush_48h": "Expedition Rush",
        "server_event_preset_shop_sale_20_48h": "Shop Sale −20%",
        "server_event_preset_build_research_rush_24h": "Build / Research Rush",
        "server_event_preset_world_boss_leviathan": "World Boss: Ancient Leviathan",
        "server_event_preset_mega_weekend": "Mega Weekend",
        "server_event_preset_asteroid_storm_48h": "Asteroid Storm",
        "server_event_preset_boss_hunt_24h": "Boss Hunt",
        "server_event_preset_inactive_farm_weekend": "Inactive Farm Weekend",
        "server_event_preset_chaos_weekend": "Chaos Weekend",
        "server_event_scheduled_fallback": "Scheduled Event",
        "server_event_effect_shop_discount": "Shop −%(pct)s%",
        "server_event_effect_production": "%(value)s% Production",
        "server_event_effect_expedition_hold": "%(value)s% Expedition Hold",
        "server_event_effect_build_speed": "%(value)s% Build Speed",
        "server_event_effect_research_speed": "%(value)s% Research Speed",
        "server_event_effect_asteroid_spawn": "Asteroid Spawns ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Boss Hunt ×%(mult)s",
        "server_event_effect_inactive_farm": "Inactive Farms ×%(mult)s",
    },
    "de": {
        "server_event_preset_weekend_prod_expo": "Ressourcenproduktion / Expeditions-Event",
        "server_event_preset_double_production_24h": "Doppelte Produktion",
        "server_event_preset_expedition_rush_48h": "Expeditionsrausch",
        "server_event_preset_shop_sale_20_48h": "Shop-Angebot −20%",
        "server_event_preset_build_research_rush_24h": "Bau- / Forschungsrausch",
        "server_event_preset_world_boss_leviathan": "World Boss: Uralter Leviathan",
        "server_event_preset_mega_weekend": "Mega-Wochenende",
        "server_event_preset_asteroid_storm_48h": "Asteroidensturm",
        "server_event_preset_boss_hunt_24h": "Bossjagd",
        "server_event_preset_inactive_farm_weekend": "Inaktiven-Farm-Wochenende",
        "server_event_preset_chaos_weekend": "Chaos-Wochenende",
        "server_event_scheduled_fallback": "Geplantes Event",
        "server_event_effect_shop_discount": "Shop −%(pct)s%",
        "server_event_effect_production": "%(value)s% Produktion",
        "server_event_effect_expedition_hold": "%(value)s% Expeditions-Haltezeit",
        "server_event_effect_build_speed": "%(value)s% Baugeschwindigkeit",
        "server_event_effect_research_speed": "%(value)s% Forschungsgeschwindigkeit",
        "server_event_effect_asteroid_spawn": "Asteroiden-Spawns ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Bossjagd ×%(mult)s",
        "server_event_effect_inactive_farm": "Inaktiven-Farmen ×%(mult)s",
    },
    "fr": {
        "server_event_preset_weekend_prod_expo": "Production de ressources / Expéditions",
        "server_event_preset_double_production_24h": "Production doublée",
        "server_event_preset_expedition_rush_48h": "Ruée d’expédition",
        "server_event_preset_shop_sale_20_48h": "Promo boutique −20 %",
        "server_event_preset_build_research_rush_24h": "Ruée construction / recherche",
        "server_event_preset_world_boss_leviathan": "Boss mondial : Léviathan antique",
        "server_event_preset_mega_weekend": "Méga week-end",
        "server_event_preset_asteroid_storm_48h": "Tempête d’astéroïdes",
        "server_event_preset_boss_hunt_24h": "Chasse au boss",
        "server_event_preset_inactive_farm_weekend": "Week-end de pillage des inactifs",
        "server_event_preset_chaos_weekend": "Week-end du chaos",
        "server_event_scheduled_fallback": "Événement planifié",
        "server_event_effect_shop_discount": "Boutique −%(pct)s %",
        "server_event_effect_production": "%(value)s % Production",
        "server_event_effect_expedition_hold": "%(value)s % Temps d’expédition",
        "server_event_effect_build_speed": "%(value)s % Vitesse de construction",
        "server_event_effect_research_speed": "%(value)s % Vitesse de recherche",
        "server_event_effect_asteroid_spawn": "Apparition d’astéroïdes ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Chasse au boss ×%(mult)s",
        "server_event_effect_inactive_farm": "Fermes inactives ×%(mult)s",
    },
    "es": {
        "server_event_preset_weekend_prod_expo": "Producción de recursos / Expediciones",
        "server_event_preset_double_production_24h": "Producción doble",
        "server_event_preset_expedition_rush_48h": "Fiebre de expediciones",
        "server_event_preset_shop_sale_20_48h": "Oferta de tienda −20 %",
        "server_event_preset_build_research_rush_24h": "Construcción / Investigación exprés",
        "server_event_preset_world_boss_leviathan": "Jefe mundial: Leviatán ancestral",
        "server_event_preset_mega_weekend": "Mega fin de semana",
        "server_event_preset_asteroid_storm_48h": "Tormenta de asteroides",
        "server_event_preset_boss_hunt_24h": "Caza de jefes",
        "server_event_preset_inactive_farm_weekend": "Fin de semana de granjas inactivas",
        "server_event_preset_chaos_weekend": "Fin de semana del caos",
        "server_event_scheduled_fallback": "Evento programado",
        "server_event_effect_shop_discount": "Tienda −%(pct)s %",
        "server_event_effect_production": "%(value)s % Producción",
        "server_event_effect_expedition_hold": "%(value)s % Tiempo de expedición",
        "server_event_effect_build_speed": "%(value)s % Velocidad de construcción",
        "server_event_effect_research_speed": "%(value)s % Velocidad de investigación",
        "server_event_effect_asteroid_spawn": "Aparición de asteroides ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Caza de jefes ×%(mult)s",
        "server_event_effect_inactive_farm": "Granjas inactivas ×%(mult)s",
    },
    "pl": {
        "server_event_preset_weekend_prod_expo": "Produkcja zasobów / Ekspedycje",
        "server_event_preset_double_production_24h": "Podwójna produkcja",
        "server_event_preset_expedition_rush_48h": "Szturm ekspedycyjny",
        "server_event_preset_shop_sale_20_48h": "Wyprzedaż sklepu −20%",
        "server_event_preset_build_research_rush_24h": "Pośpiech budowy / badań",
        "server_event_preset_world_boss_leviathan": "Boss świata: Pradawny Lewiatan",
        "server_event_preset_mega_weekend": "Mega weekend",
        "server_event_preset_asteroid_storm_48h": "Burza asteroid",
        "server_event_preset_boss_hunt_24h": "Polowanie na bossa",
        "server_event_preset_inactive_farm_weekend": "Weekend farmienia nieaktywnych",
        "server_event_preset_chaos_weekend": "Weekend chaosu",
        "server_event_scheduled_fallback": "Zaplanowane wydarzenie",
        "server_event_effect_shop_discount": "Sklep −%(pct)s%",
        "server_event_effect_production": "%(value)s% Produkcja",
        "server_event_effect_expedition_hold": "%(value)s% Czas ekspedycji",
        "server_event_effect_build_speed": "%(value)s% Szybkość budowy",
        "server_event_effect_research_speed": "%(value)s% Szybkość badań",
        "server_event_effect_asteroid_spawn": "Pojawianie asteroid ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Polowanie na bossa ×%(mult)s",
        "server_event_effect_inactive_farm": "Farmienie nieaktywnych ×%(mult)s",
    },
    "tr": {
        "server_event_preset_weekend_prod_expo": "Kaynak Üretimi / Sefer Etkinliği",
        "server_event_preset_double_production_24h": "Çifte Üretim",
        "server_event_preset_expedition_rush_48h": "Sefer Hücumu",
        "server_event_preset_shop_sale_20_48h": "Mağaza İndirimi −20%",
        "server_event_preset_build_research_rush_24h": "İnşa / Araştırma Hücumu",
        "server_event_preset_world_boss_leviathan": "Dünya Bossu: Kadim Leviathan",
        "server_event_preset_mega_weekend": "Mega Hafta Sonu",
        "server_event_preset_asteroid_storm_48h": "Asteroit Fırtınası",
        "server_event_preset_boss_hunt_24h": "Boss Avı",
        "server_event_preset_inactive_farm_weekend": "Pasif Oyuncu Yağma Hafta Sonu",
        "server_event_preset_chaos_weekend": "Kaos Hafta Sonu",
        "server_event_scheduled_fallback": "Planlanmış Etkinlik",
        "server_event_effect_shop_discount": "Mağaza −%(pct)s%",
        "server_event_effect_production": "%(value)s% Üretim",
        "server_event_effect_expedition_hold": "%(value)s% Sefer bekleme süresi",
        "server_event_effect_build_speed": "%(value)s% İnşa hızı",
        "server_event_effect_research_speed": "%(value)s% Araştırma hızı",
        "server_event_effect_asteroid_spawn": "Asteroit çıkışı ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Boss avı ×%(mult)s",
        "server_event_effect_inactive_farm": "Pasif oyuncu çiftlikleri ×%(mult)s",
    },
    "ru": {
        "server_event_preset_weekend_prod_expo": "Производство ресурсов / Экспедиции",
        "server_event_preset_double_production_24h": "Двойное производство",
        "server_event_preset_expedition_rush_48h": "Экспедиционный рывок",
        "server_event_preset_shop_sale_20_48h": "Распродажа в магазине −20%",
        "server_event_preset_build_research_rush_24h": "Ускорение строительства / исследований",
        "server_event_preset_world_boss_leviathan": "Мировой босс: Древний Левиафан",
        "server_event_preset_mega_weekend": "Мега-выходные",
        "server_event_preset_asteroid_storm_48h": "Астероидный шторм",
        "server_event_preset_boss_hunt_24h": "Охота на босса",
        "server_event_preset_inactive_farm_weekend": "Выходные охоты на неактивных",
        "server_event_preset_chaos_weekend": "Выходные хаоса",
        "server_event_scheduled_fallback": "Запланированное событие",
        "server_event_effect_shop_discount": "Магазин −%(pct)s%",
        "server_event_effect_production": "%(value)s% Производство",
        "server_event_effect_expedition_hold": "%(value)s% Время экспедиции",
        "server_event_effect_build_speed": "%(value)s% Скорость строительства",
        "server_event_effect_research_speed": "%(value)s% Скорость исследований",
        "server_event_effect_asteroid_spawn": "Появление астероидов ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Охота на босса ×%(mult)s",
        "server_event_effect_inactive_farm": "Фарм неактивных ×%(mult)s",
    },
    "pt": {
        "server_event_preset_weekend_prod_expo": "Produção de recursos / Expedições",
        "server_event_preset_double_production_24h": "Produção em dobro",
        "server_event_preset_expedition_rush_48h": "Corrida de expedições",
        "server_event_preset_shop_sale_20_48h": "Promoção na loja −20%",
        "server_event_preset_build_research_rush_24h": "Corrida de construção / pesquisa",
        "server_event_preset_world_boss_leviathan": "Chefe mundial: Leviatã Ancestral",
        "server_event_preset_mega_weekend": "Mega fim de semana",
        "server_event_preset_asteroid_storm_48h": "Tempestade de asteroides",
        "server_event_preset_boss_hunt_24h": "Caçada ao chefe",
        "server_event_preset_inactive_farm_weekend": "Fim de semana de farm em inativos",
        "server_event_preset_chaos_weekend": "Fim de semana do caos",
        "server_event_scheduled_fallback": "Evento programado",
        "server_event_effect_shop_discount": "Loja −%(pct)s%",
        "server_event_effect_production": "%(value)s% Produção",
        "server_event_effect_expedition_hold": "%(value)s% Tempo de expedição",
        "server_event_effect_build_speed": "%(value)s% Velocidade de construção",
        "server_event_effect_research_speed": "%(value)s% Velocidade de pesquisa",
        "server_event_effect_asteroid_spawn": "Surgimento de asteroides ×%(mult)s",
        "server_event_effect_world_boss_spawn": "Caçada ao chefe ×%(mult)s",
        "server_event_effect_inactive_farm": "Farm em inativos ×%(mult)s",
    },
}


for locale, mapping in LOCALE_KEYS.items():
    append_locale_keys(ROOT / "locales" / f"{locale}.json", mapping)

server_events = ROOT / "game" / "server_events.py"
replace_once(
    server_events,
    "from .db import db, table_exists\n",
    "from .db import db, table_exists\nfrom .i18n import get_locale_dict, tr\n",
)

preset_titles = {
    '        "title": "Res-Prod / Expo Event",\n': '        "title_key": "server_event_preset_weekend_prod_expo",\n',
    '        "title": "Double Production",\n': '        "title_key": "server_event_preset_double_production_24h",\n',
    '        "title": "Expedition Rush",\n': '        "title_key": "server_event_preset_expedition_rush_48h",\n',
    '        "title": "Shop Sale −20%",\n': '        "title_key": "server_event_preset_shop_sale_20_48h",\n',
    '        "title": "Build / Research Rush",\n': '        "title_key": "server_event_preset_build_research_rush_24h",\n',
    '        "title": "World Boss: Ancient Leviathan",\n': '        "title_key": "server_event_preset_world_boss_leviathan",\n',
    '        "title": "Mega Weekend",\n': '        "title_key": "server_event_preset_mega_weekend",\n',
    '        "title": "Asteroid Storm",\n': '        "title_key": "server_event_preset_asteroid_storm_48h",\n',
    '        "title": "Boss Hunt",\n': '        "title_key": "server_event_preset_boss_hunt_24h",\n',
    '        "title": "Inactive Farm Weekend",\n': '        "title_key": "server_event_preset_inactive_farm_weekend",\n',
    '        "title": "Chaos Weekend",\n': '        "title_key": "server_event_preset_chaos_weekend",\n',
}
for old, new in preset_titles.items():
    replace_once(server_events, old, new)

replace_once(
    server_events,
    'def _normalize_slug(raw: str) -> str:\n    return str(raw or "").strip().lower().replace(" ", "-")\n\n\n',
    '''def _normalize_slug(raw: str) -> str:\n    return str(raw or "").strip().lower().replace(" ", "-")\n\n\ndef _preset_fallback_title(preset: Mapping[str, Any]) -> str:\n    """Stable English DB/admin fallback; player rendering uses title_key."""\n    title_key = str(preset.get("title_key") or "").strip()\n    if title_key:\n        text = get_locale_dict("en").get(title_key)\n        if text:\n            return str(text)\n    return str(preset.get("id") or "server_event")\n\n\ndef _preset_title_key_for_slug(slug: str) -> str:\n    slug_n = _normalize_slug(slug)\n    if not slug_n:\n        return ""\n    for preset in EVENT_PRESETS.values():\n        prefix = _normalize_slug(str(preset.get("slug_prefix") or ""))\n        title_key = str(preset.get("title_key") or "").strip()\n        if not prefix or not title_key:\n            continue\n        if slug_n == prefix or slug_n.startswith(f"{prefix}-"):\n            return title_key\n    return ""\n\n\ndef _localized_event_title(event: Mapping[str, Any], *, locale: Optional[str] = None) -> str:\n    title = str(event.get("title") or event.get("slug") or "")\n    title_key = str(event.get("title_key") or _preset_title_key_for_slug(str(event.get("slug") or "")))\n    if not title_key:\n        return title\n    return tr(title_key, title, locale=locale)\n\n\n''',
)

replace_once(
    server_events,
    '        "slug": str(row.get("slug") or ""),\n        "title": str(row.get("title") or ""),\n',
    '        "slug": str(row.get("slug") or ""),\n        "title": str(row.get("title") or ""),\n        "title_key": _preset_title_key_for_slug(str(row.get("slug") or "")),\n',
)
replace_once(
    server_events,
    '                "title": e["title"],\n',
    '                "title": _localized_event_title(e),\n                "title_key": str(e.get("title_key") or ""),\n',
)

old_summary_start = server_events.read_text(encoding="utf-8").index("def effect_summary_short(")
old_summary_end = server_events.read_text(encoding="utf-8").index("\n\ndef active_events_banner", old_summary_start)
text = server_events.read_text(encoding="utf-8")
new_summary = '''def effect_summary_short(effects: Any, *, locale: Optional[str] = None) -> List[str]:\n    """Compact player-facing labels resolved through locale SSOT."""\n    out: List[str] = []\n    if not isinstance(effects, list):\n        return out\n    for eff in effects:\n        if not isinstance(eff, Mapping):\n            continue\n        kind = str(eff.get("kind") or "").strip()\n        if kind == KIND_SHOP_DISCOUNT_BPS:\n            try:\n                bps = int(eff.get("bps") or 0)\n            except (TypeError, ValueError):\n                continue\n            if bps > 0:\n                pct = int(round(bps / 100.0))\n                out.append(tr("server_event_effect_shop_discount", locale=locale, pct=pct))\n            continue\n        try:\n            mult = float(eff.get("mult") or 1.0)\n        except (TypeError, ValueError):\n            continue\n        if kind == KIND_PRODUCTION_MULT and mult > 0:\n            pct = int(round((mult - 1.0) * 100))\n            if pct != 0:\n                value = f"+{pct}" if pct > 0 else str(pct)\n                out.append(tr("server_event_effect_production", locale=locale, value=value))\n        elif kind == KIND_EXPEDITION_HOLD_MULT and mult > 0:\n            pct = int(round((1.0 - mult) * 100))\n            if pct != 0:\n                value = f"−{pct}" if pct > 0 else f"+{abs(pct)}"\n                out.append(tr("server_event_effect_expedition_hold", locale=locale, value=value))\n        elif kind == KIND_BUILD_TIME_SPEED and mult > 0:\n            pct = int(round((mult - 1.0) * 100))\n            if pct != 0:\n                value = f"+{pct}" if pct > 0 else str(pct)\n                out.append(tr("server_event_effect_build_speed", locale=locale, value=value))\n        elif kind == KIND_RESEARCH_TIME_SPEED and mult > 0:\n            pct = int(round((mult - 1.0) * 100))\n            if pct != 0:\n                value = f"+{pct}" if pct > 0 else str(pct)\n                out.append(tr("server_event_effect_research_speed", locale=locale, value=value))\n        elif kind == KIND_ASTEROID_SPAWN_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:\n            out.append(tr("server_event_effect_asteroid_spawn", locale=locale, mult=f"{mult:g}"))\n        elif kind == KIND_WORLD_BOSS_SPAWN_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:\n            out.append(tr("server_event_effect_world_boss_spawn", locale=locale, mult=f"{mult:g}"))\n        elif kind == KIND_INACTIVE_FARM_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:\n            out.append(tr("server_event_effect_inactive_farm", locale=locale, mult=f"{mult:g}"))\n    return out\n'''
server_events.write_text(text[:old_summary_start] + new_summary + text[old_summary_end:], encoding="utf-8")

replace_once(
    server_events,
    'def active_events_banner(*, now: Optional[float] = None, conn=None) -> List[Dict[str, Any]]:\n',
    'def active_events_banner(*, now: Optional[float] = None, conn=None, locale: Optional[str] = None) -> List[Dict[str, Any]]:\n',
)
replace_once(
    server_events,
    '                "title": str(ev.get("title") or ""),\n                "title_key": "",\n                "effects_summary": effect_summary_short(effects),\n',
    '                "title": _localized_event_title(ev, locale=locale),\n                "title_key": str(ev.get("title_key") or ""),\n                "effects_summary": effect_summary_short(effects, locale=locale),\n',
)
replace_once(
    server_events,
    '        titles.append(str(ev.get("title") or ev.get("slug") or ""))\n',
    '        titles.append(_localized_event_title(ev))\n',
)
replace_once(
    server_events,
    '                "title": preset["title"],\n',
    '                "title": _preset_fallback_title(preset),\n                "title_key": str(preset.get("title_key") or ""),\n',
)
replace_once(
    server_events,
    '                title=str(preset.get("title") or preset["id"]),\n',
    '                title=_preset_fallback_title(preset),\n',
)
replace_once(
    server_events,
    '        title = str(rule.get("name") or "Scheduled Event")\n',
    '        title = str(rule.get("name") or get_locale_dict("en").get("server_event_scheduled_fallback") or "scheduled_event")\n',
)
replace_once(
    server_events,
    '            title = str(preset.get("title") or title)\n',
    '            title = _preset_fallback_title(preset)\n',
)

overview = ROOT / "game" / "overview_page.py"
replace_once(
    overview,
    '                items.extend(active_events_banner(now=ts, conn=conn))\n',
    '                items.extend(active_events_banner(now=ts, conn=conn, locale=locale))\n',
)

tests = ROOT / "tests" / "test_server_events.py"
replace_once(
    tests,
    '    assert effect_summary_short([{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}]) == ["+100% Prod"]\n',
    '    assert effect_summary_short([{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}], locale="en") == ["+100% Production"]\n',
)
replace_once(
    tests,
    '    assert any("Hold" in s for s in summaries)\n',
    '    assert any("Hold" in s for s in summaries)\n',
)

anchor = '\n\ndef test_apply_preset_weekend_and_list(events_db):\n'
text = tests.read_text(encoding="utf-8")
if text.count(anchor) != 1:
    raise SystemExit("tests/test_server_events.py: apply-preset anchor mismatch")
new_tests = r'''

def test_server_event_presets_are_locale_key_only():
    import json
    from pathlib import Path

    from game.server_events import EVENT_PRESETS, list_presets

    assert EVENT_PRESETS
    assert all("title" not in preset for preset in EVENT_PRESETS.values())
    title_keys = {str(preset.get("title_key") or "") for preset in EVENT_PRESETS.values()}
    assert all(key.startswith("server_event_preset_") for key in title_keys)
    assert len(title_keys) == len(EVENT_PRESETS)

    root = Path(__file__).resolve().parents[1]
    expected_effect_keys = {
        "server_event_scheduled_fallback",
        "server_event_effect_shop_discount",
        "server_event_effect_production",
        "server_event_effect_expedition_hold",
        "server_event_effect_build_speed",
        "server_event_effect_research_speed",
        "server_event_effect_asteroid_spawn",
        "server_event_effect_world_boss_spawn",
        "server_event_effect_inactive_farm",
    }
    for locale in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads((root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        assert title_keys <= set(data)
        assert expected_effect_keys <= set(data)
        assert all(str(data[key]).strip() for key in title_keys | expected_effect_keys)

    catalog = list_presets()
    assert len(catalog) == len(EVENT_PRESETS)
    assert all(p.get("title") and p.get("title_key") for p in catalog)


def test_server_event_effect_summary_localizes_all_effect_kinds():
    from game.server_events import (
        KIND_ASTEROID_SPAWN_MULT,
        KIND_BUILD_TIME_SPEED,
        KIND_EXPEDITION_HOLD_MULT,
        KIND_INACTIVE_FARM_MULT,
        KIND_PRODUCTION_MULT,
        KIND_RESEARCH_TIME_SPEED,
        KIND_SHOP_DISCOUNT_BPS,
        KIND_WORLD_BOSS_SPAWN_MULT,
        effect_summary_short,
    )

    effects = [
        {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
        {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
        {"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 2000},
        {"kind": KIND_BUILD_TIME_SPEED, "mult": 1.25},
        {"kind": KIND_RESEARCH_TIME_SPEED, "mult": 1.25},
        {"kind": KIND_ASTEROID_SPAWN_MULT, "mult": 2.0},
        {"kind": KIND_WORLD_BOSS_SPAWN_MULT, "mult": 2.0},
        {"kind": KIND_INACTIVE_FARM_MULT, "mult": 3.0},
    ]
    en = effect_summary_short(effects, locale="en")
    de = effect_summary_short(effects, locale="de")
    assert "+100% Production" in en
    assert "−25% Expedition Hold" in en
    assert "+100% Produktion" in de
    assert "−25% Expeditions-Haltezeit" in de
    assert "Asteroiden-Spawns ×2" in de
    assert en != de


def test_server_event_preset_title_key_and_custom_title_compatibility(events_db):
    from game.server_events import active_events_banner, apply_preset, create_event

    now = int(time.time())
    result, err = apply_preset(
        "double_production_24h",
        starts_at=now - 10,
        ends_at=now + 3600,
        now=float(now),
    )
    assert err is None, err
    assert result and result["event"]
    preset_slug = str(result["event"]["slug"])

    custom, custom_err = create_event(
        slug=f"custom-{uuid.uuid4().hex[:8]}",
        title="Community Surprise",
        starts_at=now - 10,
        ends_at=now + 3600,
        effects=[{"kind": KIND_PRODUCTION_MULT, "mult": 1.1}],
    )
    assert custom_err is None, custom_err
    assert custom

    banner_de = active_events_banner(now=float(now), locale="de")
    preset_row = next(row for row in banner_de if row.get("slug") == preset_slug)
    custom_row = next(row for row in banner_de if row.get("slug") == custom["slug"])
    assert preset_row["title_key"] == "server_event_preset_double_production_24h"
    assert preset_row["title"] == "Doppelte Produktion"
    assert custom_row["title_key"] == ""
    assert custom_row["title"] == "Community Surprise"
'''
tests.write_text(text.replace(anchor, new_tests + anchor), encoding="utf-8")

print("GC I18N Phase 3 server-events patch applied")
