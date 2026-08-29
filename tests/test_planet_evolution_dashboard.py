"""Tests for Planet Evolution dashboard UX payloads."""

from __future__ import annotations

from pathlib import Path

import pytest

from game.models import db, create_user, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.bootstrap import backfill_all_planets_evolution, ensure_planet_evolution
from game.planet_evolution.dashboard import _next_action, _research_ux, _trait_cards, build_dashboard_extras
from game.planet_evolution.definitions import get_trait, reload_definitions
from game.planet_evolution.repository import get_planet_dna, get_planet_row
from game.planet_evolution.ux_copy import humanize_requirement_lines, trait_effect_lines


@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pe_dash_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    conn = db()
    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"pe_dash_{id(conn)}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="DashTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_next_action_event_includes_cta_fields():
    action = _next_action(
        planet={},
        level=10,
        active_event={"label_key": "pe_event_test"},
        eligible_specs=[],
        research_ux={"recommended": [], "queue_has_room": True, "active": []},
        warnings=[],
        economy={"deficits": []},
    )
    assert action["priority"] == "event"
    assert action["cta_action"] == "focus_tab"
    assert action["cta_target"] == "events"
    assert action["cta_highlight"] == "pe-event-decision"
    assert action["cta_label_key"] == "pe_action_event_cta"


def test_next_action_research_highlights_tech_card():
    action = _next_action(
        planet={"specialization_key": "forge_world"},
        level=12,
        active_event=None,
        eligible_specs=[],
        research_ux={
            "recommended": [{
                "tech_key": "industry_t1_automation",
                "label_key": "pe_industry_t1_automation",
                "impact": {"current": 0, "after": 1, "rows": [{"label_key": "pe_impact_effect_research_speed", "value": "+15%"}], "scopes": ["pe_impact_scope_research"]},
            }],
            "queue_has_room": True,
            "active": [],
        },
        warnings=[],
        economy={"deficits": []},
    )
    assert action["priority"] == "research"
    assert action["cta_action"] == "focus_tab"
    assert action["cta_target"] == "research"
    assert action["cta_highlight"] == "pe-research-card-industry_t1_automation"
    assert action["tech_key"] == "industry_t1_automation"
    assert action["impact"]["current"] == 0
    assert action["impact"]["after"] == 1
    assert action["impact"]["rows"][0]["value"] == "+15%"


def test_next_action_economy_uses_normalized_deficit_evidence():
    deficit = {
        "resource_key": "refined_ferronit",
        "label_key": "resource_refined_ferronit",
        "received": 30.0,
        "required": 100.0,
        "pct": 30,
        "status": "critical",
    }
    action = _next_action(
        planet={"specialization_key": "forge_world"},
        level=12,
        active_event=None,
        eligible_specs=[],
        research_ux={"recommended": [], "queue_has_room": True, "active": []},
        warnings=[],
        economy={"deficits": [deficit]},
    )
    assert action["priority"] == "economy"
    assert action["cta_target"] == "economy"
    assert action["deficit"] == deficit
    assert action["deficit"]["pct"] == 30


def test_next_action_specialization_focuses_picker():
    action = _next_action(
        planet={},
        level=8,
        active_event=None,
        eligible_specs=["forge_world"],
        research_ux={"recommended": [], "queue_has_room": True, "active": []},
        warnings=[],
        economy={"deficits": []},
    )
    assert action["priority"] == "specialization"
    assert action["cta_action"] == "focus_section"
    assert action["cta_highlight"] == "pe-spec-picker"


def test_trait_effect_lines_from_definitions():
    reload_definitions()
    tdef = get_trait("ferronit_rich_crust")
    assert tdef
    lines = trait_effect_lines(tdef)
    kinds = {line["kind"] for line in lines}
    assert "affinity" in kinds
    assert "unlock" in kinds
    affinity = next(line for line in lines if line["kind"] == "affinity")
    assert affinity["value"] == 15
    assert affinity["affinity_key"] == "industry"


def test_trait_effect_lines_include_blocks():
    reload_definitions()
    tdef = get_trait("high_gravity")
    lines = trait_effect_lines(tdef)
    assert any(line["kind"] == "block" for line in lines)


def test_trait_cards_include_effect_lines(evo_db):
    reload_definitions()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    dna = get_planet_dna(pid, conn=conn)
    planet = get_planet_row(pid, conn=conn)
    reveal = int(planet.get("dna_reveal_tier") or 0)
    cards = _trait_cards(dna, reveal)
    conn.close()
    if cards:
        assert "effect_lines" in cards[0]
        assert isinstance(cards[0]["effect_lines"], list)


