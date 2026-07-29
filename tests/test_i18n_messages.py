"""Per-player locale for inbox notifications."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.i18n import format_i18n, get_player_locale, set_player_locale, tr
from game.messages import notify_transport
from game.models import create_user, init_db, load_player

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "locale_messages_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = __import__("os").environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _create_player(username: str) -> int:
    import uuid

    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    try:
        db().close()
    except Exception:
        pass
    player = load_player(int(user["id"]))
    assert player
    return int(player["id"])


def test_format_i18n_brace_placeholders():
    assert format_i18n("{count} aktives Gebot", count=3) == "3 aktives Gebot"
    assert format_i18n("Deaktivierung in {time}", time="2h 5m") == "Deaktivierung in 2h 5m"


def test_format_i18n_percent_placeholders():
    assert format_i18n("Urlaub bis %(time)s", time="1h") == "Urlaub bis 1h"


def test_tr_brace_count_placeholder():
    text = tr("options_blocker_auction_bids", locale="de", count=2)
    assert "{count}" not in text
    assert "2" in text


def test_en_locale_falls_back_to_en_for_new_languages(monkeypatch):
    """GC-900C: get_locale_dict() must still fall back to the English value
    for any key a supported locale hasn't translated yet (its merge
    contract). fr.json has since gained a real translation for
    buildings_title ("Bâtiments" — see
    test_gc900c_non_de_locales_differ_from_en_for_ui_sample and
    test_gc900c_non_de_fallback_chain_uses_en, which assert non-de locales
    now intentionally differ from en), so asserting fr == en for that key
    no longer reflects canon. Simulate a not-yet-translated key instead to
    keep exercising the actual fallback merge.
    """
    import game.i18n as i18n

    cached_load_locale = i18n._load_locale
    real_load_locale = cached_load_locale.__wrapped__

    def fake_load_locale(locale):
        data = dict(real_load_locale(locale))
        if locale == "fr":
            data.pop("buildings_title", None)
        return data

    # Warm the mtime cache with the real files first so get_locale_dict's
    # change-detection branch (which calls _load_locale.cache_clear()) does
    # not run against our monkeypatched loader below.
    i18n.get_locale_dict("fr")
    i18n.get_locale_dict("en")

    monkeypatch.setattr(i18n, "_load_locale", fake_load_locale)
    fr = i18n.get_locale_dict("fr")
    en = i18n.get_locale_dict("en")
    assert fr.get("buildings_title") == en.get("buildings_title")


def test_T_interpolates_brace_placeholders():
    from app import T
    from game.i18n import set_request_locale

    set_request_locale("de")
    text = T("options_blocker_auction_bids", count=2)
    assert "{count}" not in text
    assert "2" in text


def test_tr_respects_explicit_locale():
    de = tr(
        "fleet_transport_report_outbound",
        locale="de",
        coords="[1:1:1]",
        target="Colony",
        cargo="keine Ressourcen",
    )
    en = tr(
        "fleet_transport_report_outbound",
        locale="en",
        coords="[1:1:1]",
        target="Colony",
        cargo="no resources",
    )
    assert "Transport nach" in de
    assert "Transport to" in en


def test_notify_transport_uses_recipient_locale(temp_db):
    _run_migrate(temp_db)
    init_db()
    pid = _create_player("locale_notify")
    set_player_locale(pid, "en")

    res = notify_transport(
        pid,
        tr("fleet_transport_report_subject", locale="en", coords="[1:2:3]"),
        tr(
            "fleet_transport_report_outbound",
            locale="en",
            coords="[1:2:3]",
            target="Colony",
            cargo="no resources",
        ),
        locale="en",
    )
    assert res["ok"]

    conn = db()
    try:
        row = conn.execute(
            "SELECT subject, body, sender_name FROM player_messages WHERE recipient_player_id = ?;",
            (pid,),
        ).fetchone()
        assert row
        assert "Transport report" in row["subject"]
        assert "Transport to" in row["body"]
        assert row["sender_name"] == "Transport report"
    finally:
        conn.close()

    assert get_player_locale(pid) == "en"
