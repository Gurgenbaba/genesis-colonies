from __future__ import annotations

from pathlib import Path
import re


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    out, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, got {n}")
    return out


def patch_auto_empire() -> None:
    path = Path("game/auto_empire.py")
    text = path.read_text(encoding="utf-8")

    text = sub_once(
        text,
        r"(def try_enqueue_building\(.*?\n\s+duration_cap: Optional\[int\] = None,\n)(\) -> Dict\[str, Any\]:)",
        r"\1    target_scale: float = 1.0,\n\2",
        "building signature",
        re.S,
    )
    text = sub_once(
        text,
        r"    target_cap = int\(BUILD_TARGETS\.get\(building_type, 8\)\) \+ _stable_jitter\(\n\s+player_id, building_type, BUILD_TARGET_JITTER\n\s+\)\n    target_cap = max\(1, target_cap\)",
        "    scale = max(0.65, min(1.60, float(target_scale or 1.0)))\n"
        "    base_target = int(BUILD_TARGETS.get(building_type, 8))\n"
        "    target_cap = int(round(float(base_target) * scale)) + _stable_jitter(\n"
        "        player_id, building_type, BUILD_TARGET_JITTER\n"
        "    )\n"
        "    target_cap = max(1, target_cap)",
        "building target scale",
    )

    text = sub_once(
        text,
        r"(def try_enqueue_research\(.*?\n\s+duration_cap: Optional\[int\] = None,\n)(\) -> Dict\[str, Any\]:)",
        r"\1    target_scale: float = 1.0,\n\2",
        "research signature",
        re.S,
    )
    text = sub_once(
        text,
        r"    target_cap = int\(RESEARCH_TARGETS\.get\(tech_key, 5\)\) \+ _stable_jitter\(\n\s+player_id, tech_key, RESEARCH_TARGET_JITTER\n\s+\)\n    target_cap = max\(1, target_cap\)",
        "    scale = max(0.65, min(1.60, float(target_scale or 1.0)))\n"
        "    base_target = int(RESEARCH_TARGETS.get(tech_key, 5))\n"
        "    target_cap = int(round(float(base_target) * scale)) + _stable_jitter(\n"
        "        player_id, tech_key, RESEARCH_TARGET_JITTER\n"
        "    )\n"
        "    target_cap = max(1, target_cap)",
        "research target scale",
    )

    text = sub_once(
        text,
        r"(def try_build_defense\(.*?\n\s+personality: str,\n)(\) -> Dict\[str, Any\]:)",
        r"\1    target_scale: float = 1.0,\n\2",
        "defense signature",
        re.S,
    )
    text = sub_once(
        text,
        r"    for defense_key, want in targets:\n        have = int\(current\.get\(defense_key\) or 0\)\n        if have >= int\(want\):\n            continue\n        amount = min\(10, max\(1, int\(want\) - have\)\)",
        "    scale = max(0.65, min(1.60, float(target_scale or 1.0)))\n"
        "    for defense_key, want in targets:\n"
        "        wanted = max(1, int(round(float(want) * scale)))\n"
        "        have = int(current.get(defense_key) or 0)\n"
        "        if have >= wanted:\n"
        "            continue\n"
        "        amount = min(10, max(1, wanted - have))",
        "defense target scale",
    )

    text = sub_once(
        text,
        r"(def plan_passive_planet_tick\(.*?\n\s+research_duration_cap: Optional\[int\] = None,\n)(\s+source: str = \"auto_empire\",)",
        r"\1    target_scale: float = 1.0,\n\2",
        "planner target scale signature",
        re.S,
    )
    text = sub_once(
        text,
        r"(res = try_enqueue_building\(.*?duration_cap=build_duration_cap,\n)(\s+\))",
        r"\1                        target_scale=target_scale,\n\2",
        "building planner call",
        re.S,
    )
    text = sub_once(
        text,
        r"(res = try_enqueue_research\(.*?duration_cap=research_duration_cap,\n)(\s+\))",
        r"\1                        target_scale=target_scale,\n\2",
        "research planner call",
        re.S,
    )
    text = sub_once(
        text,
        r"(def_res = try_build_defense\(.*?personality=str\(personality\),\n)(\s+\))",
        r"\1            target_scale=target_scale,\n\2",
        "defense planner call",
        re.S,
    )

    path.write_text(text, encoding="utf-8")


