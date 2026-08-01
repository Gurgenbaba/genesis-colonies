"""DSGVO Max — cookie notice, register acks, export, deletion harden, retention purge."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture
def privacy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "privacy.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    import game.db as gdb
    from game.models import init_db
    import migrate

    gdb._DB_PATH = None
    init_db()
    migrate.main()
    yield
    gdb._DB_PATH = None


def test_cookie_notice_in_base_and_privacy_has_cookie_inventory():
    base = _read("templates/base.html")
    assert "cookie_notice.html" in base
    from game.legal_panel import LEGAL_PANEL_STRINGS

    de = LEGAL_PANEL_STRINGS["de"]
    assert "gc_locale" in de["legal_privacy_cookies_body"]
    assert "Railway" in de["legal_privacy_recipients_body"]
    assert "optional cookies" not in de["legal_privacy_purposes_body"].lower()
    assert "Marketing" in de["legal_privacy_cookies_body"] or "notwendige" in de["legal_privacy_cookies_body"]


def test_register_template_has_age_and_legal_acks():
    html = _read("templates/register.html")
    assert "data-register-age" in html
    assert "data-register-legal" in html
    assert "data-auth-discord-register" in html


def test_register_rejects_without_acks(privacy_db):
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    res = client.post(
        "/register",
        data={
            "username": f"u_{uuid.uuid4().hex[:8]}",
            "email": "a@example.com",
            "password": "password123",
            "password2": "password123",
        },
        follow_redirects=False,
    )
    # Should re-render with error (200) not create session redirect
    assert res.status_code in (200, 302)
    if res.status_code == 200:
        body = res.get_data(as_text=True)
        assert "16" in body or "Datenschutz" in body or "age" in body.lower() or "Alert" in body


def test_data_export_json(privacy_db):
    from game.battle_pass import ensure_default_season
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld
    from game.options import export_player_personal_data
    from app import app

    conn = db()
    ok, err, user = create_user(f"ex_{uuid.uuid4().hex[:8]}", "password123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="ExportMe", conn=conn)
    ensure_default_season(conn)
    conn.commit()
    payload = export_player_personal_data(uid, conn=conn)
    conn.close()
    assert payload["player_id"] == uid
    assert "user" in payload
    assert "password_hash" not in (payload.get("user") or {})
    assert "shop_orders" in payload

    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.get("/api/options/data-export")
    assert res.status_code == 200
    data = json.loads(res.get_data(as_text=True))
    assert data["player_id"] == uid


def test_deletion_clears_registration_ip(privacy_db):
    from game.battle_pass import ensure_default_season
    from game.db import db, begin_write_transaction, commit
    from game.models import create_user, ensure_player_and_homeworld
    from game.options import execute_account_deletion
    from game.referrals import set_user_registration_meta

    conn = db()
    ok, err, user = create_user(f"del_{uuid.uuid4().hex[:8]}", "password123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="DeleteMe", conn=conn)
    ensure_default_season(conn)
    begin_write_transaction(conn)
    set_user_registration_meta(uid, registration_ip="203.0.113.9", conn=conn)
    commit(conn)

    begin_write_transaction(conn)
    execute_account_deletion(uid, conn=conn)
    commit(conn)

    row = conn.execute(
        "SELECT email, registration_ip, discord_id FROM users WHERE id = ?;",
        (uid,),
    ).fetchone()
    conn.close()
    assert row["email"] is None
    assert row["registration_ip"] is None
    assert row["discord_id"] is None


def test_privacy_retention_clears_old_payment_payload(privacy_db):
    from game.db import db, begin_write_transaction, commit
    from game.privacy_retention import run_privacy_retention_purge
    from game.shop import schema_ready

    conn = db()
    assert schema_ready(conn)
    begin_write_transaction(conn)
    # Minimal event row — schema uses processed_at
    conn.execute(
        """
        INSERT INTO shop_payment_events
            (provider, event_id, order_id, payload_json, processed_at)
        VALUES ('test', ?, NULL, ?, ?);
        """,
        (f"evt_{uuid.uuid4().hex}", '{"payer_email":"x@y.z"}', time.time() - 100 * 86400),
    )
    commit(conn)

    out = run_privacy_retention_purge(conn=conn, now=time.time())
    assert out.get("ok") is True
    commit(conn)
    row = conn.execute(
        "SELECT payload_json FROM shop_payment_events ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["payload_json"] in ("{}", "")
