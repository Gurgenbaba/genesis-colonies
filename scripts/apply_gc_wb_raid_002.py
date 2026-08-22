#!/usr/bin/env python3
"""Canonical GC-WB-RAID-002 codemod entrypoint.

The implementation transform and its downstream World Boss regression contract
are applied together. Required legacy anchors fail loudly, and ``--verify``
proves that a second application produces no additional working-tree diff.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import _apply_gc_wb_raid_002_impl as impl

ROOT = Path(__file__).resolve().parents[1]
LEGACY_TEST = ROOT / "tests" / "test_world_boss.py"
LEGACY_ARRIVAL_MARKER = "# GC-WB-RAID-002 — legacy arrival raid parity"

_TEST_REPLACEMENTS = (
    (
        "    assert damage == 100_000\n",
        "    assert damage == int(max_hp * WAVE_HP_FRACTION)\n",
        "full-wipe damage assertion",
    ),
    (
        "    assert 40_000 <= half <= 60_000\n",
        "    assert 0 < half < damage\n"
        "    assert abs(half - (damage // 2)) <= max(2_000, int(damage * 0.15))\n",
        "half-loss damage assertion",
    ),
    (
        "    # Solo mega: at least 10 waves, at most ~20 waves to clear the bar.\n"
        "    assert mega_damage * 10 <= max_hp\n"
        "    assert mega_damage * 20 >= max_hp\n",
        "    # GC-WB-RAID-002: a capped mega fleet now needs roughly 34 single waves.\n"
        "    assert mega_damage * 30 < max_hp\n"
        "    assert mega_damage * 40 >= max_hp\n",
        "mega-fleet pacing assertion",
    ),
    (
        "        wave_cap = max(1, int(float(x5[\"boss\"][\"max_hp\"]) * 0.08))\n",
        "        wave_cap = max(1, int(float(x5[\"boss\"][\"max_hp\"]) * 0.03))\n",
        "single-wave cap assertion",
    ),
    (
        '    \"\"\"Even fight full wipe ≈ WAVE_HP_FRACTION; mega fleet hits soft overkill cap (~10–20 waves).\"\"\"\n',
        '    \"\"\"Even fight follows WAVE_HP_FRACTION; mega fleets obey the hardened single-wave cap.\"\"\"\n',
        "full-wipe regression docstring",
    ),
    (
        '    \"\"\"Hangar past the 8% wave HP cap → send only what is needed for the cap.\"\"\"\n',
        '    \"\"\"Hangar past the current wave HP cap → send only what is needed for the cap.\"\"\"\n',
        "auto-selection regression docstring",
    ),
    (
        "        assert after == before + expected\n        assert after > before\n",
        "        assert after == before + expected\n"
        "        assert (after > before) == (expected > 0)\n",
        "alliance XP threshold assertion",
    ),
    (
        '            "UPDATE world_boss_events SET max_hp = 100, current_hp = 2 WHERE id = ?;",\n',
        '            "UPDATE world_boss_events SET max_hp = 1000000, current_hp = 2 WHERE id = ?;",\n',
        "HP-floor regression fixture",
    ),
)


def _replace_required(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"GC-WB-RAID-002 legacy test anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_legacy_arrival_raid_contract() -> None:
    """Route pre-deployment in-flight arrivals through the canonical raid rules."""
    text = impl.WB.read_text(encoding="utf-8")
    start = text.index("def resolve_attack_arrival(\n")
    end = text.index("\ndef _player_name(\n", start)
    block = text[start:end]
    if LEGACY_ARRIVAL_MARKER in block:
        return

    old_damage = '''    damage = compute_world_boss_hp_damage(
        defender_ships_before=defender_ships,
        defender_losses=combat_result.defender_losses or {},
        max_hp=int(event["max_hp"]),
        attacker_ships_before=ships,
    )

    remaining_def = remaining_stock(defender_ships, combat_result.defender_losses or {})
    new_hp = max(0, int(event["current_hp"]) - damage)
    defeated = new_hp <= 0
'''
    new_damage = '''    damage = compute_world_boss_hp_damage(
        defender_ships_before=defender_ships,
        defender_losses=combat_result.defender_losses or {},
        max_hp=int(event["max_hp"]),
        attacker_ships_before=ships,
    )

    # GC-WB-RAID-002 — legacy arrival raid parity
    # Flights dispatched before the instant-raid deployment may still arrive later.
    # They must obey the same x1 cap, Containment, Resonance and Last Stand rules.
    damage, raid_damage_meta, raid_before = _apply_raid_damage_rules(
        damage,
        hit_mult=1,
        event=event,
        player_id=int(player_id),
        conn=conn,
        now=ts,
    )
    target_lock_before = int((raid_before.get("target_lock") or {}).get("charge") or 0)

    remaining_def = remaining_stock(defender_ships, combat_result.defender_losses or {})
    before_hp = max(0, int(event["current_hp"]))
    new_hp = max(0, before_hp - int(damage))
    damage = max(0, before_hp - new_hp)
    raid_damage_meta["applied_damage"] = int(damage)
    defeated = new_hp <= 0
'''
    block = _replace_required(block, old_damage, new_damage, "legacy arrival damage parity")

    old_contribution = '''    _upsert_contribution(
        event_id=int(event["id"]),
        player_id=int(player_id),
        alliance_id=alliance_id,
        damage=damage,
        alliance_xp=wave_xp,
        now=ts,
        conn=conn,
    )

    if alliance_id is not None and wave_xp > 0:
'''
    new_contribution = '''    _upsert_contribution(
        event_id=int(event["id"]),
        player_id=int(player_id),
        alliance_id=alliance_id,
        damage=damage,
        alliance_xp=wave_xp,
        now=ts,
        conn=conn,
    )

    raid_after = _advance_world_boss_raid_after_hit(
        event=event,
        player_id=int(player_id),
        hit_mult=1,
        target_lock_before=target_lock_before,
        target_lock_consumed=False,
        defeated=defeated,
        conn=conn,
        now=ts,
        state_before=raid_before,
    )

    if alliance_id is not None and wave_xp > 0:
'''
    block = _replace_required(
        block,
        old_contribution,
        new_contribution,
        "legacy arrival raid state advancement",
    )

    old_return = '''        "defender_ships_before": defender_ships,
        "alliance_id": int(alliance_id) if alliance_id is not None else None,
        "alliance_xp_granted": int(alliance_xp_granted),
'''
    new_return = '''        "defender_ships_before": defender_ships,
        "raid": raid_after,
        "raid_modifiers": raid_damage_meta,
        "alliance_id": int(alliance_id) if alliance_id is not None else None,
        "alliance_xp_granted": int(alliance_xp_granted),
'''
    block = _replace_required(block, old_return, new_return, "legacy arrival raid response")

    impl.WB.write_text(text[:start] + block + text[end:], encoding="utf-8")


def patch_legacy_test_contract() -> None:
    if not LEGACY_TEST.is_file():
        raise SystemExit(f"GC-WB-RAID-002 required regression file missing: {LEGACY_TEST}")
    text = LEGACY_TEST.read_text(encoding="utf-8")
    for old, new, label in _TEST_REPLACEMENTS:
        text = _replace_required(text, old, new, label)
    LEGACY_TEST.write_text(text, encoding="utf-8")


def verify_contract() -> None:
    if not LEGACY_TEST.is_file():
        raise SystemExit(f"GC-WB-RAID-002 required regression file missing: {LEGACY_TEST}")
    text = LEGACY_TEST.read_text(encoding="utf-8")
    for _old, new, label in _TEST_REPLACEMENTS:
        if new not in text:
            raise SystemExit(f"GC-WB-RAID-002 transformed test contract missing: {label}")
    wb_text = impl.WB.read_text(encoding="utf-8")
    if LEGACY_ARRIVAL_MARKER not in wb_text:
        raise SystemExit("GC-WB-RAID-002 transformed legacy arrival contract missing")
    if not impl.TEST.is_file():
        raise SystemExit(f"GC-WB-RAID-002 generated regression file missing: {impl.TEST}")


def apply_once() -> None:
    impl.patch_world_boss()
    patch_legacy_arrival_raid_contract()
    impl.patch_template()
    patch_legacy_test_contract()
    impl.write_tests()
    verify_contract()


def _git_bytes(*args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout


def _working_tree_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(b"unstaged\0")
    digest.update(_git_bytes("diff", "--binary", "--no-ext-diff"))
    digest.update(b"staged\0")
    digest.update(_git_bytes("diff", "--cached", "--binary", "--no-ext-diff"))
    untracked = _git_bytes("ls-files", "--others", "--exclude-standard", "-z")
    for raw in sorted(item for item in untracked.split(b"\0") if item):
        rel = raw.decode("utf-8", errors="surrogateescape")
        path = ROOT / rel
        digest.update(b"untracked\0")
        digest.update(raw)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_idempotence() -> None:
    before = _working_tree_fingerprint()
    apply_once()
    after = _working_tree_fingerprint()
    if before != after:
        raise SystemExit(
            "GC-WB-RAID-002 idempotence failure: second application changed the working tree"
        )
    print("GC-WB-RAID-002 verify OK: second application produced 0 additional diff")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--verify":
        verify_idempotence()
        return
    if len(sys.argv) != 1:
        raise SystemExit("usage: apply_gc_wb_raid_002.py [--verify]")
    apply_once()
    print("GC-WB-RAID-002 codemod applied with canonical test contract")


if __name__ == "__main__":
    main()
