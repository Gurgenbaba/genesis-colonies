"""GC-913 — Imperial Directives claim API and reward grants."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.directives.generator import STATUS_CLAIMED, STATUS_COMPLETED, ensure_player_directives
from game.directives.rewards import claim_all_directive_rewards, claim_directive_reward
from game.inventory import _inventory_amount
from game.models import create_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def id_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperial_directives_claim.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    yield db_file


@pytest.fixture()
def claim_client(id_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    uname = f"id_claim_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    player_id = int(user["id"])

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id
    return client, player_id


def _create_player(conn) -> int:
    ok, _reason, user = create_user(f"id_claim_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def _mark_first_daily_completed(conn, player_id: int, *, fixed_now: float | None = None) -> int:
    ts = float(fixed_now if fixed_now is not None else time.time())
    ensure_player_directives(player_id, conn=conn, now=ts)
    row = conn.execute(
        """
        SELECT id FROM player_directives
        WHERE player_id = ? AND cadence = 'daily'
        ORDER BY id ASC LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    assert row is not None
    directive_id = int(row["id"])
    conn.execute(
        """
        UPDATE player_directives
        SET progress_value = target_value, status = ?
        WHERE id = ? AND player_id = ?;
        """,
        (STATUS_COMPLETED, directive_id, int(player_id)),
    )
    conn.commit()
    return directive_id


def test_claim_directive_reward_grants_inventory(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        directive_id = _mark_first_daily_completed(conn, player_id)

        ok, reason, result = claim_directive_reward(player_id, directive_id, conn=conn)
        conn.commit()
        assert ok is True
        assert reason == "ok"
        assert result and result["directive_id"] == directive_id

        row = conn.execute(
            "SELECT status FROM player_directives WHERE id = ?;",
            (directive_id,),
        ).fetchone()
        assert row["status"] == STATUS_CLAIMED
        for item_key in result.get("granted_items") or []:
            assert _inventory_amount(player_id, item_key, conn=conn) >= 1
    finally:
        conn.close()


def test_claim_directive_reward_idempotent(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        directive_id = _mark_first_daily_completed(conn, player_id)

        ok1, _, _ = claim_directive_reward(player_id, directive_id, conn=conn)
        conn.commit()
        assert ok1 is True

        ok2, reason2, _ = claim_directive_reward(player_id, directive_id, conn=conn)
        assert ok2 is False
        assert reason2 == "reward_already_claimed"
    finally:
        conn.close()


def test_claim_all_directive_rewards(id_db):
    conn = db()
    try:
        player_id = _create_player(conn)
        now = time.time()
        ensure_player_directives(player_id, conn=conn, now=now)
        conn.execute(
            """
            UPDATE player_directives
            SET progress_value = target_value, status = ?
            WHERE player_id = ? AND status != ?;
            """,
            (STATUS_COMPLETED, player_id, STATUS_CLAIMED),
        )
        conn.commit()

        ok, reason, result = claim_all_directive_rewards(player_id, conn=conn)
        conn.commit()
        assert ok is True
        assert reason == "ok"
        assert int(result.get("count") or 0) >= 1

        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM player_directives WHERE player_id = ? AND status = ?;",
            (player_id, STATUS_COMPLETED),
        ).fetchone()["c"]
        assert int(pending) == 0
    finally:
        conn.close()


def test_api_imperial_directives_claim_contract(claim_client):
    client, player_id = claim_client
    conn = db()
    try:
        directive_id = _mark_first_daily_completed(conn, player_id)
    finally:
        conn.close()

    request_id = f"req-{uuid.uuid4().hex}"
    r1 = client.post(
        "/api/imperial-directives/claim",
        json={"directive_id": directive_id, "request_id": request_id},
    )
    assert r1.status_code == 200
    body1 = r1.get_json()
    assert body1["ok"] is True
    assert body1["reason"] == "ok"
    assert "state" in body1
    assert "imperial_directives" in body1
    assert body1["claim"]["directive_id"] == directive_id

    r2 = client.post(
        "/api/imperial-directives/claim",
        json={"directive_id": directive_id, "request_id": request_id},
    )
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2 == body1
