"""Politics-page diplomacy surface — blocs, personality, emergency, sessions (GC-POL)."""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..alliance import get_player_alliance, is_officer_role
from ..db import begin_write_transaction, commit, db
from ..galactic_directives.voting import _serialize_tradeoff_chips
from .blocs import (
    get_alliance_bloc,
    list_alliance_blocs_for_galaxy,
    normalize_galaxy,
    set_alliance_bloc,
)
from .definitions import (
    list_bloc_definitions,
    normalize_bloc_key,
    schema_ready,
)
from .emergencies import get_active_emergency
from .personality import get_galaxy_personality
from .resolutions import get_active_resolution, get_resolution_definition
from .sessions import (
    BLOC_COOLDOWN_SECONDS,
    get_open_resolution_session,
    open_resolution_session,
    sessions_schema_ready,
)

_BLOC_MONOGRAMS = {
    "scientific_bloc": "SCI",
    "military_bloc": "MIL",
    "industrial_bloc": "IND",
    "frontier_bloc": "FRN",
    "neutral_bloc": "NEU",
}

_BLOC_STANCE_KEYS = {
    "scientific_bloc": "gd_politics_stance_scientific",
    "military_bloc": "gd_politics_stance_military",
    "industrial_bloc": "gd_politics_stance_industrial",
    "frontier_bloc": "gd_politics_stance_frontier",
    "neutral_bloc": "gd_politics_stance_neutral",
}


def _effects_from_definition(definition: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Server-authored effect chips from mechanics (and tradeoffs overlay)."""
    if not isinstance(definition, dict):
        return []
    mechanics = definition.get("mechanics") if isinstance(definition.get("mechanics"), dict) else {}
    tradeoffs = definition.get("tradeoffs") if isinstance(definition.get("tradeoffs"), dict) else {}
    er: Dict[str, Any] = {}
    flags: Dict[str, Any] = {}
    if isinstance(mechanics.get("effect_resolver"), dict):
        er.update(mechanics["effect_resolver"])
    if isinstance(mechanics.get("flags"), dict):
        flags.update(mechanics["flags"])
    if isinstance(tradeoffs.get("effect_resolver"), dict):
        er.update(tradeoffs["effect_resolver"])
    if isinstance(tradeoffs.get("flags"), dict):
        flags.update(tradeoffs["flags"])
    return _serialize_tradeoff_chips({"effect_resolver": er, "flags": flags})


def _chip_from_definition(
    kind: str,
    key: str,
    definition: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    defn = definition if isinstance(definition, dict) else {}
    prefix = {
        "personality": "gdp_trait",
        "resolution": "gdp_res",
        "emergency": "gdp_emergency",
        "bloc": "gdp_bloc",
    }.get(kind, "gdp")
    chip: Dict[str, Any] = {
        "type": kind,
        "key": key,
        "label_key": str(defn.get("label_key") or f"{prefix}_{key}_title"),
        "description_key": str(defn.get("description_key") or f"{prefix}_{key}_desc"),
        "monogram": _BLOC_MONOGRAMS.get(key, key[:3].upper() if key else "—"),
        "effects": _effects_from_definition(defn),
        "grants_mechanics": kind != "bloc",
    }
    if kind in ("resolution", "emergency"):
        chip["duration_days"] = int(defn.get("duration_days") or 0)
    return chip


def _alliance_tag(alliance_id: int, conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT tag, name FROM alliances WHERE id = ? LIMIT 1;",
        (int(alliance_id),),
    ).fetchone()
    if not row:
        return f"#{alliance_id}"
    tag = str(row["tag"] or "").strip()
    if tag:
        return tag
    return str(row["name"] or f"#{alliance_id}")


def build_bloc_landscape(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    player_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Aggregate alliance blocs for a galaxy + player officer controls."""
    if not schema_ready(conn=conn):
        return {
            "blocs": [],
            "player_bloc": None,
            "can_set_bloc": False,
            "options": [],
            "cooldown_seconds": 0,
            "grants_mechanics": False,
            "role": "stance",
        }

    rows = list_alliance_blocs_for_galaxy(galaxy_id, conn=conn)
    by_bloc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("bloc_key") or "")
        aid = int(row.get("alliance_id") or 0)
        by_bloc[key].append(
            {
                "alliance_id": aid,
                "tag": _alliance_tag(aid, conn),
                "bloc_key": key,
            }
        )

    blocs_out: List[Dict[str, Any]] = []
    for definition in list_bloc_definitions(conn=conn):
        key = str(definition.get("bloc_key") or "")
        alliances = by_bloc.get(key, [])
        blocs_out.append(
            {
                "bloc_key": key,
                "label_key": definition.get("label_key") or f"gdp_bloc_{key}_title",
                "description_key": definition.get("description_key") or f"gdp_bloc_{key}_desc",
                "stance_key": _BLOC_STANCE_KEYS.get(key, "gd_politics_stance_neutral"),
                "monogram": _BLOC_MONOGRAMS.get(key, "—"),
                "alliance_count": len(alliances),
                "alliances": alliances[:12],
                "grants_mechanics": False,
                "role": "stance",
            }
        )

    membership = get_player_alliance(int(player_id), conn=conn) if player_id else None
    player_bloc = None
    can_set = False
    cooldown_seconds = 0
    if membership:
        aid = int(membership["alliance_id"])
        existing = get_alliance_bloc(aid, galaxy_id, conn=conn)
        if existing:
            player_bloc = {
                "alliance_id": aid,
                "bloc_key": existing.get("bloc_key"),
                "label_key": (existing.get("definition") or {}).get("label_key"),
                "monogram": _BLOC_MONOGRAMS.get(str(existing.get("bloc_key") or ""), "—"),
                "since_at": existing.get("since_at"),
                "grants_mechanics": False,
                "role": "stance",
            }
            since = int(existing.get("updated_at") or existing.get("since_at") or 0)
            remaining = max(0, since + BLOC_COOLDOWN_SECONDS - int(time.time()))
            cooldown_row = conn.execute(
                """
                SELECT cooldown_until FROM gd_alliance_blocs
                WHERE alliance_id = ? AND galaxy = ?
                LIMIT 1;
                """,
                (aid, int(galaxy_id)),
            ).fetchone()
            if cooldown_row and cooldown_row["cooldown_until"]:
                cooldown_seconds = max(0, int(cooldown_row["cooldown_until"]) - int(time.time()))
            elif remaining and existing.get("bloc_key"):
                cooldown_seconds = 0
        can_set = is_officer_role(str(membership.get("role") or ""))

    options = [
        {
            "bloc_key": str(d.get("bloc_key") or ""),
            "label_key": d.get("label_key"),
            "description_key": d.get("description_key"),
            "stance_key": _BLOC_STANCE_KEYS.get(str(d.get("bloc_key") or ""), "gd_politics_stance_neutral"),
            "monogram": _BLOC_MONOGRAMS.get(str(d.get("bloc_key") or ""), "—"),
            "grants_mechanics": False,
            "role": "stance",
        }
        for d in list_bloc_definitions(conn=conn)
    ]

    return {
        "blocs": blocs_out,
        "player_bloc": player_bloc,
        "can_set_bloc": bool(can_set and cooldown_seconds <= 0),
        "can_manage": bool(can_set),
        "options": options,
        "cooldown_seconds": int(cooldown_seconds),
        "alliance_id": int(membership["alliance_id"]) if membership else None,
        "grants_mechanics": False,
        "role": "stance",
    }


