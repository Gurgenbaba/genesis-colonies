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
from game.messages import dispatch_combat_reports, normalize_combat_metadata
from game.models import create_user
from game.chronicles import (
    CHRONICLES_SECTION_PVP,
    PVP_TAB_ATTACKS,
    PVP_TAB_DEFENSES,
    PVP_TAB_LOSSES,
    PVP_TAB_WINS,
    build_chronicles_api_payload,
    build_pvp_stats,
    list_pvp_battles,
)


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
