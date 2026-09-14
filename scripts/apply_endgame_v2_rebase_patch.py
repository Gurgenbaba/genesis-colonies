#!/usr/bin/env python3
"""One-shot source patcher used by the feature-branch CI bootstrap.

The file is removed before merge; it exists only because the GitHub connector can
create new files more safely than replacing several very large source files.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    # Production: final candidate pivot is L120, while mode remains fail-closed legacy.
    replace_once(
        "game/production_formula.py",
        '''ENDGAME_PRODUCTION_PIVOT_LEVEL = _env_int(\n    "GC_ENDGAME_PRODUCTION_PIVOT",\n    650,\n    minimum=120,\n    maximum=100_000,\n)''',
        '''ENDGAME_PRODUCTION_PIVOT_LEVEL = _env_int(\n    "GC_ENDGAME_PRODUCTION_PIVOT",\n    120,\n    minimum=120,\n    maximum=100_000,\n)''',
    )
    replace_once(
        "game/production_formula.py",
        '''def endgame_economy_mode() -> str:\n    """Return the process-local rollout mode: legacy, shadow, or active."""\n    return _normalize_endgame_mode(ENDGAME_ECONOMY_MODE)\n''',
        '''def endgame_economy_mode() -> str:\n    """Return the process-local rollout mode: legacy, shadow, or active."""\n    return _normalize_endgame_mode(ENDGAME_ECONOMY_MODE)\n\n\nENDGAME_RESEARCH_PIVOT_LEVEL = 120\nENDGAME_RESEARCH_TAIL_SCALE = 120\n\n\ndef research_effective_level(level: int, *, force_v2: Optional[bool] = None) -> float:\n    """Effective production-research level with a C1 diminishing tail after L120.\n\n    Legacy and shadow modes intentionally preserve the historical linear effect.\n    Active mode keeps levels <=120 byte-for-byte equivalent, then continues as\n    ``120 + 120*ln(1 + (L-120)/120)``: monotone, unbounded, but diminishing.\n    """\n    lvl = max(0, int(level or 0))\n    use_v2 = endgame_economy_mode() == "active" if force_v2 is None else bool(force_v2)\n    if not use_v2 or lvl <= ENDGAME_RESEARCH_PIVOT_LEVEL:\n        return float(lvl)\n    pivot = Decimal(ENDGAME_RESEARCH_PIVOT_LEVEL)\n    with localcontext() as ctx:\n        ctx.prec = max(96, len(str(lvl)) + 64)\n        ratio = Decimal(lvl - ENDGAME_RESEARCH_PIVOT_LEVEL) / pivot\n        effective = pivot + Decimal(ENDGAME_RESEARCH_TAIL_SCALE) * (Decimal(1) + ratio).ln()\n        return float(effective)\n''',
    )
    replace_once(
        "game/production_formula.py",
        '''def research_modifier_for(resource_type: str, research: Optional[Mapping[str, Any]]) -> float:\n    key = _normalize_resource_type(resource_type)\n    mining = _lvl(research, "mining_tech")\n    crystal = _lvl(research, "crystal_tech")\n    drone = _lvl(research, "drone_tech")\n    if key == "metal":\n        return (1.0 + MINING_TECH_PER_LEVEL * mining) * (1.0 + DRONE_TECH_PER_LEVEL * drone)\n    if key == "crystal":\n        return (1.0 + CRYSTAL_TECH_PER_LEVEL * crystal) * (1.0 + DRONE_TECH_PER_LEVEL * drone)\n    return 1.0\n''',
        '''def research_modifier_for(resource_type: str, research: Optional[Mapping[str, Any]]) -> float:\n    key = _normalize_resource_type(resource_type)\n    mining = research_effective_level(_lvl(research, "mining_tech"))\n    crystal = research_effective_level(_lvl(research, "crystal_tech"))\n    drone = research_effective_level(_lvl(research, "drone_tech"))\n    if key == "metal":\n        return (1.0 + MINING_TECH_PER_LEVEL * mining) * (1.0 + DRONE_TECH_PER_LEVEL * drone)\n    if key == "crystal":\n        return (1.0 + CRYSTAL_TECH_PER_LEVEL * crystal) * (1.0 + DRONE_TECH_PER_LEVEL * drone)\n    return 1.0\n''',
    )

    # Gameplay price anchor: only active mode gets the rising V2 horizon.
    replace_once(
        "game/economy_balance.py",
        '''def mine_roi_anchor_hours(level: int) -> float:\n    """Log-interpolated ROI target between GC-821F anchor levels."""\n    return _log_interpolate_anchor_map(level, MINE_UPGRADE_ROI_TARGET_HOURS)\n''',
        '''def mine_roi_anchor_hours(level: int) -> float:\n    """Mine ROI target; V2 rises smoothly after the historical L120 anchor."""\n    lvl = max(1, int(level))\n    from .production_formula import ENDGAME_PRODUCTION_PIVOT_LEVEL, endgame_economy_mode\n\n    pivot = max(120, int(ENDGAME_PRODUCTION_PIVOT_LEVEL))\n    if endgame_economy_mode() == "active" and lvl > pivot:\n        pivot_hours = _log_interpolate_anchor_map(pivot, MINE_UPGRADE_ROI_TARGET_HOURS)\n        return float(pivot_hours) * ((float(lvl) / float(pivot)) ** 0.70)\n    return _log_interpolate_anchor_map(lvl, MINE_UPGRADE_ROI_TARGET_HOURS)\n''',
    )

    # Score V2 is atomic with the same rollout mode. Shadow/legacy stay untouched.
    replace_once(
        "game/ranking_core.py",
        '''    total = _safe_int(resources + building + research + fleet + defense + evolution)''',
        '''    from .production_formula import endgame_economy_mode\n\n    if endgame_economy_mode() == "active":\n        total = _safe_int(building + research + fleet + defense + evolution)\n    else:\n        total = _safe_int(resources + building + research + fleet + defense + evolution)''',
    )
    replace_once(
        "game/ranking_core.py",
        '''    from .economy_balance import cumulative_upgrade_resource_totals\n    from .models import get_planet_buildings, get_planets_by_player\n    from .resource_score import score_from_cost_dict\n''',
        '''    from .economy_balance import cumulative_upgrade_resource_totals\n    from .models import get_planet_buildings, get_planets_by_player\n    from .production_formula import endgame_economy_mode\n    from .progression_valuation import building_progression_resources_v2\n    from .resource_score import score_from_cost_dict\n''',
    )
    replace_once(
        "game/ranking_core.py",
        '''            totals = cumulative_upgrade_resource_totals(key, level)\n            total_metal += int(totals.get("metal") or 0)\n            total_crystal += int(totals.get("crystal") or 0)\n            total_fuel += int(totals.get("fuel_cells") or 0)''',
        '''            if endgame_economy_mode() == "active":\n                m, c, f = building_progression_resources_v2(str(key), level)\n                total_metal += int(m)\n                total_crystal += int(c)\n                total_fuel += int(f)\n            else:\n                totals = cumulative_upgrade_resource_totals(key, level)\n                total_metal += int(totals.get("metal") or 0)\n                total_crystal += int(totals.get("crystal") or 0)\n                total_fuel += int(totals.get("fuel_cells") or 0)''',
    )
    replace_once(
        "game/ranking_core.py",
        '''    from .models import get_research_levels\n    from .research import RESEARCH_TECHS, cumulative_research_resource_totals\n    from .resource_score import score_from_cost_dict\n''',
        '''    from .models import get_research_levels\n    from .production_formula import endgame_economy_mode\n    from .progression_valuation import research_progression_resources_v2\n    from .research import RESEARCH_TECHS, cumulative_research_resource_totals\n    from .resource_score import score_from_cost_dict\n''',
    )
    replace_once(
        "game/ranking_core.py",
        '''        totals = cumulative_research_resource_totals(tech_key, level)\n        total_metal += int(totals.get("metal") or 0)\n        total_crystal += int(totals.get("crystal") or 0)\n        total_fuel += int(totals.get("fuel_cells") or 0)''',
        '''        if endgame_economy_mode() == "active":\n            m, c, f = research_progression_resources_v2(str(tech_key), level)\n            total_metal += int(m)\n            total_crystal += int(c)\n            total_fuel += int(f)\n        else:\n            totals = cumulative_research_resource_totals(tech_key, level)\n            total_metal += int(totals.get("metal") or 0)\n            total_crystal += int(totals.get("crystal") or 0)\n            total_fuel += int(totals.get("fuel_cells") or 0)''',
    )
    replace_once(
        "game/ranking_core.py",
        '''def _total_score_sql(conn) -> str:\n    parts = []\n    if column_exists(conn, "player_scores", "score_resources"):\n        parts.append("COALESCE(ps.score_resources, '0')")''',
        '''def _total_score_sql(conn) -> str:\n    from .production_formula import endgame_economy_mode\n\n    parts = []\n    if endgame_economy_mode() != "active" and column_exists(conn, "player_scores", "score_resources"):\n        parts.append("COALESCE(ps.score_resources, '0')")''',
    )

    # Keep server-side effect previews aligned with active research diminishing returns.
    replace_once(
        "game/effects/effect_resolver.py",
        '''    def metal_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import MINING_TECH_PER_LEVEL\n\n        return int(round(MINING_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))''',
        '''    def metal_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import MINING_TECH_PER_LEVEL, research_effective_level\n\n        return int(round(MINING_TECH_PER_LEVEL * research_effective_level(level) * 100))''',
    )
    replace_once(
        "game/effects/effect_resolver.py",
        '''    def crystal_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import CRYSTAL_TECH_PER_LEVEL\n\n        return int(round(CRYSTAL_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))''',
        '''    def crystal_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import CRYSTAL_TECH_PER_LEVEL, research_effective_level\n\n        return int(round(CRYSTAL_TECH_PER_LEVEL * research_effective_level(level) * 100))''',
    )
    replace_once(
        "game/effects/effect_resolver.py",
        '''    def drone_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import DRONE_TECH_PER_LEVEL\n\n        return int(round(DRONE_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))''',
        '''    def drone_prod_bonus_pct(level: int) -> int:\n        from ..production_formula import DRONE_TECH_PER_LEVEL, research_effective_level\n\n        return int(round(DRONE_TECH_PER_LEVEL * research_effective_level(level) * 100))''',
    )

    # Release marker.
    version = ROOT / "VERSION"
    if version.read_text(encoding="utf-8").strip() == "0.5.9.170":
        version.write_text("0.5.9.171", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
