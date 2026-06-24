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
    "fleet_speed_war",
    "fleet_speed_holding",
    "fleet_speed_peaceful",
    "queue_limit",
    "research_queue_limit",
    "shipyard_speed",
    "shipyard_queue_limit",
    "score_weight_buildings",
    "score_weight_research",
    "score_weight_fleet",
    "score_cost_exponent",
    "score_softcap",
    "exchange_enabled",
    "exchange_rate_metal_to_crystal",
    "exchange_rate_crystal_to_metal",
    "exchange_daily_limit_pct",
    "exchange_daily_limit_min",
    "exchange_min_amount",
    "fuel_exchange_enabled",
    "fuel_exchange_metal_per_unit",
    "fuel_exchange_crystal_per_unit",
    "fuel_exchange_min_units",
    "fuel_production_per_hour",
)

_INT_NONNEG = frozenset({
    "start_metal",
    "start_crystal",
    "exchange_min_amount",
    "fuel_exchange_min_units",
    "fuel_production_per_hour",
    "exchange_daily_limit_pct",
    "exchange_daily_limit_min",
})
_INT_POS = frozenset({"queue_limit", "research_queue_limit", "shipyard_queue_limit"})
_FLOAT_POS = frozenset(
    {
        "production_speed",
        "build_speed",
        "research_speed",
        "fleet_speed_war",
        "fleet_speed_holding",
        "fleet_speed_peaceful",
        "shipyard_speed",
        "exchange_rate_metal_to_crystal",
        "exchange_rate_crystal_to_metal",
        "fuel_exchange_metal_per_unit",
        "fuel_exchange_crystal_per_unit",
        "score_cost_exponent",
    }
)
_INT_PCT = frozenset({"exchange_daily_limit_pct"})
_FLOAT_NONNEG = frozenset({
    "score_weight_buildings",
    "score_weight_research",
    "score_weight_fleet",
    "score_softcap",
})
_BOOL_KEYS = frozenset({"exchange_enabled", "fuel_exchange_enabled"})

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
    "score_weight_fleet": 1.0,
    "score_cost_exponent": float(DEFAULT_GAME_SETTINGS.get("score_cost_exponent", 1.0)),
    "score_softcap": float(DEFAULT_GAME_SETTINGS.get("score_softcap", 0.0)),
    "exchange_enabled": True,
    "exchange_rate_metal_to_crystal": float(DEFAULT_GAME_SETTINGS["exchange_rate_metal_to_crystal"]),
    "exchange_rate_crystal_to_metal": float(DEFAULT_GAME_SETTINGS["exchange_rate_crystal_to_metal"]),
    "exchange_daily_limit_pct": int(float(DEFAULT_GAME_SETTINGS.get("exchange_daily_limit_pct", 80))),
    "exchange_daily_limit_min": int(DEFAULT_GAME_SETTINGS.get("exchange_daily_limit_min", 500_000)),
    "exchange_min_amount": int(DEFAULT_GAME_SETTINGS["exchange_min_amount"]),
    "fuel_exchange_enabled": True,
    "fuel_exchange_metal_per_unit": float(DEFAULT_GAME_SETTINGS["fuel_exchange_metal_per_unit"]),
    "fuel_exchange_crystal_per_unit": float(DEFAULT_GAME_SETTINGS["fuel_exchange_crystal_per_unit"]),
    "fuel_exchange_min_units": int(DEFAULT_GAME_SETTINGS["fuel_exchange_min_units"]),
    "fuel_production_per_hour": int(float(DEFAULT_GAME_SETTINGS["fuel_production_per_hour"])),
}


def _parse_int(raw: Any) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        s = str(raw).strip().replace(" ", "").replace(",", ".")
        return int(float(s))
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

    if key in _INT_NONNEG | _INT_POS | _INT_PCT:
        val = _parse_int(raw)
        if val is None:
            return None, f"{key}: invalid integer"
        if key in _INT_POS and val < 1:
            return None, f"{key}: must be >= 1"
        if key in _INT_PCT and (val < 0 or val > 100):
            return None, f"{key}: must be 0–100"
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
    if key in _INT_NONNEG | _INT_POS | _INT_PCT:
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


def build_balance_hud_snapshot(player_id: int) -> Optional[Dict[str, Any]]:
    """
    Read-only HUD payload after balance changes — no queue finish, no fleet tick.
    Avoids blocking the dev server on a full /api/game-state refresh.
    """
    from .db import db
    from .logic import _read_player_live_state_no_writes, get_building_production_per_hour
    from .models import load_player
    from .planet_evolution.repository import get_context_planet

    uid = int(player_id)
    conn = db()
    try:
        player = load_player(uid, conn=conn)
        if not player:
            return None
        planet = get_context_planet(uid, conn=conn)
        player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
            _read_player_live_state_no_writes(uid, conn, player, planet)
        )
        prod = get_building_production_per_hour(
            buildings,
            ratio,
            user_id=uid,
            conn=conn,
        )
        metal = int(float(player_view.get("metal") or 0))
        crystal = int(float(player_view.get("crystal") or 0))
        fuel_cells = int(float(player_view.get("fuel_cells") or 0))
        payload: Dict[str, Any] = {
            "ok": True,
            "player": {
                "metal": metal,
                "crystal": crystal,
                "fuel_cells": fuel_cells,
                "energy_used": int(energy_used),
                "energy_total": int(energy_total),
            },
            "resources": {
                "metal": metal,
                "crystal": crystal,
                "fuel_cells": fuel_cells,
                "energy_used": int(energy_used),
                "energy_total": int(energy_total),
            },
            "production_per_hour": prod,
            "storage": storage_caps,
            "energy": {
                "total": int(energy_total),
                "used": int(energy_used),
                "ratio": float(ratio),
            },
        }
        try:
            import time

            from .ranking import get_player_rank, get_player_score_cached

            score = get_player_score_cached(uid, read_only=True) or {}
            rank, total_players = get_player_rank(uid)
            payload["score"] = {
                "total": int(score.get("total") or 0),
                "buildings": int(score.get("buildings") or 0),
                "research": int(score.get("research") or 0),
                "rank": int(rank) if rank else 0,
                "total_players": int(total_players or 0),
            }
            payload["server_time"] = int(time.time())
        except Exception:
            pass
        return payload
    finally:
        conn.close()


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
    data = dict(payload or {})
    apply_start = data.pop("apply_start_to_existing", None)
    apply_start_flag = apply_start in (True, 1, "1", "true", "on")

    cleaned, err = validate_balance_payload(data)
    if err:
        return None, err

    save_game_settings(cleaned)

    if apply_start_flag:
        from .admin import apply_start_resources_to_homeworlds

        settings_now = get_game_settings() or {}
        apply_start_resources_to_homeworlds(
            int(cleaned.get("start_metal", settings_now.get("start_metal", 0)) or 0),
            int(cleaned.get("start_crystal", settings_now.get("start_crystal", 0)) or 0),
        )

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
