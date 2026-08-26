"""Player-facing Planet Evolution impact previews derived from canonical gameplay data.

This module deliberately does not re-implement Planet Evolution math. Mechanics
previews are projected through the same parser used by ``compile_planet_mechanics``
and event previews consume the authoritative event outcome payloads.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from .mechanics import _parse_mechanics_json


_SCOPE_BY_FLAG = {
    "planet_research_speed_bonus": "pe_impact_scope_research",
    "chain_output_bonus": "pe_impact_scope_chains",
    "chain_output_mult": "pe_impact_scope_chains",
    "auto_conversion": "pe_impact_scope_conversion",
    "trade_route_bonus": "pe_impact_scope_trade",
    "discovery_roll_bonus": "pe_impact_scope_discoveries",
    "discovery_roll_mult": "pe_impact_scope_discoveries",
    "experimental_slot": "pe_impact_scope_experimental",
    "export_slots_bonus": "pe_impact_scope_trade",
    "stability_penalty": "pe_impact_scope_culture",
    "auto_research_weekly": "pe_impact_scope_research",
    "experimental_enabled": "pe_impact_scope_experimental",
    "policy_tier": "pe_impact_scope_policies",
}

_LABEL_BY_FLAG = {
    "planet_research_speed_bonus": "pe_impact_effect_research_speed",
    "chain_output_bonus": "pe_impact_effect_chain_output",
    "chain_output_mult": "pe_impact_effect_chain_output",
    "auto_conversion": "pe_impact_effect_auto_conversion",
    "trade_route_bonus": "pe_impact_effect_trade_routes",
    "discovery_roll_bonus": "pe_impact_effect_discovery_chance",
    "discovery_roll_mult": "pe_impact_effect_discovery_chance",
    "experimental_slot": "pe_impact_effect_experimental_slots",
    "export_slots_bonus": "pe_impact_effect_export_slots",
    "stability_penalty": "pe_impact_effect_stability",
    "auto_research_weekly": "pe_impact_effect_auto_research",
    "experimental_enabled": "pe_impact_effect_experimental_access",
    "policy_tier": "pe_impact_effect_policy_tier",
}

_CULTURE_STATS = {
    "stability",
    "loyalty",
    "prosperity",
    "militarization",
    "science_focus",
    "crime",
    "industrial_pressure",
}


def _signed_percent(value: Any) -> str:
    pct = float(value or 0) * 100.0
    if abs(pct - round(pct)) < 1e-9:
        return f"{int(round(pct)):+d}%"
    return f"{pct:+.1f}%"


def _multiplier_delta(value: Any) -> str:
    mult = float(value or 0)
    return _signed_percent(mult - 1.0)


def _signed_number(value: Any) -> str:
    num = float(value or 0)
    if abs(num - round(num)) < 1e-9:
        return f"{int(round(num)):+d}"
    return f"{num:+.1f}"


def _target_label(token: str) -> str:
    raw = str(token or "")
    if raw.startswith("chain:"):
        return f"chain_{raw.split(':', 1)[1]}"
    if raw.startswith("policy:"):
        return f"policy_{raw.split(':', 1)[1]}"
    if raw.startswith("event_pool:"):
        return f"pe_event_pool_{raw.split(':', 1)[1]}"
    if raw.startswith("export:"):
        return f"resource_{raw.split(':', 1)[1]}"
    return ""


def _dedupe_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple] = set()
    for row in rows:
        sig = (
            row.get("kind"),
            row.get("label_key"),
            row.get("value"),
            row.get("target"),
            row.get("scope_key"),
        )
        if sig in seen:
            continue
        seen.add(sig)
        out.append(row)
    return out


def mechanics_impact_rows(raw: Any) -> List[Dict[str, Any]]:
    """Render only mechanics that the live compiler actually recognizes."""
    bundle = _parse_mechanics_json(raw)
    rows: List[Dict[str, Any]] = []

    unlocks = [str(v) for v in (bundle.get("unlocks") or [])]
    required_chain_tokens = {
        token.replace("required_unlock:", "", 1)
        for token in unlocks
        if token.startswith("required_unlock:chain:")
    }
    for token in unlocks:
        if token.startswith("required_unlock:chain:"):
            continue
        rows.append(
            {
                "kind": "unlock",
                "label_key": "pe_impact_effect_unlock",
                "target": token,
                "target_label_key": _target_label(token),
                "scope_key": "pe_impact_scope_chains" if token.startswith("chain:") else "pe_impact_scope_planet",
            }
        )

    for resource_key in bundle.get("export_slots") or []:
        rows.append(
            {
                "kind": "unlock",
                "label_key": "pe_impact_effect_export_unlock",
                "target": f"export:{resource_key}",
                "target_label_key": f"resource_{resource_key}",
                "scope_key": "pe_impact_scope_trade",
            }
        )

    for queue_key, amount in (bundle.get("queue_limits") or {}).items():
        rows.append(
            {
                "kind": "number",
                "label_key": "pe_impact_effect_queue_limit",
                "value": str(int(amount)),
                "target": str(queue_key),
                "scope_key": "pe_impact_scope_queues",
            }
        )

    for flag_key, value in (bundle.get("flags") or {}).items():
        key = str(flag_key)
        if key.startswith("event_pool:"):
            rows.append(
                {
                    "kind": "unlock",
                    "label_key": "pe_impact_effect_event_pool",
                    "target": key,
                    "target_label_key": _target_label(key),
                    "scope_key": "pe_impact_scope_events",
                }
            )
            continue
        if key.startswith("policy_unlock:"):
            policy_key = key.split(":", 1)[1]
            rows.append(
                {
                    "kind": "unlock",
                    "label_key": "pe_impact_effect_policy_unlock",
                    "target": f"policy:{policy_key}",
                    "target_label_key": f"policy_{policy_key}",
                    "scope_key": "pe_impact_scope_policies",
                }
            )
            continue

        label_key = _LABEL_BY_FLAG.get(key, "pe_impact_effect_runtime_flag")
        scope_key = _SCOPE_BY_FLAG.get(key, "pe_impact_scope_planet")
        if key in {"planet_research_speed_bonus", "trade_route_bonus", "discovery_roll_bonus"}:
            value_text = _signed_percent(value)
        elif key == "discovery_roll_mult":
            value_text = _multiplier_delta(value)
        elif key == "chain_output_mult":
            value_text = _multiplier_delta(value)
        elif key == "chain_output_bonus" and isinstance(value, Mapping):
            for chain_key, chain_value in value.items():
                rows.append(
                    {
                        "kind": "value",
                        "label_key": label_key,
                        "value": _signed_percent(chain_value),
                        "target": f"chain:{chain_key}",
                        "target_label_key": f"chain_{chain_key}",
                        "scope_key": scope_key,
                    }
                )
            continue
        elif key == "chain_output_bonus":
            value_text = _signed_percent(value)
        elif key == "stability_penalty":
            value_text = _signed_number(value)
        elif isinstance(value, bool):
            value_text = ""
        elif isinstance(value, (int, float)):
            value_text = _signed_number(value) if key not in {"policy_tier"} else str(int(value))
        else:
            value_text = str(value)
        rows.append(
            {
                "kind": "enabled" if isinstance(value, bool) else "value",
                "label_key": label_key,
                "value": value_text,
                "target": key,
                "scope_key": scope_key,
            }
        )

    for risk_key, value in (bundle.get("risk_modifiers") or {}).items():
        rows.append(
            {
                "kind": "value",
                "label_key": "pe_impact_effect_risk_modifier",
                "value": str(value),
                "target": str(risk_key),
                "scope_key": "pe_impact_scope_risk",
            }
        )

    return _dedupe_rows(rows)


def policy_tradeoff_rows(raw: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(raw, Mapping):
        return rows
    for key, value in raw.items():
        stat = str(key).replace("_drift", "")
        if stat not in _CULTURE_STATS:
            continue
        rows.append(
            {
                "kind": "culture_drift",
                "label_key": f"pe_culture_{stat}",
                "value": _signed_number(value),
                "scope_key": "pe_impact_scope_culture",
            }
        )
    return rows


def event_outcome_impact_rows(outcome: Any, culture: Mapping[str, Any] | None = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(outcome, Mapping):
        return rows
    current_culture = culture or {}
    for stat, delta in (outcome.get("culture_delta") or {}).items():
        if stat not in _CULTURE_STATS:
            continue
        current = float(current_culture.get(stat, 0) or 0)
        after = max(0.0, min(100.0, current + float(delta)))
        rows.append(
            {
                "kind": "culture_change",
                "label_key": f"pe_culture_{stat}",
                "value": _signed_number(delta),
                "current": int(round(current)),
                "after": int(round(after)),
                "scope_key": "pe_impact_scope_culture",
            }
        )
    for resource_key, amount in (outcome.get("grant_special_resource") or {}).items():
        rows.append(
            {
                "kind": "resource",
                "label_key": "pe_impact_effect_resource_gain",
                "target": str(resource_key),
                "target_label_key": f"resource_{resource_key}",
                "value": f"+{int(amount)}",
                "scope_key": "pe_impact_scope_resources",
            }
        )
    if outcome.get("add_failure"):
        failure_key = str(outcome["add_failure"])
        rows.append(
            {
                "kind": "failure",
                "label_key": "pe_impact_effect_failure",
                "target": failure_key,
                "target_label_key": f"pe_failure_{failure_key}",
                "scope_key": "pe_impact_scope_risk",
            }
        )
    return rows


def impact_scopes(rows: Iterable[Mapping[str, Any]]) -> List[str]:
    out: List[str] = []
    for row in rows:
        key = str(row.get("scope_key") or "pe_impact_scope_planet")
        if key not in out:
            out.append(key)
    return out
