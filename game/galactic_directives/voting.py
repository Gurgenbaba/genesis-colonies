"""Galactic directive voting cycles — monthly galaxy-scoped elections (GC-720G)."""

from __future__ import annotations

import calendar
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..db import begin_write_transaction, commit, db
from .definitions import (
    get_directive_definition,
    list_directive_definitions,
    normalize_directive_key,
    schema_ready,
)
from .state import (
    FALLBACK_PRIMARY,
    ensure_galaxy_state,
    get_active_directives_for_galaxy,
    get_player_vote_galaxies,
    normalize_galaxy,
)

PHASE_VOTE_OPEN = "vote_open"
PHASE_ACTIVE = "active"
PHASE_RESOLVED = "resolved"


def _utc_ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp())


def _calendar_parts(ts: int) -> Tuple[int, int]:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return int(dt.year), int(dt.month)


def _next_month(year: int, month: int) -> Tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def _ym_key(year: int, month: int) -> str:
    return f"{int(year):04d}{int(month):02d}"


def _cycle_timestamps(year: int, month: int) -> Dict[str, int]:
    """
    Monthly politics schedule (GC-720 launch):

    - Vote open for the **entire calendar month** (day 1 → last day).
    - After vote_end, resolve winners; mandate is active for the **following** month.
    """
    last_day = calendar.monthrange(int(year), int(month))[1]
    next_year, next_month = _next_month(int(year), int(month))
    next_last = calendar.monthrange(next_year, next_month)[1]
    return {
        "vote_start_at": _utc_ts(year, month, 1, 0, 0, 0),
        "vote_end_at": _utc_ts(year, month, last_day, 23, 59, 59),
        "effect_start_at": _utc_ts(next_year, next_month, 1, 0, 0, 0),
        "effect_end_at": _utc_ts(next_year, next_month, next_last, 23, 59, 59),
    }


def _row_to_cycle(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else dict(row)


def _sync_open_cycle_timestamps(
    cycle: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Dict[str, Any]:
    """
    Keep unfinished current-month cycles on the full-month vote window.

    Also re-opens auto-resolved zero-vote cycles so players can vote immediately
    after the schedule change (mid-month launch).
    """
    stamps = _cycle_timestamps(int(cycle["year"]), int(cycle["month"]))
    total_votes = int(cycle.get("total_votes") or 0)
    has_winner = bool(cycle.get("winning_primary"))
    needs_stamp_sync = (
        int(cycle.get("vote_end_at") or 0) != int(stamps["vote_end_at"])
        or int(cycle.get("effect_start_at") or 0) != int(stamps["effect_start_at"])
        or int(cycle.get("effect_end_at") or 0) != int(stamps["effect_end_at"])
    )
    reopen_empty = has_winner and total_votes == 0 and int(stamps["vote_end_at"]) >= int(now)
    if not needs_stamp_sync and not reopen_empty:
        return cycle

    begin_write_transaction(conn)
    if reopen_empty:
        conn.execute(
            """
            UPDATE gd_cycles
            SET vote_start_at = ?,
                vote_end_at = ?,
                effect_start_at = ?,
                effect_end_at = ?,
                winning_primary = NULL,
                winning_secondary = NULL,
                winning_primary_votes = 0,
                winning_secondary_votes = 0,
                total_votes = 0,
                total_voters = 0,
                is_tie_primary = 0,
                is_tie_secondary = 0,
                results_sent = 0,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                stamps["vote_start_at"],
                stamps["vote_end_at"],
                stamps["effect_start_at"],
                stamps["effect_end_at"],
                PHASE_VOTE_OPEN,
                now,
                int(cycle["id"]),
            ),
        )
    else:
        phase = get_vote_phase(
            {
                "vote_end_at": stamps["vote_end_at"],
                "effect_end_at": stamps["effect_end_at"],
            },
            now,
        )
        # Real winners stay resolved/active; only unfinished cycles follow new phase.
        status = str(cycle.get("status") or phase) if has_winner else phase
        conn.execute(
            """
            UPDATE gd_cycles
            SET vote_start_at = ?,
                vote_end_at = ?,
                effect_start_at = ?,
                effect_end_at = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                stamps["vote_start_at"],
                stamps["vote_end_at"],
                stamps["effect_start_at"],
                stamps["effect_end_at"],
                status,
                now,
                int(cycle["id"]),
            ),
        )
    commit(conn)
    refreshed = _fetch_cycle(int(cycle["galaxy"]), int(cycle["year"]), int(cycle["month"]), conn)
    return refreshed or cycle


def get_vote_phase(cycle: Dict[str, Any], now: Optional[int] = None) -> str:
    """Return vote_open, active, or resolved for a cycle row."""
    ts = int(now if now is not None else time.time())
    vote_end = int(cycle.get("vote_end_at") or 0)
    effect_end = int(cycle.get("effect_end_at") or 0)
    if ts <= vote_end:
        return PHASE_VOTE_OPEN
    if ts <= effect_end:
        return PHASE_ACTIVE
    return PHASE_RESOLVED


def _fetch_cycle(galaxy: int, year: int, month: int, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ? AND year = ? AND month = ?
        LIMIT 1;
        """,
        (int(galaxy), int(year), int(month)),
    ).fetchone()
    return _row_to_cycle(row) if row else None


def _sync_cycle_status(cycle: Dict[str, Any], *, conn: sqlite3.Connection, now: int) -> Dict[str, Any]:
    phase = get_vote_phase(cycle, now)
    stored = str(cycle.get("status") or "")
    if stored == phase:
        return cycle
    conn.execute(
        "UPDATE gd_cycles SET status = ?, updated_at = ? WHERE id = ?;",
        (phase, now, int(cycle["id"])),
    )
    commit(conn)
    cycle = dict(cycle)
    cycle["status"] = phase
    cycle["updated_at"] = now
    return cycle


def _resolve_overdue_cycles(galaxy_id: int, *, conn: sqlite3.Connection, now: int) -> None:
    rows = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ?
          AND (
            (status != ? AND effect_end_at < ?)
            OR (status = ? AND vote_end_at < ? AND winning_primary IS NULL)
            OR (status = ? AND vote_end_at < ? AND effect_end_at >= ?)
          )
        ORDER BY year ASC, month ASC;
        """,
        (
            int(galaxy_id),
            PHASE_RESOLVED,
            now,
            PHASE_VOTE_OPEN,
            now,
            PHASE_VOTE_OPEN,
            now,
            now,
        ),
    ).fetchall()
    for row in rows:
        cycle = _row_to_cycle(row)
        if int(cycle.get("vote_end_at") or 0) < now and not cycle.get("winning_primary"):
            resolve_directive_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn=conn, now=now)
            cycle = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn) or cycle
        if get_vote_phase(cycle, now) == PHASE_RESOLVED and str(cycle.get("status")) != PHASE_RESOLVED:
            _sync_cycle_status(cycle, conn=conn, now=now)