def test_build_dashboard_next_action_shape(evo_db):
    reload_definitions()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.commit()
    planet = get_planet_row(pid, conn=conn)
    dna = get_planet_dna(pid, conn=conn)
    from game.planet_evolution.repository import get_planet_culture
    from game.planet_evolution.mechanics import compile_planet_mechanics
    from game.planet_evolution.planet_research import get_planet_research_status

    culture = get_planet_culture(pid, conn=conn)
    mechanics = compile_planet_mechanics(pid, conn=conn)
    research = get_planet_research_status(pid, conn=conn)
    dash = build_dashboard_extras(
        pid,
        planet=planet,
        dna=dna,
        culture=culture,
        mechanics=mechanics,
        research=research,
        active_event=None,
        conn=conn,
    )
    conn.close()
    action = dash["next_action"]
    assert "cta_action" in action
    assert "cta_target" in action
    assert "cta_label_key" in action
    teaser = dash.get("identity_teaser") or {}
    assert "visible" in teaser
    if teaser.get("visible"):
        assert "status" in teaser


def test_identity_teaser_countdown_below_level_8():
    from game.planet_evolution.dashboard import build_identity_teaser

    teaser = build_identity_teaser(
        planet={"planet_level": 5, "specialization_key": None},
        eligible_specs=["forge_world"],
        xp_pct=40,
        planet_score=120,
    )
    assert teaser["visible"] is True
    assert teaser["status"] == "countdown"
    assert teaser["levels_remaining"] == 3
    assert teaser["unlock_level"] == 8


def test_identity_teaser_hidden_below_level_3():
    from game.planet_evolution.dashboard import build_identity_teaser

    teaser = build_identity_teaser(
        planet={"planet_level": 2, "specialization_key": None},
        eligible_specs=[],
    )
    assert teaser["visible"] is False


def test_identity_teaser_ready_at_level_8():
    from game.planet_evolution.dashboard import build_identity_teaser

    teaser = build_identity_teaser(
        planet={"planet_level": 8, "specialization_key": None},
        eligible_specs=["forge_world", "science_nexus"],
    )
    assert teaser["status"] == "ready"
    assert teaser["eligible_count"] == 2


def test_research_ux_includes_cost_and_affordability(evo_db):
    reload_definitions()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 0, crystal = 0 WHERE id = ?;", (pid,))
    conn.execute("UPDATE planet_buildings SET research_lab = 1 WHERE planet_id = ?;", (pid,))
    conn.commit()
    planet = get_planet_row(pid, conn=conn)
    from game.planet_evolution.planet_research import get_planet_research_status

    research = get_planet_research_status(pid, conn=conn)
    rdx = _research_ux(
        research,
        int(planet.get("planet_level") or 1),
        planet_id=pid,
        planet=planet,
        conn=conn,
    )
    conn.close()
    assert rdx["recommended"], "expected at least one recommended tech with research_lab"
    card = rdx["recommended"][0]
    assert "cost_metal" in card and card["cost_metal"] > 0
    assert "cost_crystal" in card
    assert "duration_seconds" in card and card["duration_seconds"] > 0
    assert card["can_afford"] is False
    assert card["missing_resources"]
    assert card["unavailable_reason_key"] == "not_enough_resources"


def test_research_ux_can_afford_when_funded(evo_db):
    reload_definitions()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;", (pid,))
    conn.execute("UPDATE planet_buildings SET research_lab = 1 WHERE planet_id = ?;", (pid,))
    conn.commit()
    planet = get_planet_row(pid, conn=conn)
    from game.planet_evolution.planet_research import get_planet_research_status

    research = get_planet_research_status(pid, conn=conn)
    rdx = _research_ux(
        research,
        int(planet.get("planet_level") or 1),
        planet_id=pid,
        planet=planet,
        conn=conn,
    )
    conn.close()
    affordable = [c for c in rdx["recommended"] if c.get("can_afford")]
    assert affordable
    assert affordable[0]["can_start"] is True
    assert affordable[0]["unavailable_reason_key"] is None


def test_planet_research_icon_maps_branch_to_existing_asset():
    from game.planet_evolution.ux_copy import planet_research_icon, planet_research_icon_fallback

    assert planet_research_icon("industry_t1_automation", "INDUSTRY") == "bauoptimierung.png"
    assert planet_research_icon("science_t1_field_labs", "SCIENCE") == "metallveredelung.png"
    assert planet_research_icon("ancient_t1_ruins_survey", "ANCIENT TECH") == "kryo-antriebstechnik.png"
    assert planet_research_icon("unknown_t9_x", None) == "metallveredelung.png"
    assert planet_research_icon_fallback("industry_t1_automation", "INDUSTRY") == "🏭"


