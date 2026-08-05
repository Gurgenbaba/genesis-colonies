"""
Internal HTTP cron tests — ranking recompute inside web service.

Run: python -m pytest tests/test_internal_cron.py -q
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from game.db import db
from game.models import add_build_job, create_user, get_homeworld, get_planet_buildings
from game.ranking import get_player_score_row
from game.ranking_worker import RANKING_WORKER_KEY, RANKING_WORKER_INTERVAL_SEC
from game.runtime_state import set_runtime_value
ROOT = Path(__file__).resolve().parent.parent
CRON_URL = "/api/internal/cron/ranking"
TOKEN = "test-internal-cron-secret-token"


@pytest.fixture()
def cron_env(tmp_path, monkeypatch):
    db_file = tmp_path / "internal_cron_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_INTERNAL_CRON_TOKEN", TOKEN)
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    return db_file


@pytest.fixture()
def cron_client(cron_env, monkeypatch):
    monkeypatch.setenv("GC_INTERNAL_CRON_TOKEN", TOKEN)
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import migrate

    migrate.main()

    import importlib
    import app as app_module

    importlib.reload(app_module)
    return app_module.app.test_client()


def _auth_headers(token: str | None = TOKEN) -> dict:
    if token is None:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _unique_cron_username() -> str:
    """Letter-only unique name — digit stamps can hit name_policy (e.g. substring 1488)."""
    n = time.time_ns()
    letters = []
    while n:
        letters.append("abcdefghij"[n % 10])
        n //= 10
    return "cron" + "".join(reversed(letters) or "a")


def _create_player_with_building() -> int:
    ok, err, user = create_user(_unique_cron_username(), "test-pass-123")
    assert ok and user, err
    pid = int(user["id"])
    hw = get_homeworld(pid)
    planet_id = int(hw["id"])
    now = time.time()
    conn = db()
    add_build_job(planet_id, "metal_mine", now - 20, now - 1, conn=conn)
    conn.commit()
    conn.close()
    from game.queue_engine import finish_due_work

    finish_due_work(player_id=pid, planet_id=planet_id, source="test")
    buildings = get_planet_buildings(planet_id)
    assert int(buildings.get("metal_mine") or 0) >= 1
    return pid


def test_internal_cron_unauthorized_without_token(cron_client):
    resp = cron_client.post(CRON_URL)
    assert resp.status_code == 401
    data = resp.get_json()
    assert data.get("ok") is False
    assert data.get("error") == "unauthorized"


def test_internal_cron_unauthorized_wrong_token(cron_client):
    resp = cron_client.post(CRON_URL, headers=_auth_headers("wrong-token"))
    assert resp.status_code == 401
    assert resp.get_json().get("error") == "unauthorized"


def test_internal_cron_recomputes_ranking(cron_client):
    pid = _create_player_with_building()
    # Live paths may already write score rows; cron must still recompute ranks.
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?;", (pid,))
    conn.commit()
    conn.close()
    row_before = get_player_score_row(pid)
    assert row_before is None or int(row_before.get("score_buildings") or 0) == 0

    resp = cron_client.post(CRON_URL, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    assert int(data.get("players_updated") or 0) >= 1
    assert int(data.get("ranks_assigned") or 0) >= 1
    assert "duration_ms" in data
    assert data.get("skipped_interval") is False
    assert "sqlite_backup" in data

    row_after = get_player_score_row(pid)
    assert row_after is not None
    assert int(row_after["score_buildings"]) > 0


def test_internal_cron_interval_guard(cron_client):
    _create_player_with_building()
    set_runtime_value(
        RANKING_WORKER_KEY,
        json.dumps(
            {
                "at": int(time.time()),
                "source": "test",
                "ok": True,
                "players_updated": 1,
                "ranks_assigned": 1,
                "duration_ms": 5,
                "errors": [],
            }
        ),
    )

    with patch("game.internal_cron.run_ranking_worker") as mock_run:
        mock_run.return_value = {
            "ok": True,
            "skipped_interval": True,
            "players_updated": 0,
            "ranks_assigned": 0,
            "duration_ms": 1,
            "errors": [],
            "next_run_in_sec": 300,
        }
        resp = cron_client.post(CRON_URL, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("skipped_interval") is True
    mock_run.assert_called_once_with(
        source="http_cron",
        force=False,
        persist=True,
        allow_empty=False,
    )


def test_internal_cron_force_bypasses_guard(cron_client):
    _create_player_with_building()
    set_runtime_value(
        RANKING_WORKER_KEY,
        json.dumps(
            {
                "at": int(time.time()),
                "source": "test",
                "ok": True,
                "players_updated": 1,
                "ranks_assigned": 1,
                "duration_ms": 5,
                "errors": [],
            }
        ),
    )

    with patch("game.internal_cron.run_ranking_worker") as mock_run:
        mock_run.return_value = {
            "ok": True,
            "skipped_interval": False,
            "players_updated": 2,
            "ranks_assigned": 2,
            "duration_ms": 10,
            "errors": [],
        }
        resp = cron_client.post(
            f"{CRON_URL}?force=1",
            headers=_auth_headers(),
        )
    assert resp.status_code == 200
    mock_run.assert_called_once_with(
        source="http_cron",
        force=True,
        persist=True,
        allow_empty=False,
    )


def test_internal_cron_worker_failure_returns_500(cron_client):
    with patch("game.internal_cron.run_ranking_worker") as mock_run:
        mock_run.return_value = {
            "ok": False,
            "players_updated": 0,
            "ranks_assigned": 0,
            "duration_ms": 1,
            "errors": ["boom"],
            "skipped_interval": False,
        }
        resp = cron_client.post(CRON_URL, headers=_auth_headers())
    assert resp.status_code == 500
    data = resp.get_json()
    assert data.get("ok") is False
    assert "boom" in (data.get("errors") or [])


def test_internal_cron_exception_not_swallowed(cron_client):
    with patch("game.internal_cron.run_ranking_worker", side_effect=RuntimeError("cron exploded")):
        resp = cron_client.post(CRON_URL, headers=_auth_headers())
    assert resp.status_code == 500
    data = resp.get_json()
    assert data.get("ok") is False
    assert "cron exploded" in str(data.get("error", ""))


def test_internal_cron_real_guard_skips_within_interval(cron_client):
    _create_player_with_building()
    first = cron_client.post(CRON_URL, headers=_auth_headers())
    assert first.status_code == 200
    assert first.get_json().get("skipped_interval") is False

    second = cron_client.post(CRON_URL, headers=_auth_headers())
    assert second.status_code == 200
    second_data = second.get_json()
    assert second_data.get("skipped_interval") is True
    assert int(second_data.get("next_run_in_sec") or 0) > 0
    assert int(second_data.get("next_run_in_sec") or 0) <= RANKING_WORKER_INTERVAL_SEC


def test_internal_cron_ranking_does_not_piggyback_vote_reengagement(cron_client):
    """Synthetic vote grants were removed from the maintenance bag."""
    _create_player_with_building()
    resp = cron_client.post(CRON_URL, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert "vote_reengagement" not in data
    assert "fleet_tick" in data


def test_internal_cron_vote_reengagement_endpoint_removed(cron_client):
    resp = cron_client.post("/api/internal/cron/vote-reengagement", headers=_auth_headers())
    assert resp.status_code == 404
