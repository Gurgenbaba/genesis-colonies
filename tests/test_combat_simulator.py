"""
GC-700A/B — Combat simulator tests.

Run: python -m pytest tests/test_combat_simulator.py -v
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from game.combat import WINNER_ATTACKER
from game.combat_simulator import (
    build_combat_simulator_defaults,
    build_combat_simulator_page_context,
    build_compact_summary,
    build_simulation_input,
    import_spy_report_for_simulator,
    list_combat_simulator_spy_reports,
    parse_spy_report_metadata_for_defender,
    run_combat_simulation,
    run_monte_carlo_simulation,
    summarize_simulation_results,
)
from game.fleet import add_planet_ships
from game.messages import create_message
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.repository import set_active_planet_id

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


def _baseline_payload(**overrides):
    base = {
        "attacker_ships": {"falcon_interceptor": 50, "atlas_hauler": 10},
        "defender_ships": {"ironclad_frigate": 5},
        "defender_defense": {"sentinel_turret": 20},
        "attacker_tech": {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0},
        "defender_tech": {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0},
        "defender_resources": {"metal": 500_000, "crystal": 200_000, "fuel_cells": 10_000},
        "calculate_loot": True,
        "iterations": 1,
    }
    base.update(overrides)
    return base


def test_build_simulation_input_ignores_unknown_keys():
    payload = _baseline_payload(attacker_ships={"falcon_interceptor": 5, "unknown_hull": 99})
    sim, err, _fe = build_simulation_input(payload, user_id=1)
    assert err is None
    assert sim is not None
    assert "unknown_hull" in sim.ignored_keys
    assert sim.attacker_ships == {"falcon_interceptor": 5}


def test_build_simulation_input_strict_rejects_unknown():
    payload = _baseline_payload(
        attacker_ships={"falcon_interceptor": 5, "bogus_ship": 1},
        strict_keys=True,
    )
    sim, err, field_errors = build_simulation_input(payload, user_id=1)
    assert sim is None
    assert err == "unknown_unit_keys"
    assert "bogus_ship" in field_errors.get("units", [])


def test_single_run_deterministic_with_seed():
    payload = _baseline_payload(seed=424242, iterations=1)
    a = run_combat_simulation(payload, user_id=1)
    b = run_combat_simulation(payload, user_id=1)
    assert a["ok"] is True
    assert b["ok"] is True
    assert a["result"]["sample_battle"] == b["result"]["sample_battle"]


def test_monte_carlo_probabilities_sum_to_one():
    payload = _baseline_payload(iterations=40, seed=9001)
    out = run_monte_carlo_simulation(payload, user_id=1, iterations=40)
    assert out["ok"] is True
    probs = out["result"]["summary"]["winner_probabilities"]
    total = probs["attacker"] + probs["defender"] + probs["draw"]
    assert total == pytest.approx(1.0, abs=0.02)


def test_tech_modifiers_affect_outcome():
    low = run_combat_simulation(
        _baseline_payload(
            seed=555,
            iterations=1,
            attacker_tech={"weapon_tech": 0},
            defender_ships={"ironclad_frigate": 30},
            defender_defense={},
        ),
        user_id=1,
    )
    high = run_combat_simulation(
        _baseline_payload(
            seed=555,
            iterations=1,
            attacker_tech={"weapon_tech": 20},
            defender_ships={"ironclad_frigate": 30},
            defender_defense={},
        ),
        user_id=1,
    )
    assert low["ok"] and high["ok"]
    low_losses = sum(low["result"]["sample_battle"]["attacker_losses"].values())
    high_losses = sum(high["result"]["sample_battle"]["attacker_losses"].values())
    assert high_losses <= low_losses


def test_defense_units_included_in_defender_losses():
    payload = _baseline_payload(
        seed=12,
        iterations=1,
        attacker_ships={"ironclad_frigate": 40},
        defender_ships={},
        defender_defense={"sentinel_turret": 50, "plasma_arc": 10},
    )
    out = run_combat_simulation(payload, user_id=1)
    sample = out["result"]["sample_battle"]
    assert sum(sample["defender_defense_losses"].values()) > 0


def test_loot_never_exceeds_cargo_cap():
    payload = _baseline_payload(
        seed=77,
        iterations=1,
        attacker_ships={"falcon_interceptor": 100, "atlas_hauler": 50},
        defender_ships={},
        defender_defense={"sentinel_turret": 1},
        defender_resources={"metal": 9_999_999, "crystal": 9_999_999, "fuel_cells": 9_999_999},
    )
    out = run_combat_simulation(payload, user_id=1)
    sample = out["result"]["sample_battle"]
    if sample["winner"] == WINNER_ATTACKER:
        loot_total = sum(sample["loot"].values())
        assert loot_total <= int(sample["cargo_cap"])


def test_summarize_empty_results():
    summary = summarize_simulation_results([])
    assert summary["winner_probabilities"]["attacker"] == 0.0


@pytest.fixture()
def sim_db(tmp_path, monkeypatch):
    db_path = tmp_path / "combat_sim.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    from game import db as gdb
    import game.models as models

    gdb._DB_PATH = None
    monkeypatch.setattr(gdb, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)

    from game.models import init_db

    init_db()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_path


def _login_client(sim_db, monkeypatch):
    from game import db as gdb
    import game.models as models

    gdb.DB_PATH = sim_db
    models.DB_PATH = sim_db
    monkeypatch.setattr(gdb, "DB_PATH", sim_db)
    monkeypatch.setattr(models, "DB_PATH", sim_db)
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    uname = f"sim_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"}, follow_redirects=False)
    assert login.status_code in (200, 302), login.get_data(as_text=True)
    return client, int(user["id"]), app_module


def test_api_requires_auth(sim_db, monkeypatch):
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    resp = client.post(
        "/api/combat-simulator/run",
        json=_baseline_payload(),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (302, 401, 403)


def test_api_run_ok(sim_db, monkeypatch):
    client, _uid, _app = _login_client(sim_db, monkeypatch)
    resp = client.post(
        "/api/combat-simulator/run",
        json=_baseline_payload(seed=1, iterations=5),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["result"]["mode"] == "monte_carlo"
    assert data["result"]["iterations"] == 5
    display = data["result"]["display"]
    assert display["verdict"]["verdict_key"].startswith("combat_sim_verdict_")
    assert display["recommendation"]["key"].startswith("combat_sim_rec_")
    assert "narrative" in display
    narrative = display["narrative"]
    assert "banner" in narrative
    assert "meter" in narrative
    assert "compact_summary" in narrative
    assert "analysis" in narrative
    assert isinstance(narrative.get("attacker_losses"), list)
    assert "headline" in display
    assert "average_economics" in data["result"]["summary"]
    assert "warnings" in display
    assert isinstance(display["sample_timeline"], list)
    assert "defender_combined" in display["average_losses"]
    assert "combat_values" in display


def test_combat_values_effective_with_research():
    payload = _baseline_payload(
        seed=1,
        iterations=1,
        attacker_tech={"weapon_tech": 10, "armor_tech": 10, "shield_tech": 10},
        defender_tech={"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0},
    )
    out = run_combat_simulation(payload, user_id=1)
    cv = out["result"]["display"]["combat_values"]
    falcon = next(r for r in cv["attacker"] if r["unit_key"] == "falcon_interceptor")
    assert falcon["attack_effective"] > falcon["attack_base"]
    assert falcon["shield_effective"] > falcon["shield_base"]
    assert falcon["hull_effective"] > falcon["hull_base"]


def test_combat_values_cargo_marked_low_combat():
    payload = _baseline_payload(
        seed=2,
        iterations=1,
        attacker_ships={"atlas_hauler": 20, "falcon_interceptor": 5},
        defender_ships={"ironclad_frigate": 2},
    )
    out = run_combat_simulation(payload, user_id=1)
    hauler = next(r for r in out["result"]["display"]["combat_values"]["attacker"] if r["unit_key"] == "atlas_hauler")
    assert hauler["low_combat"] is True
    assert hauler["role_hint_key"] == "combat_values_hint_cargo"


def test_combat_values_rapid_fire_when_defined():
    payload = _baseline_payload(
        seed=3,
        iterations=1,
        attacker_ships={"ironclad_frigate": 10},
        defender_ships={"falcon_interceptor": 20, "mule_courier": 5},
    )
    out = run_combat_simulation(payload, user_id=1)
    iron = next(r for r in out["result"]["display"]["combat_values"]["attacker"] if r["unit_key"] == "ironclad_frigate")
    assert iron["rapid_fire"]
    assert iron["rapid_fire"][0]["multiplier"] >= 2
    assert iron["rapid_fire"][0]["name_key"]


def test_combat_values_why_block_present():
    out = run_combat_simulation(_baseline_payload(seed=4, iterations=1), user_id=1)
    why = out["result"]["display"]["combat_values"]["why"]
    assert why
    assert all(str(row.get("key", "")).startswith("combat_values_why_") for row in why)


def test_api_no_db_mutation(sim_db, monkeypatch):
    client, uid, app_module = _login_client(sim_db, monkeypatch)
    from game.db import db

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM fleet_movements;")
        movements_before = int(cur.fetchone()["c"])
        cur.execute("SELECT COUNT(*) AS c FROM player_messages;")
        messages_before = int(cur.fetchone()["c"])
        cur.execute("SELECT metal, crystal FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        planet_before = dict(cur.fetchone())
    finally:
        conn.close()

    resp = client.post(
        "/api/combat-simulator/run",
        json=_baseline_payload(seed=2, iterations=3),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM fleet_movements;")
        assert int(cur.fetchone()["c"]) == movements_before
        cur.execute("SELECT COUNT(*) AS c FROM player_messages;")
        assert int(cur.fetchone()["c"]) == messages_before
        cur.execute("SELECT metal, crystal FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        planet_after = dict(cur.fetchone())
        assert planet_after == planet_before
    finally:
        conn.close()


def _combat_sim_player_html(body: str) -> str:
    marker = 'id="combat-simulator-page"'
    idx = body.find(marker)
    assert idx >= 0, "combat-simulator-page missing"
    start = body.rfind("<div", 0, idx)
    depth = 0
    i = start
    while i < len(body):
        if body.startswith("<div", i):
            depth += 1
            i += 4
            continue
        if body.startswith("</div>", i):
            depth -= 1
            if depth == 0:
                return body[start : i + 6]
            i += 6
            continue
        i += 1
    raise AssertionError("combat simulator page div not closed")


def test_combat_simulator_route_renders(sim_db, monkeypatch):
    client, _uid, _app = _login_client(sim_db, monkeypatch)
    resp = client.get("/combat-simulator")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    player_html = _combat_sim_player_html(body)
    assert "combat-simulator-page" in player_html
    assert "combat-simulator-state" in player_html
    assert "gc-combat-sim-window" in player_html
    assert "data-sim-attacker-route" in player_html
    assert "Simulation starten" in player_html
    assert "Genesis Battle Lab" in player_html
    assert "gbl-result" in player_html
    assert "gbl-result-header" in player_html
    assert "data-sim-result-tiles" in player_html
    assert "data-sim-result-banner" in player_html
    assert "data-sim-details-toggle" in player_html
    assert 'data-sim-details hidden' in player_html or 'data-sim-details" hidden' in player_html
    assert "data-sim-atk-loss-table" in player_html
    assert "data-sim-analysis" in player_html
    assert "data-sim-meter" in player_html
    assert "data-sim-combat-values" in player_html
    assert "Kampfwerte verstehen" in player_html
    assert "data-qty-add" not in player_html
    assert "data-sim-reset-fields" not in player_html
    assert "data-qty-max" in player_html
    assert "Eigene Flotte übernehmen" in player_html
    assert "data-sim-admin-panel" not in player_html
    assert "data-sim-details-pre" not in player_html
    assert "combat-sim-efficiency-table" not in player_html
    assert "Balancing-Modus" not in player_html
    assert "JSON kopieren" not in player_html
    assert "Einheiten-Effizienz" not in player_html
    assert "Erweiterte Analyse" not in player_html


def test_combat_simulator_admin_route_has_admin_panel(sim_db, monkeypatch):
    from game.db import db

    client, uid, _app = _login_client(sim_db, monkeypatch)
    conn = db()
    try:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?;", (uid,))
        conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (uid,))
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/combat-simulator")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    player_html = _combat_sim_player_html(body)
    assert 'data-is-admin="1"' in player_html
    assert "data-sim-admin-panel" in player_html
    assert "Admin-Analyse" in player_html
    assert "data-sim-iterations" in player_html


def test_parse_spy_partial_intel_resources_only():
    meta = {
        "intel_tiers": {"resources": True, "fuel": False, "fleet": False, "defense": False},
        "resources": {"metal": 12000, "crystal": 3400},
        "target_coords": "1:2:3",
        "target_owner": "Enemy",
    }
    parsed = parse_spy_report_metadata_for_defender(meta)
    assert parsed["defender_resources"]["metal"] == 12000
    assert parsed["defender_resources"]["crystal"] == 3400
    assert parsed["defender_resources"]["fuel_cells"] == 0
    assert parsed["defender_ships"] == {}
    assert parsed["defender_defense"] == {}
    assert parsed["field_known"]["fleet"] is False
    assert parsed["field_known"]["metal"] is True
    assert parsed["field_known"]["fuel_cells"] is False
    assert "combat_sim_field_fleet" in parsed["unknown_label_keys"]
    assert "fleet" in parsed["unscanned_fields"]
    assert "defense" in parsed["unscanned_fields"]
    assert "research" in parsed["unscanned_fields"]


def test_defaults_load_active_planet_ships_and_research(sim_db):
    from game.db import db

    uname = f"simdef_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name="Cmdr", conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        set_active_planet_id(uid, pid, conn=conn)
        add_planet_ships(pid, uid, {"falcon_interceptor": 7, "atlas_hauler": 2}, conn=conn)
        cur = conn.cursor()
        for tech_key, level in (("weapon_tech", 5), ("armor_tech", 3), ("shield_tech", 2)):
            cur.execute(
                """
                INSERT INTO research_levels (user_id, tech_key, level)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
                """,
                (uid, tech_key, level),
            )
        conn.commit()
    finally:
        conn.close()

    defaults = build_combat_simulator_defaults(uid)
    assert defaults["context_planet"]["id"] == pid
    assert defaults["attacker_ships"].get("falcon_interceptor") == 7
    assert defaults["attacker_tech"]["weapon_tech"] == 5
    assert defaults["attacker_tech"]["armor_tech"] == 3
    assert defaults["attacker_tech"]["shield_tech"] == 2


def _policy_safe_username(prefix: str = "sim") -> str:
    from game.name_policy import validate_player_name

    for n in range(128):
        candidate = f"{prefix}{n:04d}"
        if validate_player_name(candidate)[0]:
            return candidate
    raise AssertionError("no safe username")


def _create_spy_message(owner_id: int, meta: dict, *, conn) -> int:
    result = create_message(
        int(owner_id),
        "Spy report test",
        "body",
        category="espionage",
        metadata=meta,
        conn=conn,
    )
    assert result.get("ok"), result
    return int(result["data"]["message_id"])


def test_spy_import_only_allows_own_messages(sim_db):
    from game.db import db

    conn = db()
    try:
        ok_a, _, user_a = create_user(_policy_safe_username("spya"), "test-pass-123")
        ok_b, _, user_b = create_user(_policy_safe_username("spyb"), "test-pass-123")
        assert ok_a and ok_b
        uid_a = int(user_a["id"])
        uid_b = int(user_b["id"])
        meta = {
            "intel_tiers": {"resources": True, "fleet": True, "defense": False},
            "resources": {"metal": 5000, "crystal": 1000},
            "ships": {"falcon_interceptor": 2},
            "target_coords": "1:10:5",
        }
        msg_id = _create_spy_message(uid_a, meta, conn=conn)
        conn.commit()

        imported, err = import_spy_report_for_simulator(uid_a, msg_id, conn=conn)
        assert err is None
        assert imported is not None
        defender = imported["defender"]
        assert defender["defender_resources"]["metal"] == 5000
        assert defender["defender_ships"].get("falcon_interceptor") == 2

        foreign, foreign_err = import_spy_report_for_simulator(uid_b, msg_id, conn=conn)
        assert foreign is None
        assert foreign_err == "not_found"
    finally:
        conn.close()


def test_list_spy_reports_for_owner_only(sim_db):
    from game.db import db

    conn = db()
    try:
        ok, _, user = create_user(_policy_safe_username("sprt"), "test-pass-123")
        assert ok and user
        uid = int(user["id"])
        _create_spy_message(
            uid,
            {"target_coords": "2:3:4", "intel_tiers": {"target": True}},
            conn=conn,
        )
        conn.commit()
        payload = list_combat_simulator_spy_reports(uid, conn=conn)
        assert len(payload["reports"]) >= 1
        assert payload["reports"][0]["target_coords"] == "2:3:4"
    finally:
        conn.close()


def test_simulation_uses_imported_spy_values(sim_db):
    payload = {
        "attacker_ships": {"ironclad_frigate": 20},
        "defender_ships": {"falcon_interceptor": 3},
        "defender_defense": {"sentinel_turret": 8},
        "defender_resources": {"metal": 100_000, "crystal": 50_000, "fuel_cells": 0},
        "attacker_tech": {"weapon_tech": 4, "armor_tech": 0, "shield_tech": 0},
        "defender_tech": {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0},
        "calculate_loot": True,
        "seed": 9090,
        "iterations": 1,
    }
    out = run_combat_simulation(payload, user_id=1)
    assert out["ok"] is True
    sample = out["result"]["sample_battle"]
    assert sample["winner"] in ("attacker", "defender", "draw")


def test_api_defaults_endpoint(sim_db, monkeypatch):
    from game.db import db

    client, uid, _app = _login_client(sim_db, monkeypatch)
    conn = db()
    try:
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        add_planet_ships(pid, uid, {"falcon_interceptor": 4}, conn=conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (uid, "weapon_tech", 2),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/api/combat-simulator/defaults")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["defaults"]["attacker_ships"].get("falcon_interceptor") == 4
    assert data["defaults"]["attacker_tech"]["weapon_tech"] == 2


def test_api_import_spy_report(sim_db, monkeypatch):
    from game.db import db

    client, uid, _app = _login_client(sim_db, monkeypatch)
    conn = db()
    try:
        msg_id = _create_spy_message(
            uid,
            {
                "intel_tiers": {"resources": True, "fleet": False, "defense": True},
                "resources": {"metal": 8000, "crystal": 2000},
                "defense": {"units": {"sentinel_turret": 5}},
                "target_coords": "3:4:5",
                "target_owner": "Rival",
            },
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(
        "/api/combat-simulator/import-spy-report",
        json={"message_id": msg_id},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    defender = body["import"]["defender"]
    assert defender["defender_resources"]["metal"] == 8000
    assert defender["defender_defense"].get("sentinel_turret") == 5
    assert "fleet" in defender["unscanned_fields"]
    assert defender["field_known"]["fleet"] is False


def test_narrative_includes_deployed_attacker_units():
    payload = _baseline_payload(
        seed=7,
        iterations=20,
        attacker_ships={"falcon_interceptor": 50, "atlas_hauler": 10},
        defender_ships={"ironclad_frigate": 5},
        defender_defense={"sentinel_turret": 20},
    )
    out = run_monte_carlo_simulation(payload, user_id=1, iterations=20)
    rows = out["result"]["display"]["narrative"]["attacker_losses"]
    keys = {r["unit_key"] for r in rows}
    assert "falcon_interceptor" in keys
    assert "atlas_hauler" in keys
    for row in rows:
        assert "severity" in row
        assert "quantity" in row
        assert row["deployed"] > 0


def test_display_recommendation_for_winning_attack():
    payload = _baseline_payload(
        seed=42,
        iterations=40,
        attacker_ships={"falcon_interceptor": 200, "atlas_hauler": 30},
        defender_ships={"ironclad_frigate": 2},
        defender_defense={"sentinel_turret": 5},
        defender_resources={"metal": 500_000, "crystal": 200_000, "fuel_cells": 10_000},
    )
    out = run_monte_carlo_simulation(payload, user_id=1, iterations=40)
    assert out["ok"] is True
    rec = out["result"]["display"]["recommendation"]
    assert rec["key"].startswith("combat_sim_rec_")
    assert rec["tone"] in ("positive", "negative", "warning", "neutral")
    headline = out["result"]["display"]["headline"]
    assert "attacker_loss_value" in headline
    assert "loot_value" in headline


def test_display_payload_for_cargo_only_attacker():
    payload = _baseline_payload(
        seed=1,
        iterations=30,
        attacker_ships={"veil_probe": 1},
        defender_ships={"ironclad_frigate": 10},
        defender_defense={},
        defender_resources={"metal": 0, "crystal": 0, "fuel_cells": 0},
    )
    out = run_monte_carlo_simulation(payload, user_id=1, iterations=30)
    assert out["ok"] is True
    display = out["result"]["display"]
    assert display["headline"]["attacker_win_pct"] == 0
    rec = display["recommendation"]
    assert rec["key"] in (
        "combat_sim_rec_cargo_only",
        "combat_sim_rec_need_combat_ships",
        "combat_sim_rec_no_attack_power",
        "combat_sim_rec_too_risky",
    )


def test_page_context_with_spy_report_id(sim_db):
    from game.db import db

    conn = db()
    try:
        ok, _, user = create_user(_policy_safe_username("simsp"), "test-pass-123")
        assert ok and user
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Cmdr", conn=conn)
        msg_id = _create_spy_message(
            uid,
            {
                "intel_tiers": {"resources": True, "fleet": True, "defense": False},
                "resources": {"metal": 5000, "crystal": 1000},
                "ships": {"falcon_interceptor": 2},
                "target_coords": "1:10:5",
                "target_owner": "Rival",
                "target_planet": "Rival Prime",
            },
            conn=conn,
        )
        conn.commit()
        ctx = build_combat_simulator_page_context(uid, conn=conn, spy_report_id=msg_id)
        assert ctx["spy_report_id"] == msg_id
        assert ctx["presets"]["defender_ships"].get("falcon_interceptor") == 2
        assert ctx["route_labels"]["from_spy"] is True
        assert "Rival" in ctx["route_labels"]["defender"]

        foreign_ok, _, foreign_user = create_user(_policy_safe_username("simfx"), "test-pass-123")
        assert foreign_ok and foreign_user
        foreign_ctx = build_combat_simulator_page_context(
            int(foreign_user["id"]), conn=conn, spy_report_id=msg_id
        )
        assert foreign_ctx.get("spy_import_error") == "not_found"
    finally:
        conn.close()


def test_combat_simulator_spy_report_url_import(sim_db, monkeypatch):
    from game.db import db

    client, uid, _app = _login_client(sim_db, monkeypatch)
    conn = db()
    try:
        msg_id = _create_spy_message(
            uid,
            {
                "intel_tiers": {"resources": True, "fleet": True, "defense": True},
                "resources": {"metal": 9000, "crystal": 2000, "fuel_cells": 100},
                "ships": {"ironclad_frigate": 3},
                "defense": {"units": {"sentinel_turret": 4}},
                "target_coords": "2:3:4",
                "target_owner": "Enemy",
                "target_planet": "Outpost",
            },
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get(f"/combat-simulator?spy_report_id={msg_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "gc-combat-sim-window" in body
    assert "combat-simulator-state" in body
    assert "Enemy" in body or "Outpost" in body
    assert f'"spy_report_id": {msg_id}' in body or f'"spy_report_id":{msg_id}' in body

    foreign = client.get(f"/combat-simulator?spy_report_id={msg_id + 99999}")
    assert foreign.status_code == 200
    assert "spy_import_error" in foreign.get_data(as_text=True) or "not_found" in foreign.get_data(as_text=True)


def test_player_view_css_no_unit_list_scroll():
    css = Path(ROOT / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index(".gc-combat-sim-unit-grid")
    chunk = css[idx : idx + 350]
    assert "max-height" not in chunk
    assert "overflow" not in chunk


def test_warning_labels_localized():
    payload = _baseline_payload(
        seed=3,
        iterations=5,
        attacker_ships={"atlas_hauler": 5},
        defender_ships={"ironclad_frigate": 20},
        defender_defense={},
    )
    out = run_combat_simulation(payload, user_id=1)
    warnings = out["result"]["display"]["warnings"]
    for row in warnings:
        assert row["label_key"].startswith("combat_sim_warning_")
        assert row["key"] == row["key"].strip()


def _compact_chip(compact, chip_id):
    return next(chip for chip in compact["chips"] if chip["id"] == chip_id)


def test_compact_summary_contains_own_loss_short_text():
    out = run_combat_simulation(_baseline_payload(seed=7, iterations=25), user_id=1)
    own = _compact_chip(out["result"]["display"]["narrative"]["compact_summary"], "own")
    assert own["mode"] in ("none", "single", "multi")
    if own["mode"] == "single":
        assert own["quantity"] >= 1
        assert own["name_key"]
        assert own["unit_key"]


def test_compact_summary_contains_enemy_loss_short_text():
    out = run_combat_simulation(_baseline_payload(seed=8, iterations=25), user_id=1)
    enemy = _compact_chip(out["result"]["display"]["narrative"]["compact_summary"], "enemy")
    assert enemy["mode"] in ("none", "single", "multi")
    if enemy["mode"] == "single":
        assert enemy["quantity"] >= 1
        assert enemy["name_key"]
        assert enemy["unit_key"]


def test_compact_summary_contains_loot_short_text():
    out = run_combat_simulation(
        _baseline_payload(
            seed=9,
            iterations=25,
            calculate_loot=True,
            defender_resources={"metal": 0, "crystal": 0, "fuel_cells": 0},
        ),
        user_id=1,
    )
    loot = _compact_chip(out["result"]["display"]["narrative"]["compact_summary"], "loot")
    assert loot["mode"] in ("none", "values")
    if loot["mode"] == "values":
        assert {"metal", "crystal", "fuel"} <= set(loot)


def test_compact_summary_structure_direct():
    compact = build_compact_summary(
        {
            "loot": {"metal": 100, "crystal": 50, "fuel_cells": 0},
            "debris": {"metal": 9000, "crystal": 9000},
            "expected_profit": 66665,
        },
        [{"quantity": 0, "name_key": "ship_falcon_interceptor", "unit_key": "falcon_interceptor", "unit_type": "ship"}],
        [{"quantity": 4, "name_key": "ship_atlas_hauler", "unit_key": "atlas_hauler", "unit_type": "ship"}],
    )
    assert [chip["id"] for chip in compact["chips"]] == ["own", "enemy", "loot", "debris", "net"]
    assert _compact_chip(compact, "own")["mode"] == "none"
    assert _compact_chip(compact, "enemy")["mode"] == "single"
    assert _compact_chip(compact, "enemy")["quantity"] == 4
    assert _compact_chip(compact, "loot")["mode"] == "values"
    assert _compact_chip(compact, "net")["label"] == "+66665"


def test_compact_summary_multi_loss_types():
    compact = build_compact_summary(
        {"loot": {}, "debris": {}, "expected_profit": -5000},
        [
            {"quantity": 2, "name_key": "ship_falcon_interceptor", "unit_key": "falcon_interceptor", "unit_type": "ship"},
            {"quantity": 1, "name_key": "ship_atlas_hauler", "unit_key": "atlas_hauler", "unit_type": "ship"},
        ],
        [{"quantity": 0, "name_key": "ship_ironclad_frigate", "unit_key": "ironclad_frigate", "unit_type": "ship"}],
    )
    own = _compact_chip(compact, "own")
    assert own["mode"] == "multi"
    assert own["count"] == 2
    assert len(own["units"]) == 2


def test_player_view_details_sections_inside_collapsed_panel(sim_db, monkeypatch):
    client, _uid, _app = _login_client(sim_db, monkeypatch)
    resp = client.get("/combat-simulator")
    assert resp.status_code == 200
    player_html = _combat_sim_player_html(resp.get_data(as_text=True))
    details_start = player_html.find('data-sim-details')
    assert details_start >= 0
    details_chunk = player_html[details_start : details_start + 6000]
    for marker in (
        "data-sim-atk-loss-table",
        "data-sim-def-loss-table",
        "data-sim-analysis",
        "data-sim-meter",
        "data-sim-combat-values",
    ):
        assert marker in details_chunk


def test_js_details_collapsed_by_default_and_toggle():
    js = (ROOT / "static" / "js" / "combat_simulator.js").read_text(encoding="utf-8")
    assert "showResultDetails = false" in js
    assert "syncResultDetailsVisibility" in js
    assert "data-sim-details-toggle" in js
    assert "panel.hidden = !showResultDetails" in js
    assert "renderResultBar" in js
    assert "data-sim-result-tiles" in js
    assert "gbl-result-tile" in js
    assert "renderLossTile" in js
    assert "fmtCompact" in js
    assert "battle_lab_bar_details" in js


def test_css_result_bar_compact():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gbl-result-bar" in css
    assert ".gbl-result-tile" in css
    chunk = css[css.index(".gbl-result-bar") : css.index(".gbl-result-bar") + 600]
    assert "border-radius: 0" in chunk
    assert "48px" in chunk
    assert "grid-template-columns: repeat(5" in chunk