def build_diplomacy_politics_payload(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    player_id: Optional[int] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Read-only + actionable diplomacy block for one galaxy politics card."""
    ts = int(now if now is not None else time.time())
    if not schema_ready(conn=conn):
        return {
            "ready": False,
            "personality": None,
            "resolution": None,
            "emergency": None,
            "session": None,
            "blocs": build_bloc_landscape(galaxy_id, conn=conn, player_id=player_id),
        }

    personality = None
    try:
        pstate = get_galaxy_personality(galaxy_id, conn=conn)
        key = str(pstate.get("personality_key") or "")
        if key:
            personality = _chip_from_definition(
                "personality", key, pstate.get("definition")
            )
            if personality:
                personality["in_force"] = True
    except (ValueError, TypeError, RuntimeError):
        personality = None

    resolution = None
    try:
        rstate = get_active_resolution(galaxy_id, conn=conn)
        if rstate:
            resolution = _chip_from_definition(
                "resolution",
                str(rstate.get("resolution_key") or ""),
                rstate.get("definition"),
            )
            if resolution:
                ends = rstate.get("ends_at")
                resolution["ends_at"] = ends
                resolution["countdown_seconds"] = (
                    max(0, int(ends) - ts) if ends else 0
                )
                resolution["in_force"] = True
    except (ValueError, TypeError, RuntimeError):
        resolution = None

    emergency = None
    try:
        estate = get_active_emergency(galaxy_id, conn=conn)
        if estate:
            emergency = _chip_from_definition(
                "emergency",
                str(estate.get("emergency_key") or ""),
                estate.get("definition"),
            )
            if emergency:
                ends = estate.get("ends_at")
                emergency["ends_at"] = ends
                emergency["countdown_seconds"] = (
                    max(0, int(ends) - ts) if ends else 0
                )
                emergency["in_force"] = True
    except (ValueError, TypeError, RuntimeError):
        emergency = None

    session = None
    if sessions_schema_ready(conn=conn):
        session = get_open_resolution_session(
            galaxy_id, conn=conn, player_id=player_id, now=ts
        )
        if session:
            defn = get_resolution_definition(str(session.get("resolution_key") or ""), conn=conn)
            session["effects"] = _effects_from_definition(defn)
            session["duration_days"] = int((defn or {}).get("duration_days") or 0)

    can_propose = False
    membership = get_player_alliance(int(player_id), conn=conn) if player_id else None
    is_officer = bool(membership and is_officer_role(str(membership.get("role") or "")))
    if is_officer:
        can_propose = session is None

    resolution_options = []
    if can_propose:
        from .resolutions import list_resolution_definitions

        for d in list_resolution_definitions(conn=conn):
            resolution_options.append(
                {
                    "resolution_key": d.get("resolution_key"),
                    "label_key": d.get("label_key"),
                    "description_key": d.get("description_key"),
                    "duration_days": int(d.get("duration_days") or 0),
                    "effects": _effects_from_definition(d),
                }
            )

    return {
        "ready": True,
        "personality": personality,
        "resolution": resolution,
        "emergency": emergency,
        "session": session,
        "can_propose_resolution": can_propose,
        "resolution_options": resolution_options,
        "is_officer": is_officer,
        "has_alliance": bool(membership),
        "blocs": build_bloc_landscape(galaxy_id, conn=conn, player_id=player_id),
    }


def submit_bloc_membership(
    player_id: int,
    galaxy: Any,
    bloc_key: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Alliance officer sets bloc for one galaxy."""
    key = normalize_bloc_key(bloc_key)
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}
    if not key:
        return {"ok": False, "reason": "invalid_bloc"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}
        membership = get_player_alliance(int(player_id), conn=conn)
        if not membership:
            return {"ok": False, "reason": "no_alliance"}
        if not is_officer_role(str(membership.get("role") or "")):
            return {"ok": False, "reason": "not_officer"}

        aid = int(membership["alliance_id"])
        existing = conn.execute(
            """
            SELECT bloc_key, cooldown_until FROM gd_alliance_blocs
            WHERE alliance_id = ? AND galaxy = ?
            LIMIT 1;
            """,
            (aid, galaxy_id),
        ).fetchone()
        if existing and existing["cooldown_until"] and int(existing["cooldown_until"]) > ts:
            return {
                "ok": False,
                "reason": "cooldown",
                "cooldown_seconds": int(existing["cooldown_until"]) - ts,
            }
        if existing and str(existing["bloc_key"]) == key:
            return {"ok": True, "bloc_key": key, "unchanged": True}

        set_alliance_bloc(aid, galaxy_id, key, conn=conn)
        cooldown_until = ts + BLOC_COOLDOWN_SECONDS
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE gd_alliance_blocs
            SET cooldown_until = ?, updated_at = ?
            WHERE alliance_id = ? AND galaxy = ?;
            """,
            (cooldown_until, ts, aid, galaxy_id),
        )
        commit(conn)
        return {"ok": True, "bloc_key": key, "alliance_id": aid, "galaxy": galaxy_id}
    finally:
        if own_conn:
            conn.close()


def propose_resolution_session(
    player_id: int,
    galaxy: Any,
    resolution_key: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Officer opens a resolution vote session for a galaxy."""
    membership = None
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        membership = get_player_alliance(int(player_id), conn=conn)
        if not membership:
            return {"ok": False, "reason": "no_alliance"}
        if not is_officer_role(str(membership.get("role") or "")):
            return {"ok": False, "reason": "not_officer"}
        galaxy_id = normalize_galaxy(galaxy, conn=conn)
        if galaxy_id is None:
            return {"ok": False, "reason": "invalid_galaxy"}
        from ..galactic_directives.state import get_player_vote_galaxies

        if galaxy_id not in get_player_vote_galaxies(int(player_id), conn=conn):
            return {"ok": False, "reason": "no_colony"}
        return open_resolution_session(
            galaxy_id,
            resolution_key,
            created_by=int(player_id),
            conn=conn,
            now=now,
        )
    finally:
        if own_conn:
            conn.close()


