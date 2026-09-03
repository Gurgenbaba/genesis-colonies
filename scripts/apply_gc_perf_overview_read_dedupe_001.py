"""One-shot GC-PERF-OVERVIEW-READ-DEDUPE-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOTE = ROOT / "game" / "vote_rewards.py"
OVERVIEW = ROOT / "game" / "overview_page.py"


def replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one target, found {count}")
    return src.replace(old, new, 1)


def replace_block(src: str, start: str, end: str, new: str, label: str) -> str:
    i = src.find(start)
    if i < 0:
        raise SystemExit(f"{label}: start marker missing")
    j = src.find(end, i)
    if j < 0:
        raise SystemExit(f"{label}: end marker missing")
    return src[:i] + new.rstrip() + "\n\n\n" + src[j:]


def patch_vote_rewards() -> None:
    src = VOTE.read_text(encoding="utf-8")
    if "GC-PERF-OVERVIEW-READ-DEDUPE-001" in src:
        print("vote_rewards patch already applied")
        return

    start = "def count_vote_center_attention(user_id: int, *, conn, now: Optional[int] = None) -> int:\n"
    end = "def get_vote_center_state(user_id: int, *, conn) -> Dict[str, Any]:\n"
    old = src[src.find(start):src.find(end)]
    if not old.startswith(start):
        raise SystemExit("vote attention block missing")

    new = '''def vote_center_attention_summary(
    user_id: int,
    *,
    conn,
    now: Optional[int] = None,
) -> Dict[str, int]:
    """GC-PERF-OVERVIEW-READ-DEDUPE-001: one bulk vote-attention read.

    Returns pending and currently voteable counts separately so page warnings and
    nav badges can share the same query shape without repeating provider/schema probes.
    """
    uid = int(user_id)
    if uid <= 0:
        return {"pending": 0, "voteable": 0, "total": 0}
    if not tables_exist(conn, ("vote_rewards", "vote_providers")):
        return {"pending": 0, "voteable": 0, "total": 0}

    reward_columns = table_columns(conn, "vote_rewards")
    has_channel = "vote_channel" in reward_columns
    has_next_at = "provider_next_vote_at" in reward_columns
    channel_filter = (
        " AND COALESCE(vote_channel, 'player') = 'player'" if has_channel else ""
    )
    next_at_select = (
        "provider_next_vote_at" if has_next_at else "NULL AS provider_next_vote_at"
    )
    ts = int(now if now is not None else time.time())

    rows = conn.execute(
        f"""
        WITH latest_ranked AS (
            SELECT provider, voted_at, {next_at_select},
                   ROW_NUMBER() OVER (
                       PARTITION BY provider
                       ORDER BY voted_at DESC
                   ) AS rn
            FROM vote_rewards
            WHERE user_id = ?{channel_filter}
        ),
        pending AS (
            SELECT COUNT(*) AS c
            FROM vote_rewards
            WHERE user_id = ? AND status = 'pending'
        ),
        providers AS (
            SELECT provider_key, cooldown_sec, sort_order
            FROM vote_providers
            WHERE enabled = 1
        )
        SELECT p.provider_key, p.cooldown_sec,
               l.voted_at, l.provider_next_vote_at,
               pending.c AS pending_count
        FROM pending
        LEFT JOIN providers p ON 1 = 1
        LEFT JOIN latest_ranked l
          ON l.provider = p.provider_key AND l.rn = 1
        ORDER BY p.sort_order ASC, p.provider_key ASC;
        """,
        (uid, uid),
    ).fetchall()

    pending_count = int(rows[0]["pending_count"] or 0) if rows else 0
    voteable = 0
    for row in rows:
        provider_key = str(row["provider_key"] or "")
        if not provider_key:
            continue
        canonical = VOTE_PROVIDERS.get(provider_key) or {}
        cooldown_sec = int(
            canonical.get("cooldown_seconds")
            or row["cooldown_sec"]
            or VOTE_COOLDOWN_SEC
        )
        voted_at = row["voted_at"]
        if voted_at is None:
            voteable += 1
            continue

        next_at = 0
        next_at_raw = row["provider_next_vote_at"]
        if next_at_raw is not None:
            try:
                next_at = int(next_at_raw)
            except (TypeError, ValueError):
                next_at = 0
        vote_end = next_at if next_at > 0 else int(voted_at) + cooldown_sec
        if vote_end <= ts:
            voteable += 1

    return {
        "pending": int(pending_count),
        "voteable": int(voteable),
        "total": int(voteable + pending_count),
    }


def count_vote_center_attention(user_id: int, *, conn, now: Optional[int] = None) -> int:
    """Diet-safe Vote Center badge: voteable providers + pending rewards."""
    return int(
        vote_center_attention_summary(int(user_id), conn=conn, now=now).get("total") or 0
    )'''

    src = replace_block(src, start, end, new, "vote attention summary")
    VOTE.write_text(src, encoding="utf-8")


def patch_overview() -> None:
    src = OVERVIEW.read_text(encoding="utf-8")
    if "GC-PERF-OVERVIEW-READ-DEDUPE-001" in src:
        print("overview patch already applied")
        return

    old_vote = '''    try:\n        if conn is not None:\n            from .vote_rewards import (\n                count_pending_vote_rewards,\n                count_voteable_providers,\n                vote_system_ready,\n            )\n\n            uid = int(user_id)\n            if vote_system_ready(conn):\n                pending = count_pending_vote_rewards(uid, conn=conn)\n                voteable = count_voteable_providers(uid, conn=conn)\n                if pending > 0:\n                    warnings.append(\n                        {\n                            "key": "vote_rewards_pending",\n                            "severity": "info",\n                            "label_key": "overview_warning_vote_rewards_pending",\n                            "href_key": "vote_center_view",\n                            "count": pending,\n                        }\n                    )\n                elif voteable > 0:\n                    warnings.append(\n                        {\n                            "key": "vote_available",\n                            "severity": "info",\n                            "label_key": "overview_warning_vote_available",\n                            "href_key": "vote_center_view",\n                            "count": voteable,\n                        }\n                    )\n    except Exception:\n        pass\n'''
    new_vote = '''    try:\n        if conn is not None:\n            # GC-PERF-OVERVIEW-READ-DEDUPE-001: one combined vote-attention read.\n            from .vote_rewards import vote_center_attention_summary\n\n            attention = vote_center_attention_summary(int(user_id), conn=conn)\n            pending = int(attention.get("pending") or 0)\n            voteable = int(attention.get("voteable") or 0)\n            if pending > 0:\n                warnings.append(\n                    {\n                        "key": "vote_rewards_pending",\n                        "severity": "info",\n                        "label_key": "overview_warning_vote_rewards_pending",\n                        "href_key": "vote_center_view",\n                        "count": pending,\n                    }\n                )\n            elif voteable > 0:\n                warnings.append(\n                    {\n                        "key": "vote_available",\n                        "severity": "info",\n                        "label_key": "overview_warning_vote_available",\n                        "href_key": "vote_center_view",\n                        "count": voteable,\n                    }\n                )\n    except Exception:\n        pass\n'''
    src = replace_once(src, old_vote, new_vote, "overview vote warning")

    src = replace_once(
        src,
        '''def _load_overview_queue_fleet(\n    user_id: int,\n    planet_id: int,\n    *,\n    conn=None,\n) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:\n''',
        '''def _load_overview_queue_fleet(\n    user_id: int,\n    planet_id: int,\n    *,\n    conn=None,\n    shipyard_level: Optional[int] = None,\n) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:\n''',
        "overview queue signature",
    )

    old_sy = '''        from .shipyard import get_shipyard_level\n        from .shipyard_queue import shipyard_queue_for_client, shipyard_queue_table_ready\n\n        if shipyard_queue_table_ready(conn):\n            sy_level = get_shipyard_level(int(user_id), int(planet_id), conn=conn)\n            shipyard_queue = shipyard_queue_for_client(\n                int(user_id), int(planet_id), sy_level, conn=conn\n            )\n'''
    new_sy = '''        from .shipyard_queue import shipyard_queue_for_client, shipyard_queue_table_ready\n\n        if shipyard_queue_table_ready(conn):\n            if shipyard_level is None:\n                from .shipyard import get_shipyard_level\n\n                sy_level = get_shipyard_level(int(user_id), int(planet_id), conn=conn)\n            else:\n                sy_level = max(0, int(shipyard_level))\n            shipyard_queue = shipyard_queue_for_client(\n                int(user_id), int(planet_id), sy_level, conn=conn\n            )\n'''
    src = replace_once(src, old_sy, new_sy, "overview shipyard level")

    src = replace_once(
        src,
        '''    fleet_movements: Optional[List[Dict[str, Any]]] = None,\n) -> Dict[str, Any]:\n''',
        '''    fleet_movements: Optional[List[Dict[str, Any]]] = None,\n    shipyard_level: Optional[int] = None,\n) -> Dict[str, Any]:\n''',
        "overview status signature",
    )
    src = replace_once(
        src,
        '''        loaded_sy, loaded_def, loaded_fleet = _load_overview_queue_fleet(\n            int(user_id), planet_id, conn=conn\n        )\n''',
        '''        loaded_sy, loaded_def, loaded_fleet = _load_overview_queue_fleet(\n            int(user_id),\n            planet_id,\n            conn=conn,\n            shipyard_level=shipyard_level,\n        )\n''',
        "overview status shared shipyard level",
    )

    old_page = '''    player_view = ctx["player_view"]\n    status = build_overview_status(\n'''
    new_page = '''    player_view = ctx["player_view"]\n    # GC-PERF-OVERVIEW-READ-DEDUPE-001: live context already owns the active\n    # planet Buildings snapshot; do not re-read it just to derive Shipyard level.\n    buildings = ctx.get("buildings") or {}\n    shared_shipyard_level = max(\n        int(buildings.get("orbital_shipyard") or 0),\n        int(buildings.get("shipyard") or 0),\n    )\n    status = build_overview_status(\n'''
    src = replace_once(src, old_page, new_page, "overview page shared buildings")
    src = replace_once(
        src,
        '''        planet=planet,\n        include_log=False,\n        conn=conn,\n    )\n''',
        '''        planet=planet,\n        include_log=False,\n        conn=conn,\n        shipyard_level=shared_shipyard_level,\n    )\n''',
        "overview page shared shipyard arg",
    )

    OVERVIEW.write_text(src, encoding="utf-8")


def main() -> int:
    patch_vote_rewards()
    patch_overview()
    print("applied GC-PERF-OVERVIEW-READ-DEDUPE-001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
