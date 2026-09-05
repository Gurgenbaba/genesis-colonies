#!/usr/bin/env python3
"""Read-only PostgreSQL numeric readiness audit.

Queries schema metadata only (information_schema.columns). It never reads
gameplay rows, player values, secrets, balances, or payload contents.

Usage:
    GC_DB_BACKEND=postgres DATABASE_URL=... python scripts/pg_numeric_readiness_audit.py
    ... --json
    ... --strict   # non-zero when P0/P1 policy violations are present
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class NumericPolicy:
    table: str
    column: str
    contract: str
    priority: str
    note: str


# Contracts:
#   exact_unbounded  -> exact economy/value, arbitrary GC scale
#   exact_snapshot   -> lossless paid snapshot; TEXT/NUMERIC are canonical
#   at_least_i64     -> current operational floor; BIGINT is accepted but finite
#   decimal_rate     -> fractional value allowed, but exact decimal preferred
#   bounded_int      -> explicitly bounded counter / configuration (not audited here)
POLICIES: tuple[NumericPolicy, ...] = (
    # P0 core resources / economy.
    NumericPolicy("planets", "metal", "exact_unbounded", "P0", "primary resource balance"),
    NumericPolicy("planets", "crystal", "exact_unbounded", "P0", "primary resource balance"),
    NumericPolicy("planets", "fuel_cells", "exact_unbounded", "P0", "primary resource balance"),
    NumericPolicy("exchange_log", "give_amount", "exact_unbounded", "P0", "trader amount"),
    NumericPolicy("exchange_log", "receive_amount", "exact_unbounded", "P0", "trader amount"),
    NumericPolicy("players", "exchange_daily_used", "exact_unbounded", "P0", "trader daily amount"),
    NumericPolicy("planets", "fuel_exchange_daily_used", "exact_unbounded", "P0", "fuel trader daily amount"),
    NumericPolicy("debris_fields", "metal", "exact_unbounded", "P0", "debris resource"),
    NumericPolicy("debris_fields", "crystal", "exact_unbounded", "P0", "debris resource"),
    NumericPolicy("asteroid_fields", "metal", "exact_unbounded", "P0", "asteroid resource"),
    NumericPolicy("asteroid_fields", "crystal", "exact_unbounded", "P0", "asteroid resource"),
    NumericPolicy("asteroid_fields", "fuel_cells", "exact_unbounded", "P0", "asteroid resource"),
    NumericPolicy("asteroid_field_claims", "metal", "exact_unbounded", "P0", "asteroid claim resource"),
    NumericPolicy("asteroid_field_claims", "crystal", "exact_unbounded", "P0", "asteroid claim resource"),
    NumericPolicy("asteroid_field_claims", "fuel_cells", "exact_unbounded", "P0", "asteroid claim resource"),

    # P0 auctions.
    NumericPolicy("auction_house_listings", "start_price", "exact_unbounded", "P0", "resource-denominated price"),
    NumericPolicy("auction_house_listings", "current_bid", "exact_unbounded", "P0", "resource-denominated bid"),
    NumericPolicy("auction_house_bids", "amount", "exact_unbounded", "P0", "resource-denominated bid"),

    # P0 alliance economy.
    NumericPolicy("alliances", "pool_metal", "exact_unbounded", "P0", "alliance resource pool"),
    NumericPolicy("alliances", "pool_crystal", "exact_unbounded", "P0", "alliance resource pool"),
    NumericPolicy("alliances", "pool_fuel_cells", "exact_unbounded", "P0", "alliance resource pool"),
    NumericPolicy("alliance_donations", "amount", "exact_unbounded", "P0", "resource donation"),
    NumericPolicy("alliance_projects", "cost_metal", "exact_snapshot", "P0", "project paid cost"),
    NumericPolicy("alliance_projects", "cost_crystal", "exact_snapshot", "P0", "project paid cost"),
    NumericPolicy("alliance_projects", "cost_fuel_cells", "exact_snapshot", "P0", "project paid cost"),

    # Queue paid-cost contracts.
    NumericPolicy("build_queue", "cost_metal_exact", "exact_snapshot", "P0", "exact build paid cost"),
    NumericPolicy("build_queue", "cost_crystal_exact", "exact_snapshot", "P0", "exact build paid cost"),
    NumericPolicy("research_queue", "cost_metal_exact", "exact_snapshot", "P0", "exact research paid cost"),
    NumericPolicy("research_queue", "cost_crystal_exact", "exact_snapshot", "P0", "exact research paid cost"),
    NumericPolicy("shipyard_queue", "cost_metal_exact", "exact_snapshot", "P0", "exact shipyard batch paid cost"),
    NumericPolicy("shipyard_queue", "cost_crystal_exact", "exact_snapshot", "P0", "exact shipyard batch paid cost"),
    NumericPolicy("shipyard_queue", "cost_fuel_cells_exact", "exact_snapshot", "P0", "exact shipyard batch paid cost"),
    NumericPolicy("defense_queue", "cost_metal_exact", "exact_snapshot", "P0", "exact defense batch paid cost"),
    NumericPolicy("defense_queue", "cost_crystal_exact", "exact_snapshot", "P0", "exact defense batch paid cost"),
    NumericPolicy("defense_queue", "cost_fuel_cells_exact", "exact_snapshot", "P0", "exact defense batch paid cost"),
    NumericPolicy("troop_queue", "cost_metal_exact", "exact_snapshot", "P1", "exact troop batch paid cost"),
    NumericPolicy("troop_queue", "cost_crystal_exact", "exact_snapshot", "P1", "exact troop batch paid cost"),

    # Stock / queue amounts.
    NumericPolicy("planet_ships", "amount", "at_least_i64", "P1", "ship stock"),
    NumericPolicy("shipyard_queue", "amount", "at_least_i64", "P1", "ship order quantity"),
    NumericPolicy("planet_defense", "amount", "at_least_i64", "P1", "defense stock"),
    NumericPolicy("defense_queue", "amount", "at_least_i64", "P0", "defense order quantity"),
    NumericPolicy("planet_troops", "amount", "at_least_i64", "P0", "troop stock"),
    NumericPolicy("troop_queue", "amount", "at_least_i64", "P0", "troop order quantity"),

    # Boss/combat/value growth.
    NumericPolicy("world_boss_definitions", "max_hp", "at_least_i64", "P1", "boss HP definition"),
    NumericPolicy("world_boss_events", "max_hp", "at_least_i64", "P1", "boss event HP"),
    NumericPolicy("world_boss_events", "current_hp", "at_least_i64", "P1", "boss event HP"),
    NumericPolicy("world_boss_contributions", "damage", "at_least_i64", "P1", "boss lifetime event damage"),
    NumericPolicy("pirate_bases", "max_hp", "at_least_i64", "P1", "pirate boss max HP"),
    NumericPolicy("pirate_bases", "current_hp", "at_least_i64", "P1", "pirate boss current HP"),
    NumericPolicy("pirate_base_contributions", "damage", "at_least_i64", "P1", "pirate boss damage"),
    NumericPolicy("combat_hall_of_fame", "attacker_loss_score", "at_least_i64", "P1", "combat loss value"),
    NumericPolicy("combat_hall_of_fame", "defender_loss_score", "at_least_i64", "P1", "combat loss value"),
    NumericPolicy("combat_hall_of_fame", "total_destroyed_score", "at_least_i64", "P1", "combat value"),

    # Imperial Directives / Case Battle values mentioned by the binding audit doc.
    NumericPolicy("player_directives", "target_value", "at_least_i64", "P1", "directive target"),
    NumericPolicy("player_directives", "progress_value", "at_least_i64", "P1", "directive progress"),
    NumericPolicy("directive_progress", "delta", "at_least_i64", "P1", "directive progress event delta"),
    NumericPolicy("case_battles", "total_battle_value", "at_least_i64", "P1", "case battle aggregate value"),
    NumericPolicy("case_battle_rolls", "reward_amount", "at_least_i64", "P1", "case battle reward quantity"),
    NumericPolicy("case_battle_rolls", "reward_value", "at_least_i64", "P1", "case battle reward value"),

    # Existing widened aggregates.
    NumericPolicy("expedition_daily_value", "expo_value_total", "at_least_i64", "P1", "expedition aggregate"),
    NumericPolicy("expedition_daily_recorded", "expo_value", "at_least_i64", "P1", "expedition aggregate"),
    NumericPolicy("pirate_intel", "resources_score", "at_least_i64", "P1", "pirate intel value"),
    NumericPolicy("pirate_intel", "fleet_score", "at_least_i64", "P1", "pirate intel value"),
    NumericPolicy("pirate_intel", "defense_score", "at_least_i64", "P1", "pirate intel value"),

    # Planet Evolution economic decimals.
    NumericPolicy("planet_special_resources", "amount", "exact_unbounded", "P1", "special resource balance"),
    NumericPolicy("planet_special_resources", "cap", "exact_unbounded", "P1", "special resource cap"),
    NumericPolicy("planet_special_resources", "production_per_hour", "decimal_rate", "P1", "special resource rate"),
    NumericPolicy("planet_special_resources", "consumption_per_hour", "decimal_rate", "P1", "special resource rate"),
    NumericPolicy("planet_trade_routes", "amount_per_hour", "decimal_rate", "P1", "trade rate"),
    NumericPolicy("planet_import_demands", "required_per_hour", "decimal_rate", "P1", "import demand rate"),

    # Known good arbitrary score persistence.
    NumericPolicy("player_scores", "score_total", "exact_snapshot", "P1", "arbitrary score"),
    NumericPolicy("player_scores", "score_resources", "exact_snapshot", "P1", "arbitrary score"),
    NumericPolicy("player_scores", "score_buildings", "exact_snapshot", "P1", "arbitrary score"),
    NumericPolicy("player_scores", "score_research", "exact_snapshot", "P1", "arbitrary score"),
    NumericPolicy("player_scores", "score_fleet", "exact_snapshot", "P1", "arbitrary score"),
    NumericPolicy("player_scores", "score_defense", "exact_snapshot", "P1", "arbitrary score"),
)


def normalize_type(data_type: str | None) -> str:
    return str(data_type or "").strip().lower()


def classify_type(
    data_type: str | None,
    contract: str,
    *,
    numeric_precision: int | None = None,
    numeric_scale: int | None = None,
) -> tuple[str, str]:
    """Return (status, reason) from information_schema numeric metadata."""
    t = normalize_type(data_type)
    exact = {"numeric", "decimal"}
    bigint = {"bigint", "int8"}
    int4 = {"integer", "int", "int4", "smallint", "int2"}
    floating = {"double precision", "real", "float", "float4", "float8"}

    if not t:
        return "missing", "column missing"

    if t in exact:
        constrained = numeric_precision is not None
        scale = None if numeric_scale is None else int(numeric_scale)
        precision = None if numeric_precision is None else int(numeric_precision)

        if contract in {"exact_unbounded", "exact_snapshot"}:
            if constrained:
                return (
                    "limited",
                    f"exact but finite NUMERIC({precision},{scale if scale is not None else '?'}) ceiling",
                )
            return "ready", "unconstrained exact SQL numeric"

        if contract == "at_least_i64":
            if not constrained:
                return "ready", "unconstrained exact SQL numeric"
            integer_digits = precision - max(scale or 0, 0)
            if integer_digits >= 19:
                return "ready", f"exact NUMERIC with {integer_digits} integer digits"
            return "not_ready", f"NUMERIC provides only {integer_digits} integer digits (<19)"

        if contract == "decimal_rate":
            if constrained and (scale is None or scale <= 0):
                return "not_ready", "NUMERIC scale must be > 0 for intended fractional rates"
            return "ready", "exact decimal rate"

    if contract == "exact_unbounded":
        if t == "text":
            return "limited", "exact storage but SQL arithmetic needs casts/Python"
        if t in bigint:
            return "limited", "exact but finite signed 64-bit ceiling"
        if t in floating:
            return "not_ready", "IEEE-754 integer precision loss above 2^53"
        if t in int4:
            return "not_ready", "PostgreSQL int4 ceiling"
        return "review", f"unclassified type {t}"

    if contract == "exact_snapshot":
        if t == "text":
            return "ready", "lossless exact snapshot"
        if t in bigint:
            return "limited", "exact but finite signed 64-bit ceiling"
        if t in floating:
            return "not_ready", "paid snapshot can lose integer precision"
        if t in int4:
            return "not_ready", "paid snapshot can overflow int4"
        return "review", f"unclassified type {t}"

    if contract == "at_least_i64":
        if t == "text":
            return "ready", "meets/exceeds i64 floor"
        if t in bigint:
            return "limited", "meets i64 floor but remains finite"
        if t in int4:
            return "not_ready", "below required i64 floor"
        if t in floating:
            return "not_ready", "integer quantity stored approximately"
        return "review", f"unclassified type {t}"

    if contract == "decimal_rate":
        if t in floating:
            return "limited", "fractional rate works but is approximate"
        if t in bigint or t in int4:
            return "review", "integer type may reject intended fractions"
        return "review", f"unclassified type {t}"

    return "review", f"unknown contract {contract}"

def _load_schema_columns(conn) -> dict[tuple[str, str], dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position;
        """
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cur.fetchall() or []:
        item = dict(row)
        out[(str(item["table_name"]), str(item["column_name"]))] = item
    return out


