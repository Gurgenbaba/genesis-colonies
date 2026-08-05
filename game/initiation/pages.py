"""Map HTTP paths / finish_sources to Command Initiation page keys."""

from __future__ import annotations

from typing import Optional

# Longest-prefix wins. Used when finish_source is generic (page_load).
_PATH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/combat-simulator", "combat_simulator"),
    ("/planet-evolution", "planet_evolution"),
    ("/imperial-directives", "imperial_directives"),
    ("/galactic-politics", "galactic_politics"),
    ("/auction-house", "auction_house"),
    ("/login-rewards", "login_rewards"),
    ("/trader-hub", "trader_hub"),
    ("/hall-of-fame", "hall_of_fame"),
    ("/world-boss", "world_boss"),
    ("/vote-center", "vote_center"),
    ("/skilltree", "skilltree"),
    ("/techtree", "techtree"),
    ("/inventory", "inventory"),
    ("/referrals", "referrals"),
    ("/alliance", "alliance"),
    ("/messages", "messages"),
    ("/ranking", "ranking"),
    ("/premium", "premium"),
    ("/records", "records"),
    ("/galaxy", "galaxy"),
    ("/empire", "empire"),
    ("/story", "story"),
    ("/shop", "shop"),
    ("/fleet", "fleet"),
    ("/buildings", "buildings"),
    ("/research", "research"),
    ("/shipyard", "shipyard"),
    ("/defense", "defense"),
    ("/overview", "overview"),
)

# Named page loads that already pass a specific finish_source.
# Keep in sync with visit_page filters in command_initiation.json.
_FINISH_SOURCE_PAGES: dict[str, str] = {
    "overview": "overview",
    "buildings": "buildings",
    "research": "research",
    "techtree": "techtree",
    "skilltree": "skilltree",
    "fleet": "fleet",
    "galaxy": "galaxy",
    "combat_simulator": "combat_simulator",
    "planet_evolution": "planet_evolution",
    "trader_hub": "trader_hub",
    "inventory": "inventory",
    "auction_house": "auction_house",
    "imperial_directives": "imperial_directives",
    "story": "story",
    "login_rewards": "login_rewards",
    "premium": "premium",
    "shop": "shop",
    "shop_return": "shop",
    "alliance": "alliance",
    "alliance_visitor": "alliance",
    "galactic_politics": "galactic_politics",
    "vote_center": "vote_center",
    "referrals": "referrals",
    "ranking": "ranking",
    "hall_of_fame": "hall_of_fame",
    "messages": "messages",
    "world_boss": "world_boss",
    "records": "records",
    "empire": "empire",
}

# Poll / mutation sources — never count as page visits.
_SKIP_FINISH_SOURCES = frozenset(
    {
        "game_state",
        "game_state_panel",
        "game_state_buildings_finish",
        "page_load",  # resolve via path only
        "api_planets_active",
        "initiation",  # mission page itself
    }
)


def page_key_from_path(path: str | None) -> str:
    raw = str(path or "").strip().split("?", 1)[0].rstrip("/") or "/"
    if raw != "/" and not raw.startswith("/"):
        raw = "/" + raw
    best = ""
    best_len = -1
    for prefix, key in _PATH_PREFIXES:
        if raw == prefix or raw.startswith(prefix + "/"):
            if len(prefix) > best_len:
                best = key
                best_len = len(prefix)
    return best


def page_key_from_finish_source(finish_source: str | None) -> str:
    src = str(finish_source or "").strip()
    if not src or src in _SKIP_FINISH_SOURCES or src.startswith("api_"):
        return ""
    return str(_FINISH_SOURCE_PAGES.get(src) or "")


def resolve_page_key(
    *,
    path: str | None = None,
    finish_source: str | None = None,
) -> str:
    """Prefer explicit finish_source mapping; fall back to request path."""
    src = str(finish_source or "").strip()
    if src.startswith("api_") or src in (
        "game_state",
        "game_state_panel",
        "game_state_buildings_finish",
        "api_planets_active",
    ):
        return ""
    keyed = page_key_from_finish_source(finish_source)
    if keyed:
        return keyed
    return page_key_from_path(path)


def should_record_page_visit(finish_source: str | None) -> bool:
    src = str(finish_source or "").strip()
    if not src or src.startswith("api_"):
        return False
    if src in ("game_state", "game_state_panel", "game_state_buildings_finish", "api_planets_active"):
        return False
    return True
