"""Admin Bot-Log + Kill-Switch payloads (EPIC-21 / GC-P08 / GC-P19)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .accounts import (
    FACTION_BOTS,
    bootstrap_faction_bots,
    ensure_faction_bot,
    list_bot_roster,
)
from .bases import list_live_bases, spawn_pirate_base
from .log import log_pirate_action, recent_action_log
from .settings import is_pirates_ai_enabled, set_pirates_ai_enabled


def build_admin_pirates_payload(conn, *, log_limit: int = 80) -> Dict[str, Any]:
    ai_on = is_pirates_ai_enabled(conn=conn)
    bases = list_live_bases(conn, limit=50)
    logs = recent_action_log(conn, limit=log_limit)
    raid_count = sum(1 for row in logs if row.get("kind") == "raid_dispatch")
    spy_count = sum(1 for row in logs if row.get("kind") == "spy_dispatch")
    spawn_count = sum(1 for row in logs if row.get("kind") == "base_spawn")
    war_count = sum(1 for row in logs if row.get("kind") == "pirate_war_started")
    play_loop_in_log = sum(1 for row in logs if row.get("kind") == "bot_play_loop")
    heat_rows: List[Dict[str, Any]] = []
    try:
        cur = conn.execute(
            """
            SELECT galaxy_id, heat, updated_at
            FROM galaxy_heat
            ORDER BY heat DESC
            LIMIT 12;
            """
        )
        for r in cur.fetchall():
            heat_rows.append(
                {
                    "galaxy_id": int(r["galaxy_id"]),
                    "heat": int(r["heat"] or 0),
                    "updated_at": float(r["updated_at"]) if r["updated_at"] else None,
                }
            )
    except Exception:
        pass
    infiltrations = []
    smugglers = []
    try:
        from .infiltration import list_active_infiltrations

        infiltrations = list_active_infiltrations(conn, limit=30)
    except Exception:
        pass
    try:
        from .smugglers import list_live_smugglers

        smugglers = list_live_smugglers(conn, limit=30)
    except Exception:
        pass
    pirate_wars: List[Dict[str, Any]] = []
    try:
        from ..galactic_diplomacy import get_active_emergency

        for h in heat_rows:
            active = get_active_emergency(int(h["galaxy_id"]), conn=conn)
            if active and str(active.get("emergency_key") or "") == "pirate_war":
                pirate_wars.append(
                    {
                        "galaxy_id": int(h["galaxy_id"]),
                        "ends_at": active.get("ends_at"),
                        "heat": h["heat"],
                    }
                )
    except Exception:
        pass
    bots = list_bot_roster(conn=conn)
    bots_online = sum(1 for b in bots if b.get("exists"))
    return {
        "ok": True,
        "ai_enabled": ai_on,
        "live_bases": len(bases),
        "bots": bots,
        "bases": [
            {
                "id": b["id"],
                "faction_key": b["faction_key"],
                "galaxy": b["galaxy"],
                "system": b["system"],
                "position": b["position"],
                "strength": b["strength"],
                "status": b["status"],
                "current_hp": b["current_hp"],
                "max_hp": b["max_hp"],
            }
            for b in bases
        ],
        "heat_top": heat_rows,
        "pirate_wars": pirate_wars,
        "infiltrations": infiltrations,
        "smugglers": smugglers,
        "kpis": {
            "bots_online": bots_online,
            "raid_dispatch_in_log": raid_count,
            "spy_dispatch_in_log": spy_count,
            "base_spawn_in_log": spawn_count,
            "pirate_war_in_log": war_count,
            "play_loop_in_log": play_loop_in_log,
            "live_infiltrations": len(infiltrations),
            "live_smugglers": len(smugglers),
            "log_rows": len(logs),
        },
        "log": logs,
    }


def admin_set_ai(conn, enabled: bool) -> Dict[str, Any]:
    set_pirates_ai_enabled(bool(enabled), conn=conn)
    bootstrapped: List[Dict[str, Any]] = []
    if enabled:
        bots = bootstrap_faction_bots(conn=conn)
        bootstrapped = [
            {
                "faction_key": b["faction_key"],
                "player_id": b["player_id"],
                "planet_id": b["planet_id"],
                "galaxy": b.get("galaxy"),
                "system": b.get("system"),
                "position": b.get("position"),
            }
            for b in bots
        ]
        log_pirate_action(
            conn,
            kind="bots_bootstrapped",
            message=f"Soft-On bootstrap: {len(bootstrapped)} faction bots",
            severity="info",
            payload={"bots": bootstrapped},
        )
    log_pirate_action(
        conn,
        kind="ai_toggle",
        message=f"admin set AI {'on' if enabled else 'off'}",
        severity="warn",
        payload={
            "enabled": bool(enabled),
            "mode": "soft",
            "bots_bootstrapped": len(bootstrapped),
        },
    )
    return {
        "ok": True,
        "ai_enabled": is_pirates_ai_enabled(conn=conn),
        "mode": "soft",
        "bots_bootstrapped": len(bootstrapped),
        "bots": bootstrapped,
    }


def admin_force_spawn_hottest(
    conn,
    *,
    galaxy_id: Optional[int] = None,
) -> Dict[str, Any]:
    """LiveOps: force-spawn a pirate base in the hottest (or given) galaxy."""
    g = galaxy_id
    heat = 0
    if g is None:
        try:
            cur = conn.execute(
                """
                SELECT galaxy_id, heat FROM galaxy_heat
                ORDER BY heat DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
            if row:
                g = int(row["galaxy_id"])
                heat = int(row["heat"] or 0)
        except Exception:
            pass
        if g is None:
            g = 1
    else:
        g = int(g)
        try:
            from .heat import get_galaxy_heat

            heat = int(get_galaxy_heat(conn, g).get("heat") or 0)
        except Exception:
            heat = 0

    res = spawn_pirate_base(conn, galaxy=int(g), announce=True, force=True)
    if res.get("ok"):
        log_pirate_action(
            conn,
            kind="base_force_spawn",
            galaxy_id=int(g),
            faction_key=str((res.get("base") or {}).get("faction_key") or ""),
            base_id=int(res.get("base_id") or (res.get("base") or {}).get("base_id") or 0)
            or None,
            message=f"admin force-spawn G{g} heat={heat}",
            severity="warn",
            payload={"galaxy_id": int(g), "heat": heat, "result": res},
        )
    return {
        "ok": bool(res.get("ok")),
        "galaxy_id": int(g),
        "heat": heat,
        "spawn": res,
        "error": res.get("error"),
    }


def admin_hard_disable_ai(conn) -> Dict[str, Any]:
    """Soft-Off + recall outbound/holding fleets for all faction bots."""
    from ..fleet import recall_fleet_movement

    set_pirates_ai_enabled(False, conn=conn)
    recalled = 0
    failed = 0
    for faction_key in FACTION_BOTS:
        bot = ensure_faction_bot(faction_key, conn=conn)
        if not bot:
            continue
        pid = int(bot["player_id"])
        cur = conn.execute(
            """
            SELECT id FROM fleet_movements
            WHERE player_id = ? AND status IN ('outbound', 'holding');
            """,
            (pid,),
        )
        for row in cur.fetchall():
            ok, _reason, _meta = recall_fleet_movement(pid, int(row["id"]), conn=conn)
            if ok:
                recalled += 1
            else:
                failed += 1
    log_pirate_action(
        conn,
        kind="ai_hard_off",
        message=f"admin hard-off; recalled={recalled} failed={failed}",
        severity="warn",
        payload={"recalled": recalled, "failed": failed, "mode": "hard"},
    )
    return {
        "ok": True,
        "ai_enabled": False,
        "mode": "hard",
        "recalled": recalled,
        "failed": failed,
    }
