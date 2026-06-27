"""Genesis Codex — catalog, unlocks, player knowledge surfaces (GC-950)."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import sqlite3

from .db import db
from .i18n import current_locale, tr
from .knowledge_parser import ROOT as _ROOT

_CATALOG_PATH = _ROOT / "generated" / "codex" / "catalog.json"

_CODEX_SECTION_DEFS: tuple[tuple[str, str, str], ...] = (
    ("summary", "codex_section_summary", "Summary"),
    ("why", "codex_section_why", "Why it matters"),
    ("how_it_works", "codex_section_how", "How it works"),
)

_ROUTE_PRIMARY: Dict[str, str] = {
    "overview": "genesis_ark",
    "buildings_view": "buildings",
    "research_view": "research",
    "planet_evolution_view": "planet_evolution",
    "empire_view": "galaxy",
    "galaxy_view": "galaxy",
    "fleet_view": "fleet",
    "shipyard_view": "fleet",
    "defense_view": "defense",
    "trader_hub_view": "trader",
}


@lru_cache(maxsize=1)
def load_catalog() -> Dict[str, Any]:
    if not _CATALOG_PATH.is_file():
        return {"articles": {}, "routes": {}, "bands": {}, "commander_tips_pool": []}
    with open(_CATALOG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def catalog_articles() -> Dict[str, Any]:
    return dict(load_catalog().get("articles") or {})


def _visit_unlock_key(route: str) -> str:
    return f"codex_visit:{route}"


def record_codex_route_visit(player_id: int, route: str, *, conn: sqlite3.Connection | None = None) -> None:
    route = str(route or "").strip()
    if not route or not player_id:
        return
    own = conn is None
    c = conn or db()
    try:
        from .inventory_use import unlocks_schema_ready

        if not unlocks_schema_ready(c):
            return
        key = _visit_unlock_key(route)
        row = c.execute(
            "SELECT id FROM player_unlocks WHERE user_id = ? AND unlock_key = ? LIMIT 1",
            (int(player_id), key),
        ).fetchone()
        if row:
            return
        c.execute(
            "INSERT INTO player_unlocks (user_id, unlock_key, source_item_key, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (int(player_id), key, "codex"),
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def _has_route_visit(player_id: int, route: str, *, conn: sqlite3.Connection) -> bool:
    key = _visit_unlock_key(route)
    row = conn.execute(
        "SELECT 1 FROM player_unlocks WHERE user_id = ? AND unlock_key = ? LIMIT 1",
        (int(player_id), key),
    ).fetchone()
    return bool(row)


def _player_has_fleet_movement(player_id: int, *, conn: sqlite3.Connection) -> bool:
    try:
        from .fleet import fleet_schema_ready

        if not fleet_schema_ready():
            return False
        row = conn.execute(
            "SELECT 1 FROM fleet_movements WHERE player_id = ? LIMIT 1",
            (int(player_id),),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _active_planet_building_level(
    player_id: int, building_key: str, *, conn: sqlite3.Connection
) -> int:
    from .planet_evolution.repository import get_context_planet
    from .models import get_planet_buildings

    planet = get_context_planet(int(player_id), conn=conn)
    if not planet:
        return 0
    buildings = get_planet_buildings(int(planet["id"]), conn=conn) or {}
    level = int(buildings.get(building_key) or 0)
    if building_key == "orbital_shipyard":
        level = max(level, int(buildings.get("shipyard") or 0))
    return level


def is_codex_unlocked(
    player_id: int,
    codex_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> bool:
    articles = catalog_articles()
    article = articles.get(str(codex_id or ""))
    if not article:
        return False
    unlock = dict(article.get("unlock") or {"type": "always"})
    utype = str(unlock.get("type") or "always")
    if utype == "always":
        return True

    own = conn is None
    c = conn or db()
    try:
        uid = int(player_id)
        if utype == "homeworld_level":
            from .planet_evolution.expansion_gates import get_homeworld_level

            need = int(unlock.get("value") or 1)
            site_key = str(unlock.get("site_key") or "").strip()
            if site_key:
                from .planet_evolution.expansion_gates import is_expansion_site_unlocked

                hw = get_homeworld_level(uid, conn=c)
                return is_expansion_site_unlocked(site_key, hw) or hw >= need
            return get_homeworld_level(uid, conn=c) >= need
        if utype == "expansion_site":
            from .planet_evolution.expansion_gates import get_homeworld_level, is_expansion_site_unlocked

            site_key = str(unlock.get("site_key") or "").strip()
            if not site_key:
                return False
            return is_expansion_site_unlocked(site_key, get_homeworld_level(uid, conn=c))
        if utype == "building":
            bkey = str(unlock.get("building") or "").strip()
            return _active_planet_building_level(uid, bkey, conn=c) >= 1
        if utype == "route_visit":
            route = str(unlock.get("route") or "").strip()
            return _has_route_visit(uid, route, conn=c)
        if utype == "player_flag":
            flag = str(unlock.get("flag") or "").strip()
            if flag == "first_fleet_sent":
                return _player_has_fleet_movement(uid, conn=c)
            return _has_route_visit(uid, flag, conn=c)
        return True
    finally:
        if own:
            c.close()


def unlocked_codex_ids(player_id: int, *, conn: sqlite3.Connection | None = None) -> Set[str]:
    own = conn is None
    c = conn or db()
    try:
        out: Set[str] = set()
        for codex_id in catalog_articles().keys():
            if is_codex_unlocked(int(player_id), codex_id, conn=c):
                out.add(codex_id)
        return out
    finally:
        if own:
            c.close()


def primary_codex_for_route(endpoint: str) -> Optional[str]:
    ep = str(endpoint or "").strip()
    if ep in _ROUTE_PRIMARY:
        return _ROUTE_PRIMARY[ep]
    catalog = load_catalog()
    routes = catalog.get("routes") or {}
    if ep in routes and routes[ep]:
        return str(routes[ep][0])
    return None


def quick_help_for_route(
    player_id: int,
    endpoint: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> Optional[Dict[str, str]]:
    codex_id = primary_codex_for_route(endpoint)
    if not codex_id:
        return None
    if not is_codex_unlocked(int(player_id), codex_id, conn=conn):
        return None
    article = catalog_articles().get(codex_id) or {}
    if "quick_help" not in (article.get("surfaces") or []):
        return None
    key = f"codex_{codex_id}_quick_help"
    return {"codex_id": codex_id, "text_key": key}


def commander_tip_for_date(
    player_id: int,
    *,
    when: date | None = None,
    conn: sqlite3.Connection | None = None,
) -> Optional[Dict[str, str]]:
    pool = list(load_catalog().get("commander_tips_pool") or [])
    if not pool:
        return None
    day = when or date.today()
    idx = hash(day.isoformat()) % len(pool)
    entry = pool[idx]
    codex_id = str(entry.get("codex_id") or "")
    if not is_codex_unlocked(int(player_id), codex_id, conn=conn):
        return None
    # Find tip index within article
    tips = [
        t
        for t in pool
        if str(t.get("codex_id") or "") == codex_id
    ]
    tip_text = str(entry.get("text") or "")
    tip_idx = next((i for i, t in enumerate(tips) if t.get("text") == tip_text), 0)
    return {
        "codex_id": codex_id,
        "text_key": f"codex_{codex_id}_tip_{tip_idx}",
    }


def build_codex_panel_state(player_id: int, *, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        unlocked = unlocked_codex_ids(int(player_id), conn=c)
        catalog = load_catalog()
        bands_order = ["I", "II", "III", "IV", "—"]
        bands_out: List[Dict[str, Any]] = []
        for band in bands_order:
            ids = list((catalog.get("bands") or {}).get(band) or [])
            if not ids:
                continue
            entries = []
            for cid in ids:
                art = catalog_articles().get(cid) or {}
                entries.append(
                    {
                        "codex_id": cid,
                        "unlocked": cid in unlocked,
                        "teaser_key": str(art.get("teaser_key") or ""),
                        "estimated_read": str(art.get("estimated_read") or ""),
                        "title_key": f"codex_{cid}_title",
                    }
                )
            bands_out.append(
                {
                    "band": band,
                    "label_key": f"codex_band_{band}" if band != "—" else "codex_title",
                    "articles": entries,
                }
            )
        return {"bands": bands_out, "unlocked_ids": sorted(unlocked)}
    finally:
        if own:
            c.close()


def codex_for_game_state(player_id: int, *, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        tip = commander_tip_for_date(int(player_id), conn=c)
        unlocked = unlocked_codex_ids(int(player_id), conn=c)
        client = build_codex_client_config(int(player_id), conn=c)
        return {
            "unlocked_count": len(unlocked),
            "total_count": len(catalog_articles()),
            "unlocked_ids": sorted(unlocked),
            "commander_tip": tip,
            "articles": client.get("articles") or {},
        }
    finally:
        if own:
            c.close()


def _codex_locale_text(key: str, default: str = "", *, locale: str | None = None) -> str:
    if not key:
        return default
    text = tr(key, default or key, locale=locale)
    if not text or text == key:
        return default
    return text


def _codex_unlock_label(article: Dict[str, Any], *, locale: str | None = None) -> str:
    teaser_key = str(article.get("teaser_key") or "").strip()
    if teaser_key:
        return _codex_locale_text(teaser_key, "", locale=locale)
    unlock = dict(article.get("unlock") or {"type": "always"})
    utype = str(unlock.get("type") or "always")
    if utype == "always":
        return ""
    if utype == "building":
        building = str(unlock.get("building") or "").strip()
        return _codex_locale_text(
            "codex_unlock_building",
            f"Build {building} on your active world.",
            locale=locale,
        )
    if utype == "route_visit":
        return _codex_locale_text(
            "codex_unlock_route_visit",
            "Visit the related game page to unlock this topic.",
            locale=locale,
        )
    if utype == "player_flag" and str(unlock.get("flag") or "") == "first_fleet_sent":
        return _codex_locale_text(
            "codex_unlock_first_fleet",
            "Send your first fleet to unlock this topic.",
            locale=locale,
        )
    if utype in ("homeworld_level", "expansion_site"):
        return _codex_locale_text(
            "codex_unlock_expansion_teaser",
            "Develop your Genesis Ark to unlock this topic.",
            locale=locale,
        )
    return _codex_locale_text("codex_unlock_generic", "Progress further to unlock this topic.", locale=locale)


def build_codex_article_client_entry(
    player_id: int,
    codex_id: str,
    *,
    conn: sqlite3.Connection,
    locale: str | None = None,
) -> Dict[str, Any]:
    """Resolved article payload for Codex detail panel (GC-950 client contract)."""
    cid = str(codex_id or "").strip()
    art = catalog_articles().get(cid) or {}
    loc = locale or current_locale()
    prefix = f"codex_{cid}"
    locked = not is_codex_unlocked(int(player_id), cid, conn=conn)
    teaser_key = str(art.get("teaser_key") or "").strip()
    teaser = _codex_locale_text(teaser_key, "", locale=loc) if teaser_key else ""
    unlock_label = _codex_unlock_label(art, locale=loc)
    title = _codex_locale_text(f"{prefix}_title", cid.replace("_", " ").title(), locale=loc)

    sections: List[Dict[str, Any]] = []
    summary = ""

    if not locked:
        for field, title_key, title_default in _CODEX_SECTION_DEFS:
            body = _codex_locale_text(f"{prefix}_{field}", "", locale=loc)
            if not body:
                continue
            if field == "summary":
                summary = body
            sections.append(
                {
                    "key": field,
                    "title": _codex_locale_text(title_key, title_default, locale=loc),
                    "body": body,
                }
            )

        faq_count = int(art.get("faq_count") or 0)
        faq_items: List[Dict[str, str]] = []
        for i in range(faq_count):
            q = _codex_locale_text(f"{prefix}_faq_{i}_q", "", locale=loc)
            a = _codex_locale_text(f"{prefix}_faq_{i}_a", "", locale=loc)
            if q:
                faq_items.append({"q": q, "a": a})
        if faq_items:
            sections.append(
                {
                    "key": "faq",
                    "title": _codex_locale_text("codex_faq_title", "FAQ", locale=loc),
                    "items": faq_items,
                }
            )

    related = list(art.get("related_codex") or [])

    surfaces = list(art.get("surfaces") or [])
    preview = ""
    if locked and "quick_help" in surfaces:
        preview = _codex_locale_text(f"{prefix}_quick_help", "", locale=loc)

    return {
        "codex_id": cid,
        "title": title,
        "summary": summary,
        "sections": sections,
        "locked": locked,
        "teaser": teaser,
        "unlock_label": unlock_label,
        "preview": preview,
        "related": related,
        "title_key": f"{prefix}_title",
        "summary_key": f"{prefix}_summary",
        "why_key": f"{prefix}_why",
        "how_it_works_key": f"{prefix}_how_it_works",
        "faq": [
            {"q_key": f"{prefix}_faq_{i}_q", "a_key": f"{prefix}_faq_{i}_a"}
            for i in range(int(art.get("faq_count") or 0))
        ],
    }


def build_codex_client_config(
    player_id: int,
    *,
    conn: sqlite3.Connection | None = None,
    locale: str | None = None,
) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        loc = locale or current_locale()
        articles: Dict[str, Any] = {}
        for cid in catalog_articles().keys():
            articles[cid] = build_codex_article_client_entry(
                int(player_id), cid, conn=c, locale=loc
            )
        return {"articles": articles}
    finally:
        if own:
            c.close()


def build_codex_template_context(
    player_id: int,
    endpoint: str,
    *,
    conn: sqlite3.Connection,
    record_visit: bool = True,
) -> Dict[str, Any]:
    route = codex_route_for_endpoint(endpoint)
    if record_visit and route:
        record_codex_route_visit(int(player_id), route, conn=conn)
    route_key = route or str(endpoint or "").strip()
    primary = primary_codex_for_route(route_key)
    return {
        "CODEX_PANEL": build_codex_panel_state(int(player_id), conn=conn),
        "CODEX_QUICK_HELP": quick_help_for_route(int(player_id), route_key, conn=conn),
        "CODEX_COMMANDER_TIP": commander_tip_for_date(int(player_id), conn=conn),
        "CODEX_PRIMARY": primary,
        "CODEX_CLIENT": build_codex_client_config(int(player_id), conn=conn),
    }


def codex_route_for_endpoint(endpoint: str) -> Optional[str]:
    ep = str(endpoint or "").strip()
    routes = load_catalog().get("routes") or {}
    if ep in routes:
        return ep
    return None


def article_content_keys(codex_id: str) -> Dict[str, Any]:
    """Keys for template/JS to render one article (i18n via T)."""
    art = catalog_articles().get(str(codex_id or "")) or {}
    prefix = f"codex_{codex_id}"
    keys: Dict[str, Any] = {
        "codex_id": codex_id,
        "title_key": f"{prefix}_title",
        "related": list(art.get("related_codex") or []),
    }
    for section in ("summary", "why", "how_it_works"):
        if section.replace("_", "_") in ("summary", "why", "how_it_works"):
            keys[f"{section}_key"] = f"{prefix}_{section}"
    keys["summary_key"] = f"{prefix}_summary"
    keys["why_key"] = f"{prefix}_why"
    keys["how_it_works_key"] = f"{prefix}_how_it_works"
    faq_count = int(art.get("faq_count") or 0)
    keys["faq"] = [
        {"q_key": f"{prefix}_faq_{i}_q", "a_key": f"{prefix}_faq_{i}_a"}
        for i in range(faq_count)
    ]
    return keys
