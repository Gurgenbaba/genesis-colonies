"""Pirate base destroy rewards: every contributor gets a damage-proportional share.

_grant_destroy_rewards() read an undefined ``share`` (NameError) for every contributor
once a base was destroyed.
"""
from __future__ import annotations

from tests.test_pirate_ecosystem import pirate_db  # noqa: F401  (fixture)


def _player(name: str) -> int:
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld

    ok, err, user = create_user(name, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return uid


def _resources(uid: int) -> tuple[float, float]:
    from game.db import db
    from game.models import get_planets_by_player

    conn = db()
    try:
        home = dict(get_planets_by_player(uid, conn=conn)[0])
        return float(home["metal"]), float(home["crystal"])
    finally:
        conn.close()


def test_destroy_rewards_split_by_damage_share(pirate_db):  # noqa: F811
    from game.db import db
    from game.pirates import record_heat_event, set_pirates_ai_enabled
    from game.pirates.bases import _grant_destroy_rewards, get_base_by_id, spawn_pirate_base

    big = _player("pirate_big")
    small = _player("pirate_small")
    before = {big: _resources(big), small: _resources(small)}

    conn = db()
    try:
        set_pirates_ai_enabled(True, conn=conn)
        record_heat_event(conn, 1, "combat", amount=200)
        res = spawn_pirate_base(conn, galaxy=1, faction_key="crimson_corsairs", announce=False)
        assert res["ok"] is True
        base_id = int(res["base"]["base_id"])
        for pid, damage in ((big, 750), (small, 250)):
            conn.execute(
                """
                INSERT INTO pirate_base_contributions
                    (base_id, player_id, damage, waves, created_at, updated_at)
                VALUES (?, ?, ?, 1, 1.0, 1.0);
                """,
                (base_id, pid, damage),
            )
        conn.commit()
        base = get_base_by_id(base_id, conn=conn)
        _grant_destroy_rewards(conn, base, now=100.0)  # must not raise NameError
        conn.commit()
        claims = conn.execute(
            "SELECT COUNT(*) AS n FROM pirate_base_claims WHERE base_id = ?;", (base_id,)
        ).fetchone()
        assert int(claims["n"]) == 2
    finally:
        conn.close()

    gain = {pid: tuple(a - b for a, b in zip(_resources(pid), before[pid])) for pid in (big, small)}
    assert gain[big][0] > 0 and gain[small][0] > 0
    # 75% vs 25% of the same pool
    assert abs(gain[big][0] / gain[small][0] - 3.0) < 0.05
    assert abs(gain[big][1] / gain[small][1] - 3.0) < 0.05

    # a second call is idempotent (claim marker) and still does not raise
    conn = db()
    try:
        _grant_destroy_rewards(conn, get_base_by_id(base_id, conn=conn), now=101.0)
        conn.commit()
    finally:
        conn.close()
    assert _resources(big) == (before[big][0] + gain[big][0], before[big][1] + gain[big][1])