def get_or_create_current_cycle(
    galaxy: Any,
    now: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Return the current calendar-month cycle for a galaxy, creating it if needed."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return None

        _resolve_overdue_cycles(galaxy_id, conn=conn, now=ts)
        year, month = _calendar_parts(ts)
        cycle = _fetch_cycle(galaxy_id, year, month, conn)
        if cycle is None:
            stamps = _cycle_timestamps(year, month)
            phase = get_vote_phase({**stamps}, ts)
            begin_write_transaction(conn)
            try:
                conn.execute(
                    """
                    INSERT INTO gd_cycles (
                        galaxy, year, month,
                        vote_start_at, vote_end_at, effect_start_at, effect_end_at,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        galaxy_id,
                        year,
                        month,
                        stamps["vote_start_at"],
                        stamps["vote_end_at"],
                        stamps["effect_start_at"],
                        stamps["effect_end_at"],
                        phase,
                        ts,
                        ts,
                    ),
                )
                commit(conn)
            except sqlite3.IntegrityError:
                pass
            cycle = _fetch_cycle(galaxy_id, year, month, conn)

        if cycle is None:
            return None

        # Mid-month launch / schedule migration: keep unfinished cycles vote_open.
        cycle = _sync_open_cycle_timestamps(cycle, conn=conn, now=ts)

        if int(cycle.get("vote_end_at") or 0) < ts and not cycle.get("winning_primary"):
            resolve_directive_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn=conn, now=ts)
            cycle = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn) or cycle

        return _sync_cycle_status(cycle, conn=conn, now=ts)
    finally:
        if own_conn:
            conn.close()


def _tally_votes(cycle_id: int, conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT directive_key, COUNT(*) AS vote_count
        FROM gd_votes
        WHERE cycle_id = ?
        GROUP BY directive_key
        ORDER BY vote_count DESC, directive_key ASC;
        """,
        (int(cycle_id),),
    ).fetchall()
    out: List[Tuple[str, int]] = []
    for row in rows:
        key = normalize_directive_key(row["directive_key"])
        if not key:
            continue
        out.append((key, int(row["vote_count"] or 0)))
    return out


def _pick_from_tied(candidates: List[str]) -> str:
    if not candidates:
        return FALLBACK_PRIMARY
    return random.choice(candidates)


def _resolve_winners(
    tallies: List[Tuple[str, int]],
) -> Tuple[str, Optional[str], int, int, bool, bool]:
    if not tallies:
        return "", None, 0, 0, False, False

    top_votes = tallies[0][1]
    primary_candidates = [key for key, count in tallies if count == top_votes]
    primary = _pick_from_tied(primary_candidates)
    tie_primary = len(primary_candidates) > 1

    remaining = [(key, count) for key, count in tallies if key != primary]
    secondary: Optional[str] = None
    secondary_votes = 0
    tie_secondary = False
    if remaining:
        second_votes = remaining[0][1]
        secondary_candidates = [key for key, count in remaining if count == second_votes]
        secondary = _pick_from_tied(secondary_candidates)
        secondary_votes = second_votes
        tie_secondary = len(secondary_candidates) > 1

    return primary, secondary, top_votes, secondary_votes, tie_primary, tie_secondary


def _directive_on_cooldown(
    state: Dict[str, Any],
    directive_key: str,
    year: int,
    month: int,
) -> bool:
    cd_key = normalize_directive_key(state.get("cooldown_directive"))
    until = str(state.get("cooldown_until_ym") or "").strip()
    if not cd_key or not until:
        return False
    return cd_key == directive_key and until == _ym_key(year, month)


def resolve_directive_cycle(
    galaxy: Any,
    year: int,
    month: int,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Tally votes for a cycle and write winners into gd_galaxy_state."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return None

        cycle = _fetch_cycle(galaxy_id, int(year), int(month), conn)
        if cycle is None:
            return None

        if int(cycle.get("vote_end_at") or 0) > ts:
            return cycle

        if cycle.get("winning_primary"):
            return _sync_cycle_status(cycle, conn=conn, now=ts)

        state = ensure_galaxy_state(galaxy_id, conn=conn)
        tallies = _tally_votes(int(cycle["id"]), conn)
        total_votes = sum(count for _, count in tallies)
        total_voters = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM gd_votes WHERE cycle_id = ?;",
                (int(cycle["id"]),),
            ).fetchone()["c"]
            or 0
        )

        tie_p = False
        tie_s = False
        if tallies:
            primary, secondary, p_votes, s_votes, tie_p, tie_s = _resolve_winners(tallies)
        else:
            primary = normalize_directive_key(state.get("primary_directive")) or FALLBACK_PRIMARY
            raw_secondary = state.get("secondary_directive")
            secondary = (
                normalize_directive_key(raw_secondary) or None
                if raw_secondary not in (None, "")
                else None
            )
            p_votes = 0
            s_votes = 0

        old_primary = normalize_directive_key(state.get("primary_directive")) or FALLBACK_PRIMARY
        consecutive = int(state.get("consecutive_primary_wins") or 0)
        if primary == old_primary:
            consecutive += 1
        else:
            consecutive = 1 if primary else 0

        cooldown_directive = state.get("cooldown_directive")
        cooldown_until_ym = state.get("cooldown_until_ym")
        if primary and consecutive >= 2:
            next_year, next_month = _next_month(int(year), int(month))
            cooldown_directive = primary
            cooldown_until_ym = _ym_key(next_year, next_month)
            consecutive = 0

        phase = get_vote_phase(cycle, ts)
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE gd_cycles
            SET winning_primary = ?,
                winning_secondary = ?,
                winning_primary_votes = ?,
                winning_secondary_votes = ?,
                total_votes = ?,
                total_voters = ?,
                is_tie_primary = ?,
                is_tie_secondary = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                primary or None,
                secondary,
                int(p_votes),
                int(s_votes),
                int(total_votes),
                int(total_voters),
                1 if tie_p else 0,
                1 if tie_s else 0,
                phase,
                ts,
                int(cycle["id"]),
            ),
        )
        # PG: bare `WHEN ? IS NOT NULL` with a NULL bind → IndeterminateDatatype ($3).
        # Use an explicit 0/1 flag so the parameter type is never ambiguous.
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = ?,
                secondary_directive = ?,
                primary_since = CASE WHEN ? = 1 THEN ? ELSE primary_since END,
                consecutive_primary_wins = ?,
                cooldown_directive = ?,
                cooldown_until_ym = ?,
                last_cycle_id = ?,
                updated_at = ?
            WHERE galaxy = ?;
            """,
            (
                primary or FALLBACK_PRIMARY,
                secondary,
                1 if primary else 0,
                ts,
                int(consecutive),
                cooldown_directive,
                cooldown_until_ym,
                int(cycle["id"]),
                ts,
                galaxy_id,
            ),
        )
        commit(conn)
        refreshed = _fetch_cycle(galaxy_id, int(year), int(month), conn)
        try:
            _refresh_galaxy_personality_from_history(galaxy_id, conn=conn, now=ts)
        except Exception:
            pass
        try:
            from .results import maybe_broadcast_cycle_results

            maybe_broadcast_cycle_results(int(year), int(month), conn=conn, now=ts)
        except Exception:
            pass
        return refreshed
    finally:
        if own_conn:
            conn.close()


def _refresh_galaxy_personality_from_history(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    now: int,
) -> None:
    """Score recent primary winners into galaxy personality (GC-POL / GC-721D)."""
    from ..galactic_diplomacy.personality import (
        infer_personality_key,
        score_directive_history,
        set_galaxy_personality,
    )

    rows = conn.execute(
        """
        SELECT winning_primary FROM gd_cycles
        WHERE galaxy = ?
          AND winning_primary IS NOT NULL
          AND winning_primary != ''
        ORDER BY year ASC, month ASC
        LIMIT 24;
        """,
        (int(galaxy_id),),
    ).fetchall()
    keys = [str(r["winning_primary"]) for r in rows]
    if not keys:
        return
    scores = score_directive_history(keys)
    trait = infer_personality_key(scores)
    if not trait:
        return
    dominance = int(scores.get(trait) or 0)
    set_galaxy_personality(galaxy_id, trait, score=dominance, conn=conn)

def _player_has_vote_right(player_id: int, galaxy_id: int, conn: sqlite3.Connection) -> bool:
    return galaxy_id in get_player_vote_galaxies(int(player_id), conn=conn)


def submit_directive_vote(
    player_id: int,
    galaxy: Any,
    directive_key: str,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Cast or update a player's vote for the current cycle in a galaxy."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    key = normalize_directive_key(directive_key)
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}
    if not key:
        return {"ok": False, "reason": "invalid_directive"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}

        if not _player_has_vote_right(int(player_id), galaxy_id, conn):
            return {"ok": False, "reason": "no_colony"}

        cycle = get_or_create_current_cycle(galaxy_id, now=ts, conn=conn)
        if cycle is None:
            return {"ok": False, "reason": "cycle_unavailable"}

        phase = get_vote_phase(cycle, ts)
        if phase != PHASE_VOTE_OPEN:
            return {"ok": False, "reason": "vote_closed"}

        state = ensure_galaxy_state(galaxy_id, conn=conn)
        if _directive_on_cooldown(state, key, int(cycle["year"]), int(cycle["month"])):
            return {"ok": False, "reason": "cooldown"}

        definition = get_directive_definition(key, conn=conn)
        if definition is None:
            return {"ok": False, "reason": "invalid_directive"}

        eligible = definition.get("eligible_as") or []
        if isinstance(eligible, str):
            eligible = []
        if "primary" not in eligible:
            return {"ok": False, "reason": "invalid_directive"}

        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO gd_votes (cycle_id, galaxy, player_id, directive_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cycle_id, player_id) DO UPDATE SET
                directive_key = excluded.directive_key,
                updated_at = excluded.updated_at;
            """,
            (int(cycle["id"]), galaxy_id, int(player_id), key, ts, ts),
        )
        commit(conn)
        return {"ok": True, "directive": key, "galaxy": galaxy_id, "cycle_id": int(cycle["id"])}
    finally:
        if own_conn:
            conn.close()


