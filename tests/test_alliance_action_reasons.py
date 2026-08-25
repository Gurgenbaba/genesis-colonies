from pathlib import Path
import json


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_alliance_reason_mapper_is_actionable_and_never_leaks_raw_codes():
    js = _source("static/main.js")
    start = js.index("function allianceErrorMessage")
    end = js.index("function patchAllianceDom", start)
    block = js[start:end]
    assert "res?.reason || res?.error" in block
    for reason in (
        "diplomacy_locked", "invalid_request", "invalid_target", "peace_requires_war",
        "war_active", "already_at_war", "duplicate_diplomacy_request", "request_not_found",
        "not_in_alliance", "requirements_not_met", "max_level",
    ):
        assert f'key === "{reason}"' in block
    assert "return key ||" not in block
    assert 'return t("alliance_action_failed"' in block


def test_diplomacy_blocked_reasons_are_server_state_driven_and_visible():
    tpl = _source("templates/alliance.html")
    assert "{% if st.can_manage %}" in tpl
    assert 'data-alliance-blocked-reason="diplomacy_role"' in tpl
    assert "d.peace_request_pending" in tpl
    assert "st.diplomacy_requests.outgoing" in tpl
    assert "alliance_dip_waiting_response" in tpl
    assert "alliance_dip_peace_pending" in tpl


def test_alliance_action_reason_locale_parity():
    keys = {
        "alliance_action_unavailable", "alliance_diplomacy_manage_required",
        "alliance_diplomacy_target_required", "alliance_dip_outgoing",
        "alliance_dip_waiting_response", "alliance_dip_peace_pending",
        "alliance_err_forbidden_action", "alliance_err_not_found_hint",
        "alliance_err_diplomacy_locked", "alliance_err_invalid_request_hint",
        "alliance_err_invalid_target_hint", "alliance_err_peace_requires_war",
        "alliance_err_war_active", "alliance_err_already_at_war",
        "alliance_err_duplicate_diplomacy_hint", "alliance_err_request_not_found_hint",
        "alliance_err_not_in_alliance", "alliance_err_alliance_unavailable",
        "alliance_err_player_already_allied", "alliance_err_project_invalid",
        "alliance_err_project_max_level", "alliance_err_requirements_not_met",
        "alliance_err_invalid_recruitment_mode",
    }
    for loc in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads(Path(f"locales/{loc}.json").read_text(encoding="utf-8"))
        assert not (keys - set(data)), f"{loc} missing {sorted(keys - set(data))}"
        assert all(str(data[k]).strip() for k in keys)


def test_diplomacy_target_has_clear_client_input_feedback():
    js = _source("static/main.js")
    send = js.index('"/api/alliance/diplomacy/send"')
    block = js[send - 700 : send + 800]
    assert "alliance_diplomacy_target_required" in block
