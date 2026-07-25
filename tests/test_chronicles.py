"""GC-700C — Chronicles hub (PvP section) tests."""

from __future__ import annotations

import importlib
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.combat import build_combat_report
from game.combat_models import CombatResult, CombatRound
from game.db import db
from game.messages import dispatch_combat_reports, normalize_combat_metadata, delete_message, list_messages
from game.models import create_user
from game.chronicles import (
    CHRONICLES_SECTION_EXPEDITIONS,
    CHRONICLES_SECTION_PVP,
    CHRONICLES_SECTION_RECORDS,
    EXPEDITION_TAB_LOOT,
    EXPEDITION_TAB_PIRATES,
    PVP_TAB_ATTACKS,
    PVP_TAB_DEFENSES,
    PVP_TAB_LOSSES,
    PVP_TAB_WINS,
    build_chronicles_api_payload,
    build_expedition_stats,
    build_pvp_stats,
    list_expedition_events,
    list_pvp_battles,
)
from game.expedition_events import EXPEDITION_REPORT_VERSION
from game.messages import notify_expedition


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "chronicles_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player(prefix: str) -> tuple[int, str]:
    uname = f"{prefix}_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    return int(user["id"]), uname


def _seed_combat_reports(attacker_id: int, defender_id: int, *, winner: str = "attacker") -> None:
    combat_result = CombatResult(
        winner=winner,
        rounds=(
            CombatRound(1, {}, {"sentinel_turret": 2}),
            CombatRound(2, {"falcon_interceptor": 1}, {}),
        ),
        attacker_losses={"falcon_interceptor": 1},
        defender_losses={"sentinel_turret": 2},
    )
    body, meta = build_combat_report(
        attacker_id=attacker_id,
        attacker_name="Attacker",
        defender_id=defender_id,
        defender_name="Defender",
        coords="2:3:4",
        attacking_ships={"falcon_interceptor": 5},
        defending_ships={},
        defending_defense={"sentinel_turret": 4},
        combat_result=combat_result,
        return_ships={"falcon_interceptor": 4},
        origin_coords="1:2:3",
        origin_planet_name="Alpha",
        target_planet_name="Beta",
    )
    meta = normalize_combat_metadata(meta)
    sent = dispatch_combat_reports(
        attacker_id=attacker_id,
        defender_id=defender_id,
        coords="2:3:4",
        body=body,
        metadata=meta,
    )
    assert sent["attacker"]["ok"]
    assert sent["defender"]["ok"]


def _seed_expedition_report(
    player_id: int,
    *,
    event_key: str = "mineral_deposit",
    rewards: dict | None = None,
    losses_total: int = 0,
    salvaged_total: int = 0,
    story_tier: str = "",
) -> None:
    meta = {
        "report_version": EXPEDITION_REPORT_VERSION,
        "target_coords": "1:2:16",
        "event_key": event_key,
        "event_label_key": f"expedition_event_{event_key}",
        "event_desc_key": f"expedition_event_{event_key}_desc",
        "rewards": rewards if rewards is not None else {"metal": 8000, "crystal": 1200},
        "losses_total": int(losses_total),
        "salvaged_total": int(salvaged_total),
        "losses": {},
        "salvaged_ships": {},
        "lootboxes": [],
    }
    if story_tier:
        meta["story_tier"] = story_tier
    if event_key == "pirate_encounter":
        meta["pirate_combat"] = {"won": salvaged_total > 0, "loss_pct": 12}
    res = notify_expedition(
        int(player_id),
        f"Expedition {event_key}",
        "Test expedition body",
        metadata=meta,
    )
    assert res["ok"], res


def test_chronicles_pvp_stats_and_tabs(temp_db):
    attacker_id, _ = _create_player("chron_atk")
    defender_id, _ = _create_player("chron_def")
    _seed_combat_reports(attacker_id, defender_id, winner="attacker")

    conn = db()
    try:
        payload = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_PVP,
            tab=PVP_TAB_WINS,
            conn=conn,
        )
        atk_stats = build_pvp_stats(attacker_id, conn=conn)
        def_losses = list_pvp_battles(defender_id, tab=PVP_TAB_LOSSES, conn=conn)
        atk_attacks = list_pvp_battles(attacker_id, tab=PVP_TAB_ATTACKS, conn=conn)
        def_defenses = list_pvp_battles(defender_id, tab=PVP_TAB_DEFENSES, conn=conn)
    finally:
        conn.close()

    assert payload["ok"] is True
    assert payload["section"] == "pvp"
    assert payload["section_live"] is True
    assert payload["count"] == 1
    assert payload["battles"][0]["outcome"] == "victory"
    assert atk_stats["wins"] == 1
    assert len(def_losses) == 1
    assert len(atk_attacks) == 1
    assert len(def_defenses) == 1


