"""Role-based sidebar navigation (GC-591) — presentation only, no route or permission changes."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

ALL_NAV_MODULES: List[str] = [
    "overview",
    "buildings",
    "research",
    "techtree",
    "planet_evolution",
    "empire",
    "shipyard",
    "defense",
    "fleet",
    "logistics",
    "trading",
    "alliance",
    "galaxy",
    "ranking",
    "hall_of_fame",
    "chronicles",
    "referrals",
    "records",
    "login_rewards",
    "premium",
    "messages",
    "options",
    "support",
]

STANDALONE_NAV_MODULES = frozenset({"messages"})
MOBILE_ALWAYS_BOTTOM: Tuple[str, ...] = ()

NAV_SECTION_MODULES: Dict[str, Tuple[str, ...]] = {
    "command": ("overview", "galaxy", "planet_evolution", "login_rewards", "premium"),
    "messages": ("messages",),
    "infrastructure": ("buildings", "research"),
    "military": ("shipyard", "fleet", "defense", "logistics"),
    "economy": ("trading", "empire", "techtree"),
    "administration": ("alliance", "ranking", "chronicles", "hall_of_fame", "referrals", "records", "support"),
}

UTILITY_MODULES = frozenset(NAV_SECTION_MODULES["administration"])
# Back-compat alias for templates/tests/client config.
ADMINISTRATION_MODULES = UTILITY_MODULES

MODULE_PRIMARY_SECTION: Dict[str, str] = {
    module: section
    for section, modules in NAV_SECTION_MODULES.items()
    if section != "administration"
    for module in modules
}

OVERFLOW_MODULE_ORDER: Tuple[str, ...] = tuple(
    module
    for section in ("command", "infrastructure", "military", "economy")
    for module in NAV_SECTION_MODULES[section]
)

MOBILE_BOTTOM_PRIORITY: List[str] = [
    "overview",
    "buildings",
    "research",
    "defense",
    "logistics",
    "fleet",
    "galaxy",
    "planet_evolution",
    "trading",
    "ranking",
    "hall_of_fame",
    "chronicles",
    "referrals",
    "records",
]
MOBILE_BOTTOM_MAX = 4

_HOMEWORLD_ROLE_KEYS = frozenset({"homeworld", "genesis_ark"})
# Empire-wide core modules — always visible on every colony (GC-641 / GC-641B).
_ALWAYS_PROMINENT_MODULES = frozenset({"trading", "empire", "ranking", "records", "referrals"})

_ROLE_PROMINENT: Dict[str, Iterable[str]] = {
    "mining": (
        "overview",
        "buildings",
        "defense",
        "logistics",
        "fleet",
        "trading",
    ),
    "research": (
        "overview",
        "research",
        "techtree",
        "planet_evolution",
        "buildings",
        "defense",
    ),
    "shipyard": (
        "overview",
        "shipyard",
        "fleet",
        "buildings",
        "defense",
    ),
    "fortress": (
        "overview",
        "defense",
        "fleet",
        "buildings",
        "shipyard",
    ),
    "frontier": (
        "overview",
        "planet_evolution",
        "buildings",
        "fleet",
        "galaxy",
    ),
    "trade": (
        "overview",
        "trading",
        "logistics",
        "buildings",
        "fleet",
        "defense",
    ),
}


def resolve_sidebar_nav(
    *,
    empire_role_key: str = "general",
    is_homeworld: bool = False,
) -> Dict[str, Any]:
    """Return sidebar visibility tiers for the active colony role."""
    role = str(empire_role_key or "general").strip().lower()
    if is_homeworld or role in _HOMEWORLD_ROLE_KEYS:
        return _full_nav_payload("homeworld")

    prominent = set(_ROLE_PROMINENT.get(role, ()))
    if not prominent:
        return _full_nav_payload(role)

    modules: Dict[str, str] = {}
    for key in ALL_NAV_MODULES:
        if key in _ALWAYS_PROMINENT_MODULES:
            modules[key] = "prominent"
        else:
            modules[key] = "prominent" if key in prominent else "secondary"

    return {
        "empire_role_key": role,
        "is_homeworld": False,
        "full_nav": False,
        "show_more_section": True,
        "modules": modules,
    }


def _full_nav_payload(role_key: str) -> Dict[str, Any]:
    return {
        "empire_role_key": role_key,
        "is_homeworld": role_key in _HOMEWORLD_ROLE_KEYS,
        "full_nav": True,
        "show_more_section": False,
        "modules": {key: "prominent" for key in ALL_NAV_MODULES},
    }


def nav_module_tier(sidebar_nav: Dict[str, Any] | None, module: str) -> str:
    """Template helper — unknown modules stay prominent."""
    if module in STANDALONE_NAV_MODULES:
        return "prominent"
    if not sidebar_nav or sidebar_nav.get("full_nav"):
        return "prominent"
    return str(sidebar_nav.get("modules", {}).get(module) or "prominent")


def module_display_section(sidebar_nav: Dict[str, Any] | None, module: str) -> Optional[str]:
    """Exactly one sidebar section per module, or None if hidden."""
    if module in ("support", "options"):
        return None
    if module in STANDALONE_NAV_MODULES:
        return "messages"
    if module in UTILITY_MODULES:
        return "administration"
    return MODULE_PRIMARY_SECTION.get(module)


def secondary_overflow_modules(sidebar_nav: Dict[str, Any] | None) -> List[str]:
    """Deprecated — Verwaltung no longer mirrors secondary modules (GC-621B)."""
    return []


def visible_sidebar_modules(sidebar_nav: Dict[str, Any] | None) -> List[str]:
    """Ordered unique modules visible anywhere in the sidebar."""
    seen: set[str] = set()
    ordered: List[str] = []
    for module in ALL_NAV_MODULES:
        if module_display_section(sidebar_nav, module) and module not in seen:
            seen.add(module)
            ordered.append(module)
    return ordered


def module_in_section(sidebar_nav: Dict[str, Any] | None, module: str, section: str) -> bool:
    return module_display_section(sidebar_nav, module) == section


def sidebar_section_visible(sidebar_nav: Dict[str, Any] | None, section: str) -> bool:
    if section == "administration":
        return any(module_in_section(sidebar_nav, module, "administration") for module in ALL_NAV_MODULES)
    modules = NAV_SECTION_MODULES.get(section, ())
    return any(module_in_section(sidebar_nav, module, section) for module in modules)


def nav_link_visible(sidebar_nav: Dict[str, Any] | None, module: str, placement: str) -> bool:
    """Legacy placement helper — maps to single-section display."""
    section = module_display_section(sidebar_nav, module)
    if not section:
        return False
    if placement == "administration":
        return section == "administration"
    return section == MODULE_PRIMARY_SECTION.get(module)


def nav_module_shows_primary(sidebar_nav: Dict[str, Any] | None, module: str) -> bool:
    return module_in_section(sidebar_nav, module, MODULE_PRIMARY_SECTION.get(module, ""))


def nav_module_shows_administration(sidebar_nav: Dict[str, Any] | None, module: str) -> bool:
    return module_in_section(sidebar_nav, module, "administration")


def mobile_bottom_modules(sidebar_nav: Dict[str, Any] | None) -> List[str]:
    """Prominent modules shown in the mobile bottom bar (max 4, messages always pinned)."""
    always = list(MOBILE_ALWAYS_BOTTOM)
    slot_count = max(0, MOBILE_BOTTOM_MAX - len(always))
    if not sidebar_nav or sidebar_nav.get("full_nav"):
        base = ["overview", "buildings", "research", "fleet"]
    else:
        base = [
            key
            for key in MOBILE_BOTTOM_PRIORITY
            if key not in always and nav_module_tier(sidebar_nav, key) == "prominent"
        ]
    return base[:slot_count] + always


def mobile_drawer_shows_module(
    sidebar_nav: Dict[str, Any] | None,
    module: str,
    *,
    bottom_modules: List[str] | None = None,
) -> bool:
    """Whether a module link belongs in the mobile drawer (deduped)."""
    bottom = bottom_modules if bottom_modules is not None else mobile_bottom_modules(sidebar_nav)
    if module in bottom:
        return False
    if not sidebar_nav or sidebar_nav.get("full_nav"):
        return True
    section = module_display_section(sidebar_nav, module)
    if section == "administration":
        return module in UTILITY_MODULES or nav_module_tier(sidebar_nav, module) == "secondary"
    if section and MODULE_PRIMARY_SECTION.get(module) == section:
        return nav_module_tier(sidebar_nav, module) == "prominent"
    return False


def client_sidebar_nav_config() -> Dict[str, Any]:
    """Minimal role map for client-side sidebar sync after planet switch."""
    return {
        "all_modules": list(ALL_NAV_MODULES),
        "prominent_by_role": {key: list(modules) for key, modules in _ROLE_PROMINENT.items()},
        "homeworld_roles": sorted(_HOMEWORLD_ROLE_KEYS),
        "always_prominent_modules": sorted(_ALWAYS_PROMINENT_MODULES),
        "mobile_bottom_priority": list(MOBILE_BOTTOM_PRIORITY),
        "mobile_bottom_max": MOBILE_BOTTOM_MAX,
        "mobile_always_bottom": list(MOBILE_ALWAYS_BOTTOM),
        "standalone_modules": sorted(STANDALONE_NAV_MODULES),
        "utility_modules": sorted(UTILITY_MODULES),
        "administration_modules": sorted(UTILITY_MODULES),
        "module_primary_section": dict(MODULE_PRIMARY_SECTION),
        "overflow_module_order": list(OVERFLOW_MODULE_ORDER),
    }