def test_planet_evolution_template_uses_research_icon_field():
    tpl = (Path(__file__).resolve().parents[1] / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert "tech.icon" in tpl
    assert "tech.icon_fallback" in tpl
    assert "gc-card-queue-glyph" in tpl
    assert "tech_key ~ '.png'" not in tpl


def test_planet_evolution_template_shows_cost_and_disabled_afford():
    tpl = (Path(__file__).resolve().parents[1] / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert "pe_research_card_meta" in tpl
    assert "pe-research-cost" in tpl
    assert "pe_research_cannot_afford" in tpl
    assert 'disabled aria-disabled="true"' in tpl


def test_main_js_pe_research_uses_notify_not_raw_alert():
    src = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")
    idx = src.find(".pe-research-btn")
    assert idx >= 0
    block = src[idx : idx + 1200]
    # Failure handling was consolidated into a shared peMutationFailed(btn, res)
    # helper (used by every pe-*-btn handler: research/spec/spec-upgrade/policy/...)
    # instead of a per-button-type showNotify(reasonText(...)) inline call —
    # single Owner for "surface a PE mutation error", not duplicated per action.
    assert "peMutationFailed(researchBtn, res)" in block
    assert 'alert(reasonText(res?.reason))' not in block
    failed_helper_idx = src.find("const peMutationFailed = (btn, res) =>")
    assert failed_helper_idx >= 0
    assert failed_helper_idx < idx, "peMutationFailed must be defined before the research handler uses it"
    helper_block = src[failed_helper_idx : failed_helper_idx + 200]
    assert "showNotify(reasonText(res?.reason)" in helper_block


def test_overview_planet_teaser_integration(evo_db):
    from game.planet_evolution.teaser import get_overview_planet_teaser

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.execute("UPDATE planets SET planet_level = 5, planet_xp = 500 WHERE id = ?;", (pid,))
    conn.commit()
    planet = get_planet_row(pid, conn=conn)
    teaser = get_overview_planet_teaser(
        uid,
        metal=float(planet.get("metal") or 0),
        crystal=float(planet.get("crystal") or 0),
        conn=conn,
    )
    conn.close()
    assert teaser.get("visible") is True
    assert "planet_level" in teaser


def test_humanize_requirement_lines_renders_translated_text_not_raw_dict():
    lines = humanize_requirement_lines(
        ["traits_any:['mantle_rich']", "planet_level>=5"],
        planet_level=3,
        locale="de",
    )
    assert len(lines) == 2
    assert lines[0] == "Benötigt passende Planet-Eigenschaft"
    assert lines[1] == "Planet muss Stufe 5 erreichen (aktuell: Stufe 3)"
    for line in lines:
        assert "label_key" not in line
        assert "fallback" not in line


def test_pe_ssr_boot_history_limit_and_locked_card_template():
    """GC-PERF-PJAX-BYTES-HEAVY-001: SSR history window + locked cards omit info source."""
    tpl = (Path(__file__).resolve().parents[1] / "templates" / "planet_evolution.html").read_text(
        encoding="utf-8"
    )
    card_macro = tpl.split("{% macro pe_research_tech_card")[1].split("{% endmacro %}")[0]
    assert "variant != 'locked'" in card_macro
    assert "GC-PERF-PJAX-BYTES-HEAVY-001" in card_macro
    assert "pe_tech_info_source(tech)" in card_macro

    app_src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    pe_view = app_src.split("def planet_evolution_view()")[1].split("@app.route", 1)[0]
    assert "ssr_boot=True" in pe_view

    svc = (Path(__file__).resolve().parents[1] / "game" / "planet_evolution" / "service.py").read_text(
        encoding="utf-8"
    )
    payload_fn = svc.split("def get_planet_state_payload(")[1].split("\ndef set_active_planet")[0]
    assert "ssr_boot: bool = False" in payload_fn
    assert "history_limit = 5 if ssr_boot else 20" in payload_fn


def test_ssr_boot_payload_uses_short_history(evo_db):
    from game.planet_evolution.history import append_history
    from game.planet_evolution.service import get_planet_state_payload

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    for i in range(12):
        append_history(
            pid,
            "level_up",
            "pe_history_level_up",
            conn=conn,
            payload={"level": i + 1},
        )
    conn.commit()
    ssr = get_planet_state_payload(pid, player_id=uid, conn=conn, ssr_boot=True)
    full = get_planet_state_payload(pid, player_id=uid, conn=conn, ssr_boot=False)
    conn.close()
    assert len((ssr.get("dashboard") or {}).get("history", {}).get("items") or []) <= 5
    assert len((full.get("dashboard") or {}).get("history", {}).get("items") or []) >= 5
    assert len((full.get("dashboard") or {}).get("history", {}).get("items") or []) <= 20
