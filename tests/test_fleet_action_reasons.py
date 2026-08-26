from pathlib import Path
import json


def _src(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_fleet_reason_mapper_never_exposes_raw_unknown_reason():
    js = _src("static/main.js")
    start = js.index("const fleetReasonHintKey = (reason) =>")
    end = js.index("const runPreview = async (page) =>", start)
    block = js[start:end]
    assert "fleet_error_generic" in block
    assert "withFleetActionHint" in block
    assert "return reason" not in block
    assert "return String(reason" not in block


def test_disabled_fleet_launch_shows_reason_before_submit():
    js = _src("static/main.js")
    start = js.index("const runPreview = async (page) =>")
    end = js.index("const schedulePreview = (page) =>", start)
    block = js[start:end]
    assert 'const errorEl = page.querySelector("[data-fleet-error]")' in block
    assert "errorEl.textContent = reasonText(reason, p)" in block
    assert "errorEl.hidden = false" in block
    assert "sendBtn.disabled = !p.can_send" in block


def test_server_send_failure_passes_context_to_reason_mapper():
    js = _src("static/main.js")
    send = js.index('GC.fetchGameAction("/api/fleet/send"')
    block = js[send : send + 7000]
    assert "reasonText(apiError(res), fleetPayload(res))" in block


def test_fleet_send_api_only_forwards_safe_actionable_context():
    app = _src("app.py")
    start = app.rindex('state = _fleet_mutation_game_state("api_fleet_send")')
    block = app[start : start + 2400]
    for key in ("attack_limit", "noob_protection", "troop_slots_needed", "troop_berths"):
        assert f'"{key}"' in block
    assert 'err_data.update(result)' not in block


def test_fleet_launch_reason_is_polite_status_and_square():
    tpl = _src("templates/fleet.html")
    css = _src("static/style.css")
    assert 'class="fleet-form-error fleet-launch-reason"' in tpl
    assert 'role="status" aria-live="polite"' in tpl
    assert "#fleet-page .fleet-launch-reason" in css
    assert "border-radius: 0" in css[css.index("#fleet-page .fleet-launch-reason") :]


def test_fleet_action_reason_locale_parity():
    keys = {
        "fleet_action_hint_ships", "fleet_action_hint_slots", "fleet_action_hint_resources",
        "fleet_action_hint_target", "fleet_action_hint_relation", "fleet_action_hint_mission",
        "fleet_action_hint_troops", "fleet_action_hint_wait",
        "fleet_error_not_enough_troop_berths_detail", "fleet_error_invalid_target_planet",
        "fleet_error_invalid_world_key", "fleet_error_vacation_target_protected",
        "fleet_error_no_debris_at_target", "fleet_error_no_asteroid_at_target",
        "fleet_error_recycle_requires_reclaimer", "fleet_error_not_enough_troops",
        "fleet_error_troops_attack_only", "fleet_error_troops_unavailable",
        "fleet_error_use_world_boss_attack", "fleet_error_world_boss_inactive",
        "fleet_error_pirate_base_inactive", "fleet_error_no_spy_probes_available",
        "fleet_error_cargo_required_for_collect", "fleet_error_cargo_required_for_recycle",
        "fleet_error_recycle_no_departure_cargo",
    }
    for loc in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads(Path(f"locales/{loc}.json").read_text(encoding="utf-8"))
        missing = keys - set(data)
        assert not missing, f"{loc} missing {sorted(missing)}"
        assert all(str(data[k]).strip() for k in keys)
