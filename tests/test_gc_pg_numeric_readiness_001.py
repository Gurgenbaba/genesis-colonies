"""GC-PG-NUMERIC-READINESS-001 — schema/type policy regression gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pg_numeric_readiness_audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("gc_pg_numeric_audit", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_critical_p0_numeric_domains_are_in_policy():
    mod = _load_audit_module()
    keys = {(p.table, p.column) for p in mod.POLICIES}
    required = {
        ("planets", "metal"),
        ("planets", "crystal"),
        ("planets", "fuel_cells"),
        ("auction_house_bids", "amount"),
        ("auction_house_listings", "current_bid"),
        ("alliances", "pool_metal"),
        ("defense_queue", "amount"),
        ("defense_queue", "cost_metal"),
        ("planet_troops", "amount"),
        ("troop_queue", "amount"),
        ("shipyard_queue", "cost_metal"),
        ("shipyard_queue", "cost_fuel_cells"),
        ("research_queue", "cost_metal"),
        ("build_queue", "cost_metal_exact"),
        ("debris_fields", "metal"),
        ("asteroid_fields", "metal"),
    }
    assert required <= keys


def test_classifier_distinguishes_int4_bigint_double_numeric_and_text():
    mod = _load_audit_module()

    assert mod.classify_type("numeric", "exact_unbounded")[0] == "ready"
    assert mod.classify_type("double precision", "exact_unbounded")[0] == "not_ready"
    assert mod.classify_type("integer", "exact_unbounded")[0] == "not_ready"
    assert mod.classify_type("bigint", "exact_unbounded")[0] == "limited"

    assert mod.classify_type("text", "exact_snapshot")[0] == "ready"
    assert mod.classify_type("bigint", "exact_snapshot")[0] == "limited"
    assert mod.classify_type("double precision", "exact_snapshot")[0] == "not_ready"

    assert mod.classify_type("integer", "at_least_i64")[0] == "not_ready"
    assert mod.classify_type("bigint", "at_least_i64")[0] == "limited"
    assert mod.classify_type("numeric", "at_least_i64")[0] == "ready"


def test_runtime_auditor_is_schema_metadata_only():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "information_schema.columns" in src
    # Runtime metadata query must not SELECT balances/rows from gameplay tables.
    query = src.split("def _load_schema_columns", 1)[1].split("def audit_schema", 1)[0]
    assert "FROM information_schema.columns" in query
    for forbidden in (
        "FROM planets",
        "FROM player_scores",
        "FROM shipyard_queue",
        "FROM auction_house_bids",
        "FROM alliance_donations",
    ):
        assert forbidden not in query


def test_audit_marks_known_current_types_as_expected():
    mod = _load_audit_module()
    columns = {
        ("planets", "metal"): {"data_type": "double precision"},
        ("auction_house_bids", "amount"): {"data_type": "integer"},
        ("planet_ships", "amount"): {"data_type": "bigint"},
        ("build_queue", "cost_metal_exact"): {"data_type": "text"},
        ("player_scores", "score_total"): {"data_type": "text"},
    }
    rows = {
        (r["table"], r["column"]): r
        for r in mod.audit_schema(columns)
    }
    assert rows[("planets", "metal")]["status"] == "not_ready"
    assert rows[("auction_house_bids", "amount")]["status"] == "not_ready"
    assert rows[("planet_ships", "amount")]["status"] == "limited"
    assert rows[("build_queue", "cost_metal_exact")]["status"] == "ready"
    assert rows[("player_scores", "score_total")]["status"] == "ready"
