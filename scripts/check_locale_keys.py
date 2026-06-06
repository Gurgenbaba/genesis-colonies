#!/usr/bin/env python3
"""GC-537: Audit locale keys used in Python, Jinja templates, and JS."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "locales"

# Static locale key (exclude trailing '_' — those are dynamic prefix fragments)
_RE_TR = re.compile(r"""(?<![A-Za-z0-9_])tr\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")
_RE_T = re.compile(r"""T\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")
_RE_T_JS = re.compile(r"""(?<![A-Za-z0-9_])t\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")
_RE_TF = re.compile(r"""(?<![A-Za-z0-9_])tf\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")
_RE_RANKING_T = re.compile(r"""rankingT\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")
_RE_TT = re.compile(r"""(?<![A-Za-z0-9_])tt\(\s*['"]([a-zA-Z0-9][a-zA-Z0-9_]*)['"]""")

_DYNAMIC_PREFIX_RE = re.compile(
    r"""(?:T|t|tt)\(\s*['"]([a-zA-Z0-9_]+)_['"]\s*(?:~|\+)"""
)

_SCAN_GLOBS = (
    "templates/**/*.html",
    "game/**/*.py",
    "app.py",
    "static/**/*.js",
)


def _load_json(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {str(k): str(v) for k, v in data.items()}


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _SCAN_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            files.append(path)
    return files


def _is_static_key(key: str) -> bool:
    return bool(key) and not key.endswith("_")


def _collect_static_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for rx in (_RE_TR, _RE_T, _RE_T_JS, _RE_TF, _RE_RANKING_T, _RE_TT):
        for key in rx.findall(text):
            if _is_static_key(key):
                keys.add(key)
    return keys


def _collect_dynamic_prefixes(text: str) -> set[str]:
    return set(_DYNAMIC_PREFIX_RE.findall(text))


def _keys_with_prefix(data: dict[str, str], prefix: str) -> set[str]:
    return {k for k in data if k.startswith(prefix)}


def _expand_registry_keys() -> set[str]:
    keys: set[str] = set()
    try:
        from game.buildings import BUILDING_ORDER, OVERVIEW_BUILDING_KEYS

        for b in BUILDING_ORDER:
            keys.add(f"building_{b}")
            keys.add(f"desc_{b}")
        for b in OVERVIEW_BUILDING_KEYS:
            keys.add(f"overview_building_{b}")
    except Exception:
        pass

    try:
        from game.research import RESEARCH_TECHS

        for tech, cfg in RESEARCH_TECHS.items():
            keys.add(tech)
            label_key = str(cfg.get("label_key") or tech)
            if _is_static_key(label_key):
                keys.add(label_key)
            desc_key = str(cfg.get("description_key") or f"desc_{tech}")
            if _is_static_key(desc_key):
                keys.add(desc_key)
    except Exception:
        pass

    try:
        from game.fleet_defs import SHIPS

        for sk in SHIPS:
            keys.add(f"fleet_ship_{sk}")
    except Exception:
        pass

    try:
        from game.defense_defs import DEFENSES

        for dk, spec in DEFENSES.items():
            name_key = str(spec.get("name_key") or f"defense_{dk}")
            if _is_static_key(name_key):
                keys.add(name_key)
            desc_key = str(spec.get("description_key") or f"defense_{dk}_desc")
            if _is_static_key(desc_key):
                keys.add(desc_key)
            role = str(spec.get("role") or "")
            if role:
                keys.add(f"defense_role_{role}")
    except Exception:
        pass

    try:
        from game.fleet_defs import MISSION_TYPES

        for m in MISSION_TYPES:
            keys.add(f"fleet_mission_{m}")
    except Exception:
        pass

    for s in ("outbound", "holding", "returning", "completed", "cancelled", "failed"):
        keys.add(f"fleet_status_{s}")

    for p in ("raid", "farm", "spy", "transport", "deploy", "expedition", "custom"):
        keys.add(f"fleet_preset_type_{p}")

    for r in ("cargo", "combat", "spy", "recycle", "expedition", "scout", "utility", "colony"):
        keys.add(f"shipyard_role_{r}")

    for r in (
        "already_running",
        "research_locked",
        "choice_required",
        "max_level",
        "queue_full",
        "not_enough_resources",
    ):
        keys.add(f"pe_reason_{r}")

    for a in ("build", "research", "fleet", "shipyard"):
        keys.add(f"overview_activity_{a}")

    try:
        from game.playercard import ALLOWED_THEMES

        for th in ALLOWED_THEMES:
            keys.add(f"playercard_theme_{th}")
    except Exception:
        pass

    return keys


def collect_used_keys() -> set[str]:
    used: set[str] = set()
    prefixes: set[str] = set()

    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        used.update(_collect_static_keys(text))
        prefixes.update(_collect_dynamic_prefixes(text))

    used.update(_expand_registry_keys())

    de = _load_json(LOCALES_DIR / "de.json")
    for prefix in prefixes:
        used.update(_keys_with_prefix(de, prefix))

    return used


def find_missing(locale: str, used: set[str]) -> list[str]:
    data = _load_json(LOCALES_DIR / f"{locale}.json")
    return sorted(k for k in used if k not in data)


def main() -> int:
    used = collect_used_keys()
    de_missing = find_missing("de", used)
    en_path = LOCALES_DIR / "en.json"
    en_missing = find_missing("en", used) if en_path.exists() else []

    print(f"Used keys (static + expanded dynamic): {len(used)}")
    print(f"Missing in de.json: {len(de_missing)}")
    if en_path.exists():
        print(f"Missing in en.json: {len(en_missing)}")

    if de_missing:
        print("\n--- Missing in de.json ---")
        for key in de_missing:
            print(key)

    if en_missing:
        print("\n--- Missing in en.json ---")
        for key in en_missing:
            print(key)

    if de_missing or en_missing:
        return 1
    print("OK — all used locale keys are present.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
