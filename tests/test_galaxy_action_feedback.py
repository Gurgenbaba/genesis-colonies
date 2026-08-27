from pathlib import Path
import json


def _js() -> str:
    return Path("static/js/galaxy-quick-action.js").read_text(encoding="utf-8")


def test_galaxy_fleet_errors_prefer_fleet_reason_over_generic_mapper():
    js = _js()
    block = js.split("notifyFleetError(reason, res, reasonMap)")[1].split("async runGuarded")[0]
    assert "fleet_error_${key}" in block
    assert "mapActionError(key, payload)" in block
    assert block.index("fleet_error_${key}") < block.index("mapActionError(key, payload)")
    assert 't("msg_generic_error", "")' in block
    assert "mapped !== genericAction" in block


def test_galaxy_fleet_send_normalizes_reason_and_handles_transport_failure():
    js = _js()
    block = js.split("async postFleetSend")[1].split("closeAttackMenu")[0]
    assert "this.fleetReason(res)" in block
    assert 'onError("server_error", { ok: false, error: "server_error" })' in block


def test_galaxy_recycler_lookup_failure_is_not_reported_as_no_ships():
    js = _js()
    assert "if (available === null)" in js
    assert 't("fleet_error_server_error"' in js
    helper = js.split("async resolveAvailableReclaimersAsync")[1].split("async sendDebrisRecycle")[0]
    assert "return null" in helper


def test_galaxy_attack_preset_load_failure_is_retryable_and_clear():
    js = _js()
    block = js.split("async loadAttackPresets")[1].split("async sendAttackPreset")[0]
    assert "_attackPresetsLoadFailed = true" in block
    assert "_attackPresetsCache = null" in block
    render = js.split("renderAttackMenu(menu, presets, trigger)")[1].split("async loadAttackPresets")[0]
    assert "_attackPresetsLoadFailed" in render
    assert "fleet_error_server_error" in render


def test_galaxy_relocation_transport_failure_has_specific_feedback():
    js = _js()
    block = js.split("async handleRelocationClick")[1].split("bindRingView(root)")[0]
    assert 't("fleet_error_server_error"' in block
    assert "catch (_err)" in block


def test_fleet_slots_full_translation_exists_in_all_supported_locales():
    for loc in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads(Path(f"locales/{loc}.json").read_text(encoding="utf-8"))
        assert str(data.get("fleet_error_fleet_slots_full") or "").strip(), loc
