from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests" / "test_alliance.py"

text = TESTS.read_text(encoding="utf-8")
start_marker = "\n\ndef _setup_war_pair(conn, *, tag_a=\"WRA\", tag_b=\"WRB\"):\n"
end_marker = "\n\ndef test_gc_al_dip_01_fleet_mission_hooks(alliance_db):\n"

if text.count(start_marker) != 1:
    raise SystemExit("WAR-01 compact-tests: generated start marker mismatch")
if text.count(end_marker) != 1:
    raise SystemExit("WAR-01 compact-tests: existing diplomacy marker mismatch")

start = text.index(start_marker)
end = text.index(end_marker, start)

bundle = r'''


def test_gc_al_war_01_lifecycle_bundle(alliance_db):
    """GC-AL-WAR-01: one migrated DB covers peace, stale-request guards, permissions, fleet hooks and UI."""
    from game.alliance import get_alliance_relation, get_players_diplomacy_relation
    from game.fleet import mission_allowed_for_target, resolve_fleet_target

    # _player() creates the account through its own DB connection. Create every
    # participant before opening the shared diplomacy connection so SQLite never
    # has two writers competing during this bundled regression.
    leader_a = _player(name="War Leader A")
    leader_b = _player(name="War Leader B")
    member_a = _player(name="War Member A")
    member_b = _player(name="War Member B")

    conn = db()
    try:
        create_alliance("WPA", "War Peace A", leader_a, conn=conn)
        create_alliance("WPB", "War Peace B", leader_b, conn=conn)
        conn.commit()
        aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
        aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])

        for aid in (aid_a, aid_b):
            conn.execute(
                "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
                (aid,),
            )
        conn.commit()

        # Older bilateral offers exist before the newer war transition.
        send_diplomacy_request(leader_a, "WPB", "nap", conn=conn)
        send_diplomacy_request(leader_a, "WPB", "alliance", conn=conn)
        send_diplomacy_request(leader_b, "WPA", "nap", conn=conn)
        conn.commit()
        pending_before = conn.execute(
            """
            SELECT COUNT(*) AS c FROM alliance_diplomacy_requests
            WHERE status = 'pending'
              AND ((from_alliance_id = ? AND to_alliance_id = ?)
                OR (from_alliance_id = ? AND to_alliance_id = ?));
            """,
            (aid_a, aid_b, aid_b, aid_a),
        ).fetchone()["c"]
        assert int(pending_before) == 3

        send_diplomacy_request(leader_a, "WPB", "war", conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
        pending_after = conn.execute(
            """
            SELECT COUNT(*) AS c FROM alliance_diplomacy_requests
            WHERE status = 'pending'
              AND ((from_alliance_id = ? AND to_alliance_id = ?)
                OR (from_alliance_id = ? AND to_alliance_id = ?));
            """,
            (aid_a, aid_b, aid_b, aid_a),
        ).fetchone()["c"]
        assert int(pending_after) == 0

        with pytest.raises(ValueError, match="war_active"):
            send_diplomacy_request(leader_a, "WPB", "nap", conn=conn)
        with pytest.raises(ValueError, match="war_active"):
            send_diplomacy_request(leader_a, "WPB", "alliance", conn=conn)
        with pytest.raises(ValueError, match="already_at_war"):
            send_diplomacy_request(leader_a, "WPB", "war", conn=conn)

        # Peace is mutual: members cannot offer or accept it, leaders can decline without ending war.
        send_diplomacy_request(leader_a, "WPB", "peace", conn=conn)
        conn.commit()
        peace_id = int(
            conn.execute(
                """
                SELECT id FROM alliance_diplomacy_requests
                WHERE from_alliance_id = ? AND to_alliance_id = ?
                  AND request_type = 'peace' AND status = 'pending'
                LIMIT 1;
                """,
                (aid_a, aid_b),
            ).fetchone()["id"]
        )

        join_alliance_by_tag(member_a, "WPA", conn=conn)
        join_alliance_by_tag(member_b, "WPB", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            send_diplomacy_request(member_a, "WPB", "peace", conn=conn)
        with pytest.raises(ValueError, match="forbidden"):
            respond_diplomacy_request(member_b, peace_id, accept=True, conn=conn)

        respond_diplomacy_request(leader_b, peace_id, accept=False, conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"

        # A fresh peace offer can be accepted and immediately restores neutral fleet rules.
        send_diplomacy_request(leader_a, "WPB", "peace", conn=conn)
        conn.commit()
        peace_id = int(
            conn.execute(
                """
                SELECT id FROM alliance_diplomacy_requests
                WHERE from_alliance_id = ? AND to_alliance_id = ?
                  AND request_type = 'peace' AND status = 'pending'
                ORDER BY id DESC LIMIT 1;
                """,
                (aid_a, aid_b),
            ).fetchone()["id"]
        )
        respond_diplomacy_request(leader_b, peace_id, accept=True, conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "neutral"
        assert get_players_diplomacy_relation(leader_a, leader_b, conn=conn) == "neutral"

        planet_b = get_context_planet(player_id=leader_b, conn=conn)
        target = resolve_fleet_target(
            leader_a,
            int(planet_b["galaxy"]),
            int(planet_b["system"]),
            int(planet_b["position"]),
            conn=conn,
        )
        assert target["target_type"] == "foreign_planet"
        assert target.get("diplomacy_relation") == "neutral"
        assert mission_allowed_for_target("attack", target)[0] is True

        with pytest.raises(ValueError, match="peace_requires_war"):
            send_diplomacy_request(leader_a, "WPB", "peace", conn=conn)

        # UI exposes peace only to managers while the relation is an active war.
        neutral_body = _alliance_member_hub_html(alliance_db, uid=leader_a)
        assert 'name="request_type" value="peace"' not in neutral_body

        send_diplomacy_request(leader_a, "WPB", "war", conn=conn)
        conn.commit()
        leader_body = _alliance_member_hub_html(alliance_db, uid=leader_a)
        member_body = _alliance_member_hub_html(alliance_db, uid=member_a)
        assert 'name="request_type" value="peace"' in leader_body
        assert 'data-alliance-submit="diplomacy"' in leader_body
        assert 'name="request_type" value="peace"' not in member_body
    finally:
        conn.close()
'''

TESTS.write_text(text[:start] + bundle + text[end:], encoding="utf-8")
print("GC-AL-WAR-01 generated tests compacted")
