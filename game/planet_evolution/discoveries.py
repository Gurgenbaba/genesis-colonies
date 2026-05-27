"""Rare discovery rolls after research and events."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .definitions import get_discoveries_defs, get_discovery_def
from .history import append_history
from .mechanics import compile_planet_mechanics, get_flag
from .planet_level import add_planet_xp
from .repository import _json_dumps, get_discoveries, get_planet_row
from .requirements import check_requirements


def _stable_roll(planet_id: int, discovery_key: str, salt: str) -> float:
    raw = f"{planet_id}|{discovery_key}|{salt}|discovery"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def try_roll_discovery(
    planet_id: int,
    conn: sqlite3.Connection,
    *,
    source: str = "research",
    pool: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    have = {str(d["discovery_key"]) for d in get_discoveries(planet_id, conn=conn)}
    roll_mult = float(get_flag(planet_id, "discovery_roll_mult", 1.0, conn=conn) or 1.0)
    roll_mult += float(get_flag(planet_id, "discovery_roll_bonus", 0.0, conn=conn) or 0.0)

    day_salt = str(int(time.time() // 86400))
    candidates = []
    for key, ddef in get_discoveries_defs().items():
        if pool and key not in pool:
            continue
        if key in have:
            continue
        ok, _ = check_requirements(planet_id, ddef.get("requirements") or {}, conn)
        if not ok:
            continue
        weight = float(ddef.get("roll_weight") or 0) * roll_mult
        if weight <= 0:
            continue
        roll = _stable_roll(planet_id, key, f"{source}:{day_salt}")
        if roll < weight:
            candidates.append((key, weight, roll))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    discovery_key = candidates[0][0]
    ddef = get_discovery_def(discovery_key) or {}

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO planet_discoveries (
            planet_id, discovery_key, rarity, discovered_at, announced_globally, effects_applied_json
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (
            int(planet_id),
            str(discovery_key),
            str(ddef.get("rarity") or "common"),
            time.time(),
            int(ddef.get("announce_global") or 0),
            _json_dumps({"source": source}),
        ),
    )

    append_history(
        planet_id,
        "discovery",
        str(ddef.get("label_key") or discovery_key),
        history_tag=f"discovery_{discovery_key}",
        payload={"discovery_key": discovery_key, "source": source},
        visibility="global" if int(ddef.get("announce_global") or 0) else "owner",
        conn=conn,
    )
    compile_planet_mechanics(planet_id, conn)
    rarity_xp = {"common": 50, "uncommon": 100, "rare": 250, "epic": 500, "legendary": 1000}
    add_planet_xp(planet_id, rarity_xp.get(str(ddef.get("rarity")), 50), conn, reason=f"discovery:{discovery_key}")

    return {"discovery_key": discovery_key, "rarity": ddef.get("rarity"), "source": source}
