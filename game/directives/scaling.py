"""Imperium score scaling for directive targets (GC-911A / GC-915)."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from ..exact_math import scale_ratio_power_int

# Midgame anchor — at this total_score, count tiers sit in the middle band.
SCORE_ANCHOR = 20_000
SCORE_FLOOR = 100

SCALE_PROFILES: Dict[str, Dict[str, float]] = {
    "produce": {
        "exponent": 0.0,
        "weekly_multiplier": 5.0,
        "min_target": 500,
        "max_target": 0,
    },
    "count_light": {"exponent": 0.25, "weekly_multiplier": 3.5, "min_target": 1, "max_target": 10},
    "count_medium": {"exponent": 0.30, "weekly_multiplier": 4.0, "min_target": 1, "max_target": 50},
    "count_heavy": {"exponent": 0.35, "weekly_multiplier": 4.5, "min_target": 1, "max_target": 30},
    "ships": {"exponent": 0.28, "weekly_multiplier": 3.5, "min_target": 2, "max_target": 150},
}

DEFAULT_PROFILE = "count_light"


def scale_profile_config(profile: str) -> Dict[str, float]:
    key = str(profile or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
    cfg = SCALE_PROFILES.get(key)
    if cfg is None:
        return dict(SCALE_PROFILES[DEFAULT_PROFILE])
    return dict(cfg)


def _resolve_total_score(total_score: int | float | Mapping[str, Any] | None) -> int:
    if isinstance(total_score, Mapping):
        raw = total_score.get("total")
        if raw is None:
            raw = total_score.get("total_score")
        return max(SCORE_FLOOR, int(raw or 0))
    return max(SCORE_FLOOR, int(total_score or 0))


def compute_scaled_target(
    base_target: int,
    total_score: int | float | Mapping[str, Any] | None,
    *,
    scale_profile: str,
    cadence: str = "daily",
) -> int:
    """
    Legacy score-only scaling (tests + fallback).

    Prefer compute_directive_target() for player-facing generation.
    """
    base = max(1, int(base_target or 1))
    score = _resolve_total_score(total_score)
    cfg = scale_profile_config(scale_profile)
    exponent = cfg.get("exponent")
    if exponent is None:
        exponent = 0.25
    weekly = str(cadence or "daily").strip().lower() == "weekly"
    weekly_mult = (cfg.get("weekly_multiplier") or 1.0) if weekly else 1.0
    max_target = int(cfg.get("max_target") or 0)
    result = scale_ratio_power_int(
        base,
        max(SCORE_FLOOR, score),
        SCORE_ANCHOR,
        exponent,
        weekly_mult,
        cap=max_target if max_target > 0 else None,
    )
    min_target = int(cfg.get("min_target") or 1)
    result = max(min_target, result)

    return result


def produce_metal_anchor_samples() -> Dict[int, int]:
    """Reference produce targets at score anchors (production-aware via balancing)."""
    from .balancing import compute_directive_target

    scores = (2_000, 20_000, 500_000, 50_000_000)
    out: Dict[int, int] = {}
    for score in scores:
        daily_metal = max(12_000, score * 10)
        out[score] = compute_directive_target(
            {
                "key": "produce_metal",
                "objective_kind": "accumulate",
                "scale_profile": "produce",
                "base_target": 5000,
                "filters": {"resource": "metal"},
            },
            rarity="common",
            cadence="daily",
            context={"total_score": score, "daily_production": {"metal": daily_metal}},
        )
    return out
