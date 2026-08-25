from __future__ import annotations

import os
import tempfile
from pathlib import Path


def expect_value_error(fn, reason: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert str(exc) == reason, (str(exc), reason)
    else:
        raise AssertionError(f"expected ValueError({reason!r})")


with tempfile.TemporaryDirectory(prefix="gc-war-01-") as tmp:
    db_path = Path(tmp) / "war01.db"
    os.environ["GC_DB_PATH"] = str(db_path)
    os.environ["GC_DB_BACKEND"] = "sqlite"
    os.environ["GC_SKIP_MIGRATION_CHECK"] = "1"
    os.environ["GC_EMBEDDED_CRON"] = "0"
    os.environ.setdefault("SECRET_KEY", "gc-war-01-verifier-secret-key-not-for-production")

    import game.db as gdb

    gdb._DB_PATH = None

    from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db

    init_db()
    import migrate

    migrate.main()

    from game.alliance import (
        create_alliance,
        get_alliance_relation,
        get_player_alliance,
        get_players_diplomacy_relation,
        join_alliance_by_tag,
        respond_diplomacy_request,
        send_diplomacy_request,
    )
    from game.db import db
    from game.fleet import resolve_fleet_target

    conn = db()

    def player(name: str) -> int:
        ok, err, user = create_user(name, "test-pass-123")
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        conn.commit()
        return uid

    leader_a = player("war01_a")
    leader_b = player("war01_b")
    create_alliance("W1A", "War One A", leader_a, conn=conn)
    create_alliance("W1B", "War One B", leader_b, conn=conn)
    conn.commit()
    aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
    aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
    conn.executemany(
        "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
        [(aid_a,), (aid_b,)],
    )
    conn.commit()

    # Peace outside war is illegal.
    expect_value_error(lambda: send_diplomacy_request(leader_a, "W1B", "peace", conn=conn), "peace_requires_war")

    # A pending pact must become stale when a newer war declaration wins.
    send_diplomacy_request(leader_a, "W1B", "nap", conn=conn)
    conn.commit()
    nap_id = int(
        conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='nap' AND status='pending' LIMIT 1;"
        ).fetchone()["id"]
    )
    send_diplomacy_request(leader_a, "W1B", "war", conn=conn)
    conn.commit()
    assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
    assert conn.execute(
        "SELECT status FROM alliance_diplomacy_requests WHERE id=?;", (nap_id,)
    ).fetchone()["status"] == "declined"
    expect_value_error(lambda: send_diplomacy_request(leader_a, "W1B", "nap", conn=conn), "war_active")
    expect_value_error(lambda: send_diplomacy_request(leader_a, "W1B", "alliance", conn=conn), "war_active")
    expect_value_error(lambda: send_diplomacy_request(leader_a, "W1B", "war", conn=conn), "already_at_war")

    # War is visible through the canonical fleet target resolver.
    home_b = get_homeworld(leader_b, conn=conn)
    target = resolve_fleet_target(
        leader_a,
        int(home_b["galaxy"]),
        int(home_b["system"]),
        int(home_b["position"]),
        conn=conn,
    )
    assert target.get("diplomacy_relation") == "war"
    assert "attack" in target.get("allowed_missions", [])

    # Member cannot offer peace.
    member = player("war01_member")
    join_alliance_by_tag(member, "W1A", conn=conn)
    conn.commit()
    expect_value_error(lambda: send_diplomacy_request(member, "W1B", "peace", conn=conn), "forbidden")

    # Peace offer exists exactly once bilaterally; member cannot accept it.
    send_diplomacy_request(leader_b, "W1A", "peace", conn=conn)
    conn.commit()
    peace_id = int(
        conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='peace' AND status='pending' LIMIT 1;"
        ).fetchone()["id"]
    )
    expect_value_error(
        lambda: respond_diplomacy_request(member, peace_id, accept=True, conn=conn),
        "forbidden",
    )
    expect_value_error(lambda: send_diplomacy_request(leader_a, "W1B", "peace", conn=conn), "duplicate_diplomacy_request")

    # Declining peace keeps war.
    respond_diplomacy_request(leader_a, peace_id, accept=False, conn=conn)
    conn.commit()
    assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"

    # A new peace offer can then be accepted and immediately returns to neutral.
    send_diplomacy_request(leader_a, "W1B", "peace", conn=conn)
    conn.commit()
    peace_id_2 = int(
        conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='peace' AND status='pending' LIMIT 1;"
        ).fetchone()["id"]
    )
    respond_diplomacy_request(leader_b, peace_id_2, accept=True, conn=conn)
    conn.commit()
    assert get_alliance_relation(aid_a, aid_b, conn=conn) == "neutral"
    assert get_players_diplomacy_relation(leader_a, leader_b, conn=conn) == "neutral"
    target_after = resolve_fleet_target(
        leader_a,
        int(home_b["galaxy"]),
        int(home_b["system"]),
        int(home_b["position"]),
        conn=conn,
    )
    assert target_after.get("diplomacy_relation") == "neutral"
    assert "attack" in target_after.get("allowed_missions", [])

    # UI contract: peace uses the existing generic diplomacy action, no parallel JS path.
    template = Path("templates/alliance.html").read_text(encoding="utf-8")
    assert "d.relation == 'war' and st.can_manage" in template
    assert 'name="request_type" value="peace"' in template
    assert 'data-alliance-submit="diplomacy"' in template
    assert 'T("alliance_dip_offer_peace"' in template

    conn.close()

print("GC-AL-WAR-01 focused lifecycle verification passed")
