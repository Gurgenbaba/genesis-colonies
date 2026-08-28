from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    claim_tail = '''    return {\n        "available": True,\n        "reason": "ok",\n        "next_day": next_day,\n        "next_unlock_in_sec": 0,\n    }\n\n\ndef _grant_day_rewards(\n'''
    claim_new = '''    return {\n        "available": True,\n        "reason": "ok",\n        "next_day": next_day,\n        "next_unlock_in_sec": 0,\n    }\n\n\ndef login_reward_available_for_nav(\n    player_id: int,\n    *,\n    conn,\n    now: Optional[float] = None,\n) -> bool:\n    """Read-only Login Rewards attention bit for high-frequency shell polling.\n\n    Mirrors ``ensure_progress`` + ``claim_status`` availability without creating or\n    resetting progress rows. The actual Login Rewards page/claim path remains the\n    owner of lifecycle writes.\n    """\n    if int(player_id or 0) <= 0 or not schema_ready(conn):\n        return False\n\n    ts = float(now if now is not None else time.time())\n    row = _fetch_progress(int(player_id), conn=conn)\n    if not row:\n        # ``ensure_progress`` would create day-0 progress and day 1 is claimable.\n        return True\n\n    progress = _row_to_progress(row)\n    last = progress.get("last_claim_day_bucket")\n    if last is not None and day_bucket(ts) > int(last) + 1:\n        # ``ensure_progress`` would reset the missed streak, making day 1 claimable.\n        return True\n    return bool(claim_status(progress, now=ts).get("available"))\n\n\ndef _grant_day_rewards(\n'''
    replace_once("game/login_rewards.py", claim_tail, claim_new, "login nav helper")

    old_wb = '''    wb_active = False\n    wb_count = 0\n    try:\n        from game.world_boss import list_active_events\n\n        active_events = list_active_events(conn=conn, limit=10)\n        wb_count = len(active_events)\n        wb_active = wb_count > 0\n    except Exception:\n        wb_active = False\n        wb_count = 0\n\n    login_available = False\n    bp_claimable = 0\n    story_attention = 0\n    server_event_count = 0\n    try:\n        from game.server_events import list_active_events as list_server_events\n        from game.server_events import schema_ready as server_events_ready\n\n        if server_events_ready(conn):\n            server_event_count = len(list_server_events(now=None, conn=conn))\n    except Exception:\n        server_event_count = 0\n    try:\n        from game.login_rewards import serialize_for_client as lr_serialize\n\n        lr = lr_serialize(uid, conn=conn)\n        login_available = bool(lr.get("ready") and lr.get("available"))\n    except Exception:\n        login_available = False\n'''
    new_wb = '''    wb_active = False\n    wb_count = 0\n\n    login_available = False\n    bp_claimable = 0\n    story_attention = 0\n    try:\n        from game.login_rewards import login_reward_available_for_nav\n\n        login_available = bool(login_reward_available_for_nav(uid, conn=conn))\n    except Exception:\n        login_available = False\n'''
    replace_once("game/live_state.py", old_wb, new_wb, "nav login and duplicate liveops preloads")

    old_live = '''    live_events_count = 0\n    try:\n        from game.overview_page import build_overview_live_events\n\n        live_events_count = len(build_overview_live_events(user_id=uid, conn=conn))\n    except Exception:\n        live_events_count = server_event_count + wb_count\n'''
    new_live = '''    live_events_count = 0\n    try:\n        from game.overview_page import build_overview_live_events\n\n        live_event_rows = [\n            row\n            for row in build_overview_live_events(user_id=uid, conn=conn)\n            if isinstance(row, dict)\n        ]\n        live_events_count = len(live_event_rows)\n        wb_count = sum(\n            1 for row in live_event_rows if str(row.get("kind") or "") == "world_boss"\n        )\n        # Overview intentionally caps World Boss cards at five. Only when that cap\n        # is saturated do we need the dedicated badge's historical up-to-10 count.\n        if wb_count >= 5:\n            from game.world_boss import list_active_events\n\n            wb_count = len(list_active_events(conn=conn, limit=10))\n        wb_active = wb_count > 0\n    except Exception:\n        # Preserve the old degraded fallback without penalizing the normal path.\n        server_event_count = 0\n        try:\n            from game.world_boss import list_active_events\n\n            wb_count = len(list_active_events(conn=conn, limit=10))\n            wb_active = wb_count > 0\n        except Exception:\n            wb_count = 0\n            wb_active = False\n        try:\n            from game.server_events import list_active_events as list_server_events\n            from game.server_events import schema_ready as server_events_ready\n\n            if server_events_ready(conn):\n                server_event_count = len(list_server_events(now=None, conn=conn))\n        except Exception:\n            server_event_count = 0\n        live_events_count = server_event_count + wb_count\n'''
    replace_once("game/live_state.py", old_live, new_live, "reuse liveops rows for nav counts")


if __name__ == "__main__":
    main()