def build_command_map_politics_overlay(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Lightweight per-galaxy politics badges for Command Map (GC-POL-08)."""
    from ..galactic_directives.state import (
        get_active_directives_for_galaxy,
        get_player_vote_galaxies,
    )

    galaxies = get_player_vote_galaxies(int(player_id), conn=conn)
    out: Dict[str, Any] = {"galaxies": {}}
    if not galaxies:
        return out
    for galaxy_id in galaxies:
        active = get_active_directives_for_galaxy(galaxy_id, conn=conn) or {}
        personality = None
        emergency = None
        try:
            p = get_galaxy_personality(galaxy_id, conn=conn)
            if p.get("personality_key"):
                personality = str(p["personality_key"])
        except (ValueError, TypeError, RuntimeError):
            pass
        try:
            e = get_active_emergency(galaxy_id, conn=conn)
            if e:
                emergency = str(e.get("emergency_key") or "")
        except (ValueError, TypeError, RuntimeError):
            pass
        blocs = list_alliance_blocs_for_galaxy(galaxy_id, conn=conn)
        majority = None
        if blocs:
            counts: Dict[str, int] = defaultdict(int)
            for b in blocs:
                counts[str(b.get("bloc_key") or "")] += 1
            majority = max(counts.items(), key=lambda kv: kv[1])[0] if counts else None
        out["galaxies"][str(galaxy_id)] = {
            "galaxy": galaxy_id,
            "primary": active.get("primary"),
            "secondary": active.get("secondary"),
            "personality": personality,
            "emergency": emergency,
            "majority_bloc": majority,
            "has_emergency": bool(emergency),
        }
    return out


__all__ = [
    "build_bloc_landscape",
    "build_command_map_politics_overlay",
    "build_diplomacy_politics_payload",
    "propose_resolution_session",
    "submit_bloc_membership",
]
