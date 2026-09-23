"""
Arcade high-score board for the developer portfolio.

Run: python -m pytest tests/test_arcade_scores.py -v
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.arcade_scores as arcade

ROOT = Path(__file__).resolve().parent.parent
SECRET = "test-secret"
NOW = 1_800_000_000


def _run(score=1200, wave=4, duration_ms=60_000, name="gcx", issued=NOW - 90):
    return {
        "token": arcade.issue_run_token(SECRET, now=issued),
        "name": name,
        "score": score,
        "wave": wave,
        "duration_ms": duration_ms,
    }


def test_valid_run_is_accepted_and_normalized():
    row, err = arcade.validate_submission(SECRET, _run(), now=NOW)
    assert err == ""
    assert row["name"] == "GCX"
    assert row["score"] == 1200 and row["wave"] == 4
    assert len(row["run_nonce"]) == 16


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"token": "123.abc.def"}, "bad_token"),
        ({"name": "AB"}, "bad_name"),
        ({"name": "A1C"}, "bad_name"),
        ({"name": "fck"}, "bad_name"),
        ({"score": 1205}, "implausible"),          # not reachable, points come in tens
        ({"score": 0}, "implausible"),
        ({"duration_ms": 2_000}, "implausible"),    # too short to count
        ({"duration_ms": 600_000}, "implausible"),  # longer than the token has existed
        ({"score": 60 * 120 + 210}, "implausible"), # faster than the game can award
        ({"wave": 40}, "implausible"),
        ({"score": "lots"}, "bad_request"),
    ],
)
def test_invalid_runs_are_rejected(overrides, error):
    data = _run()
    data.update(overrides)
    row, err = arcade.validate_submission(SECRET, data, now=NOW)
    assert row is None
    assert err == error


def test_token_signed_with_other_secret_or_expired_is_rejected():
    data = _run()
    assert arcade.validate_submission("other", data, now=NOW)[1] == "bad_token"
    old = _run(issued=NOW - arcade.TOKEN_MAX_AGE_SECONDS - 1)
    assert arcade.validate_submission(SECRET, old, now=NOW)[1] == "bad_token"


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    db_file = tmp_path / "arcade.db"
    env = {**os.environ, "GC_DB_PATH": str(db_file), "GC_DB_BACKEND": "sqlite"}
    result = subprocess.run([sys.executable, str(ROOT / "migrate.py")], cwd=str(ROOT), env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as dbmod
    import game.models as models

    monkeypatch.setattr(dbmod, "DB_PATH", db_file, raising=False)
    monkeypatch.setattr(models, "DB_PATH", db_file, raising=False)
    import app as appmod

    appmod = importlib.reload(appmod)
    arcade.reset_arcade_state()
    yield appmod.app.test_client()
    arcade.reset_arcade_state()


def _post(client, path, data=None):
    return client.post(
        path,
        data=json.dumps(data) if data is not None else "",
        content_type="text/plain",
        headers={"Origin": "https://gurgenbaba.github.io"},
    )


def test_full_flow_submit_replay_and_board(app_client, monkeypatch):
    run = _post(app_client, "/api/public/arcade/run")
    assert run.status_code == 200
    assert run.headers["Access-Control-Allow-Origin"] == "https://gurgenbaba.github.io"
    token = run.get_json()["token"]

    # Pretend the run lasted a minute.
    real_time = arcade.time.time
    monkeypatch.setattr(arcade.time, "time", lambda: real_time() + 70)
    payload = {"token": token, "name": "abc", "score": 1500, "wave": 5, "duration_ms": 65_000}
    first = _post(app_client, "/api/public/arcade/scores", payload)
    assert first.status_code == 200, first.get_json()
    body = first.get_json()
    assert body["rank"] == 1
    assert body["scores"][0]["name"] == "ABC" and body["scores"][0]["score"] == 1500

    replay = _post(app_client, "/api/public/arcade/scores", payload)
    assert replay.status_code == 409

    board = app_client.get("/api/public/arcade/scores", headers={"Origin": "https://gurgenbaba.github.io"})
    assert board.status_code == 200
    assert [r["name"] for r in board.get_json()["scores"]] == ["ABC"]
    assert board.headers["Access-Control-Allow-Origin"] == "https://gurgenbaba.github.io"


def test_submissions_are_rate_limited(app_client):
    for _ in range(arcade.SUBMIT_RATE[0]):
        assert _post(app_client, "/api/public/arcade/scores", {"token": "x"}).status_code == 400
    assert _post(app_client, "/api/public/arcade/scores", {"token": "x"}).status_code == 429
