"""Ambush + fleet-save helpers (EPIC-21 / GC-P13 / GC-P15)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

logger = logging.getLogger(__name__)


def on_expedition_pirate_ambush(
    conn,
    *,
    galaxy_id: Optional[int],
    player_id: int,
    planet_id: Optional[int] = None,
    won: bool = False,
    movement_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Escalate expo pirate skirmish into ecosystem signals (heat already recorded separately)."""
    if conn is None or not galaxy_id:
        return {"ok": False, "error": "no_galaxy"}
    gid = int(galaxy_id)
    result: Dict[str, Any] = {"ok": True, "infiltration": None}
    log_pirate_action(
        conn,
        kind="expo_ambush",
        galaxy_id=gid,
        target_player_id=int(player_id),
        message=f"expo pirate ambush won={bool(won)}",
        payload={
            "won": bool(won),
            "movement_id": movement_id,
            "planet_id": planet_id,
        },
        severity="info" if won else "warn",
    )
    # Lost ambush → void-cult style sabotage if AI on and home planet known.
    if (not won) and is_pirates_ai_enabled(conn=conn) and planet_id:
        try:
            from .infiltration import start_infiltration

            infil = start_infiltration(
                conn,
                planet_id=int(planet_id),
                faction_key="void_cult",
                effect_key="prod_sabotage",
            )
            result["infiltration"] = infil
        except Exception:
            logger.exception("ambush infiltration failed")
    return result


def panic_recall_faction_fleets(
    conn,
    *,
    faction_key: str,
    reason: str = "fleet_save",
) -> Dict[str, Any]:
    """Recall outbound/holding fleets for a faction bot (base destroy / panic)."""
    from .accounts import ensure_faction_bot
    from ..fleet import recall_fleet_movement

    bot = ensure_faction_bot(str(faction_key), conn=conn)
    if not bot:
        return {"ok": False, "error": "bot_missing", "recalled": 0}
    pid = int(bot["player_id"])
    cur = conn.execute(
        """
        SELECT id FROM fleet_movements
        WHERE player_id = ? AND status IN ('outbound', 'holding');
        """,
        (pid,),
    )
    recalled = 0
    failed = 0
    for row in cur.fetchall():
        ok, _reason, _meta = recall_fleet_movement(pid, int(row["id"]), conn=conn)
        if ok:
            recalled += 1
        else:
            failed += 1
    log_pirate_action(
        conn,
        kind="fleet_save",
        faction_key=str(faction_key),
        bot_player_id=pid,
        message=f"{reason}: recalled={recalled} failed={failed}",
        severity="warn",
        payload={"recalled": recalled, "failed": failed, "reason": reason},
    )
    return {"ok": True, "recalled": recalled, "failed": failed, "player_id": pid}
