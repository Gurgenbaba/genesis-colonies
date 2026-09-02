#!/usr/bin/env python3
"""One-shot deterministic codemod for GC-PERF-WB-AUTO-LEAN-001.

The World Boss module is deliberately large. This script changes only three
functions and fails hard if their exact expected source no longer matches.
It is removed from the feature branch after generating the real source diff.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "game" / "world_boss.py"


def _function_span(source: str, name: str) -> tuple[int, int]:
    marker = f"def {name}("
    start = source.find(marker)
    if start < 0:
        raise SystemExit(f"missing function: {name}")
    next_def = source.find("\ndef ", start + len(marker))
    end = len(source) if next_def < 0 else next_def + 1
    return start, end


def _replace_once_in_function(source: str, name: str, old: str, new: str) -> str:
    start, end = _function_span(source, name)
    block = source[start:end]
    count = block.count(old)
    if count != 1:
        raise SystemExit(f"{name}: expected exactly one match, found {count}: {old!r}")
    block = block.replace(old, new, 1)
    return source[:start] + block + source[end:]


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")

    source = _replace_once_in_function(
        source,
        "execute_instant_attack",
        "    auto_select: bool = False,\n    hit_mult: int = 1,\n) -> Dict[str, Any]:",
        "    auto_select: bool = False,\n    hit_mult: int = 1,\n    lean_response: bool = False,\n) -> Dict[str, Any]:",
    )

    source = _replace_once_in_function(
        source,
        "execute_instant_attack",
        "    the caller. ``hit_mult`` ∈ {1, 5}; ×5 remains five waves / five cooldowns.\n",
        "    the caller. ``hit_mult`` ∈ {1, 5}; ×5 remains five waves / five cooldowns.\n"
        "    ``lean_response`` keeps all gameplay writes but skips UI-only ranking,\n"
        "    recognition and second hangar reads for background worker strikes.\n",
    )

    source = _replace_once_in_function(
        source,
        "execute_instant_attack",
        """    updated = get_event_by_id(eid, conn=conn)\n    if defeated and updated:\n        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)\n        try:\n            _announce_defeat(updated, conn=conn)\n        except Exception:\n            logger.exception(\"world_boss defeat news failed event=%s\", eid)\n\n    cooldown_until = float(ts + WAVE_COOLDOWN_SEC * int(mult))\n""",
        """    # Background auto-fire only needs success/damage/defeat. Do not build\n    # ranking/recognition/hangar response payloads that the maintenance worker\n    # immediately discards. Defeat handling still needs the refreshed event.\n    updated = get_event_by_id(eid, conn=conn) if defeated else None\n    if defeated and updated:\n        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)\n        try:\n            _announce_defeat(updated, conn=conn)\n        except Exception:\n            logger.exception(\"world_boss defeat news failed event=%s\", eid)\n\n    if lean_response:\n        return {\n            \"ok\": True,\n            \"error\": \"\",\n            \"event_id\": int(eid),\n            \"damage\": int(applied),\n            \"defeated\": bool(defeated),\n        }\n\n    if updated is None:\n        updated = get_event_by_id(eid, conn=conn)\n\n    cooldown_until = float(ts + WAVE_COOLDOWN_SEC * int(mult))\n""",
    )

    source = _replace_once_in_function(
        source,
        "maybe_fire_ready_auto_attack",
        "    planet_id: Optional[int] = None,\n) -> Dict[str, Any]:",
        "    planet_id: Optional[int] = None,\n    lean_response: bool = False,\n) -> Dict[str, Any]:",
    )

    source = _replace_once_in_function(
        source,
        "maybe_fire_ready_auto_attack",
        """        now=ts,\n        auto_select=False,\n    )\n""",
        """        now=ts,\n        auto_select=False,\n        lean_response=bool(lean_response),\n    )\n""",
    )

    source = _replace_once_in_function(
        source,
        "tick_world_boss_auto_attacks",
        """            conn=conn,\n            now=ts,\n        )\n""",
        """            conn=conn,\n            now=ts,\n            lean_response=True,\n        )\n""",
    )

    TARGET.write_text(source, encoding="utf-8")
    print("GC-PERF-WB-AUTO-LEAN-001 applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
