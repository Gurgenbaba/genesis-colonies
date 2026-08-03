from __future__ import annotations

"""
GC-951 — notification sound volume sliders + attack/message dedup keys.
"""

pytest_plugins = ("tests.test_options",)

from game.db import db
from game.messages import latest_inbox_message_id, send_player_message
from game.options import (
    get_notify_sound_settings,
    get_options_snapshot,
    normalize_sound_volume,
    update_notify_sounds,
)
from tests.test_options import _create_player, _login, app_client


def test_options_notify_sound_defaults(app_client):
    pid, _, _ = _create_player()
    snap = get_options_snapshot(pid)
    assert snap["notify_attack_sound"] == 0.1
    assert snap["notify_message_sound"] == 0.1
    assert snap["sfx_ui_sound"] == 0.1
    assert snap["sfx_combat_sound"] == 0.1


def test_normalize_sound_volume_legacy_modes():
    assert normalize_sound_volume("off") == 0.0
    assert normalize_sound_volume("quiet") == 0.5
    assert normalize_sound_volume("normal") == 1.0
    assert normalize_sound_volume(None) == 0.1
    assert normalize_sound_volume("nope") == 0.1
    assert normalize_sound_volume(0.25) == 0.25
    assert normalize_sound_volume(1.5) == 1.0
    assert normalize_sound_volume(-0.2) == 0.0


def test_options_save_attack_sound_separately(app_client):
    pid, uname, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, notify_attack_sound=0.5)
    assert ok is True
    assert err == "options_saved"
    assert data["notify_attack_sound"] == 0.5
    assert data["notify_message_sound"] == 0.1
    assert data["sfx_ui_sound"] == 0.1
    assert data["sfx_combat_sound"] == 0.1
    settings = get_notify_sound_settings(pid)
    assert settings["notify_attack_sound"] == 0.5
    assert settings["notify_message_sound"] == 0.1
    assert settings["sfx_ui_sound"] == 0.1
    assert settings["sfx_combat_sound"] == 0.1


def test_options_save_message_sound_separately(app_client):
    pid, _, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, notify_message_sound=0)
    assert ok is True
    assert data["notify_attack_sound"] == 0.1
    assert data["notify_message_sound"] == 0.0


def test_options_save_ui_and_combat_sfx_separately(app_client):
    pid, _, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, sfx_ui_sound=0.5)
    assert ok is True
    assert err == "options_saved"
    assert data["sfx_ui_sound"] == 0.5
    assert data["sfx_combat_sound"] == 0.1
    ok, err, data = update_notify_sounds(pid, sfx_combat_sound=0)
    assert ok is True
    assert data["sfx_ui_sound"] == 0.5
    assert data["sfx_combat_sound"] == 0.0
    settings = get_notify_sound_settings(pid)
    assert settings["sfx_ui_sound"] == 0.5
    assert settings["sfx_combat_sound"] == 0.0
    assert settings["notify_attack_sound"] == 0.1


def test_options_save_legacy_mode_strings(app_client):
    pid, _, _ = _create_player()
    ok, err, data = update_notify_sounds(pid, notify_attack_sound="quiet")
    assert ok is True
    assert data["notify_attack_sound"] == 0.5
    ok, err, data = update_notify_sounds(pid, notify_message_sound="off")
    assert ok is True
    assert data["notify_message_sound"] == 0.0
    assert data["notify_attack_sound"] == 0.5


def test_api_options_notify_sounds_logged_in(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.post(
        "/api/options/notify-sounds",
        json={
            "notify_attack_sound": 0,
            "notify_message_sound": 0.5,
            "sfx_ui_sound": 0,
            "sfx_combat_sound": 0.5,
        },
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["notify_attack_sound"] == 0.0
    assert body["data"]["notify_message_sound"] == 0.5
    assert body["data"]["sfx_ui_sound"] == 0.0
    assert body["data"]["sfx_combat_sound"] == 0.5
    settings = get_notify_sound_settings(pid)
    assert settings == {
        "notify_attack_sound": 0.0,
        "notify_message_sound": 0.5,
        "sfx_ui_sound": 0.0,
        "sfx_combat_sound": 0.5,
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
    assert 'type="range"' in html
    assert "data-notify-mode=" not in html
    assert "gc-options-sound-btn" not in html
    assert 'data-sfx-ui-sound=' in html
    assert 'data-sfx-combat-sound=' in html
    assert "gc-options-sound-slider" in html


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
    assert "function normalizeSoundVolume(value, defaultVolume)" in src
    assert "function playSoundPreview(kind)" in src
    assert "GC.playSoundPreview = playSoundPreview" in src
    assert "_incomingAttackNotifyPrimed" not in src
    assert "function normalizeNotifySoundMode" not in src
    assert "function soundModeForKind" not in src

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