def _phase_countdown_seconds(cycle: Dict[str, Any], phase: str, now: int) -> int:
    if phase == PHASE_VOTE_OPEN:
        return max(0, int(cycle.get("vote_end_at") or 0) - now)
    if phase == PHASE_ACTIVE:
        return max(0, int(cycle.get("effect_end_at") or 0) - now)
    return 0


def _vote_tallies_for_cycle(cycle_id: int, conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT directive_key, COUNT(*) AS vote_count
        FROM gd_votes
        WHERE cycle_id = ?
        GROUP BY directive_key;
        """,
        (int(cycle_id),),
    ).fetchall()
    out: Dict[str, int] = {}
    for row in rows:
        key = normalize_directive_key(row["directive_key"])
        if key:
            out[key] = int(row["vote_count"] or 0)
    return out


_DIRECTIVE_MONOGRAMS = {
    "industrial": "IND",
    "scientific": "SCI",
    "military": "MIL",
    "logistics": "LOG",
    "defensive": "DEF",
    "expansion": "EXP",
    "exploration": "XPL",
}

CHRONICLE_LIMIT = 6

# Mechanic key → i18n label for politics tradeoff chips (GC-POL UX).
_TRADEOFF_LABEL_KEYS = {
    "mine_energy_factor": "gd_fx_mine_energy",
    "planet_research_speed_bonus": "gd_fx_planet_research",
    "weapon_bonus": "gd_fx_weapon",
    "shield_bonus": "gd_fx_shield",
    "armor_bonus": "gd_fx_armor",
    "research_time_speed": "gd_fx_research_time",
    "build_time_speed": "gd_fx_build_time",
    "shipyard_time_speed": "gd_fx_shipyard_time",
    "defense_time_speed": "gd_fx_defense_time",
    "metal_prod_factor": "gd_fx_metal_prod",
    "crystal_prod_factor": "gd_fx_crystal_prod",
    "fuel_prod_factor": "gd_fx_fuel_prod",
    "storage_factor": "gd_fx_storage",
    "fleet_speed_multiplier": "gd_fx_fleet_speed",
    "solar_output_factor": "gd_fx_solar",
    "cargo_multiplier": "gd_fx_cargo",
    "fuel_efficiency_factor": "gd_fx_fuel_efficiency",
    "gate_control_active": "gd_fx_gate_control_active",
    # Resolution / emergency / personality / directive flags (same chip path).
    "ban_directive_cycles": "gd_fx_ban_directive_cycles",
    "directive_boost_mult": "gd_fx_directive_boost_mult",
    "trigger_emergency_session": "gd_fx_trigger_emergency_session",
    "bloc_vote_weight_mult": "gd_fx_bloc_vote_weight_mult",
    "trader_daily_limit_mult": "gd_fx_trader_daily_limit_mult",
    "defense_combat_mult": "gd_fx_defense_combat_mult",
    "fleet_attack_bonus": "gd_fx_fleet_attack_bonus",
    "expedition_event_bonus": "gd_fx_expedition_event_bonus",
    "expedition_loot_mult": "gd_fx_expedition_loot_mult",
    "expedition_wreckage_bonus": "gd_fx_expedition_wreckage_bonus",
    "expedition_legendary_bonus": "gd_fx_expedition_legendary_bonus",
    "expedition_slot_bonus": "gd_fx_expedition_slot_bonus",
    "colonize_cost_mult": "gd_fx_colonize_cost_mult",
    "max_colonies_bonus": "gd_fx_max_colonies_bonus",
    "discovery_roll_bonus": "gd_fx_discovery_roll_bonus",
    "scrapyard_yield_mult": "gd_fx_scrapyard_yield_mult",
    "trade_route_speed_mult": "gd_fx_trade_route_speed_mult",
    "planet_xp_mult": "gd_fx_planet_xp_mult",
    "planet_xp_mult_cap_level": "gd_fx_planet_xp_mult_cap_level",
}

# Absolute (non-percent) integer counters — not ratio multipliers.
_TRADEOFF_ABSOLUTE_KEYS = frozenset(
    {
        "max_colonies_bonus",
        "expedition_slot_bonus",
        "planet_xp_mult_cap_level",
    }
)


def _format_tradeoff_display(key: str, value: Any) -> str:
    """Server-authored display string — no client math for meaning."""
    key_l = str(key or "")
    # Boolean / toggle flags: show human status, never raw "1".
    if key_l.endswith("_active") or key_l.startswith("trigger_"):
        try:
            truthy = bool(float(value)) if not isinstance(value, bool) else bool(value)
        except (TypeError, ValueError):
            truthy = bool(value)
        return "AKTIV" if truthy else "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if key_l.endswith("_cycles"):
        return f"{int(num)}×"
    if key_l in _TRADEOFF_ABSOLUTE_KEYS:
        if float(num).is_integer():
            return f"{int(num):+d}" if key_l.endswith("_bonus") else f"{int(num)}"
        return f"{num:g}"
    if key_l.endswith("_bonus") or "bonus" in key_l:
        return f"{num * 100:+.0f}%"
    if any(tok in key_l for tok in ("factor", "multiplier", "mult", "speed")):
        return f"{(num - 1.0) * 100:+.0f}%"
    return f"{num:g}"


def _serialize_tradeoff_chips(tradeoffs: Any) -> List[Dict[str, Any]]:
    if not isinstance(tradeoffs, dict):
        return []
    chips: List[Dict[str, Any]] = []
    for bucket in (
        tradeoffs.get("effect_resolver") if isinstance(tradeoffs.get("effect_resolver"), dict) else {},
        tradeoffs.get("flags") if isinstance(tradeoffs.get("flags"), dict) else {},
    ):
        for tk, tv in bucket.items():
            key = str(tk)
            chips.append(
                {
                    "key": key,
                    "label_key": _TRADEOFF_LABEL_KEYS.get(key, f"gd_fx_{key}"),
                    "display": _format_tradeoff_display(key, tv),
                }
            )
            if len(chips) >= 4:
                return chips
    return chips


def _serialize_directive_option(
    definition: Dict[str, Any],
    *,
    vote_count: int,
    vote_share: float,
    selected: bool,
    on_cooldown: bool,
) -> Dict[str, Any]:
    key = str(definition.get("directive_key") or "")
    tradeoffs = definition.get("tradeoffs") if isinstance(definition.get("tradeoffs"), dict) else {}
    return {
        "key": key,
        "label_key": str(definition.get("label_key") or f"gd_dir_{key}_title"),
        "description_key": str(definition.get("description_key") or f"gd_dir_{key}_desc"),
        "monogram": _DIRECTIVE_MONOGRAMS.get(key, "—"),
        "vote_count": int(vote_count),
        "vote_share": float(vote_share),
        "selected": bool(selected),
        "on_cooldown": bool(on_cooldown),
        "tradeoffs": _serialize_tradeoff_chips(tradeoffs),
    }


def _directive_label_key(key: Optional[str], *, conn: sqlite3.Connection) -> Optional[str]:
    normalized = normalize_directive_key(key) if key else ""
    if not normalized:
        return None
    definition = get_directive_definition(normalized, conn=conn)
    if definition and definition.get("label_key"):
        return str(definition["label_key"])
    return f"gd_dir_{normalized}_title"


def _directive_desc_key(key: Optional[str], *, conn: sqlite3.Connection) -> Optional[str]:
    normalized = normalize_directive_key(key) if key else ""
    if not normalized:
        return None
    definition = get_directive_definition(normalized, conn=conn)
    if definition and definition.get("description_key"):
        return str(definition["description_key"])
    return f"gd_dir_{normalized}_desc"


def _serialize_election_record(
    cycle: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    now: Optional[int] = None,
    in_force: bool = False,
    source: str = "election",
) -> Dict[str, Any]:
    """UI record for a resolved / in-force mandate election (GC-POL-00)."""
    primary = normalize_directive_key(cycle.get("winning_primary")) or None
    secondary = normalize_directive_key(cycle.get("winning_secondary")) or None
    effect_year, effect_month = _next_month(int(cycle["year"]), int(cycle["month"]))
    effect_end = int(cycle.get("effect_end_at") or 0)
    ts = int(now) if now is not None else 0
    countdown = max(0, effect_end - ts) if in_force and effect_end and ts else 0
    return {
        "cycle_id": int(cycle["id"]) if cycle.get("id") is not None else None,
        "election_year": int(cycle["year"]),
        "election_month": int(cycle["month"]),
        "effect_year": int(effect_year),
        "effect_month": int(effect_month),
        "effect_start_at": int(cycle.get("effect_start_at") or 0),
        "effect_end_at": effect_end,
        "countdown_seconds": int(countdown),
        "primary": primary,
        "secondary": secondary,
        "primary_label_key": _directive_label_key(primary, conn=conn),
        "secondary_label_key": _directive_label_key(secondary, conn=conn),
        "primary_description_key": _directive_desc_key(primary, conn=conn),
        "secondary_description_key": _directive_desc_key(secondary, conn=conn),
        "primary_monogram": _DIRECTIVE_MONOGRAMS.get(primary or "", "—"),
        "secondary_monogram": _DIRECTIVE_MONOGRAMS.get(secondary or "", "—") if secondary else None,
        "primary_votes": int(cycle.get("winning_primary_votes") or 0),
        "secondary_votes": int(cycle.get("winning_secondary_votes") or 0),
        "total_votes": int(cycle.get("total_votes") or 0),
        "total_voters": int(cycle.get("total_voters") or 0),
        "is_tie_primary": bool(int(cycle.get("is_tie_primary") or 0)),
        "is_tie_secondary": bool(int(cycle.get("is_tie_secondary") or 0)),
        "in_force": bool(in_force),
        "source": source,
    }


def _fetch_in_force_election(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Optional[Dict[str, Any]]:
    """Cycle whose effect window covers ``now`` and has winners."""
    row = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ?
          AND winning_primary IS NOT NULL
          AND winning_primary != ''
          AND effect_start_at <= ?
          AND effect_end_at >= ?
        ORDER BY year DESC, month DESC
        LIMIT 1;
        """,
        (int(galaxy_id), int(now), int(now)),
    ).fetchone()
    return _row_to_cycle(row) if row else None