def test_chronicles_page_and_legacy_pvp_redirect(temp_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uid, _ = _create_player("chron_page")
    defender_id, _ = _create_player("chron_page_def")
    _seed_combat_reports(uid, defender_id)

    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    resp = client.get("/chronicles?section=pvp")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "chronicles-page" in body
    assert "gc-chronicles-section-tabs" in body
    assert "gc-pvp-stats" in body
    assert "data-pvp-report" in body

    legacy = client.get("/pvp", follow_redirects=False)
    assert legacy.status_code == 302
    assert "section=pvp" in (legacy.headers.get("Location") or "")

    api = client.get("/api/chronicles?section=pvp&tab=wins")
    assert api.status_code == 200
    data = api.get_json()
    assert data["ok"] is True
    assert data["section"] == "pvp"
    assert data["count"] >= 1


def test_chronicles_expeditions_stats_and_tabs(temp_db):
    player_id, _ = _create_player("chron_expo")
    _seed_expedition_report(player_id, event_key="mineral_deposit")
    _seed_expedition_report(player_id, event_key="pirate_encounter", losses_total=3)
    _seed_expedition_report(
        player_id,
        event_key="ancient_beacon",
        rewards={"metal": 500, "crystal": 500},
        story_tier="legendary",
    )

    conn = db()
    try:
        payload = build_chronicles_api_payload(
            player_id=player_id,
            section=CHRONICLES_SECTION_EXPEDITIONS,
            tab=EXPEDITION_TAB_LOOT,
            conn=conn,
        )
        stats = build_expedition_stats(player_id, conn=conn)
        loot_events = list_expedition_events(player_id, tab=EXPEDITION_TAB_LOOT, conn=conn)
        pirate_events = list_expedition_events(player_id, tab=EXPEDITION_TAB_PIRATES, conn=conn)
    finally:
        conn.close()

    assert payload["ok"] is True
    assert payload["section"] == "expeditions"
    assert payload["section_live"] is True
    assert stats["total_expeditions"] == 3
    assert stats["pirate_contacts"] == 1
    assert stats["legendary_finds"] == 1
    assert len(loot_events) >= 2
    assert len(pirate_events) == 1


def test_chronicles_records_aggregation(temp_db):
    attacker_id, _ = _create_player("chron_rec_atk")
    defender_id, _ = _create_player("chron_rec_def")
    _seed_combat_reports(attacker_id, defender_id, winner="attacker")
    _seed_expedition_report(attacker_id, event_key="ancient_stash", rewards={"metal": 12000, "crystal": 4000})
    _seed_expedition_report(attacker_id, event_key="pirate_encounter", losses_total=4, salvaged_total=1)

    conn = db()
    try:
        payload = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_RECORDS,
            conn=conn,
        )
    finally:
        conn.close()

    assert payload["ok"] is True
    assert payload["section"] == "records"
    cards = payload["cards"]
    assert len(cards) == 8
    keys = {card["key"] for card in cards}
    assert "biggest_battle" in keys
    assert "biggest_expo_find" in keys
    assert "biggest_boss_hit" in keys
    assert "biggest_asteroid_haul" in keys
    assert cards[0]["has_record"] or any(c["has_record"] for c in cards)


