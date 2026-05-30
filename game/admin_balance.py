"""
Admin Balance settings – validated read/write for game pacing and economy knobs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from .models import DEFAULT_GAME_SETTINGS, get_game_settings, save_game_settings

# Keys exposed in Admin → Balance (whitelist only).
BALANCE_SETTING_KEYS: Tuple[str, ...] = (
    "start_metal",
    "start_crystal",
    "production_speed",
    "build_speed",
    "research_speed",
    "queue_limit",
    "research_queue_limit",
    "shipyard_speed",
    "shipyard_queue_limit",
    "score_weight_buildings",
    "score_weight_research",
    "exchange_enabled",
    "exchange_rate_metal_to_crystal",
    "exchange_rate_crystal_to_metal",
    "exchange_daily_limit",
    "exchange_min_amount",
)

_INT_NONNEG = frozenset({"start_metal", "start_crystal", "exchange_daily_limit", "exchange_min_amount"})
_INT_POS = frozenset({"queue_limit", "research_queue_limit", "shipyard_queue_limit"})
_FLOAT_POS = frozenset(
    {
        "production_speed",
        "build_speed",
        "research_speed",
        "shipyard_speed",
        "exchange_rate_metal_to_crystal",
        "exchange_rate_crystal_to_metal",
    }
)
_FLOAT_NONNEG = frozenset({"score_weight_buildings", "score_weight_research"})
_BOOL_KEYS = frozenset({"exchange_enabled"})

PRESET_B_BALANCE: Dict[str, Union[int, float, bool]] = {
    "start_metal": 3000,
    "start_crystal": 1500,
    "production_speed": 1.0,
    "build_speed": 1.1,
    "research_speed": 0.85,
    "queue_limit": 5,
    "research_queue_limit": 2,
    "shipyard_speed": 1.0,
    "shipyard_queue_limit": 3,
    "score_weight_buildings": 1.0,
    "score_weight_research": 0.7,
    "exchange_enabled": True,
    "exchange_rate_metal_to_crystal": float(DEFAULT_GAME_SETTINGS["exchange_rate_metal_to_crystal"]),
    "exchange_rate_crystal_to_metal": float(DEFAULT_GAME_SETTINGS["exchange_rate_crystal_to_metal"]),
    "exchange_daily_limit": int(DEFAULT_GAME_SETTINGS["exchange_daily_limit"]),
    "exchange_min_amount": int(DEFAULT_GAME_SETTINGS["exchange_min_amount"]),
}


def _parse_int(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip().replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _parse_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).strip().replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_bool(raw: Any) -> Optional[bool]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


def _coerce_setting_value(key: str, raw: Any) -> Tuple[Optional[Any], Optional[str]]:
    if key in _BOOL_KEYS:
        val = _parse_bool(raw)
        if val is None:
            return None, f"{key}: invalid boolean"
        return val, None

    if key in _INT_NONNEG | _INT_POS:
        val = _parse_int(raw)
        if val is None:
            return None, f"{key}: invalid integer"
        if key in _INT_POS and val < 1:
            return None, f"{key}: must be >= 1"
        if val < 0:
            return None, f"{key}: must be >= 0"
        return val, None

    if key in _FLOAT_POS | _FLOAT_NONNEG:
        val = _parse_float(raw)
        if val is None:
            return None, f"{key}: invalid number"
        if key in _FLOAT_POS and val <= 0:
            return None, f"{key}: must be > 0"
        if key in _FLOAT_NONNEG and val < 0:
            return None, f"{key}: must be >= 0"
        return val, None

    return None, f"{key}: unsupported"


def _display_value(key: str, raw: Any) -> Any:
    if key in _BOOL_KEYS:
        return str(raw).strip().lower() not in ("0", "false", "no", "off", "")
    if key in _INT_NONNEG | _INT_POS:
        try:
            return int(float(raw or 0))
        except (TypeError, ValueError):
            return 0
    if key in _FLOAT_POS | _FLOAT_NONNEG:
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0
    return raw


def get_balance_settings() -> Dict[str, Any]:
    settings = get_game_settings() or {}
    out: Dict[str, Any] = {}
    for key in BALANCE_SETTING_KEYS:
        if key in settings:
            out[key] = _display_value(key, settings[key])
        elif key in DEFAULT_GAME_SETTINGS:
            out[key] = _display_value(key, DEFAULT_GAME_SETTINGS[key])
        elif key in PRESET_B_BALANCE:
            out[key] = PRESET_B_BALANCE[key]
    return out


def validate_balance_payload(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(payload, dict):
        return None, "invalid_payload"

    unknown = sorted(set(payload.keys()) - set(BALANCE_SETTING_KEYS))
    if unknown:
        return None, f"unknown_keys: {', '.join(unknown)}"

    if not payload:
        return None, "empty_payload"

    cleaned: Dict[str, Any] = {}
    errors: List[str] = []
    for key, raw in payload.items():
        val, err = _coerce_setting_value(key, raw)
        if err:
            errors.append(err)
        else:
            cleaned[key] = val

    if errors:
        return None, "; ".join(errors)

    return cleaned, None


def save_balance_settings(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cleaned, err = validate_balance_payload(payload)
    if err:
        return None, err

    current = dict(get_game_settings() or {})
    current.update(cleaned)
    save_game_settings(current)

    try:
        from .ranking import invalidate_all_score_cache

        invalidate_all_score_cache()
    except Exception:
        pass

    return get_balance_settings(), None


def apply_preset_b() -> Dict[str, Any]:
    current = dict(get_game_settings() or {})
    current.update(PRESET_B_BALANCE)
    save_game_settings(current)

    try:
        from .ranking import invalidate_all_score_cache

        invalidate_all_score_cache()
    except Exception:
        pass

    return get_balance_settings()