def patch_inactive_autoplay() -> None:
    path = Path("game/inactive_autoplay.py")
    text = path.read_text(encoding="utf-8")

    text = sub_once(
        text,
        r"(INACTIVE_ACTION_PACE_RANGES_SEC = \{.*?\n\}\n)(INACTIVE_WORLD_BOSS_SAFE_HP_RATIO = 0\.05)",
        r'''\1# Permanent empire ambition: equal personalities still develop different ceilings.
INACTIVE_AMBITION_BASE = {
    "economy": 1.16,
    "aggressive": 1.02,
    "turtle": 1.08,
    "spy": 0.96,
    "swarm": 1.04,
    "elite": 1.12,
}
# Longer strategic phases shift priorities without extra polling or workers.
INACTIVE_STRATEGIC_PHASES = ("growth", "research", "fortification", "balanced")
INACTIVE_PHASE_DOMAIN_MULT = {
    "growth": {"building": 1.75, "research": 0.70, "defense": 0.55},
    "research": {"building": 0.70, "research": 1.85, "defense": 0.55},
    "fortification": {"building": 0.70, "research": 0.65, "defense": 1.90},
    "balanced": {"building": 1.00, "research": 1.00, "defense": 1.00},
}
\2''',
        "strategic constants",
        re.S,
    )

    text = sub_once(
        text,
        r"def _action_domain_for_player\(player_id: int, personality: str, action_seq: int\) -> str:\n.*?\n\ndef _next_action_delay_sec",
        '''def _ambition_scale(player_id: int, personality: str) -> float:
    base = float(INACTIVE_AMBITION_BASE.get(str(personality), 1.0))
    personal_pct = 84 + _stable_roll(player_id, "ambition", 0, 43)  # 0.84..1.26
    return round(max(0.72, min(1.55, base * (float(personal_pct) / 100.0))), 3)


def _strategic_phase_for_player(player_id: int, action_seq: int) -> str:
    span = 36 + _stable_roll(player_id, "phase-span", 0, 37)  # 36..72 decisions
    offset = _stable_roll(player_id, "phase-offset", 0, len(INACTIVE_STRATEGIC_PHASES))
    idx = ((max(0, int(action_seq)) // max(1, int(span))) + int(offset)) % len(
        INACTIVE_STRATEGIC_PHASES
    )
    return INACTIVE_STRATEGIC_PHASES[idx]


def _action_domain_for_player(player_id: int, personality: str, action_seq: int) -> str:
    base_weights = INACTIVE_ACTION_WEIGHTS.get(str(personality)) or INACTIVE_ACTION_WEIGHTS["economy"]
    phase = _strategic_phase_for_player(player_id, action_seq)
    phase_mult = INACTIVE_PHASE_DOMAIN_MULT.get(phase) or INACTIVE_PHASE_DOMAIN_MULT["balanced"]
    weights = {
        key: max(0, int(round(float(base_weights.get(key) or 0) * float(phase_mult.get(key) or 1.0))))
        for key in INACTIVE_ACTION_DOMAINS
    }
    total = sum(max(0, int(weights.get(key) or 0)) for key in INACTIVE_ACTION_DOMAINS)
    if total <= 0:
        return "building"
    roll = _stable_roll(player_id, f"domain:{phase}", action_seq, total)
    cursor = 0
    for domain in INACTIVE_ACTION_DOMAINS:
        cursor += max(0, int(weights.get(domain) or 0))
        if roll < cursor:
            return domain
    return "building"


def _next_action_delay_sec''',
        "strategic selector",
        re.S,
    )

    text = sub_once(
        text,
        r"(    personality = personality_for_player\(player_id\)\n    seq = max\(0, int\(action_seq or 0\)\)\n)",
        r"\1    strategic_phase = _strategic_phase_for_player(player_id, seq)\n    ambition_scale = _ambition_scale(player_id, personality)\n",
        "strategy metadata",
    )
    text = sub_once(
        text,
        r"(                    research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,\n)(                    source=\"inactive_autoplay\",)",
        r"\1                    target_scale=ambition_scale,\n\2",
        "inactive planner scale",
    )
    text = sub_once(
        text,
        r"(        \"personal_cooldown\": personal_cooldown,\n)(        \"boss_participation\": boss_participation,)",
        r"\1        \"strategic_phase\": strategic_phase,\n        \"ambition_scale\": ambition_scale,\n\2",
        "strategy result",
    )

    path.write_text(text, encoding="utf-8")


