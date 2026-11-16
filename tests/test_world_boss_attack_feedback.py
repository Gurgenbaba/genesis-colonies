"""World Boss: blocked controls should explain, not swallow, clicks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_locked_world_boss_attack_remains_click_explainable():
    html = read("templates/world_boss.html")
    css = read("static/style.css")
    js = read("static/main.js")
    actions = html.split('class="gc-world-boss-actions"', 1)[1].split(
        "gc-world-boss-action-hint", 1
    )[0]
    assert 'data-wb-disabled-reason="world_boss_wave_limit"' in actions
    assert 'data-wb-locked-until="{{ cooldown_until|int }}"' in actions
    cooldown = actions.split(
        "{% elif player_info and player_info.attack_block_reason == 'world_boss_cooldown' and cooldown_until %}",
        1
    )[1].split("{% else %}", 1)[0]
    assert 'tabindex="-1"' not in cooldown
    assert "\n                              disabled\n" not in cooldown
    css_section = css.split(".gc-world-boss-page .wb-attack-btn.is-disabled", 1)[1].split("}", 1)[0]
    assert "pointer-events: auto;" in css_section
    cooldown_js = js.split("const wbApplyCooldownUi = (card, cooldownUntil) => {", 1)[1].split(
        "const wbUpdateFormation", 1
    )[0]
    assert 'btn.removeAttribute("tabindex")' in cooldown_js
    assert 'btn.disabled = false' in cooldown_js
    assert 'wbShowAttackFeedback(card, wbMapAttackError(reason), "error")' in js
    assert 'btn.dataset.wbDisabledReason' in js


def test_attack_error_is_accessible_and_persistent():
    js = read("static/main.js")
    feedback = js.split("const wbShowAttackFeedback = ", 1)[1].split(
        "const wbPostInstantAttack", 1
    )[0]
    assert 'el.setAttribute("role", kind === "error" ? "alert" : "status")' in feedback
    assert 'el.setAttribute("aria-live", kind === "error" ? "assertive" : "polite")' in feedback
    assert 'el.textContent = String(message || "")' in feedback
    # Preserve the other hotfix's clear-on-success and pending states.
    assert 'wbShowAttackFeedback(card, "", "success")' in js
    assert 'wbShowAttackFeedback(card, t("wb_attack", "Attack") + "…", "pending")' in js


def test_empty_active_planet_hangar_is_not_advertised_as_ready():
    src = read("game/world_boss.py")
    card = src.split("def _event_card_for_player(", 1)[1].split(
        "def build_world_boss_live_payload(", 1
    )[0]
    assert "if ok_atk and has_hangar_snapshot and not formation:" in card
    assert 'atk_reason = "no_combat_ships_available"' in card
    assert "attack_block_reason == 'no_combat_ships_available'" in read("templates/world_boss.html")


def test_server_rejections_have_a_reason_log():
    block = read("app.py").split("def api_world_boss_attack():", 1)[1].split(
        '@app.route("/api/world-boss/auto-attack"', 1
    )[0]
    assert "world_boss_attack_rejected" in block
    assert "world_boss_attack_exception" in block
