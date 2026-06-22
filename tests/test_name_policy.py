"""GC-735 — commander name moderation blocklist."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.name_policy import (
    FORBIDDEN_REASON,
    normalize_player_name_for_policy,
    validate_player_name,
)
from game.options import update_player_name, validate_display_name

ROOT = Path(__file__).resolve().parents[1]
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "name_policy_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
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
    init_db()
    try:
        models.db().close()
    except Exception:
        pass
    return db_file


@pytest.mark.parametrize(
    "name",
    [
        "ADOLFHIZZLER",
        "AdolfHitler",
        "A.d.o.l.f",
        "H1tler",
        "Hizzler",
        "Führer",
        "Fuehrer",
        "SSCommander",
        "Nazi",
        "NSDAP",
        "n4z1",
        "H3IL_H1TL3R",
        "Jude",
        "Juden",
        "J1de",
        "1488",
        "88",
        "SSWolf",
        "H1TL3R88",
        "HH",
    ],
)
def test_name_policy_blocks_extremist_examples(name):
    ok, reason = validate_player_name(name)
    assert ok is False
    assert reason == FORBIDDEN_REASON


@pytest.mark.parametrize(
    "name",
    [
        "Nova Prime",
        "Commander_Alpha",
        "Star-Fleet",
        "MossTrader",
        "ClassicGamer",
        "GenesisPilot42",
        "RomanticPilot",
        "RomaVictor",
    ],
)
def test_name_policy_allows_normal_names(name):
    ok, reason = validate_player_name(name)
    assert ok is True
    assert reason == ""


def test_name_policy_normalization_leet_and_punctuation():
    assert normalize_player_name_for_policy("A.d.o.l.f") == "adolf"
    assert normalize_player_name_for_policy("H1tler") == "hitler"
    assert normalize_player_name_for_policy("Führer") == "fuhrer"
    assert normalize_player_name_for_policy("  SS-Commander  ") == "sscommander"


def test_name_policy_openai_supplement_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GC_NAME_POLICY_OPENAI", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from game.name_policy import _openai_moderation_blocks

    assert _openai_moderation_blocks("anything") is False


def test_create_user_blocks_forbidden_username(temp_db):
    ok, err, user = create_user("ADOLFHIZZLER", "test-pass-123")
    assert ok is False
    assert err == FORBIDDEN_REASON
    assert user is None


def test_create_user_allows_normal_username(temp_db):
    uname = f"Pilot_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok is True
    assert err is None
    assert user is not None


def test_validate_display_name_blocks_forbidden_rename():
    ok, err, cleaned = validate_display_name("AdolfHitler")
    assert ok is False
    assert err == FORBIDDEN_REASON
    assert cleaned == ""


def test_update_player_name_blocks_forbidden(temp_db):
    uname = f"rename_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    pid = int(user["id"])

    ok2, err2, _ = update_player_name(pid, "H1tler")
    assert ok2 is False
    assert err2 == FORBIDDEN_REASON

    ok3, err3, data = update_player_name(pid, "Safe Commander")
    assert ok3 is True
    assert data["player_name"] == "Safe Commander"