def audit_schema(columns: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        meta = columns.get((policy.table, policy.column))
        data_type = str((meta or {}).get("data_type") or "")
        status, reason = classify_type(
            data_type,
            policy.contract,
            numeric_precision=(meta or {}).get("numeric_precision"),
            numeric_scale=(meta or {}).get("numeric_scale"),
        )
        rows.append(
            {
                **asdict(policy),
                "data_type": data_type or None,
                "numeric_precision": (meta or {}).get("numeric_precision"),
                "numeric_scale": (meta or {}).get("numeric_scale"),
                "status": status,
                "reason": reason,
            }
        )
    return rows


def _summary(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get("status") or "unknown")
        result[key] = result.get(key, 0) + 1
    return result


def _print_human(rows: list[dict[str, Any]]) -> None:
    summary = _summary(rows)
    print("Genesis Colonies PostgreSQL Numeric Readiness")
    print("=" * 72)
    print("Schema metadata only; no gameplay values queried.")
    print("Summary:", " ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    print()
    for priority in ("P0", "P1", "P2"):
        group = [r for r in rows if r["priority"] == priority]
        if not group:
            continue
        print(priority)
        print("-" * 72)
        for row in group:
            print(
                f'{row["status"]:>10}  {row["table"]}.{row["column"]} '
                f'[{row["data_type"] or "MISSING"}]  {row["contract"]}  '
                f'- {row["reason"]}'
            )
        print()


def is_strict_violation(row: dict[str, Any]) -> bool:
    """Strict mode fails every P0/P1 contract that is not actually satisfied."""
    if row.get("priority") not in {"P0", "P1"}:
        return False
    status = str(row.get("status") or "")
    contract = str(row.get("contract") or "")
    if status in {"not_ready", "missing", "review"}:
        return True
    if status == "limited" and contract in {"exact_unbounded", "exact_snapshot"}:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 2 when a P0/P1 numeric contract is not fully satisfied",
    )
    args = parser.parse_args()

    from game.config import init_config
    from game.db import db, get_db_backend

    init_config()
    if get_db_backend() != "postgres":
        print("ERROR: numeric readiness runtime audit requires GC_DB_BACKEND=postgres", file=sys.stderr)
        return 3

    conn = db()
    try:
        rows = audit_schema(_load_schema_columns(conn))
    finally:
        conn.close()

    payload = {"summary": _summary(rows), "rows": rows}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(rows)

    if args.strict and any(is_strict_violation(row) for row in rows):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
