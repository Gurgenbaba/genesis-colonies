"""Database access helpers for planet evolution."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import column_exists, table_exists
from ..models import db


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def evolution_schema_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "planet_dna") and table_exists(conn, "pe_trait_definitions")


def get_planet_row(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def get_active_planet_id(player_id: int, conn: Optional[sqlite3.Connection] = None) -> int:
    from ..models import get_homeworld

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        if column_exists(conn, "players", "active_planet_id"):
            cur.execute(
                "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
                (int(player_id),),
            )
            row = cur.fetchone()
            ap = row["active_planet_id"] if row else None
            if ap:
                cur.execute(
                    "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
                    (int(ap), int(player_id)),
                )
                if cur.fetchone():
                    return int(ap)
        planet = get_homeworld(player_id=int(player_id), conn=conn)
        return int(planet["id"])
    finally:
        if own:
            conn.close()


def set_active_planet_id(player_id: int, planet_id: int, conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(planet_id), int(player_id)),
    )
    if not cur.fetchone():
        raise ValueError("planet_not_owned")
    if column_exists(conn, "players", "active_planet_id"):
        cur.execute(
            "UPDATE players SET active_planet_id = ? WHERE id = ?;",
            (int(planet_id), int(player_id)),
        )


def get_planet_dna(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM planet_dna WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        mapping = {
            "geology_traits_json": ("geology_traits", []),
            "atmosphere_traits_json": ("atmosphere_traits", []),
            "environment_traits_json": ("environment_traits", []),
            "anomaly_traits_json": ("anomaly_traits", []),
            "hidden_traits_json": ("hidden_traits", []),
            "affinity_scores_json": ("affinity_scores", {}),
            "risk_profile_json": ("risk_profile", {}),
            "resource_potential_json": ("resource_potential", {}),
        }
        for src, (dst, default) in mapping.items():
            data[dst] = _json_loads(data.pop(src, None), default)
        return data
    finally:
        if own:
            conn.close()


def save_planet_dna(planet_id: int, dna: Dict[str, Any], conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO planet_dna (
            planet_id, rarity_tier,
            geology_traits_json, atmosphere_traits_json, environment_traits_json,
            anomaly_traits_json, hidden_traits_json,
            affinity_scores_json, risk_profile_json, resource_potential_json,
            generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(planet_id) DO UPDATE SET
            rarity_tier = excluded.rarity_tier,
            geology_traits_json = excluded.geology_traits_json,
            atmosphere_traits_json = excluded.atmosphere_traits_json,
            environment_traits_json = excluded.environment_traits_json,
            anomaly_traits_json = excluded.anomaly_traits_json,
            hidden_traits_json = excluded.hidden_traits_json,
            affinity_scores_json = excluded.affinity_scores_json,
            risk_profile_json = excluded.risk_profile_json,
            resource_potential_json = excluded.resource_potential_json,
            generated_at = excluded.generated_at;
        """,
        (
            int(planet_id),
            str(dna.get("rarity_tier", "common")),
            _json_dumps(dna.get("geology_traits", [])),
            _json_dumps(dna.get("atmosphere_traits", [])),
            _json_dumps(dna.get("environment_traits", [])),
            _json_dumps(dna.get("anomaly_traits", [])),
            _json_dumps(dna.get("hidden_traits", [])),
            _json_dumps(dna.get("affinity_scores", {})),
            _json_dumps(dna.get("risk_profile", {})),
            _json_dumps(dna.get("resource_potential", {})),
            float(dna.get("generated_at", time.time())),
        ),
    )


def get_planet_mechanics(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM planet_mechanics WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        if not row:
            return {
                "unlocks": [],
                "flags": {},
                "export_slots": [],
                "queue_limits": {},
                "risk_modifiers": {},
            }
        return {
            "unlocks": _json_loads(row["unlocks_json"], []),
            "flags": _json_loads(row["flags_json"], {}),
            "export_slots": _json_loads(row["export_slots_json"], []),
            "queue_limits": _json_loads(row["queue_limits_json"], {}),
            "risk_modifiers": _json_loads(row["risk_modifiers_json"], {}),
            "compiled_at": row["compiled_at"],
            "compile_version": row["compile_version"],
        }
    finally:
        if own:
            conn.close()


def save_planet_mechanics(planet_id: int, mechanics: Dict[str, Any], conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO planet_mechanics (
            planet_id, unlocks_json, flags_json, export_slots_json,
            queue_limits_json, risk_modifiers_json, compiled_at, compile_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(planet_id) DO UPDATE SET
            unlocks_json = excluded.unlocks_json,
            flags_json = excluded.flags_json,
            export_slots_json = excluded.export_slots_json,
            queue_limits_json = excluded.queue_limits_json,
            risk_modifiers_json = excluded.risk_modifiers_json,
            compiled_at = excluded.compiled_at,
            compile_version = excluded.compile_version;
        """,
        (
            int(planet_id),
            _json_dumps(mechanics.get("unlocks", [])),
            _json_dumps(mechanics.get("flags", {})),
            _json_dumps(mechanics.get("export_slots", [])),
            _json_dumps(mechanics.get("queue_limits", {})),
            _json_dumps(mechanics.get("risk_modifiers", {})),
            float(time.time()),
            int(mechanics.get("compile_version", 1)),
        ),
    )


def get_planet_culture(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM planet_culture WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        if own:
            conn.close()


def ensure_planet_culture(planet_id: int, conn: sqlite3.Connection, archetype: str = "frontier_settlers") -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM planet_culture WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    if cur.fetchone():
        return
    now = time.time()
    cur.execute(
        "INSERT INTO planet_culture (planet_id, archetype_key, last_drift_at) VALUES (?, ?, ?);",
        (int(planet_id), str(archetype), now),
    )


def get_locked_choices(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT choice_group, choice_key FROM planet_locked_choices WHERE planet_id = ?;",
            (int(planet_id),),
        )
        return {str(r["choice_group"]): str(r["choice_key"]) for r in cur.fetchall()}
    finally:
        if own:
            conn.close()


def get_planet_research_levels(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tech_key, level FROM planet_research_levels WHERE planet_id = ?;",
            (int(planet_id),),
        )
        return {str(r["tech_key"]): int(r["level"]) for r in cur.fetchall()}
    finally:
        if own:
            conn.close()


def get_planet_research_queue(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_research_queue WHERE planet_id = ? ORDER BY finish_at ASC;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_special_resources(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_special_resources WHERE planet_id = ? ORDER BY resource_key ASC;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_active_event(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM planet_events
            WHERE planet_id = ? AND state IN ('pending','active')
            ORDER BY started_at DESC LIMIT 1;
            """,
            (int(planet_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def get_legacy_tags(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[str]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tag_key FROM planet_legacy_tags WHERE planet_id = ? ORDER BY last_at DESC;",
            (int(planet_id),),
        )
        return [str(r["tag_key"]) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_discoveries(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_discoveries WHERE planet_id = ? ORDER BY discovered_at DESC;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_trade_routes(owner_player_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM planet_trade_routes
            WHERE owner_player_id = ? AND is_active = 1
            ORDER BY id ASC;
            """,
            (int(owner_player_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_import_demands(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_import_demands WHERE planet_id = ?;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_policies(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_policies WHERE planet_id = ? ORDER BY slot ASC;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_production_chains(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planet_production_chains WHERE planet_id = ? AND is_active = 1;",
            (int(planet_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()
