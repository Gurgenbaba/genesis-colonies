"""
EPIC-30 / GC-3007 — Stellar Forge (Orbital Shipyard Ascension), Phase 1.

Run: python -m pytest tests/test_stellar_forge.py -q
"""

from __future__ import annotations

import uuid

import pytest

from game.stellar_forge import (
    OPERATIONAL_PROTOCOLS_REQUIRED,
    ascend,
    forge_cores_required,
    get_forge_cores,
    get_raw_state,
    grant_forge_cores,
    hull_mass_target,
    is_unlocked,
    manufacturing_trial_complete,
    pay_tribute,
    record_hull_mass_delivery,
    record_operational_progress,
    ship_hull_mass,
    start_campaign,
    tribute_cost_for_rank,
    tribute_hours,
)


def _fund_planet(planet_id: int, metal: int = 10**18, crystal: int = 10**18, fuel_cells: int = 10**18) -> None:
    from game.db import db

    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (int(metal), int(crystal), float(fuel_cells), int(planet_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _add_hull_mass(pid: int, ship_key: str, amount: int) -> None:
    import time

    from game.db import begin_write_transaction, commit, db

    conn = db()
    try:
        begin_write_transaction(conn)
        record_hull_mass_delivery(pid, ship_key, amount, conn=conn, now=time.time())
        commit(conn)
    finally:
        conn.close()


def _add_operational(pid: int, protocol: str, amount: float) -> None:
    import time

    from game.db import begin_write_transaction, commit, db

    conn = db()
    try:
        begin_write_transaction(conn)
        record_operational_progress(pid, protocol, amount, conn=conn, now=time.time())
        commit(conn)
    finally:
        conn.close()


def _grant_cores(uid: int, amount: int) -> None:
    import time

    from game.db import begin_write_transaction, commit, db

    conn = db()
    try:
        begin_write_transaction(conn)
        grant_forge_cores(uid, amount, conn=conn, now=time.time())
        commit(conn)
    finally:
        conn.close()


# One representative buildable ship per MANUFACTURING_ROLE_POOL entry (GC-3009 —
# roles are rolled randomly per campaign, so tests must build whatever got rolled).
_SHIP_KEY_BY_ROLE = {
    "cargo": "mule_courier",
    "combat": "falcon_interceptor",
    "expedition": "solar_skiff",
    "expedition_combat": "eclipse_runner",
    "recycle": "harvest_reclaimer",
    "scout": "spark_drone",
    "siege": "planet_breaker",
    "spy": "veil_probe",
}


def _complete_manufacturing(pid: int, rank: int) -> None:
    """Deliver enough Hull Mass across the campaign's 3 rolled roles to satisfy Pillar 2."""
    from game.fleet_defs import get_ship

    state = get_raw_state(pid)
    required_roles = state["manufacturing_roles"]
    assert len(required_roles) == 3, required_roles
    target = hull_mass_target(rank)
    # Generous per-role buffer — integer division across 3 roles must clear the
    # exact target, not just approach it (floor(units) loses a bit each time).
    per_ship = target // 3 + 50_000
    for role in required_roles:
        ship_key = _SHIP_KEY_BY_ROLE[role]
        build_cost = get_ship(ship_key)["build_cost"]
        mass_per_unit = max(1, ship_hull_mass(build_cost))
        units = max(1, per_ship // mass_per_unit)
        _add_hull_mass(pid, ship_key, units)


def _complete_operational(pid: int, rank: int, count: int = OPERATIONAL_PROTOCOLS_REQUIRED) -> None:
    from game.stellar_forge.formulas import OPERATIONAL_PROTOCOLS, operational_target

    for protocol in OPERATIONAL_PROTOCOLS[:count]:
        _add_operational(pid, protocol, operational_target(protocol, rank))


@pytest.fixture
def forge_db(tmp_path, monkeypatch):
    import game.db as dbmod
    import game.models as models
    from game.models import create_user, ensure_player_and_homeworld, init_db

    db_file = tmp_path / "stellar_forge.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"forge_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _max_out_shipyard(pid: int) -> None:
    from game.models import get_planet_buildings, save_planet_buildings

    buildings = get_planet_buildings(pid)
    buildings["orbital_shipyard"] = 50
    save_planet_buildings(pid, buildings)


class TestStellarForgeFormulas:
    def test_tribute_hours_scale(self):
        assert tribute_hours(1) == 24
        assert tribute_hours(2) == 36
        assert tribute_hours(3) == 48

    def test_hull_mass_target_scale(self):
        assert hull_mass_target(1) == 2_000_000
        assert hull_mass_target(2) == 3_000_000

    def test_forge_cores_required_scale(self):
        assert forge_cores_required(1) == 3
        assert forge_cores_required(2) == 7
        assert forge_cores_required(3) == 11

    def test_ship_hull_mass_weights_fuel_cells(self):
        assert ship_hull_mass({"metal": 100, "crystal": 50, "fuel_cells": 10}) == 100 + 50 + 30

    def test_manufacturing_trial_needs_role_diversity(self):
        target = hull_mass_target(1)
        # Single role, total met — should still fail (min 3 roles).
        assert not manufacturing_trial_complete(target, 1, {"combat": target})
        # Two roles, total met — still fails (min 3 roles).
        two_roles = {"combat": target - 10, "cargo": 10}
        assert not manufacturing_trial_complete(sum(two_roles.values()), 1, two_roles)
        # No per-role cap anymore (GC-3008) — heavily skewed but 3 distinct
        # roles must still pass, since unit-cost tiers vary too much for a
        # flat 60%-of-total ceiling to be a fair constraint.
        skewed = {"combat": int(target * 0.9), "cargo": int(target * 0.05), "expedition": int(target * 0.05)}
        assert manufacturing_trial_complete(sum(skewed.values()), 1, skewed)
        # Balanced across 3 roles, total met.
        balanced = {"combat": target // 3, "cargo": target // 3, "expedition": target // 3 + 10}
        assert manufacturing_trial_complete(sum(balanced.values()), 1, balanced)

    def test_tribute_cost_scales_with_production(self):
        cost = tribute_cost_for_rank(1, {"metal": 1000, "crystal": 500, "fuel_cells": 100})
        assert cost["metal"] == int(round(1000 * 24 * 0.55))
        assert cost["crystal"] == int(round(500 * 24 * 0.30))
        assert cost["fuel_cells"] == int(round(100 * 24 * 0.15))

    def test_manufacturing_trial_requires_specific_rolled_roles(self):
        """GC-3009 — with required_roles given, diversity is exact-3-roles, not any-3."""
        target = hull_mass_target(1)
        required = ["cargo", "combat", "scout"]
        # Total met, but one required role has zero — must fail even though 3
        # OTHER roles (not the required ones) are present.
        wrong_roles = {"expedition": target // 3, "recycle": target // 3, "spy": target // 3 + 10}
        assert not manufacturing_trial_complete(sum(wrong_roles.values()), 1, wrong_roles, required)
        # Extra unrelated roles built too — still fine, as long as all 3
        # required roles have something > 0.
        mixed = {"cargo": 10, "combat": 10, "scout": 10, "spy": target}
        assert manufacturing_trial_complete(sum(mixed.values()), 1, mixed, required)
        # All 3 required present but total under target — must fail.
        under_target = {"cargo": 10, "combat": 10, "scout": 10}
        assert not manufacturing_trial_complete(sum(under_target.values()), 1, under_target, required)

    def test_roll_manufacturing_roles_picks_three_distinct_from_pool(self):
        from game.stellar_forge import MANUFACTURING_ROLE_POOL, roll_manufacturing_roles

        for _ in range(25):
            roles = roll_manufacturing_roles()
            assert len(roles) == 3
            assert len(set(roles)) == 3
            assert all(r in MANUFACTURING_ROLE_POOL for r in roles)
            assert "colony" not in roles
            assert roles == sorted(roles)


class TestStellarForgeUnlock:
    def test_locked_below_max_level(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        assert is_unlocked(pid) is False

    def test_unlocked_at_max_level(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)
        assert is_unlocked(pid) is True


class TestStellarForgeCampaign:
    def test_start_campaign_requires_unlock(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        ok, reason, _ = start_campaign(uid, dict(planet))
        assert not ok
        assert reason == "not_unlocked"

    def test_start_campaign_ok_when_unlocked(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)

        ok, reason, payload = start_campaign(uid, dict(planet))
        assert ok, reason
        assert payload["next_rank"] == 1
        state = get_raw_state(pid)
        assert state["campaign_active"] is True

        # Cannot start a second campaign while one is active.
        ok2, reason2, _ = start_campaign(uid, dict(planet))
        assert not ok2
        assert reason2 == "campaign_active"

    def test_pay_tribute_spends_planet_resources(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)
        _fund_planet(pid)

        ok, reason, _ = start_campaign(uid, dict(planet))
        assert ok, reason

        ok, reason, payload = pay_tribute(uid, dict(planet))
        assert ok, reason
        assert payload["cost"]["metal"] >= 0
        state = get_raw_state(pid)
        assert state["tribute_paid"] is True

        # Already paid → rejected.
        ok2, reason2, _ = pay_tribute(uid, dict(planet))
        assert not ok2
        assert reason2 == "already_paid"

    def test_hull_mass_and_operational_progress_only_while_active(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)

        # No active campaign yet — progress must not accumulate.
        _add_hull_mass(pid, "spark_drone", 100)
        assert get_raw_state(pid)["hull_mass_progress"] == 0

        ok, reason, _ = start_campaign(uid, dict(planet))
        assert ok, reason
        _add_hull_mass(pid, "spark_drone", 100)
        state = get_raw_state(pid)
        assert state["hull_mass_progress"] == ship_hull_mass({"metal": 625, "crystal": 250, "fuel_cells": 0}) * 100
        assert state["hull_mass_by_role"].get("scout") == state["hull_mass_progress"]

        _add_operational(pid, "exploration", 3)
        state = get_raw_state(pid)
        assert state["operational_progress"]["exploration"] == 3

    def test_ascend_requires_all_four_pillars(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)
        _fund_planet(pid)

        # No campaign yet.
        ok, reason, _ = ascend(uid, dict(planet))
        assert not ok and reason == "no_campaign"

        ok, reason, _ = start_campaign(uid, dict(planet))
        assert ok, reason

        # Tribute unpaid.
        ok, reason, _ = ascend(uid, dict(planet))
        assert not ok and reason == "tribute_unpaid"

        ok, reason, _ = pay_tribute(uid, dict(planet))
        assert ok, reason

        # Manufacturing incomplete.
        ok, reason, _ = ascend(uid, dict(planet))
        assert not ok and reason == "manufacturing_incomplete"

        _complete_manufacturing(pid, 1)

        # Operational incomplete.
        ok, reason, _ = ascend(uid, dict(planet))
        assert not ok and reason == "operational_incomplete"

        _complete_operational(pid, 1)

        # Forge Cores missing.
        ok, reason, payload = ascend(uid, dict(planet))
        assert not ok and reason == "forge_cores_missing"
        assert payload["forge_cores_required"] == forge_cores_required(1)

        _grant_cores(uid, forge_cores_required(1))

        ok, reason, payload = ascend(uid, dict(planet))
        assert ok, reason
        assert payload["forge_rank"] == 1
        assert payload["forge_rank_roman"] == "I"

        state = get_raw_state(pid)
        assert state["forge_rank"] == 1
        assert state["campaign_active"] is False
        assert state["hull_mass_progress"] == 0
        assert get_forge_cores(uid) == 0

    def test_ascend_forbidden_for_non_owner(self, forge_db):
        from game.models import create_user, ensure_player_and_homeworld, get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        ok, _, other_user = create_user(f"other_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok
        other_uid = int(other_user["id"])
        ensure_player_and_homeworld(other_uid)

        ok, reason, _ = start_campaign(other_uid, dict(planet))
        assert not ok
        assert reason == "forbidden"


class TestStellarForgePanel:
    def test_panel_fields_locked_vs_unlocked(self, forge_db):
        from game.models import get_homeworld
        from game.stellar_forge import panel_forge_fields

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])

        fields = panel_forge_fields(dict(planet))
        assert fields["stellar_forge_unlocked"] is False

        _max_out_shipyard(pid)
        planet = get_homeworld(player_id=uid)
        _fund_planet(pid)
        fields = panel_forge_fields(dict(planet))
        assert fields["stellar_forge_unlocked"] is True
        assert fields["stellar_forge_next_rank"] == 1
        assert fields["stellar_forge_hull_mass_target"] == hull_mass_target(1)
        assert fields["stellar_forge_forge_cores_required"] == forge_cores_required(1)
        assert fields["stellar_forge_can_ascend"] is False

    def test_buildings_panel_row_carries_forge_fields(self, forge_db):
        from game.buildings import get_buildings_panel_rows
        from game.models import get_homeworld, get_planet_buildings

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)
        planet = dict(get_homeworld(player_id=uid))
        planet["metal"] = 1e12
        planet["crystal"] = 1e12
        planet["fuel_cells"] = 1e9
        buildings = get_planet_buildings(pid)

        rows = get_buildings_panel_rows(planet, buildings, active_tab="military")
        yard = next((r for r in rows.get("military", []) if r["key"] == "orbital_shipyard"), None)
        assert yard is not None
        assert yard.get("stellar_forge_unlocked") is True


class TestStellarForgeApiIdempotent:
    def test_start_and_ascend_request_id_idempotent(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)
        _fund_planet(pid)

        import app as app_module

        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = uid

        rid = f"forge-start-{uuid.uuid4().hex}"
        r1 = client.post("/api/shipyard/forge-campaign/start", json={"request_id": rid})
        assert r1.status_code == 200
        j1 = r1.get_json()
        assert j1["ok"] is True

        r2 = client.post("/api/shipyard/forge-campaign/start", json={"request_id": rid})
        assert r2.status_code == 200
        j2 = r2.get_json()
        assert j2["ok"] is True
        state = get_raw_state(pid)
        assert state["campaign_active"] is True

    def test_forge_campaign_get_state(self, forge_db):
        from game.models import get_homeworld

        uid = forge_db
        planet = get_homeworld(player_id=uid)
        pid = int(planet["id"])
        _max_out_shipyard(pid)

        import app as app_module

        app_module.app.config["TESTING"] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = uid

        r = client.get("/api/shipyard/forge-campaign")
        assert r.status_code == 200
        j = r.get_json()
        assert j["ok"] is True
        assert j["forge"]["stellar_forge_unlocked"] is True


class TestStellarForgeDocs:
    def test_master_doc_and_owner_listed(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        doc = (root / "docs" / "STELLAR_FORGE.md").read_text(encoding="utf-8")
        assert "Tribute" in doc
        assert "Hull Mass" in doc
        assert "Forge Cores" in doc
        assert "GC-3001" in doc
        core = (root / "docs" / "CORE_ARCHITECTURE.md").read_text(encoding="utf-8")
        assert "game/stellar_forge/" in core
        assert "STELLAR_FORGE.md" in core
        epics = (root / "docs" / "EPICS.md").read_text(encoding="utf-8")
        assert "EPIC-30" in epics
