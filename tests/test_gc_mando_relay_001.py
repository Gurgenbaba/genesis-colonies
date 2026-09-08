"""GC-MANDO-RELAY-001 — shipless own-empire resource consolidation."""

from __future__ import annotations

import time
import uuid

from game.db import begin_write_transaction, commit, db, rollback
from game.empire_relay import collect_empire_resources
from game.models import create_user, ensure_player_and_homeworld
from tests.test_fleet_logistics import _hub_and_sources, _player, logistics_db


def _set_stock(conn, planet_id: int, *, metal: int, crystal: int, fuel_cells: int) -> None:
    conn.execute(
        """
        UPDATE planets
        SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ?
        WHERE id = ?;
        """,
        (metal, crystal, fuel_cells, time.time(), int(planet_id)),
    )


def _active_fleet_count(conn, player_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id = ?;",
        (int(player_id),),
    ).fetchone()
    return int(row["c"])


def test_relay_moves_huge_stock_without_ships_or_fleet_rows(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    huge = 3_000_000_000_000_000
    _set_stock(conn, hub, metal=10, crystal=20, fuel_cells=30)
    for source in sources:
        _set_stock(conn, source, metal=huge, crystal=123_456_789, fuel_cells=987_654_321)
    conn.commit()

    fleet_before = _active_fleet_count(conn, uid)
    begin_write_transaction(conn)
    ok, reason, payload = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
    )
    assert ok, reason
    commit(conn)

    assert payload["uses_ships"] is False
    assert payload["uses_fleet_slots"] is False
    assert payload["source_count"] == 2
    assert int(payload["moved"]["metal"]) == huge * 2
    assert int(payload["hub_resources"]["metal"]) == huge * 2 + 10
    assert _active_fleet_count(conn, uid) == fleet_before

    for source in sources:
        row = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (int(source),),
        ).fetchone()
        assert int(row["metal"]) == 0
        assert int(row["crystal"]) == 0
        assert int(row["fuel_cells"]) == 0
    conn.close()


def test_relay_rejects_foreign_source_before_transfer(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)

    other_uid = create_user("relay-other", "secret123")
    ensure_player_and_homeworld(player_id=other_uid, player_name="relay-other", conn=conn)
    foreign = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? ORDER BY id LIMIT 1;",
        (int(other_uid),),
    ).fetchone()
    foreign_id = int(foreign["id"])
    _set_stock(conn, sources[0], metal=5000, crystal=1000, fuel_cells=500)
    conn.commit()

    before = conn.execute("SELECT metal FROM planets WHERE id = ?;", (sources[0],)).fetchone()["metal"]
    begin_write_transaction(conn)
    ok, reason, payload = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[sources[0], foreign_id],
        conn=conn,
    )
    assert not ok
    assert reason == "foreign_planet"
    assert foreign_id in payload["planet_ids"]
    rollback(conn)

    after = conn.execute("SELECT metal FROM planets WHERE id = ?;", (sources[0],)).fetchone()["metal"]
    assert int(after) == int(before)
    conn.close()


def test_relay_api_is_idempotent_and_needs_no_ship_payload(logistics_db):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _set_stock(conn, hub, metal=100, crystal=200, fuel_cells=300)
    _set_stock(conn, sources[0], metal=9000, crystal=8000, fuel_cells=7000)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    request_id = str(uuid.uuid4())
    body = {
        "target_planet_id": hub,
        "source_planet_ids": sources,
        "request_id": request_id,
    }
    first = client.post("/api/logistics/relay/collect", json=body)
    assert first.status_code == 200
    first_json = first.get_json()
    assert first_json["ok"] is True
    assert first_json["data"]["uses_ships"] is False
    assert first_json["data"]["uses_fleet_slots"] is False
    assert int(first_json["data"]["moved"]["metal"]) == 9000

    second = client.post("/api/logistics/relay/collect", json=body)
    assert second.status_code == 200
    assert second.get_json() == first_json

    conn = db()
    hub_row = conn.execute("SELECT metal FROM planets WHERE id = ?;", (hub,)).fetchone()
    source_row = conn.execute("SELECT metal FROM planets WHERE id = ?;", (sources[0],)).fetchone()
    assert int(hub_row["metal"]) == 9100
    assert int(source_row["metal"]) == 0
    assert _active_fleet_count(conn, uid) == 0
    conn.close()


def test_relay_ui_uses_canonical_action_fetch_and_no_collect_fleet_submit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "partials" / "fleet_logistics_body.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "empire_resource_relay.js").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "empire_resource_relay.css").read_text(encoding="utf-8")
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")

    assert 'data-resource-relay-submit="collect"' in template
    assert 'data-logistics-submit="collect"' not in template
    assert "GC.fetchGameAction" in script
    assert '"/api/logistics/relay/collect"' in script
    assert "GC.refreshGameState" in script
    assert "fetch(" not in script
    assert 'data-logistics-mode="collect"' in css
    assert "js/empire_resource_relay.js" in base
