"""GC-MANDO-RELAY-002 — shipless empire relay + per-planet cooldown contract."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from game.db import begin_write_transaction, commit, db, rollback
from game.empire_relay import (
    RELAY_COOLDOWN_SECONDS,
    _equal_allocations,
    collect_empire_resources,
    distribute_empire_resources,
)
from game.models import create_user
from tests.test_fleet_logistics import _hub_and_sources, _player, logistics_db

ROOT = Path(__file__).resolve().parents[1]


def _set_stock(conn, planet_id: int, *, metal: int, crystal: int, fuel_cells: int, now: int) -> None:
    conn.execute(
        """
        UPDATE planets
        SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ?
        WHERE id = ?;
        """,
        (metal, crystal, fuel_cells, float(now), int(planet_id)),
    )


def _stock(conn, planet_id: int) -> dict[str, int]:
    row = conn.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    return {
        "metal": int(row["metal"] or 0),
        "crystal": int(row["crystal"] or 0),
        "fuel_cells": int(row["fuel_cells"] or 0),
    }


def _fleet_rows(conn, player_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id = ?;",
        (int(player_id),),
    ).fetchone()
    return int(row["c"])


def _cooldown(conn, player_id: int, planet_id: int, direction: str) -> int:
    row = conn.execute(
        """
        SELECT ready_at
        FROM empire_resource_relay_cooldowns
        WHERE player_id = ? AND planet_id = ? AND direction = ?;
        """,
        (int(player_id), int(planet_id), str(direction)),
    ).fetchone()
    return int(row["ready_at"] or 0) if row else 0


def _seed_cooldown(conn, player_id: int, planet_id: int, direction: str, ready_at: int) -> None:
    conn.execute(
        """
        INSERT INTO empire_resource_relay_cooldowns
            (player_id, planet_id, direction, ready_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player_id, planet_id, direction) DO UPDATE SET
            ready_at = excluded.ready_at,
            updated_at = excluded.updated_at;
        """,
        (int(player_id), int(planet_id), str(direction), int(ready_at), int(ready_at) - 1),
    )


def test_collect_all_ready_sources_in_one_click_and_cooldown_each(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    now = 1_800_000_000
    _set_stock(conn, hub, metal=100, crystal=200, fuel_cells=300, now=now)
    for idx, source in enumerate(sources, start=1):
        _set_stock(
            conn,
            source,
            metal=1_000 * idx,
            crystal=2_000 * idx,
            fuel_cells=3_000 * idx,
            now=now,
        )
    conn.commit()
    fleet_before = _fleet_rows(conn, uid)

    begin_write_transaction(conn)
    ok, reason, payload = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert payload["processed_count"] == 3
    assert payload["processed_planet_ids"] == sources
    assert payload["uses_ships"] is False
    assert payload["uses_fleet_slots"] is False
    assert payload["hub_resources"]["metal"] == str(100 + 6_000)
    assert all(
        isinstance(value, str)
        for stock in payload["colony_resources"].values()
        for value in stock.values()
    )
    assert _stock(conn, hub) == {
        "metal": 100 + 6_000,
        "crystal": 200 + 12_000,
        "fuel_cells": 300 + 18_000,
    }
    for source in sources:
        assert _stock(conn, source) == {"metal": 0, "crystal": 0, "fuel_cells": 0}
        assert _cooldown(conn, uid, source, "collect") == now + RELAY_COOLDOWN_SECONDS
    assert _fleet_rows(conn, uid) == fleet_before
    conn.close()


def test_collect_skips_one_source_on_cooldown_but_harvests_the_others(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    now = 1_800_000_000
    _set_stock(conn, hub, metal=0, crystal=0, fuel_cells=0, now=now)
    for source in sources:
        _set_stock(conn, source, metal=1_000, crystal=0, fuel_cells=0, now=now)
    blocked = sources[1]
    _seed_cooldown(conn, uid, blocked, "collect", now + 900)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, payload = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert payload["processed_count"] == 2
    assert blocked not in payload["processed_planet_ids"]
    assert any(
        item["planet_id"] == blocked
        and item["reason"] == "relay_cooldown"
        and item["retry_after_sec"] == 900
        for item in payload["skipped"]
    )
    assert _stock(conn, hub)["metal"] == 2_000
    assert _stock(conn, blocked)["metal"] == 1_000
    assert str(blocked) not in payload["colony_resources"]
    conn.close()


def test_collect_second_immediate_click_is_all_cooldown(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    now = 1_800_000_000
    _set_stock(conn, hub, metal=0, crystal=0, fuel_cells=0, now=now)
    for source in sources:
        _set_stock(conn, source, metal=500, crystal=0, fuel_cells=0, now=now)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    for source in sources:
        _set_stock(conn, source, metal=999, crystal=0, fuel_cells=0, now=now)
    conn.commit()

    begin_write_transaction(conn)
    ok2, reason2, payload2 = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
        now=now + 1,
    )
    assert not ok2
    assert reason2 == "relay_cooldown"
    assert payload2["retry_after_sec"] == RELAY_COOLDOWN_SECONDS - 1
    rollback(conn)
    conn.close()


def test_distribute_all_targets_in_one_click_and_cooldown_each(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    now = 1_800_000_000
    _set_stock(conn, hub, metal=9_000, crystal=6_000, fuel_cells=3_000, now=now)
    for target in targets:
        _set_stock(conn, target, metal=0, crystal=0, fuel_cells=0, now=now)
    conn.commit()
    fleet_before = _fleet_rows(conn, uid)

    begin_write_transaction(conn)
    ok, reason, payload = distribute_empire_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        resources={"metal": "9000", "crystal": "6000", "fuel_cells": "3000"},
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert payload["processed_count"] == 3
    assert payload["debited"] == {"metal": 9_000, "crystal": 6_000, "fuel_cells": 3_000}
    assert _stock(conn, hub) == {"metal": 0, "crystal": 0, "fuel_cells": 0}
    for target in targets:
        assert _stock(conn, target) == {"metal": 3_000, "crystal": 2_000, "fuel_cells": 1_000}
        assert _cooldown(conn, uid, target, "distribute") == now + RELAY_COOLDOWN_SECONDS
    assert _fleet_rows(conn, uid) == fleet_before
    conn.close()


def test_distribute_skips_cooldown_target_and_does_not_debit_its_share(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    now = 1_800_000_000
    _set_stock(conn, hub, metal=900, crystal=0, fuel_cells=0, now=now)
    for target in targets:
        _set_stock(conn, target, metal=0, crystal=0, fuel_cells=0, now=now)
    blocked = targets[1]
    _seed_cooldown(conn, uid, blocked, "distribute", now + 600)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, payload = distribute_empire_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        resources={"metal": 900},
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert payload["debited"]["metal"] == 600
    assert _stock(conn, hub)["metal"] == 300
    assert _stock(conn, blocked)["metal"] == 0
    for target in (targets[0], targets[2]):
        assert _stock(conn, target)["metal"] == 300
    assert any(
        item["planet_id"] == blocked and item["reason"] == "relay_cooldown"
        for item in payload["skipped"]
    )
    assert str(blocked) not in payload["colony_resources"]
    conn.close()


def test_collect_cooldown_does_not_block_same_planet_as_distribute_target(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    now = 1_800_000_000
    _set_stock(conn, hub, metal=10_000, crystal=0, fuel_cells=0, now=now)
    _set_stock(conn, source, metal=1_000, crystal=0, fuel_cells=0, now=now)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[source],
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert _cooldown(conn, uid, source, "collect") == now + RELAY_COOLDOWN_SECONDS
    assert _cooldown(conn, uid, source, "distribute") == 0

    begin_write_transaction(conn)
    ok2, reason2, payload2 = distribute_empire_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=[source],
        resources={"metal": 500},
        conn=conn,
        now=now + 1,
    )
    assert ok2, reason2
    commit(conn)

    assert payload2["processed_planet_ids"] == [source]
    assert _stock(conn, source)["metal"] == 500
    assert _cooldown(conn, uid, source, "distribute") == now + 1 + RELAY_COOLDOWN_SECONDS
    conn.close()


def test_collect_rejects_foreign_planet_before_any_transfer(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    now = 1_800_000_000
    _set_stock(conn, sources[0], metal=777, crystal=0, fuel_cells=0, now=now)
    conn.commit()

    ok_other, err_other, other_user = create_user("relay-other", "secret123")
    assert ok_other, err_other
    other_uid = int(other_user["id"])
    foreign = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? ORDER BY id ASC LIMIT 1;",
        (int(other_uid),),
    ).fetchone()
    foreign_id = int(foreign["id"])
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, payload = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[sources[0], foreign_id],
        conn=conn,
        now=now,
    )
    assert not ok
    assert reason == "foreign_planet"
    assert foreign_id in payload["planet_ids"]
    rollback(conn)
    assert _stock(conn, sources[0])["metal"] == 777
    conn.close()


def test_equal_distribution_math_is_arbitrary_precision():
    huge = 10**100 + 7
    allocations = _equal_allocations({"metal": huge, "crystal": 0, "fuel_cells": 0}, [9, 4, 7])
    assert sum(row["metal"] for row in allocations.values()) == huge
    values = sorted(row["metal"] for row in allocations.values())
    assert values[-1] - values[0] <= 1


def test_relay_api_idempotency_and_state_endpoint(logistics_db):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    now = int(time.time())
    _set_stock(conn, hub, metal=100, crystal=0, fuel_cells=0, now=now)
    _set_stock(conn, sources[0], metal=900, crystal=0, fuel_cells=0, now=now)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    rid = str(uuid.uuid4())
    body = {
        "target_planet_id": hub,
        "source_planet_ids": sources,
        "request_id": rid,
    }
    first = client.post("/api/logistics/relay/collect", json=body)
    assert first.status_code == 200
    first_json = first.get_json()
    assert first_json["ok"] is True
    assert first_json["data"]["uses_ships"] is False

    second = client.post("/api/logistics/relay/collect", json=body)
    assert second.status_code == 200
    assert second.get_json() == first_json

    state = client.get("/api/logistics/relay/state")
    assert state.status_code == 200
    state_json = state.get_json()
    assert state_json["ok"] is True
    assert state_json["data"]["cooldown_seconds"] == RELAY_COOLDOWN_SECONDS
    assert str(sources[0]) in state_json["data"]["collect"]

    conn = db()
    assert _stock(conn, hub)["metal"] == 1_000
    assert _stock(conn, sources[0])["metal"] == 0
    assert _fleet_rows(conn, uid) == 0
    conn.close()


def test_relay_ui_owns_collect_and_distribute_without_fleet_submit():
    template = (ROOT / "templates" / "partials" / "fleet_logistics_body.html").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "empire_resource_relay.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "empire_resource_relay.css").read_text(encoding="utf-8")

    assert 'data-resource-relay-submit="collect"' in template
    assert 'data-resource-relay-submit="distribute"' in template
    assert 'data-logistics-submit="collect"' not in template
    assert 'data-logistics-submit="distribute"' not in template
    assert 'data-resource-relay-cooldown="collect"' in template
    assert 'data-resource-relay-cooldown="distribute"' in template
    assert "/api/logistics/relay/state" in script
    assert "/api/logistics/relay/" in script
    assert "GC.fetchGameAction" in script
    assert "fetch(" not in script
    assert "setInterval" in script
    assert "data-logistics-select-all" in script
    assert "page._logisticsLivePending = true;" in script
    assert "function setRelayMode(page, direction)" in script
    assert 'closest?.("[data-logistics-tab]")' in script
    assert "/api/fleet/logistics/preview" not in script
    assert "js/empire_resource_relay.js" in base
    assert "css/empire_resource_relay.css" in base
    assert "logistics-relay-cooldown.is-cooldown" in css


def test_shell_loads_relay_assets_for_full_load_and_pjax():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    standalone = (ROOT / "templates" / "logistics.html").read_text(encoding="utf-8")
    fleet = (ROOT / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert "css/empire_resource_relay.css" in base
    assert "js/empire_resource_relay.js" in base
    assert "css/empire_resource_relay.css" not in standalone
    assert "js/empire_resource_relay.js" not in standalone
    assert "css/empire_resource_relay.css" not in fleet
    assert "js/empire_resource_relay.js" not in fleet
    assert "[data-resource-relay-submit]" in standalone


def test_shell_loaded_relay_sleeps_when_logistics_is_unmounted():
    script = (ROOT / "static" / "js" / "empire_resource_relay.js").read_text(encoding="utf-8")
    assert "function stopTicker()" in script
    assert "function ensureTicker()" in script
    assert "function syncMountedPage()" in script
    assert "stopTicker();" in script
    assert "syncMountedPage();" in script
    assert "state.timer = window.setInterval" in script
    ensure = script.split("function ensureTicker()", 1)[1].split("function syncMountedPage()", 1)[0]
    assert "state.timer = window.setInterval" in ensure
    tail = script.split("const shell = document.getElementById", 1)[1]
    assert "syncMountedPage();" in tail
    assert "state.timer = window.setInterval" not in tail


def test_relay_mount_observer_ignores_internal_dom_mutations():
    script = (ROOT / "static" / "js" / "empire_resource_relay.js").read_text(encoding="utf-8")
    assert "const observer = new MutationObserver(syncMountedPage);" in script
    assert "observer.observe(shell, { childList: true });" in script
    assert "observer.observe(shell, { childList: true, subtree: true });" not in script
    assert "state.timer = window.setInterval" in script


def test_relay_client_blocks_legacy_preview_handlers_for_owned_controls():
    script = (ROOT / "static" / "js" / "empire_resource_relay.js").read_text(encoding="utf-8")
    assert 'event.stopImmediatePropagation()' in script
    assert '"submit",' in script
    assert "#logistics-collect-form" in script
    assert "#logistics-distribute-form" in script
    assert '"change",' in script
    assert '"input",' in script
    assert "function syncSelectionPresentation(page)" in script
    assert 'classList.toggle("is-selected"' in script
    assert 'classList.remove("is-slots-skipped")' in script
    assert "true\n  );" in script