def _fetch_latest_election(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    """Most recent resolved election with winners (may be past its effect window)."""
    row = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ?
          AND winning_primary IS NOT NULL
          AND winning_primary != ''
        ORDER BY year DESC, month DESC
        LIMIT 1;
        """,
        (int(galaxy_id),),
    ).fetchone()
    return _row_to_cycle(row) if row else None


def _fetch_chronicle_elections(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    limit: int = CHRONICLE_LIMIT,
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ?
          AND winning_primary IS NOT NULL
          AND winning_primary != ''
        ORDER BY year DESC, month DESC
        LIMIT ?;
        """,
        (int(galaxy_id), int(limit)),
    ).fetchall()
    return [_row_to_cycle(row) for row in rows]


def _build_mandate_payload(
    galaxy_id: int,
    active: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Dict[str, Any]:
    """
    Currently governing mandate for the galaxy.

    Prefer the election whose effect window covers ``now``; otherwise the latest
    election; otherwise state/fallback without election meta.
    """
    in_force = _fetch_in_force_election(galaxy_id, conn=conn, now=now)
    if in_force is not None:
        return _serialize_election_record(
            in_force, conn=conn, now=now, in_force=True, source="election"
        )

    latest = _fetch_latest_election(galaxy_id, conn=conn)
    if latest is not None:
        record = _serialize_election_record(
            latest, conn=conn, now=now, in_force=False, source="election"
        )
        # Align displayed keys with live EffectResolver state when windows diverge.
        primary = normalize_directive_key(active.get("primary")) or record.get("primary")
        secondary = normalize_directive_key(active.get("secondary")) or record.get("secondary")
        record["primary"] = primary
        record["secondary"] = secondary
        record["primary_label_key"] = _directive_label_key(primary, conn=conn)
        record["secondary_label_key"] = _directive_label_key(secondary, conn=conn)
        record["primary_description_key"] = _directive_desc_key(primary, conn=conn)
        record["secondary_description_key"] = _directive_desc_key(secondary, conn=conn)
        record["primary_monogram"] = _DIRECTIVE_MONOGRAMS.get(primary or "", "—")
        record["secondary_monogram"] = (
            _DIRECTIVE_MONOGRAMS.get(secondary or "", "—") if secondary else None
        )
        return record

    primary = normalize_directive_key(active.get("primary")) or FALLBACK_PRIMARY
    secondary = normalize_directive_key(active.get("secondary")) or None
    year, month = _calendar_parts(now)
    return {
        "cycle_id": None,
        "election_year": None,
        "election_month": None,
        "effect_year": year,
        "effect_month": month,
        "effect_start_at": 0,
        "effect_end_at": 0,
        "countdown_seconds": 0,
        "primary": primary,
        "secondary": secondary,
        "primary_label_key": _directive_label_key(primary, conn=conn),
        "secondary_label_key": _directive_label_key(secondary, conn=conn),
        "primary_description_key": _directive_desc_key(primary, conn=conn),
        "secondary_description_key": _directive_desc_key(secondary, conn=conn),
        "primary_monogram": _DIRECTIVE_MONOGRAMS.get(primary, "—"),
        "secondary_monogram": _DIRECTIVE_MONOGRAMS.get(secondary, "—") if secondary else None,
        "primary_votes": 0,
        "secondary_votes": 0,
        "total_votes": 0,
        "total_voters": 0,
        "is_tie_primary": False,
        "is_tie_secondary": False,
        "in_force": True,
        "source": str(active.get("source") or "fallback"),
    }


def build_galaxy_politics_entry(
    player_id: int,
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Dict[str, Any]:
    cycle = get_or_create_current_cycle(galaxy_id, now=now, conn=conn)
    active = get_active_directives_for_galaxy(galaxy_id, conn=conn) or {}
    state = ensure_galaxy_state(galaxy_id, conn=conn)
    phase = get_vote_phase(cycle, now) if cycle else PHASE_RESOLVED
    has_right = _player_has_vote_right(player_id, galaxy_id, conn)

    player_vote: Optional[str] = None
    if cycle:
        row = conn.execute(
            """
            SELECT directive_key FROM gd_votes
            WHERE cycle_id = ? AND player_id = ?
            LIMIT 1;
            """,
            (int(cycle["id"]), int(player_id)),
        ).fetchone()
        if row:
            player_vote = normalize_directive_key(row["directive_key"]) or None

    tallies = _vote_tallies_for_cycle(int(cycle["id"]), conn) if cycle else {}
    tally_total = sum(int(v) for v in tallies.values()) if tallies else 0
    options: List[Dict[str, Any]] = []
    for definition in list_directive_definitions(conn=conn):
        key = str(definition.get("directive_key") or "")
        eligible = definition.get("eligible_as") or []
        if isinstance(eligible, str) or "primary" not in eligible:
            continue
        count = int(tallies.get(key, 0))
        share = round(100.0 * count / tally_total, 1) if tally_total else 0.0
        options.append(
            _serialize_directive_option(
                definition,
                vote_count=count,
                vote_share=share,
                selected=player_vote == key,
                on_cooldown=_directive_on_cooldown(
                    state,
                    key,
                    int(cycle["year"]) if cycle else 0,
                    int(cycle["month"]) if cycle else 0,
                ),
            )
        )

    can_vote = bool(has_right and cycle and phase == PHASE_VOTE_OPEN)
    vote_reason: Optional[str] = None
    if not has_right:
        vote_reason = "no_colony"
    elif phase != PHASE_VOTE_OPEN:
        vote_reason = "vote_closed"

    mandate = _build_mandate_payload(galaxy_id, active, conn=conn, now=now)
    chronicle = [
        _serialize_election_record(
            row,
            conn=conn,
            now=now,
            in_force=bool(
                mandate.get("cycle_id")
                and int(row.get("id") or 0) == int(mandate["cycle_id"])
                and mandate.get("in_force")
            ),
            source="election",
        )
        for row in _fetch_chronicle_elections(galaxy_id, conn=conn)
    ]

    diplomacy: Dict[str, Any] = {"ready": False}
    try:
        from ..galactic_diplomacy.politics_surface import build_diplomacy_politics_payload

        diplomacy = build_diplomacy_politics_payload(
            galaxy_id, conn=conn, player_id=int(player_id), now=now
        )
    except Exception:
        diplomacy = {"ready": False}

    effect_year = effect_month = None
    if cycle:
        effect_year, effect_month = _next_month(int(cycle["year"]), int(cycle["month"]))

    return {
        "galaxy": galaxy_id,
        "active": {
            "primary": active.get("primary"),
            "secondary": active.get("secondary"),
            "primary_label_key": (active.get("primary_definition") or {}).get("label_key"),
            "secondary_label_key": (active.get("secondary_definition") or {}).get("label_key"),
        },
        "mandate": mandate,
        "chronicle": chronicle,
        "diplomacy": diplomacy,
        "cycle": {
            "id": int(cycle["id"]) if cycle else None,
            "year": int(cycle["year"]) if cycle else None,
            "month": int(cycle["month"]) if cycle else None,
            "effect_year": int(effect_year) if effect_year else None,
            "effect_month": int(effect_month) if effect_month else None,
            "phase": phase,
            "status": str(cycle.get("status") or phase) if cycle else PHASE_RESOLVED,
            "vote_end_at": int(cycle.get("vote_end_at") or 0) if cycle else 0,
            "effect_end_at": int(cycle.get("effect_end_at") or 0) if cycle else 0,
            "countdown_seconds": _phase_countdown_seconds(cycle, phase, now) if cycle else 0,
            "total_votes": int(tally_total),
        },
        "player_vote": player_vote,
        "can_vote": can_vote,
        "vote_reason": vote_reason,
        "options": options,
    }


def get_galactic_politics_state(
    player_id: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """UI payload for /galactic-politics."""
    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ready": False, "galaxies": [], "server_time": ts}

        galaxies = get_player_vote_galaxies(int(player_id), conn=conn)
        entries = [
            build_galaxy_politics_entry(int(player_id), galaxy_id, conn=conn, now=ts)
            for galaxy_id in galaxies
        ]
        return {"ready": True, "galaxies": entries, "server_time": ts}
    finally:
        if own_conn:
            conn.close()


def resolve_due_cycles(
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Batch-resolve overdue galactic directive cycles for all playable galaxies (GC-720I).

    Safe to call from cron or request paths. Lazy per-galaxy resolve remains as defense.
    """
    from ..galaxy import get_galaxy_max

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    resolved: List[Dict[str, Any]] = []
    synced = 0
    try:
        if not schema_ready(conn=conn):
            return {"ok": True, "resolved": [], "synced": 0, "galaxies": 0, "server_time": ts}

        galaxy_max = int(get_galaxy_max(conn) or 1)
        for galaxy_id in range(1, galaxy_max + 1):
            before = conn.execute(
                """
                SELECT id, year, month, winning_primary, status
                FROM gd_cycles
                WHERE galaxy = ?
                  AND (
                    (status != ? AND effect_end_at < ?)
                    OR (status = ? AND vote_end_at < ? AND winning_primary IS NULL)
                    OR (status = ? AND vote_end_at < ? AND effect_end_at >= ?)
                  );
                """,
                (
                    galaxy_id,
                    PHASE_RESOLVED,
                    ts,
                    PHASE_VOTE_OPEN,
                    ts,
                    PHASE_VOTE_OPEN,
                    ts,
                    ts,
                ),
            ).fetchall()
            _resolve_overdue_cycles(galaxy_id, conn=conn, now=ts)
            # Ensure current calendar month exists so vote windows stay available.
            get_or_create_current_cycle(galaxy_id, now=ts, conn=conn)
            for row in before:
                cycle = _row_to_cycle(row)
                if not cycle.get("winning_primary"):
                    after = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn)
                    if after and after.get("winning_primary"):
                        resolved.append(
                            {
                                "galaxy": galaxy_id,
                                "year": int(after["year"]),
                                "month": int(after["month"]),
                                "primary": after.get("winning_primary"),
                                "secondary": after.get("winning_secondary"),
                            }
                        )
                else:
                    synced += 1

        # After batch resolve, try results broadcast for calendar months touched.
        try:
            from .results import maybe_broadcast_cycle_results

            year, month = _calendar_parts(ts)
            maybe_broadcast_cycle_results(year, month, conn=conn, now=ts)
            # Also previous month near month boundaries.
            prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
            maybe_broadcast_cycle_results(prev_year, prev_month, conn=conn, now=ts)
        except Exception:
            pass

        return {
            "ok": True,
            "resolved": resolved,
            "synced": synced,
            "galaxies": galaxy_max,
            "server_time": ts,
        }
    finally:
        if own_conn:
            conn.close()


def admin_force_directive(
    galaxy: Any,
    primary_key: str,
    secondary_key: Optional[str] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Close the current vote immediately and set Primary (optional Secondary) for a galaxy.
    """
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    primary = normalize_directive_key(primary_key)
    secondary = normalize_directive_key(secondary_key) if secondary_key not in (None, "") else None
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}
    if not primary:
        return {"ok": False, "reason": "invalid_directive"}
    if secondary_key not in (None, "") and not secondary:
        return {"ok": False, "reason": "invalid_secondary"}
    if secondary and secondary == primary:
        return {"ok": False, "reason": "secondary_equals_primary"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}

        if get_directive_definition(primary, conn=conn) is None:
            return {"ok": False, "reason": "invalid_directive"}
        if secondary is not None and get_directive_definition(secondary, conn=conn) is None:
            return {"ok": False, "reason": "invalid_secondary"}

        cycle = get_or_create_current_cycle(galaxy_id, now=ts, conn=conn)
        if cycle is None:
            return {"ok": False, "reason": "cycle_unavailable"}

        state = ensure_galaxy_state(galaxy_id, conn=conn)
        old_primary = normalize_directive_key(state.get("primary_directive")) or FALLBACK_PRIMARY
        consecutive = int(state.get("consecutive_primary_wins") or 0)
        if primary == old_primary:
            consecutive += 1
        else:
            consecutive = 1

        cooldown_directive = state.get("cooldown_directive")
        cooldown_until_ym = state.get("cooldown_until_ym")
        if consecutive >= 2:
            next_year, next_month = _next_month(int(cycle["year"]), int(cycle["month"]))
            cooldown_directive = primary
            cooldown_until_ym = _ym_key(next_year, next_month)
            consecutive = 0

        # Close voting immediately so the mandate is active now.
        vote_end_at = min(int(cycle.get("vote_end_at") or ts), ts)
        effect_start_at = min(int(cycle.get("effect_start_at") or ts), ts)
        forced_cycle = {
            **cycle,
            "vote_end_at": vote_end_at,
            "effect_start_at": effect_start_at,
            "winning_primary": primary,
        }
        phase = get_vote_phase(forced_cycle, ts)

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE gd_cycles
            SET vote_end_at = ?,
                effect_start_at = ?,
                winning_primary = ?,
                winning_secondary = ?,
                winning_primary_votes = COALESCE(winning_primary_votes, 0),
                winning_secondary_votes = COALESCE(winning_secondary_votes, 0),
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                vote_end_at,
                effect_start_at,
                primary,
                secondary,
                phase,
                ts,
                int(cycle["id"]),
            ),
        )
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = ?,
                secondary_directive = ?,
                primary_since = ?,
                consecutive_primary_wins = ?,
                cooldown_directive = ?,
                cooldown_until_ym = ?,
                last_cycle_id = ?,
                updated_at = ?
            WHERE galaxy = ?;
            """,
            (
                primary,
                secondary,
                ts,
                int(consecutive),
                cooldown_directive,
                cooldown_until_ym,
                int(cycle["id"]),
                ts,
                galaxy_id,
            ),
        )
        commit(conn)
        refreshed = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn)
        return {
            "ok": True,
            "galaxy": galaxy_id,
            "primary": primary,
            "secondary": secondary,
            "cycle": refreshed,
        }
    finally:
        if own_conn:
            conn.close()


def admin_unforce_directive(
    galaxy: Any,
    *,
    reset_state: bool = False,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Re-open the current cycle for voting and clear winner fields (GC-720I).

    When ``reset_state`` is True, galaxy mandate falls back to defensive / no secondary.
    """
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}

        cycle = get_or_create_current_cycle(galaxy_id, now=ts, conn=conn)
        if cycle is None:
            return {"ok": False, "reason": "cycle_unavailable"}

        stamps = _cycle_timestamps(int(cycle["year"]), int(cycle["month"]))
        # Keep vote_open relative to ``now`` so overdue resolution does not instantly re-close.
        vote_end_at = max(int(stamps["vote_end_at"]), ts)
        effect_start_at = max(int(stamps["effect_start_at"]), vote_end_at + 1)
        effect_end_at = max(int(stamps["effect_end_at"]), effect_start_at)
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE gd_cycles
            SET vote_start_at = ?,
                vote_end_at = ?,
                effect_start_at = ?,
                effect_end_at = ?,
                winning_primary = NULL,
                winning_secondary = NULL,
                winning_primary_votes = 0,
                winning_secondary_votes = 0,
                total_votes = 0,
                total_voters = 0,
                is_tie_primary = 0,
                is_tie_secondary = 0,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                stamps["vote_start_at"],
                vote_end_at,
                effect_start_at,
                effect_end_at,
                PHASE_VOTE_OPEN,
                ts,
                int(cycle["id"]),
            ),
        )
        if reset_state:
            conn.execute(
                """
                UPDATE gd_galaxy_state
                SET primary_directive = ?,
                    secondary_directive = NULL,
                    consecutive_primary_wins = 0,
                    cooldown_directive = NULL,
                    cooldown_until_ym = NULL,
                    last_cycle_id = NULL,
                    updated_at = ?
                WHERE galaxy = ?;
                """,
                (FALLBACK_PRIMARY, ts, galaxy_id),
            )
        commit(conn)
        refreshed = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn)
        return {
            "ok": True,
            "galaxy": galaxy_id,
            "reset_state": bool(reset_state),
            "cycle": refreshed,
        }
    finally:
        if own_conn:
            conn.close()