def write_tests() -> None:
    Path("tests/test_living_universe_gc2622.py").write_text(
        '''from __future__ import annotations

from unittest.mock import patch


def test_gc2622_ambition_is_stable_but_not_cloned():
    from game.auto_empire import personality_for_player
    from game.inactive_autoplay import _ambition_scale

    values = []
    for player_id in range(1, 80):
        personality = personality_for_player(player_id)
        value = _ambition_scale(player_id, personality)
        assert value == _ambition_scale(player_id, personality)
        assert 0.72 <= value <= 1.55
        values.append(value)
    assert len(set(values)) >= 15


def test_gc2622_strategic_phases_are_stable_and_rotate():
    from game.inactive_autoplay import INACTIVE_STRATEGIC_PHASES, _strategic_phase_for_player

    seen = set()
    for player_id in range(1, 30):
        p0 = _strategic_phase_for_player(player_id, 0)
        assert p0 == _strategic_phase_for_player(player_id, 0)
        assert p0 in INACTIVE_STRATEGIC_PHASES
        seen.add(p0)
        for seq in (36, 72, 108, 144, 216, 288):
            seen.add(_strategic_phase_for_player(player_id, seq))
    assert seen == set(INACTIVE_STRATEGIC_PHASES)


def test_gc2622_planner_threads_target_scale_without_parallel_systems():
    from game.auto_empire import plan_passive_planet_tick

    build_result = {"ok": True, "job_id": 7, "building_type": "metal_mine", "target_level": 2, "duration": 60}
    with patch("game.auto_empire._finish_due", return_value={}), patch(
        "game.auto_empire.try_enqueue_building", return_value=build_result
    ) as enqueue:
        out = plan_passive_planet_tick(
            object(),
            player_id=17,
            planet={"id": 91},
            now=12345.0,
            allow_buildings=True,
            allow_research=False,
            allow_ships=False,
            allow_defense=False,
            target_scale=1.37,
        )
    assert out["build"]["job_id"] == 7
    assert enqueue.call_args.kwargs["target_scale"] == 1.37


def test_gc2622_inactive_decision_passes_personal_ambition():
    from game.auto_empire import personality_for_player
    from game.inactive_autoplay import _ambition_scale, _run_player_economy

    player_id = 23
    expected = _ambition_scale(player_id, personality_for_player(player_id))
    home = {"id": 101, "is_homeworld": 1}
    with patch("game.models.get_homeworld", return_value=home), patch(
        "game.models.get_planets_by_player", return_value=[home]
    ), patch("game.inactive_autoplay._ensure_resource_floor", return_value={}), patch(
        "game.inactive_autoplay.plan_passive_planet_tick"
    ) as planner, patch(
        "game.inactive_autoplay._maybe_join_world_boss", return_value={"ok": True, "joined": False}
    ):
        planner.return_value = {
            "build": None,
            "research": None,
            "defense": None,
            "builds": [],
            "researches": [],
            "finished": {},
        }
        result = _run_player_economy(object(), player_id, now=50000.0, action_seq=4)

    assert planner.call_args.kwargs["target_scale"] == expected
    assert result["ambition_scale"] == expected
    assert result["strategic_phase"]
''',
        encoding="utf-8",
    )


def patch_docs() -> None:
    path = Path("docs/INACTIVE_AUTOPLAY.md")
    text = path.read_text(encoding="utf-8")
    marker = "## Living Universe V4 — strategic diversity"
    if marker not in text:
        text += (
            "\n\n## Living Universe V4 — strategic diversity\n\n"
            "Dormant commanders no longer converge on nearly identical long-term ceilings. "
            "Each account receives a deterministic empire ambition factor, while longer strategic "
            "phases temporarily favor growth, research, fortification, or a balanced posture. "
            "The existing one-action decision contract and SQLite writer budget remain unchanged.\n\n"
            "Player-facing messages describe colony operations and commander activity only. "
            "Internal implementation terminology must not be surfaced in public reports, community "
            "announcements, or Discord-facing text.\n"
        )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_auto_empire()
    patch_inactive_autoplay()
    patch_docs()
    write_tests()


if __name__ == "__main__":
    main()
