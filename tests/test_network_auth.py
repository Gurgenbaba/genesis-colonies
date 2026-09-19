from __future__ import annotations

import importlib
import time

import pytest

from game.db import db
from game.models import create_user, init_db


@pytest.fixture
def network_db(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "network-test-secret-" + ("x" * 48))
    import game.db as gdb
    import migrate

    initialized: set[str] = set()

    def activate(name: str):
        db_path = tmp_path / f"{name}.db"
        monkeypatch.setenv("GC_DB_PATH", str(db_path))
        gdb._DB_PATH = None
        if name not in initialized:
            init_db()
            migrate.main()
            initialized.add(name)
            gdb._DB_PATH = None
        return db_path

    yield activate
    gdb._DB_PATH = None


def _reload_network(monkeypatch, universe: str):
    monkeypatch.setenv("GC_UNIVERSE_KEY", universe)
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")
    monkeypatch.setenv("GC_NETWORK_START_RESOURCE_MULTIPLIER", "10")
    monkeypatch.setenv("GC_NETWORK_START_TIMEKEEPER_SECONDS", str(72 * 3600))
    import game.network_auth as network_auth

    return importlib.reload(network_auth)


def test_signed_handoff_round_trip_and_replay_guard(network_db, monkeypatch):
    network_db("authority")
    network_auth = _reload_network(monkeypatch, "dev")
    ok, reason, user = create_user("NetworkPilot", "test-pass-123")
    assert ok, reason

    ok, reason, token = network_auth.issue_handoff(int(user["id"]), "uni1")
    assert ok, reason
    assert token

    network_db("uni1")
    network_auth = _reload_network(monkeypatch, "uni1")
    ok, reason, local = network_auth.consume_handoff(token)
    assert ok, reason
    assert local
    assert local["username"] == "NetworkPilot"
    assert local["created"] is True
    assert int(local["id"]) != 0

    ok2, reason2, local2 = network_auth.consume_handoff(token)
    assert ok2 is False
    assert reason2 == "replayed"
    assert local2 is None


def test_first_uni1_entry_gets_10x_resources_and_72h_timekeeper(network_db, monkeypatch):
    network_db("authority")
    network_auth = _reload_network(monkeypatch, "dev")
    ok, reason, user = create_user("FreshUniPilot", "test-pass-123")
    assert ok, reason
    ok, reason, token = network_auth.issue_handoff(int(user["id"]), "uni1")
    assert ok, reason

    network_db("uni1")
    network_auth = _reload_network(monkeypatch, "uni1")
    ok, reason, local = network_auth.consume_handoff(token)
    assert ok, reason
    uid = int(local["id"])

    conn = db()
    try:
        planet = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
            (uid,),
        ).fetchone()
        assert int(planet["metal"]) == 1_500_000
        assert int(planet["crystal"]) == 1_000_000
        assert int(planet["fuel_cells"]) == 250_000

        from game.timekeeper import get_balance

        assert get_balance(uid, conn=conn) == 72 * 3600
        link = conn.execute(
            "SELECT network_account_id FROM network_account_links WHERE local_user_id = ?;",
            (uid,),
        ).fetchone()
        assert str(link["network_account_id"]).startswith("dev:")
    finally:
        conn.close()


def test_wrong_audience_is_rejected(network_db, monkeypatch):
    network_db("authority")
    network_auth = _reload_network(monkeypatch, "dev")
    ok, reason, user = create_user("AudiencePilot", "test-pass-123")
    assert ok, reason
    ok, reason, token = network_auth.issue_handoff(int(user["id"]), "uni1")
    assert ok, reason

    valid, reject_reason, payload = network_auth._decode_token(token, expected_audience="dev")
    assert valid is False
    assert reject_reason == "invalid_audience"
    assert payload is None
