from __future__ import annotations

"""
GC-951 — notification sound controls + attack/message dedup keys.
"""

pytest_plugins = ("tests.test_options",)

from game.db import db
from game.messages import latest_inbox_message_id, send_player_message
from game.options import (
    get_notify_sound_settings,
    get_options_snapshot,
    update_notify_sounds,
)
from tests.test_options import _create_player, _login, app_client


def test_options_notify_sound_defaults(app_client):
    pid, _, _ = _create_player()
    snap = get_options_snapshot(pid)
    assert snap["notify_attack_sound"] == "normal"
    assert snap["notify_message_sound"] == "normal"
    assert snap["sfx_ui_sound"] == "normal"
    assert snap["sfx_combat_sound"] == "normal"


def test_options_save_attack_sound_separately(app_client):
    pid, uname, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, notify_attack_sound="quiet")
    assert ok is True
    assert err == "options_saved"
    assert data["notify_attack_sound"] == "quiet"
    assert data["notify_message_sound"] == "normal"
    assert data["sfx_ui_sound"] == "normal"
    assert data["sfx_combat_sound"] == "normal"
    settings = get_notify_sound_settings(pid)
    assert settings["notify_attack_sound"] == "quiet"
    assert settings["notify_message_sound"] == "normal"
    assert settings["sfx_ui_sound"] == "normal"
    assert settings["sfx_combat_sound"] == "normal"


def test_options_save_message_sound_separately(app_client):
    pid, _, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, notify_message_sound="off")
    assert ok is True
    assert data["notify_attack_sound"] == "normal"
    assert data["notify_message_sound"] == "off"


def test_options_save_ui_and_combat_sfx_separately(app_client):
    pid, _, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, sfx_ui_sound="quiet")
    assert ok is True
    assert err == "options_saved"
    assert data["sfx_ui_sound"] == "quiet"
    assert data["sfx_combat_sound"] == "normal"
    ok, err, data = update_notify_sounds(pid, sfx_combat_sound="off")
    assert ok is True
    assert data["sfx_ui_sound"] == "quiet"
    assert data["sfx_combat_sound"] == "off"
    settings = get_notify_sound_settings(pid)
    assert settings["sfx_ui_sound"] == "quiet"
    assert settings["sfx_combat_sound"] == "off"
    assert settings["notify_attack_sound"] == "normal"


def test_api_options_notify_sounds_logged_in(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.post(
        "/api/options/notify-sounds",
        json={
            "notify_attack_sound": "off",
            "notify_message_sound": "quiet",
            "sfx_ui_sound": "off",
            "sfx_combat_sound": "quiet",
        },
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["notify_attack_sound"] == "off"
    assert body["data"]["notify_message_sound"] == "quiet"
    assert body["data"]["sfx_ui_sound"] == "off"
    assert body["data"]["sfx_combat_sound"] == "quiet"
    settings = get_notify_sound_settings(pid)
    assert settings == {
        "notify_attack_sound": "off",
        "notify_message_sound": "quiet",
        "sfx_ui_sound": "off",
        "sfx_combat_sound": "quiet",
    }


def test_options_page_notify_sound_controls(app_client):
    _, uname, _ = _create_player()
    _login(app_client, uname)
    html = app_client.get("/options").get_data(as_text=True)
    assert 'id="options-notify-sounds"' in html
    assert 'data-notify-sound="attack"' in html
    assert 'data-notify-sound="message"' in html
    assert 'data-notify-sound="ui"' in html
    assert 'data-notify-sound="combat"' in html
    assert 'data-sfx-ui-sound=' in html
    assert 'data-sfx-combat-sound=' in html



def test_game_state_includes_alert_and_message_keys(app_client):
    _, uname, _ = _create_player()
    _login(app_client, uname)
    body = app_client.get("/api/game-state").get_json()
    assert body.get("ok") is True
    assert "latest_message_id" in body
    assert "alert_key" in body["fleet_alerts"]
    assert "incoming_attacks" in body["fleet_alerts"]


def test_latest_inbox_message_id(app_client):
    sender_id, sender_name, _ = _create_player()
    recipient_id, recipient_name, _ = _create_player()
    send_player_message(sender_id, recipient_name, "Hello", "Body long enough for test.")
    conn = db()
    latest = latest_inbox_message_id(recipient_id, conn=conn)
    assert latest is not None
    assert latest > 0
    conn.close()


def test_main_js_notify_dedup_contract():
    from pathlib import Path

    src = Path("static/main.js").read_text(encoding="utf-8")
    assert "GC_NOTIFY_SOUND_LS_ATTACK" in src
    assert "GC_NOTIFY_SOUND_LS_MESSAGE" in src
    assert "function shouldPlayNotifySoundForKey(storageKey, alertKey)" in src
    assert "function resolveAttackAlertSoundKey(alerts)" in src
    assert "function resolveMessageNotifySoundKey(data)" in src
    assert "_maybePlayIncomingAttackNotify(data.fleet_alerts)" in src
    assert "_maybePlayMessageNotifySound(data" in src
    assert "notifySoundVolumeForKind(kind)" in src
    assert "_incomingAttackNotifyPrimed" not in src

    attack_fn = src.split("function _maybePlayIncomingAttackNotify(alerts)")[1].split(
        "function syncFleetAttackAlert(alerts)"
    )[0]
    assert "shouldPlayNotifySoundForKey" in attack_fn
    assert "resolveAttackAlertSoundKey" in attack_fn

    unread_fn = src.split("function _processUnreadMessagesPoll(data, reason, opts)")[1].split(
        "function updateNavBadges"
    )[0]
    # GC-FLEET-NOTIFICATION-BATCH-001: sound gated with toast batch / message-id dedupe.
    assert "_maybePlayMessageNotifySound(data, { unreadIncreased: true })" in unread_fn
    assert "_queueMessageNotifyItems" in unread_fn
    assert "playNewMessageNotifySound();" not in unread_fn.split("_maybePlayMessageNotifySound(data")[0]
