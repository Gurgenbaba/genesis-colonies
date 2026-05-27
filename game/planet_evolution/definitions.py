"""Load planet evolution definitions from DB with in-memory cache."""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from ..models import db
from .repository import _json_loads

_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {"loaded": False}


def _parse_row(row: sqlite3.Row, json_cols: List[str]) -> Dict[str, Any]:
    data = dict(row)
    for col in json_cols:
        if col in data:
            default: Any = {} if "json" in col and col != "choice_options_json" else None
            if col == "choice_options_json":
                default = None
            parsed = _json_loads(data.pop(col), default if default is not None else [])
            key = col.replace("_json", "")
            data[key] = parsed
    return data


def reload_definitions(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        with _CACHE_LOCK:
            _CACHE["traits"] = {
                r["trait_key"]: _parse_row(r, ["planet_class_weights_json", "effects_json", "unlocks_json", "blocks_json", "risk_json"])
                for r in cur.execute("SELECT * FROM pe_trait_definitions;").fetchall()
            }
            _CACHE["research"] = {
                r["tech_key"]: _parse_row(r, ["requirements_json", "choice_options_json", "mechanics_json", "risk_json"])
                for r in cur.execute("SELECT * FROM pe_research_definitions ORDER BY tier ASC, tech_key ASC;").fetchall()
            }
            _CACHE["specializations"] = {
                r["spec_key"]: _parse_row(r, [
                    "required_traits_any_json", "required_affinities_json", "incompatible_specs_json",
                    "tier_mechanics_json", "event_pool_json", "export_unlocks_json", "import_demands_json",
                ])
                for r in cur.execute("SELECT * FROM pe_specialization_definitions;").fetchall()
            }
            _CACHE["policies"] = {
                r["policy_key"]: _parse_row(r, ["archetype_allow_json", "mechanics_json", "tradeoffs_json"])
                for r in cur.execute("SELECT * FROM pe_policy_definitions;").fetchall()
            }
            _CACHE["events"] = {
                r["event_key"]: _parse_row(r, ["pool_tags_json", "trigger_json", "choices_json", "failure_link_json"])
                for r in cur.execute("SELECT * FROM pe_event_definitions;").fetchall()
            }
            _CACHE["discoveries"] = {
                r["discovery_key"]: _parse_row(r, ["requirements_json", "mechanics_json"])
                for r in cur.execute("SELECT * FROM pe_discovery_definitions;").fetchall()
            }
            _CACHE["special_resources"] = {r["resource_key"]: dict(r) for r in cur.execute("SELECT * FROM pe_special_resource_definitions;").fetchall()}
            _CACHE["chains"] = {
                r["chain_key"]: _parse_row(r, ["inputs_json", "failure_risk_json"])
                for r in cur.execute("SELECT * FROM pe_production_chain_definitions;").fetchall()
            }
            _CACHE["ascensions"] = {
                r["ascension_key"]: _parse_row(r, ["requirements_json", "permanent_mechanics_json"])
                for r in cur.execute("SELECT * FROM pe_ascension_definitions;").fetchall()
            }
            _CACHE["loaded"] = True
    finally:
        if own:
            conn.close()


def _ensure_loaded() -> None:
    if not _CACHE.get("loaded"):
        reload_definitions()


def get_traits() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("traits") or {})


def get_trait(trait_key: str) -> Optional[Dict[str, Any]]:
    return get_traits().get(trait_key)


def get_research_defs() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("research") or {})


def get_research_def(tech_key: str) -> Optional[Dict[str, Any]]:
    return get_research_defs().get(tech_key)


def get_specializations() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("specializations") or {})


def get_specialization(spec_key: str) -> Optional[Dict[str, Any]]:
    return get_specializations().get(spec_key)


def get_policies() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("policies") or {})


def get_policy(policy_key: str) -> Optional[Dict[str, Any]]:
    return get_policies().get(policy_key)


def get_events() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("events") or {})


def get_event(event_key: str) -> Optional[Dict[str, Any]]:
    return get_events().get(event_key)


def get_discoveries_defs() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("discoveries") or {})


def get_discovery_def(discovery_key: str) -> Optional[Dict[str, Any]]:
    return get_discoveries_defs().get(discovery_key)


def get_chains() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("chains") or {})


def get_chain(chain_key: str) -> Optional[Dict[str, Any]]:
    return get_chains().get(chain_key)


def get_ascensions() -> Dict[str, Dict[str, Any]]:
    _ensure_loaded()
    return dict(_CACHE.get("ascensions") or {})


def get_ascension(ascension_key: str) -> Optional[Dict[str, Any]]:
    return get_ascensions().get(ascension_key)


def get_special_resource_def(resource_key: str) -> Optional[Dict[str, Any]]:
    _ensure_loaded()
    return (_CACHE.get("special_resources") or {}).get(resource_key)
