"""GC-NAV-FLEET-READONLY-001 one-shot patch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "game" / "live_state.py"
src = path.read_text(encoding="utf-8")
old = '''def fleet_hud_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Player-wide active fleet slice for /api/game-state (GC-640A)."""
    from game.fleet import (
        build_active_fleets_payload,
        build_fleet_incoming_attack_alerts,
        enrich_fleet_alerts_with_radar,
        fleet_schema_ready,
        get_fleet_slot_status,
        process_fleet_tick,
    )
    from game.queue_poll import player_fleet_is_dirty

    if not fleet_schema_ready(conn):
        return None

    uid = int(user_id)
    with perf_span("fleets.dirty_tick"):
        if player_fleet_is_dirty(uid, conn=conn):
            process_fleet_tick(player_id=uid, conn=conn)

    with perf_span("fleets.alerts"):
'''
new = '''def fleet_hud_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Player-wide active fleet slice for /api/game-state (GC-640A).

    GC-NAV-FLEET-READONLY-001: this payload is strictly read-only. Due movement
    completion is already owned by ``read_player_live_state_for_poll``'s
    heartbeat-aware safety net and the dedicated Fleet worker. Running another
    dirty tick here made every PJAX navigation wait on Fleet DB/lock work.
    """
    from game.fleet import (
        build_active_fleets_payload,
        build_fleet_incoming_attack_alerts,
        enrich_fleet_alerts_with_radar,
        fleet_schema_ready,
        get_fleet_slot_status,
    )

    if not fleet_schema_ready(conn):
        return None

    uid = int(user_id)

    with perf_span("fleets.alerts"):
'''
if src.count(old) != 1:
    raise SystemExit("fleet HUD anchor mismatch")
path.write_text(src.replace(old, new, 1), encoding="utf-8")
