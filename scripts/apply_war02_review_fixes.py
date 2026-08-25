from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, replacement: str, *, label: str) -> str:
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{label}: start marker missing")
    j = text.find(end, i)
    if j < 0:
        raise RuntimeError(f"{label}: end marker missing")
    return text[:i] + replacement + text[j:]


# 1) Serialize war aggregate updates on PostgreSQL and seed atomically.
path = Path("game/alliance_war.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .db import table_exists\n",
    "from .db import get_db_backend, table_exists\n",
    label="alliance_war import",
)
new_ensure = '''def _select_campaign_stats_for_update(
    low: int,
    high: int,
    conn,
):
    """Lock one aggregate row while Python performs arbitrary-precision math."""
    lock = " FOR UPDATE" if get_db_backend() == "postgres" else ""
    return conn.execute(
        f"""
        SELECT * FROM alliance_war_stats
        WHERE alliance_id_low = ? AND alliance_id_high = ?
        LIMIT 1{lock};
        """,
        (int(low), int(high)),
    ).fetchone()


def _ensure_campaign_stats(low: int, high: int, war_started_at: int, conn) -> dict[str, Any]:
    """Atomically seed + lock the pair before reading/updating its aggregate.

    SQLite already serializes writers through the GC write transaction. PostgreSQL
    additionally takes a row lock so concurrent fleet workers cannot overwrite
    each other's arbitrary-precision TEXT totals.
    """
    now = _now()
    conn.execute(
        """
        INSERT INTO alliance_war_stats (
            alliance_id_low, alliance_id_high, war_started_at,
            low_score_raw, high_score_raw,
            low_units_destroyed, high_units_destroyed,
            low_wins, high_wins, draws, battle_count,
            last_battle_at, updated_at
        ) VALUES (?, ?, ?, '0', '0', '0', '0', 0, 0, 0, 0, NULL, ?)
        ON CONFLICT(alliance_id_low, alliance_id_high) DO NOTHING;
        """,
        (int(low), int(high), int(war_started_at), now),
    )
    row = _select_campaign_stats_for_update(low, high, conn)
    if not row:
        raise RuntimeError("alliance_war_stats_seed_failed")
    current = dict(row)
    if int(current.get("war_started_at") or 0) != int(war_started_at):
        conn.execute(
            """
            UPDATE alliance_war_stats
            SET war_started_at = ?,
                low_score_raw = '0', high_score_raw = '0',
                low_units_destroyed = '0', high_units_destroyed = '0',
                low_wins = 0, high_wins = 0, draws = 0, battle_count = 0,
                last_battle_at = NULL, updated_at = ?
            WHERE alliance_id_low = ? AND alliance_id_high = ?;
            """,
            (int(war_started_at), now, int(low), int(high)),
        )
        return _zero_stats(low, high, war_started_at)
    return current


'''
text = replace_region(
    text,
    "def _ensure_campaign_stats(",
    "def _side_payload(",
    new_ensure,
    label="alliance_war ensure region",
)
path.write_text(text, encoding="utf-8")


# 2) Preserve neutral transition state and make re-war campaign timestamps monotonic.
path = Path("game/alliance.py")
text = path.read_text(encoding="utf-8")
old_war_branch = '''        if rtype == "war":
            _invalidate_pending_diplomacy_requests_between(from_aid, to_aid, conn=conn, now=now)
            lo, hi = _diplomacy_pair(from_aid, to_aid)
            conn.execute(
                """
                INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)
                VALUES (?, ?, 'war', ?)
                ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET
                    relation = 'war', updated_at = excluded.updated_at;
                """,
                (lo, hi, now),
            )
'''
new_war_branch = '''        if rtype == "war":
            lo, hi = _diplomacy_pair(from_aid, to_aid)
            previous = conn.execute(
                """
                SELECT updated_at FROM alliance_diplomacy
                WHERE alliance_id_low = ? AND alliance_id_high = ?
                LIMIT 1;
                """,
                (lo, hi),
            ).fetchone()
            previous_transition = int(previous["updated_at"] or 0) if previous else 0
            war_started_at = max(int(now), previous_transition + 1)
            _invalidate_pending_diplomacy_requests_between(
                from_aid, to_aid, conn=conn, now=war_started_at
            )
            conn.execute(
                """
                INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)
                VALUES (?, ?, 'war', ?)
                ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET
                    relation = 'war', updated_at = excluded.updated_at;
                """,
                (lo, hi, war_started_at),
            )
'''
text = replace_once(text, old_war_branch, new_war_branch, label="monotonic war transition")
old_peace_delete = '''                conn.execute(
                    "DELETE FROM alliance_diplomacy WHERE alliance_id_low = ? AND alliance_id_high = ?;",
                    (lo, hi),
                )
'''
new_peace_neutral = '''                conn.execute(
                    """
                    INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)
                    VALUES (?, ?, 'neutral', ?)
                    ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET
                        relation = 'neutral', updated_at = excluded.updated_at;
                    """,
                    (lo, hi, now),
                )
'''
text = replace_once(text, old_peace_delete, new_peace_neutral, label="peace neutral transition")
path.write_text(text, encoding="utf-8")


