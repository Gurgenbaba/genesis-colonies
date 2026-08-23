"""One-shot GC-PERF-RESOURCE-PERSIST-001 patch helper for the perf branch.

Applies exact, assertion-guarded text transformations so read-only EffectResolver
consumers no longer create/cleanup rows during diet resource projection.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_personality() -> None:
    path = ROOT / "game" / "galactic_diplomacy" / "personality.py"
    old = '''def get_galaxy_personality(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Read galaxy personality state (bootstraps default row when missing)."""
    return ensure_galaxy_personality_state(galaxy, conn=conn)
'''
    new = '''def get_galaxy_personality(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Read galaxy personality state without bootstrapping a missing neutral row."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return _build_personality_payload(
                galaxy_id,
                _default_state_row(galaxy_id),
                conn=conn,
                source="fallback",
            )

        row = _fetch_state_row(galaxy_id, conn)
        if row is None:
            return _build_personality_payload(
                galaxy_id,
                _default_state_row(galaxy_id),
                conn=conn,
                source="fallback",
            )
        return _build_personality_payload(galaxy_id, row, conn=conn, source="state")
    finally:
        if own_conn:
            conn.close()
'''
    replace_once(path, old, new)


def patch_boosters() -> None:
    path = ROOT / "game" / "inventory_boosters.py"
    old = '''    _purge_expired(int(user_id), conn=conn, now=ts)
'''
    new = '''    # GC-PERF-RESOURCE-PERSIST-001: reads already filter `expires_at > now`.
    # Cleanup stays on booster activation/explicit maintenance, never on a poll read.
'''
    replace_once(path, old, new)


def patch_commander() -> None:
    path = ROOT / "game" / "commander_classes.py"
    old = '''def get_commander_row(player_id: int, *, conn) -> Dict[str, Any]:
    _ensure_row(int(player_id), conn=conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT player_id, class_key, chosen_at, swap_count,
               skill_points_unspent, skill_points_earned, updated_at
        FROM player_commander WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else {
        "player_id": int(player_id),
        "class_key": None,
        "chosen_at": None,
        "swap_count": 0,
        "skill_points_unspent": 0,
        "skill_points_earned": 0,
        "updated_at": 0,
    }
'''
    new = '''def _read_commander_row(player_id: int, *, conn) -> Dict[str, Any]:
    """Pure read for EffectResolver paths; missing row means neutral commander."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT player_id, class_key, chosen_at, swap_count,
               skill_points_unspent, skill_points_earned, updated_at
        FROM player_commander WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else {
        "player_id": int(player_id),
        "class_key": None,
        "chosen_at": None,
        "swap_count": 0,
        "skill_points_unspent": 0,
        "skill_points_earned": 0,
        "updated_at": 0,
    }


def get_commander_row(player_id: int, *, conn) -> Dict[str, Any]:
    _ensure_row(int(player_id), conn=conn)
    return _read_commander_row(int(player_id), conn=conn)
'''
    replace_once(path, old, new)

    old_mods = '''def get_commander_effect_modifiers(player_id: int, *, conn) -> Dict[str, float]:
    """Merged additive/multiplicative mods for EffectResolver (no meta keys)."""
    if not schema_ready(conn):
        return {}
    row = get_commander_row(int(player_id), conn=conn)
'''
    new_mods = '''def get_commander_effect_modifiers(player_id: int, *, conn) -> Dict[str, float]:
    """Merged additive/multiplicative mods for EffectResolver (no meta keys)."""
    if not schema_ready(conn):
        return {}
    row = _read_commander_row(int(player_id), conn=conn)
'''
    replace_once(path, old_mods, new_mods)

    old_sources = '''def iter_commander_effect_sources(player_id: int, *, conn) -> List[Tuple[str, str, float]]:
    """Yield (mod_key, source_label, delta_or_mult) for admin/ER source entries."""
    if not schema_ready(conn):
        return []
    row = get_commander_row(int(player_id), conn=conn)
'''
    new_sources = '''def iter_commander_effect_sources(player_id: int, *, conn) -> List[Tuple[str, str, float]]:
    """Yield (mod_key, source_label, delta_or_mult) for admin/ER source entries."""
    if not schema_ready(conn):
        return []
    row = _read_commander_row(int(player_id), conn=conn)
'''
    replace_once(path, old_sources, new_sources)


def main() -> None:
    patch_personality()
    patch_boosters()
    patch_commander()
    print("GC-PERF-RESOURCE-PERSIST-001 read-path patch applied")


if __name__ == "__main__":
    main()
