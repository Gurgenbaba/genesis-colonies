from __future__ import annotations

import sqlite3
from pathlib import Path

from game.planet_evolution.impact import mechanics_impact_rows
from game.planet_evolution.mechanics import (
    PE_CANONICAL_MECHANICS_KEYS,
    PE_DIRECT_MECHANICS_KEYS_BY_DOMAIN,
    _parse_mechanics_json,
    is_supported_mechanics_key,
)


def test_discovery_roll_mult_is_canonical_and_player_visible():
    assert "discovery_roll_mult" in PE_CANONICAL_MECHANICS_KEYS
    bundle = _parse_mechanics_json({"discovery_roll_mult": 2.0})
    assert bundle["flags"]["discovery_roll_mult"] == 2.0
    rows = mechanics_impact_rows({"discovery_roll_mult": 2.0})
    row = next(r for r in rows if r.get("target") == "discovery_roll_mult")
    assert row["label_key"] == "pe_impact_effect_discovery_chance"
    assert row["scope_key"] == "pe_impact_scope_discoveries"
    assert row["value"] == "+100%"


def test_direct_domain_consumers_are_explicit_not_generic():
    assert "choice_required" not in PE_CANONICAL_MECHANICS_KEYS
    assert "choice_required" in PE_DIRECT_MECHANICS_KEYS_BY_DOMAIN["research"]
    assert is_supported_mechanics_key("choice_required", domain="research")
    assert not is_supported_mechanics_key("choice_required", domain="policy")
    assert "import_demands" in PE_DIRECT_MECHANICS_KEYS_BY_DOMAIN["specialization"]
    assert is_supported_mechanics_key("import_demands", domain="specialization")


def test_discovery_roll_mult_changes_authoritative_roll(monkeypatch):
    from game.planet_evolution import discoveries

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE planet_discoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planet_id INTEGER NOT NULL,
            discovery_key TEXT NOT NULL,
            rarity TEXT NOT NULL,
            discovered_at REAL NOT NULL,
            announced_globally INTEGER NOT NULL DEFAULT 0,
            effects_applied_json TEXT
        );
        """
    )

    ddef = {
        "discovery_key": "contract_probe",
        "rarity": "common",
        "roll_weight": 0.10,
        "requirements": {},
        "announce_global": 0,
        "label_key": "discovery_contract_probe",
    }
    monkeypatch.setattr(discoveries, "get_planet_row", lambda *_a, **_k: {})
    monkeypatch.setattr(discoveries, "get_discoveries", lambda *_a, **_k: [])
    monkeypatch.setattr(discoveries, "get_discoveries_defs", lambda: {"contract_probe": ddef})
    monkeypatch.setattr(discoveries, "get_discovery_def", lambda _key: ddef)
    monkeypatch.setattr(discoveries, "check_requirements", lambda *_a, **_k: (True, {}))
    monkeypatch.setattr(discoveries, "_stable_roll", lambda *_a, **_k: 0.15)
    monkeypatch.setattr(
        discoveries,
        "get_flag",
        lambda _pid, flag, default=None, conn=None: 2.0 if flag == "discovery_roll_mult" else 0.0,
    )
    monkeypatch.setattr(discoveries, "append_history", lambda *_a, **_k: None)
    monkeypatch.setattr(discoveries, "compile_planet_mechanics", lambda *_a, **_k: {})
    monkeypatch.setattr(discoveries, "add_planet_xp", lambda *_a, **_k: None)

    result = discoveries.try_roll_discovery(7, conn, source="contract-test")
    assert result and result["discovery_key"] == "contract_probe"
    conn.close()


def test_reconciliation_migration_removes_known_ghost_keys():
    sql = (Path(__file__).resolve().parents[1] / "migrations/156_pe_mechanics_contract_reconciliation.sql").read_text(encoding="utf-8")
    for owner in (
        "industry_t4_mass_foundry",
        "industry_t5_overdrive",
        "black_market_tolerated",
        "martial_law",
        "closed_borders",
        "living_crystal_network",
        "quantum_rift",
        "ancient_ai",
        "industrial_ascension",
        "quantum_ascension",
        "machine_ascension",
        "ancient_ascension",
    ):
        assert owner in sql
    assert '"discovery_roll_mult":2.0' in sql
    for ghost in (
        "ancient_t6_unlock",
        "contraband_output_bonus",
        "conversion_batch_bonus",
        "defense_mechanic",
        "depletion_risk_mult",
        "export_penalty",
        "high_value_target",
        "import_penalty_immunity",
        "loyalty_mechanic_bypass",
        "output_bonus",
        "quantum_instability",
        "random_research_complete",
        "rebellion_risk",
        "risk_event",
    ):
        # Comments may name the policy, but active JSON written by migration may not retain it.
        assert f'"{ghost}"' not in sql


def test_active_migrated_definition_contract(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    from game import db as gdb

    db_path = tmp_path / "contract.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    gdb._DB_PATH = None

    from game.models import db, init_db
    import migrate
    from game.planet_evolution.definitions import (
        get_ascensions,
        get_discoveries_defs,
        get_policies,
        get_research_defs,
        get_specializations,
        reload_definitions,
    )

    init_db()
    migrate.main()
    conn = db()
    try:
        reload_definitions(conn)
        unknown = []
        for owner, row in get_research_defs().items():
            for key in (row.get("mechanics") or {}):
                if not is_supported_mechanics_key(key, domain="research"):
                    unknown.append(("research", owner, key))
        for owner, row in get_policies().items():
            for key in (row.get("mechanics") or {}):
                if not is_supported_mechanics_key(key, domain="policy"):
                    unknown.append(("policy", owner, key))
        for owner, row in get_discoveries_defs().items():
            for key in (row.get("mechanics") or {}):
                if not is_supported_mechanics_key(key, domain="discovery"):
                    unknown.append(("discovery", owner, key))
        for owner, row in get_ascensions().items():
            for key in (row.get("permanent_mechanics") or {}):
                if not is_supported_mechanics_key(key, domain="ascension"):
                    unknown.append(("ascension", owner, key))
        for owner, row in get_specializations().items():
            for tier_key, tier in (row.get("tier_mechanics") or {}).items():
                if not isinstance(tier, dict):
                    continue
                for key in tier:
                    if not is_supported_mechanics_key(key, domain="specialization"):
                        unknown.append((f"specialization:{tier_key}", owner, key))
        assert unknown == []
        quantum = get_ascensions()["quantum_ascension"]["permanent_mechanics"]
        assert quantum == {"experimental_slot": 2, "discovery_roll_mult": 2.0}
    finally:
        conn.close()
        gdb._DB_PATH = None