# 3) Register WAR-02 tables in combat reset domain, child before parent.
path = Path("game/admin_universe_reset.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    "alliances",\n    "combat_hall_of_fame",\n',
    '    "alliances",\n    "alliance_war_events",\n    "alliance_war_stats",\n    "combat_hall_of_fame",\n',
    label="reset clear order",
)
text = replace_once(
    text,
    '    "combat": (\n        "combat_hall_of_fame",\n',
    '    "combat": (\n        "alliance_war_events",\n        "alliance_war_stats",\n        "combat_hall_of_fame",\n',
    label="reset combat domain",
)
path.write_text(text, encoding="utf-8")


# 4) Bring stale pre-WAR-01 test in line with the hardened lifecycle and add same-second re-war regression.
path = Path("tests/test_alliance.py")
text = path.read_text(encoding="utf-8")
old_test_tail = '''        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
        send_diplomacy_request(leader_a, "PEA", "nap", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="duplicate_diplomacy_request"):
            send_diplomacy_request(leader_a, "PEA", "nap", conn=conn)
    finally:
        conn.close()




def test_gc_al_war_01_lifecycle_bundle(alliance_db):
'''
new_test_tail = '''        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
        with pytest.raises(ValueError, match="war_active"):
            send_diplomacy_request(leader_a, "PEA", "nap", conn=conn)
    finally:
        conn.close()


def test_diplomacy_rewar_same_second_gets_fresh_campaign(alliance_db, monkeypatch):
    from game import alliance as alliance_module
    from game.alliance import get_alliance_relation

    leader_a = _player(name="SameSecond A")
    leader_b = _player(name="SameSecond B")
    conn = db()
    try:
        create_alliance("SSA", "Same Second A", leader_a, conn=conn)
        create_alliance("SSB", "Same Second B", leader_b, conn=conn)
        conn.commit()
        aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
        aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
        for aid in (aid_a, aid_b):
            conn.execute(
                "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
                (aid,),
            )
        conn.commit()

        monkeypatch.setattr(alliance_module, "_now", lambda: 1_000)
        send_diplomacy_request(leader_a, "SSB", "war", conn=conn)
        conn.commit()
        first_started = int(
            conn.execute(
                "SELECT updated_at FROM alliance_diplomacy WHERE alliance_id_low = ? AND alliance_id_high = ?;",
                (min(aid_a, aid_b), max(aid_a, aid_b)),
            ).fetchone()["updated_at"]
        )

        send_diplomacy_request(leader_a, "SSB", "peace", conn=conn)
        conn.commit()
        req_id = int(
            conn.execute(
                "SELECT id FROM alliance_diplomacy_requests WHERE request_type = 'peace' AND status = 'pending' ORDER BY id DESC LIMIT 1;"
            ).fetchone()["id"]
        )
        respond_diplomacy_request(leader_b, req_id, accept=True, conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "neutral"

        send_diplomacy_request(leader_a, "SSB", "war", conn=conn)
        conn.commit()
        second_started = int(
            conn.execute(
                "SELECT updated_at FROM alliance_diplomacy WHERE alliance_id_low = ? AND alliance_id_high = ?;",
                (min(aid_a, aid_b), max(aid_a, aid_b)),
            ).fetchone()["updated_at"]
        )
        assert second_started > first_started
    finally:
        conn.close()


def test_gc_al_war_01_lifecycle_bundle(alliance_db):
'''
text = replace_once(text, old_test_tail, new_test_tail, label="alliance legacy + same-second tests")
path.write_text(text, encoding="utf-8")


# 5) Structural regressions for reset ownership + PostgreSQL serialization path.
path = Path("tests/test_alliance_war_meta.py")
text = path.read_text(encoding="utf-8")
append = '''\n\ndef test_postgres_path_serializes_war_aggregate_updates() -> None:\n    source = Path("game/alliance_war.py").read_text(encoding="utf-8")\n    assert 'get_db_backend() == "postgres"' in source\n    assert 'FOR UPDATE' in source\n    assert 'ON CONFLICT(alliance_id_low, alliance_id_high) DO NOTHING' in source\n'''
if "test_postgres_path_serializes_war_aggregate_updates" not in text:
    text += append
path.write_text(text, encoding="utf-8")

path = Path("tests/test_admin_universe_reset.py")
text = path.read_text(encoding="utf-8")
append = '''\n\ndef test_alliance_war_meta_belongs_to_combat_reset_domain() -> None:\n    from game.admin_universe_reset import CLEAR_TABLES_ORDER, RESET_DOMAINS\n\n    combat = RESET_DOMAINS["combat"]\n    assert "alliance_war_events" in combat\n    assert "alliance_war_stats" in combat\n    assert CLEAR_TABLES_ORDER.index("alliance_war_events") < CLEAR_TABLES_ORDER.index("alliance_war_stats")\n'''
if "test_alliance_war_meta_belongs_to_combat_reset_domain" not in text:
    text += append
path.write_text(text, encoding="utf-8")

print("WAR-02 review fixes applied")