def test_chronicles_expeditions_and_records_pages(temp_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uid, _ = _create_player("chron_sec")
    _seed_expedition_report(uid, event_key="mineral_deposit")
    _seed_combat_reports(uid, _create_player("chron_sec_def")[0])

    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    expo = client.get("/chronicles?section=expeditions")
    assert expo.status_code == 200
    expo_body = expo.get_data(as_text=True)
    assert "gc-chronicles-expo-stats" in expo_body
    assert "data-expedition-report" in expo_body

    records = client.get("/chronicles?section=records")
    assert records.status_code == 200
    records_body = records.get_data(as_text=True)
    assert "gc-chronicles-records-grid" in records_body
    assert "data-chronicles-report" in records_body

    api_expo = client.get("/api/chronicles?section=expeditions&tab=loot")
    assert api_expo.status_code == 200
    assert api_expo.get_json()["section"] == "expeditions"


def _count_chronicle_entries(player_id: int, entry_type: str) -> int:
    conn = db()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM chronicle_entries
            WHERE player_id = ? AND entry_type = ?;
            """,
            (int(player_id), str(entry_type)),
        ).fetchone()
        return int(row["c"] or 0)
    finally:
        conn.close()


def test_combat_report_creates_chronicle_entry(temp_db):
    attacker_id, _ = _create_player("chron_persist_atk")
    defender_id, _ = _create_player("chron_persist_def")
    _seed_combat_reports(attacker_id, defender_id)

    assert _count_chronicle_entries(attacker_id, "combat") == 1
    assert _count_chronicle_entries(defender_id, "combat") == 1


def test_delete_message_keeps_chronicle_entry(temp_db):
    attacker_id, _ = _create_player("chron_del_atk")
    defender_id, _ = _create_player("chron_del_def")
    _seed_combat_reports(attacker_id, defender_id)

    inbox = list_messages(attacker_id, category="combat")
    message_id = inbox["data"]["messages"][0]["id"]
    assert delete_message(attacker_id, message_id)["ok"]

    conn = db()
    try:
        remaining_inbox = conn.execute(
            """
            SELECT COUNT(*) AS c FROM player_messages
            WHERE recipient_player_id = ? AND category = 'combat'
              AND (deleted_at IS NULL OR deleted_at = 0);
            """,
            (attacker_id,),
        ).fetchone()
        assert int(remaining_inbox["c"] or 0) == 0

        payload = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_PVP,
            conn=conn,
        )
    finally:
        conn.close()

    assert _count_chronicle_entries(attacker_id, "combat") == 1
    assert payload["count"] == 1
    assert payload["battles"][0]["report_metadata"]["perspective"] == "attacker"


def test_chronicles_survive_message_cleanup(temp_db):
    attacker_id, _ = _create_player("chron_clean_atk")
    defender_id, _ = _create_player("chron_clean_def")
    _seed_combat_reports(attacker_id, defender_id)

    conn = db()
    try:
        now = int(__import__("time").time())
        conn.execute(
            "UPDATE player_messages SET deleted_at = ? WHERE recipient_player_id = ?;",
            (now, attacker_id),
        )
        conn.commit()

        payload = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_PVP,
            conn=conn,
        )
    finally:
        conn.close()

    assert _count_chronicle_entries(attacker_id, "combat") == 1
    assert payload["count"] == 1


def test_chronicle_entry_has_snapshot_without_message(temp_db):
    attacker_id, _ = _create_player("chron_snap_atk")
    defender_id, _ = _create_player("chron_snap_def")
    _seed_combat_reports(attacker_id, defender_id)

    conn = db()
    try:
        conn.execute("DELETE FROM player_messages;")
        conn.commit()

        row = conn.execute(
            """
            SELECT body_json FROM chronicle_entries
            WHERE player_id = ? AND entry_type = 'combat'
            LIMIT 1;
            """,
            (attacker_id,),
        ).fetchone()
        payload = build_chronicles_api_payload(
            player_id=attacker_id,
            section=CHRONICLES_SECTION_PVP,
            conn=conn,
        )
    finally:
        conn.close()

    assert row is not None
    assert payload["count"] == 1
    battle = payload["battles"][0]
    assert battle["report_metadata"]["attacker_name"] == "Attacker"
    assert battle["report_metadata"]["defender_losses"]["sentinel_turret"] == 2


def test_expedition_report_creates_chronicle_entry(temp_db):
    player_id, _ = _create_player("chron_expo_persist")
    _seed_expedition_report(player_id, event_key="mineral_deposit")

    assert _count_chronicle_entries(player_id, "expedition") == 1

    conn = db()
    try:
        payload = build_chronicles_api_payload(
            player_id=player_id,
            section=CHRONICLES_SECTION_EXPEDITIONS,
            conn=conn,
        )
    finally:
        conn.close()

    assert payload["count"] >= 1
    assert payload["events"][0]["event_key"] == "mineral_deposit"


def test_universe_reset_combat_domain_clears_chronicles_not_message_cleanup(temp_db):
    from game.admin_universe_reset import RESET_DOMAINS

    assert "chronicle_entries" in RESET_DOMAINS["combat"]
    assert "chronicle_entries" not in RESET_DOMAINS["messages"]
