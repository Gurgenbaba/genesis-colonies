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
    monkeypatch.setenv("GC_NETWORK_DOMAIN", "genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://dev.genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")
    monkeypatch.setenv("GC_NETWORK_START_RESOURCE_MULTIPLIER", "10")
    monkeypatch.setenv("GC_NETWORK_START_TIMEKEEPER_SECONDS", str(72 * 3600))
    import game.network_auth as network_auth

    return importlib.reload(network_auth)



def test_universe_registry_derives_future_subdomains(monkeypatch):
    monkeypatch.setenv("GC_UNIVERSE_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://dev.genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_DOMAIN", "genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1,uni2")
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", "1")
    monkeypatch.setenv("GC_NETWORK_UNI2_OPEN", "0")

    import game.network_auth as network_auth
    network_auth = importlib.reload(network_auth)

    assert network_auth.universe_url("dev") == "https://dev.genesis-colonies.com"
    assert network_auth.universe_url("uni1") == "https://uni1.genesis-colonies.com"
    assert network_auth.universe_url("uni2") == "https://uni2.genesis-colonies.com"
    assert [item["key"] for item in network_auth.universe_directory()] == ["dev", "uni1", "uni2"]
    assert network_auth.universe_directory()[-1]["open"] is False


def test_signed_handoff_round_trip_and_replay_guard(network_db, monkeypatch):
    network_db("authority")
    network_auth = _reload_network(monkeypatch, "dev")
    ok, reason, user = create_user("NetworkPilot", "test-pass-123")
    assert ok, reason

    ok, reason, token = network_auth.issue_handoff(int(user["id"]), "uni1")
    assert ok, reason
    assert token
    ok_again, reason_again, token_again = network_auth.issue_handoff(int(user["id"]), "uni1")
    assert ok_again, reason_again
    assert token_again
    valid_a, _, payload_a = network_auth._decode_token(token, expected_audience="uni1")
    valid_b, _, payload_b = network_auth._decode_token(token_again, expected_audience="uni1")
    assert valid_a and valid_b
    assert payload_a["sub"] == payload_b["sub"]
    assert str(payload_a["sub"]).startswith("acct_")

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
        assert str(link["network_account_id"]).startswith("acct_")
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


def test_non_authority_login_self_redirect_fails_closed(network_db, monkeypatch):
    network_db("uni1")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://www.genesis-colonies.de")
    network_auth = _reload_network(monkeypatch, "uni1")

    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test-secret-key-not-default-value-32chars"
    network_auth.install_network_auth(app)

    @app.route("/login")
    def login():
        return "login-form", 200

    client = app.test_client()
    response = client.get(
        "/login",
        base_url="https://www.genesis-colonies.de",
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert b"configuration error" in response.data.lower()
    assert response.headers["Cache-Control"] == "no-store"


def test_non_authority_login_redirects_to_distinct_authority_host(network_db, monkeypatch):
    network_db("uni1")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://auth.example.test")
    network_auth = _reload_network(monkeypatch, "uni1")

    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "test-secret-key-not-default-value-32chars"
    network_auth.install_network_auth(app)

    @app.route("/login")
    def login():
        return "login-form", 200

    client = app.test_client()
    response = client.get(
        "/login",
        base_url="https://uni1.example.test",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://auth.example.test/login?network_target=uni1"
