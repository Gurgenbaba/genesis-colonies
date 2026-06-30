"""
Alliance Hub — identity, members, donations, projects, diplomacy (EPIC-09).

Owner module for all alliance gameplay state. Chat integration uses get_player_alliance().
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import image_assets

from .alliance_catalog import (
    ALLIANCE_BUILDINGS,
    ALLIANCE_TECHNOLOGIES,
    BASE_MEMBER_LIMIT,
    DIPLOMACY_RELATIONS,
    DIPLOMACY_REQUEST_TYPES,
    DONATION_XP_DAILY_CAP,
    DONATION_XP_DIVISOR,
    DONATION_XP_MAX_PER_DONATION,
    OFFICER_ROLES,
    PROJECT_XP_DIVISOR,
    alliance_level_from_xp,
    alliance_xp_for_level,
    available_projects,
    building_level,
    compute_bonus_chips,
    member_limit_from_buildings,
    pool_cap_from_projects,
    project_cost_and_duration,
    tech_level,
)
from .db import begin_write_transaction, commit, db, rollback, table_exists
from .planet_evolution.repository import get_context_planet

VALID_DONATION_RESOURCES = frozenset({"metal", "crystal", "fuel_cells"})
RECRUITMENT_MODES = frozenset({"open", "application_only", "closed"})
DEFAULT_RECRUITMENT_MODE = "open"
_LOGO_API_RE = re.compile(r"^/api/alliance-logo/(\d+)$")
_LOGO_UPLOAD_COOLDOWN_SEC = 2
_LAST_LOGO_UPLOAD_TS: Dict[int, int] = {}


def _now() -> int:
    return int(time.time())


def _day_start(ts: Optional[int] = None) -> int:
    t = int(ts or _now())
    return t - (t % 86400)


def alliance_hub_schema_ready(conn) -> bool:
    return (
        table_exists(conn, "alliances")
        and table_exists(conn, "alliance_members")
        and table_exists(conn, "alliance_donations")
        and table_exists(conn, "alliance_buildings")
        and table_exists(conn, "alliance_technologies")
        and table_exists(conn, "alliance_projects")
    )


def _normalize_role(role: str) -> str:
    r = str(role or "member").strip().lower()
    if r == "owner":
        return "leader"
    return r if r in ("leader", "officer", "member") else "member"


def is_officer_role(role: str) -> bool:
    return _normalize_role(role) in OFFICER_ROLES


def can_manage_applications(role: str) -> bool:
    """Officer roles may review applications (GC-AL-009 adds recruiter)."""
    return is_officer_role(role)


def _normalize_recruitment_mode(mode: Optional[str]) -> str:
    m = str(mode or DEFAULT_RECRUITMENT_MODE).strip().lower()
    return m if m in RECRUITMENT_MODES else DEFAULT_RECRUITMENT_MODE


def allows_direct_join(mode: Optional[str]) -> bool:
    return _normalize_recruitment_mode(mode) == "open"


def allows_applications(mode: Optional[str]) -> bool:
    return _normalize_recruitment_mode(mode) in ("open", "application_only")


def _recruitment_mode_column_ready(conn) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(alliances);")
    return any(str(row[1]) == "recruitment_mode" for row in cur.fetchall())


def _logo_url_column_ready(conn) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(alliances);")
    return any(str(row[1]) == "logo_url" for row in cur.fetchall())


def _alliance_recruitment_mode(row: Mapping[str, Any]) -> str:
    if row is None:
        return DEFAULT_RECRUITMENT_MODE
    return _normalize_recruitment_mode(row.get("recruitment_mode"))


def alliance_logo_schema_ready(conn) -> bool:
    return table_exists(conn, "alliance_logos")


def alliance_logo_api_path(alliance_id: int) -> str:
    return f"/api/alliance-logo/{int(alliance_id)}"


def alliance_logo_url_for_client(url: str, version: Any = None) -> str:
    base = str(url or "").strip()
    if not base:
        return ""
    if version is None or int(version or 0) <= 0:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}v={int(version)}"


def get_alliance_logo_row(alliance_id: int, conn) -> Optional[Dict[str, Any]]:
    if not alliance_logo_schema_ready(conn):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT alliance_id, image_blob, mime_type, updated_at
        FROM alliance_logos
        WHERE alliance_id = ?
        LIMIT 1;
        """,
        (int(alliance_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def alliance_logo_exists(alliance_id: int, conn) -> bool:
    return get_alliance_logo_row(alliance_id, conn=conn) is not None


def save_alliance_logo_blob(
    alliance_id: int,
    blob: bytes,
    mime_type: str,
    *,
    conn,
    updated_at: Optional[int] = None,
) -> None:
    now = int(updated_at or _now())
    conn.execute(
        """
        INSERT INTO alliance_logos (alliance_id, image_blob, mime_type, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(alliance_id) DO UPDATE SET
            image_blob = excluded.image_blob,
            mime_type = excluded.mime_type,
            updated_at = excluded.updated_at;
        """,
        (int(alliance_id), blob, str(mime_type or image_assets.BLOB_MIME), now),
    )


def can_serve_alliance_logo(alliance_id: int, *, conn=None) -> bool:
    own = conn is None
    if own:
        conn = db()
    try:
        if int(alliance_id) <= 0:
            return False
        return alliance_logo_exists(int(alliance_id), conn)
    finally:
        if own:
            conn.close()


def resolve_alliance_logo_display(
    url: Any,
    *,
    alliance_id: Optional[int] = None,
    version: Any = None,
    conn=None,
) -> Tuple[str, bool]:
    s = str(url or "").strip()
    if not s:
        return "", False
    m = _LOGO_API_RE.match(s)
    if not m:
        return "", False
    aid = int(alliance_id or int(m.group(1)))
    if aid != int(m.group(1)):
        return "", False
    own = conn is None
    if own:
        conn = db()
    try:
        if not alliance_logo_exists(aid, conn):
            return "", False
        row = get_alliance_logo_row(aid, conn=conn)
        ver = int(version or (row.get("updated_at") if row else 0) or 0)
        return alliance_logo_url_for_client(s, ver), True
    finally:
        if own:
            conn.close()


def _alliance_logo_payload(alliance_id: int, logo_url: Any, conn) -> Dict[str, Any]:
    aid = int(alliance_id)
    raw_url = str(logo_url or "").strip()
    client_url, show = resolve_alliance_logo_display(raw_url, alliance_id=aid, conn=conn)
    version = 0
    if show:
        row = get_alliance_logo_row(aid, conn=conn)
        version = int(row.get("updated_at") or 0) if row else 0
    return {
        "logo_url": raw_url,
        "logo_url_client": client_url,
        "show_logo": show,
        "logo_version": version,
    }


def upload_alliance_logo(officer_id: int, file_storage: Any, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    membership = get_player_alliance(officer_id, conn=conn)
    if not membership or not is_officer_role(membership.get("role")):
        raise ValueError("forbidden")
    aid = int(membership["alliance_id"])
    now = _now()
    last = int(_LAST_LOGO_UPLOAD_TS.get(aid, 0) or 0)
    if last and (now - last) < _LOGO_UPLOAD_COOLDOWN_SEC:
        raise ValueError("alliance_logo_rate_limited")

    blob, err = image_assets.blob_from_upload(file_storage)
    if blob is None:
        reason = {
            "image_upload_missing": "alliance_logo_missing",
            "image_upload_too_large": "alliance_logo_too_large",
            "image_upload_invalid_type": "alliance_logo_invalid_type",
        }.get(err, "alliance_logo_invalid_type")
        raise ValueError(reason)

    public_path = alliance_logo_api_path(aid)
    try:
        begin_write_transaction(conn)
        save_alliance_logo_blob(aid, blob, image_assets.BLOB_MIME, conn=conn, updated_at=now)
        conn.execute(
            "UPDATE alliances SET logo_url = ?, updated_at = ? WHERE id = ?;",
            (public_path, now, aid),
        )
        commit(conn)
        _LAST_LOGO_UPLOAD_TS[aid] = now
        return _alliance_logo_payload(aid, public_path, conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def get_player_alliance(player_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Return alliance row + member role for player, or None."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "alliance_members"):
            return None
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                a.id AS alliance_id,
                a.tag,
                a.name,
                a.description,
                a.alliance_level,
                a.alliance_xp,
                a.pool_metal,
                a.pool_crystal,
                a.pool_fuel_cells,
                a.member_limit,
                am.role,
                am.joined_at
            FROM alliance_members am
            JOIN alliances a ON a.id = am.alliance_id
            WHERE am.player_id = ?
            LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["role"] = _normalize_role(d.get("role"))
        return d
    finally:
        if own:
            conn.close()


def get_alliance_members(alliance_id: int, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT am.player_id, am.role, am.joined_at, p.name AS player_name
            FROM alliance_members am
            JOIN players p ON p.id = am.player_id
            WHERE am.alliance_id = ?
            ORDER BY
                CASE am.role
                    WHEN 'leader' THEN 0
                    WHEN 'owner' THEN 0
                    WHEN 'officer' THEN 1
                    ELSE 2
                END,
                am.joined_at ASC;
            """,
            (int(alliance_id),),
        )
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["role"] = _normalize_role(d.get("role"))
            rows.append(d)
        return rows
    finally:
        if own:
            conn.close()


def get_alliance_members_public(alliance_id: int, conn) -> List[Dict[str, Any]]:
    """Public member roster with donation contribution totals for guest profile."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT am.player_id, am.role, am.joined_at, p.name AS player_name,
               COALESCE(SUM(d.amount), 0) AS donation_points
        FROM alliance_members am
        JOIN players p ON p.id = am.player_id
        LEFT JOIN alliance_donations d
          ON d.alliance_id = am.alliance_id AND d.player_id = am.player_id
        WHERE am.alliance_id = ?
        GROUP BY am.player_id, am.role, am.joined_at, p.name
        ORDER BY donation_points DESC,
            CASE am.role
                WHEN 'leader' THEN 0
                WHEN 'owner' THEN 0
                WHEN 'officer' THEN 1
                ELSE 2
            END,
            am.joined_at ASC;
        """,
        (int(alliance_id),),
    )
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["role"] = _normalize_role(d.get("role"))
        d["donation_points"] = int(d.get("donation_points") or 0)
        rows.append(d)
    return rows


def get_alliance_public_profile(alliance_id: int, conn=None) -> Dict[str, Any]:
    """Public alliance card for guest browse / detail (no officer-only data)."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not alliance_hub_schema_ready(conn):
            raise ValueError("alliance_unavailable")
        row = _load_alliance_row(int(alliance_id), conn)
        if not row:
            raise ValueError("alliance_not_found")
        aid = int(row["id"])
        xp = int(row.get("alliance_xp") or 0)
        level = alliance_level_from_xp(xp)
        next_xp = alliance_xp_for_level(level + 1)
        mode = _alliance_recruitment_mode(row)
        techs = _load_techs(aid, conn)
        members = get_alliance_members_public(aid, conn)
        logo_fields = _alliance_logo_payload(aid, row.get("logo_url"), conn)
        return {
            "id": aid,
            "tag": str(row.get("tag") or ""),
            "name": str(row.get("name") or ""),
            "description": str(row.get("description") or ""),
            "alliance_level": level,
            "alliance_xp": xp,
            "alliance_xp_next": next_xp,
            "member_count": len(members),
            "member_limit": int(row.get("member_limit") or BASE_MEMBER_LIMIT),
            "recruitment_mode": mode,
            "allows_direct_join": allows_direct_join(mode),
            "allows_applications": allows_applications(mode),
            "members": members,
            "bonus_chips": compute_bonus_chips(techs),
            **logo_fields,
        }
    finally:
        if own:
            conn.close()


def _load_alliance_row(alliance_id: int, conn) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM alliances WHERE id = ? LIMIT 1;", (int(alliance_id),))
    row = cur.fetchone()
    return dict(row) if row else None


def _load_buildings(alliance_id: int, conn) -> Dict[str, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT building_key, level FROM alliance_buildings WHERE alliance_id = ?;",
        (int(alliance_id),),
    )
    return {str(r["building_key"]): int(r["level"]) for r in cur.fetchall()}


def _load_techs(alliance_id: int, conn) -> Dict[str, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT tech_key, level FROM alliance_technologies WHERE alliance_id = ?;",
        (int(alliance_id),),
    )
    return {str(r["tech_key"]): int(r["level"]) for r in cur.fetchall()}


def _sync_member_limit(conn, alliance_id: int, buildings: Mapping[str, int]) -> int:
    limit = member_limit_from_buildings(buildings)
    conn.execute(
        "UPDATE alliances SET member_limit = ?, updated_at = ? WHERE id = ?;",
        (int(limit), _now(), int(alliance_id)),
    )
    return limit


def _pool_cap_bonus_pct(techs: Mapping[str, int], buildings: Mapping[str, int]) -> float:
    tc = tech_level(techs, "trade_coordination")
    tc_cfg = ALLIANCE_TECHNOLOGIES.get("trade_coordination") or {}
    tc_pct = min(
        float(tc_cfg.get("bonus_max_pct") or 0),
        float(tc_cfg.get("bonus_pct_per_level") or 0) * tc,
    )
    depot_cfg = ALLIANCE_BUILDINGS.get("logistics_depot") or {}
    depot_pct = int(depot_cfg.get("pool_cap_bonus_pct_per_level") or 0) * building_level(
        buildings, "logistics_depot"
    )
    return tc_pct + float(depot_pct)


def _pool_snapshot(alliance_row: Mapping[str, Any], conn) -> Dict[str, Any]:
    aid = int(alliance_row["id"])
    buildings = _load_buildings(aid, conn)
    techs = _load_techs(aid, conn)
    level = alliance_level_from_xp(int(alliance_row.get("alliance_xp") or 0))
    avail = available_projects(
        alliance_level=level,
        buildings=buildings,
        techs=techs,
        trade_coord_level=tech_level(techs, "trade_coordination"),
    )
    cap_bonus = _pool_cap_bonus_pct(techs, buildings)
    cap = pool_cap_from_projects(avail, cap_bonus_pct=cap_bonus)
    pool = {
        "metal": int(alliance_row.get("pool_metal") or 0),
        "crystal": int(alliance_row.get("pool_crystal") or 0),
        "fuel_cells": int(alliance_row.get("pool_fuel_cells") or 0),
    }
    return {
        "pool": pool,
        "cap": cap,
        "cap_bonus_pct": round(cap_bonus, 1),
    }


def _active_project(alliance_id: int, conn) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM alliance_projects
        WHERE alliance_id = ? AND status = 'active'
        ORDER BY id ASC LIMIT 1;
        """,
        (int(alliance_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _recent_donations(alliance_id: int, conn, *, limit: int = 8) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.id, d.player_id, d.resource, d.amount, d.created_at, p.name AS player_name
        FROM alliance_donations d
        JOIN players p ON p.id = d.player_id
        WHERE d.alliance_id = ?
        ORDER BY d.created_at DESC
        LIMIT ?;
        """,
        (int(alliance_id), int(limit)),
    )
    return [dict(r) for r in cur.fetchall()]


def _player_donation_totals(player_id: int, alliance_id: int, conn) -> Dict[str, int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT resource, COALESCE(SUM(amount), 0) AS total
        FROM alliance_donations
        WHERE alliance_id = ? AND player_id = ?
        GROUP BY resource;
        """,
        (int(alliance_id), int(player_id)),
    )
    out = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    for r in cur.fetchall():
        key = str(r["resource"])
        if key in out:
            out[key] = int(r["total"])
    return out


def _diplomacy_rows(alliance_id: int, conn) -> List[Dict[str, Any]]:
    if not table_exists(conn, "alliance_diplomacy"):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.relation, d.updated_at,
               CASE WHEN d.alliance_id_low = ? THEN d.alliance_id_high ELSE d.alliance_id_low END AS other_id,
               a.tag AS other_tag, a.name AS other_name
        FROM alliance_diplomacy d
        JOIN alliances a ON a.id = CASE WHEN d.alliance_id_low = ? THEN d.alliance_id_high ELSE d.alliance_id_low END
        WHERE d.alliance_id_low = ? OR d.alliance_id_high = ?;
        """,
        (int(alliance_id), int(alliance_id), int(alliance_id), int(alliance_id)),
    )
    return [dict(r) for r in cur.fetchall()]


def _diplomacy_requests(alliance_id: int, conn) -> Dict[str, List[Dict[str, Any]]]:
    if not table_exists(conn, "alliance_diplomacy_requests"):
        return {"incoming": [], "outgoing": []}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.*, a.tag AS other_tag, a.name AS other_name
        FROM alliance_diplomacy_requests r
        JOIN alliances a ON a.id = r.from_alliance_id
        WHERE r.to_alliance_id = ? AND r.status = 'pending'
        ORDER BY r.created_at DESC;
        """,
        (int(alliance_id),),
    )
    incoming = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT r.*, a.tag AS other_tag, a.name AS other_name
        FROM alliance_diplomacy_requests r
        JOIN alliances a ON a.id = r.to_alliance_id
        WHERE r.from_alliance_id = ? AND r.status = 'pending'
        ORDER BY r.created_at DESC;
        """,
        (int(alliance_id),),
    )
    outgoing = [dict(r) for r in cur.fetchall()]
    return {"incoming": incoming, "outgoing": outgoing}


def _player_pending_application(player_id: int, conn) -> Optional[Dict[str, Any]]:
    has_col = _recruitment_mode_column_ready(conn)
    mode_col = "a.recruitment_mode" if has_col else f"'{DEFAULT_RECRUITMENT_MODE}' AS recruitment_mode"
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT ap.id, ap.alliance_id, ap.message, ap.status, ap.created_at,
               a.tag, a.name, {mode_col}
        FROM alliance_applications ap
        JOIN alliances a ON a.id = ap.alliance_id
        WHERE ap.player_id = ? AND ap.status = 'pending'
        ORDER BY ap.created_at DESC
        LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["recruitment_mode"] = _alliance_recruitment_mode(d)
    return d


def _notify_officers_new_application(
    alliance_id: int,
    applicant_id: int,
    applicant_name: str,
    message: str,
    *,
    conn,
) -> None:
    """Optional inbox ping for leaders/officers (GC-AL-008)."""
    try:
        from .messages import create_message

        tag_row = conn.execute(
            "SELECT tag FROM alliances WHERE id = ? LIMIT 1;",
            (int(alliance_id),),
        ).fetchone()
        tag = str(tag_row["tag"] if tag_row else "")
        subject = f"[{tag}] Neue Allianzbewerbung"
        body = f"{applicant_name} (ID {int(applicant_id)}) möchte beitreten.\n\n{message}"
        for member in get_alliance_members(int(alliance_id), conn=conn):
            if not can_manage_applications(member.get("role")):
                continue
            create_message(
                int(member["player_id"]),
                subject,
                body,
                category="system",
                sender_player_id=int(applicant_id),
                sender_name=str(applicant_name or ""),
                metadata={"alliance_id": int(alliance_id), "kind": "alliance_application"},
                conn=conn,
            )
    except Exception:
        pass


def _pending_applications(alliance_id: int, conn) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ap.id, ap.player_id, ap.message, ap.created_at, p.name AS player_name
        FROM alliance_applications ap
        JOIN players p ON p.id = ap.player_id
        WHERE ap.alliance_id = ? AND ap.status = 'pending'
        ORDER BY ap.created_at ASC;
        """,
        (int(alliance_id),),
    )
    return [dict(r) for r in cur.fetchall()]


def get_alliance_state(player_id: int, conn=None) -> Dict[str, Any]:
    """Full alliance hub payload for UI / API."""
    own = conn is None
    if own:
        conn = db()
    try:
        ready = alliance_hub_schema_ready(conn)
        base: Dict[str, Any] = {"ready": ready, "in_alliance": False}
        if not ready:
            return base

        membership = get_player_alliance(player_id, conn=conn)
        if not membership:
            has_recruitment_col = _recruitment_mode_column_ready(conn)
            recruit_sel = "recruitment_mode" if has_recruitment_col else f"'{DEFAULT_RECRUITMENT_MODE}' AS recruitment_mode"
            logo_sel = "logo_url" if _logo_url_column_ready(conn) else "'' AS logo_url"
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT id, tag, name, description, member_limit, alliance_level, alliance_xp,
                       {recruit_sel}, {logo_sel},
                       (SELECT COUNT(*) FROM alliance_members am WHERE am.alliance_id = alliances.id) AS member_count
                FROM alliances
                ORDER BY alliance_xp DESC, name ASC
                LIMIT 50;
                """
            )
            browse = []
            for row in cur.fetchall():
                d = dict(row)
                mode = _alliance_recruitment_mode(d)
                d["recruitment_mode"] = mode
                d["allows_direct_join"] = allows_direct_join(mode)
                d["allows_applications"] = allows_applications(mode)
                d["alliance_level"] = alliance_level_from_xp(int(d.get("alliance_xp") or 0))
                d.update(_alliance_logo_payload(int(d["id"]), d.get("logo_url"), conn))
                browse.append(d)
            pending = _player_pending_application(player_id, conn)
            base.update(
                {
                    "browse": browse,
                    "pending_application": pending,
                    "has_pending_application": pending is not None,
                }
            )
            return base

        aid = int(membership["alliance_id"])
        alliance_row = _load_alliance_row(aid, conn) or {}
        buildings = _load_buildings(aid, conn)
        techs = _load_techs(aid, conn)
        xp = int(alliance_row.get("alliance_xp") or 0)
        level = alliance_level_from_xp(xp)
        next_xp = alliance_xp_for_level(level + 1)
        members = get_alliance_members(aid, conn=conn)
        pool_data = _pool_snapshot(alliance_row, conn)
        role = _normalize_role(membership.get("role"))
        trade_lvl = tech_level(techs, "trade_coordination")
        projects_avail = available_projects(
            alliance_level=level,
            buildings=buildings,
            techs=techs,
            trade_coord_level=trade_lvl,
        )
        active = _active_project(aid, conn)
        now = _now()
        if active and int(active.get("finish_at") or 0) <= now:
            finish_due_alliance_projects(conn=conn, alliance_id=aid)
            alliance_row = _load_alliance_row(aid, conn) or alliance_row
            buildings = _load_buildings(aid, conn)
            techs = _load_techs(aid, conn)
            active = _active_project(aid, conn)
            pool_data = _pool_snapshot(alliance_row, conn)
            projects_avail = available_projects(
                alliance_level=level,
                buildings=buildings,
                techs=techs,
                trade_coord_level=trade_lvl,
            )

        diplomacy_unlocked = building_level(buildings, "diplomacy_center") >= 1
        logo_fields = _alliance_logo_payload(aid, alliance_row.get("logo_url"), conn)
        base.update(
            {
                "in_alliance": True,
                "alliance_id": aid,
                "tag": str(alliance_row.get("tag") or ""),
                "name": str(alliance_row.get("name") or ""),
                "description": str(alliance_row.get("description") or ""),
                "alliance_level": level,
                "alliance_xp": xp,
                "alliance_xp_next": next_xp,
                "member_count": len(members),
                "member_limit": int(alliance_row.get("member_limit") or BASE_MEMBER_LIMIT),
                "recruitment_mode": _alliance_recruitment_mode(alliance_row),
                **logo_fields,
                "members": members,
                "role": role,
                "can_manage": is_officer_role(role),
                "pool": pool_data["pool"],
                "pool_cap": pool_data["cap"],
                "pool_cap_bonus_pct": pool_data["cap_bonus_pct"],
                "my_donations": _player_donation_totals(player_id, aid, conn),
                "recent_donations": _recent_donations(aid, conn),
                "buildings": buildings,
                "technologies": techs,
                "bonus_chips": compute_bonus_chips(techs),
                "available_projects": projects_avail,
                "active_project": active,
                "applications": _pending_applications(aid, conn) if can_manage_applications(role) else [],
                "diplomacy_unlocked": diplomacy_unlocked,
                "diplomacy": _diplomacy_rows(aid, conn) if diplomacy_unlocked else [],
                "diplomacy_requests": _diplomacy_requests(aid, conn) if diplomacy_unlocked else {},
                "catalog": {
                    "buildings": ALLIANCE_BUILDINGS,
                    "technologies": ALLIANCE_TECHNOLOGIES,
                },
            }
        )
        return base
    finally:
        if own:
            conn.close()


def create_alliance(
    tag: str,
    name: str,
    founder_id: int,
    *,
    description: str = "",
    conn=None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    tag = str(tag or "").strip().upper()[:8]
    name = str(name or "").strip()[:64]
    desc = str(description or "").strip()[:512]
    if not tag or not name:
        raise ValueError("invalid_alliance")
    if get_player_alliance(founder_id, conn=conn):
        raise ValueError("already_in_alliance")
    if _player_pending_application(founder_id, conn=conn):
        raise ValueError("pending_application_exists")

    now = _now()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alliances (
                tag, name, description, alliance_level, alliance_xp,
                pool_metal, pool_crystal, pool_fuel_cells, member_limit,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 1, 0, 0, 0, 0, ?, ?, ?);
            """,
            (tag, name, desc, BASE_MEMBER_LIMIT, now, now),
        )
        aid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, 'leader', ?);
            """,
            (aid, int(founder_id), now),
        )
        cur.execute(
            """
            INSERT INTO alliance_buildings (alliance_id, building_key, level)
            VALUES (?, 'alliance_headquarters', 0);
            """,
            (aid,),
        )
        commit(conn)
        return {"id": aid, "tag": tag, "name": name}
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def are_players_allied(player_id: int, other_player_id: int, *, conn=None) -> bool:
    a = int(player_id)
    b = int(other_player_id)
    if a <= 0 or b <= 0 or a == b:
        return False
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "alliance_members"):
            return False
        cur = conn.cursor()
        cur.execute(
            """
            SELECT am1.alliance_id
            FROM alliance_members am1
            INNER JOIN alliance_members am2
                ON am2.alliance_id = am1.alliance_id AND am2.player_id = ?
            WHERE am1.player_id = ?
            LIMIT 1;
            """,
            (b, a),
        )
        return cur.fetchone() is not None
    finally:
        if own and conn is not None:
            conn.close()


def add_alliance_member(alliance_id: int, player_id: int, role: str = "member", conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    now = _now()
    try:
        if own:
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alliance_id, player_id) DO NOTHING;
            """,
            (int(alliance_id), int(player_id), _normalize_role(role), now),
        )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def _member_count(alliance_id: int, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM alliance_members WHERE alliance_id = ?;",
        (int(alliance_id),),
    )
    return int(cur.fetchone()["c"])


def leave_alliance(player_id: int, conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        aid = int(membership["alliance_id"])
        role = _normalize_role(membership.get("role"))
        if own:
            begin_write_transaction(conn)
        if role == "leader":
            members = get_alliance_members(aid, conn=conn)
            others = [m for m in members if int(m["player_id"]) != int(player_id)]
            if others:
                raise ValueError("leader_must_transfer")
            conn.execute("DELETE FROM alliances WHERE id = ?;", (aid,))
        else:
            conn.execute(
                "DELETE FROM alliance_members WHERE alliance_id = ? AND player_id = ?;",
                (aid, int(player_id)),
            )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def apply_to_alliance(player_id: int, alliance_id: int, message: str = "", conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    if get_player_alliance(player_id, conn=conn):
        raise ValueError("already_in_alliance")
    if _player_pending_application(player_id, conn):
        raise ValueError("pending_application_exists")
    msg = str(message or "").strip()[:256]
    if not msg:
        raise ValueError("application_message_required")
    now = _now()
    try:
        begin_write_transaction(conn)
        row = _load_alliance_row(int(alliance_id), conn)
        if not row:
            raise ValueError("alliance_not_found")
        mode = _alliance_recruitment_mode(row)
        if not allows_applications(mode):
            raise ValueError("recruitment_closed")
        if _member_count(int(alliance_id), conn) >= int(row.get("member_limit") or BASE_MEMBER_LIMIT):
            raise ValueError("alliance_full")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM alliance_applications
            WHERE alliance_id = ? AND player_id = ? AND status = 'pending'
            LIMIT 1;
            """,
            (int(alliance_id), int(player_id)),
        )
        if cur.fetchone():
            raise ValueError("application_already_pending")
        cur.execute(
            """
            INSERT INTO alliance_applications (alliance_id, player_id, message, status, created_at)
            VALUES (?, ?, ?, 'pending', ?);
            """,
            (int(alliance_id), int(player_id), msg, now),
        )
        cur.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
        prow = cur.fetchone()
        applicant_name = str(prow["name"] if prow else f"Player {player_id}")
        _notify_officers_new_application(
            int(alliance_id),
            int(player_id),
            applicant_name,
            msg,
            conn=conn,
        )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def withdraw_application(player_id: int, conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        pending = _player_pending_application(player_id, conn=conn)
        if not pending:
            raise ValueError("application_not_found")
        now = _now()
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE alliance_applications
            SET status = 'withdrawn', responded_at = ?
            WHERE id = ? AND player_id = ? AND status = 'pending';
            """,
            (now, int(pending["id"]), int(player_id)),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def join_alliance_by_tag(player_id: int, tag: str, conn=None) -> None:
    """Direct join when alliance recruitment_mode is open and slots available."""
    own = conn is None
    if own:
        conn = db()
    tag_u = str(tag or "").strip().upper()
    if not tag_u:
        raise ValueError("invalid_tag")
    if get_player_alliance(player_id, conn=conn):
        raise ValueError("already_in_alliance")
    if _player_pending_application(player_id, conn=conn):
        raise ValueError("pending_application_exists")
    now = _now()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute("SELECT * FROM alliances WHERE tag = ? LIMIT 1;", (tag_u,))
        row = cur.fetchone()
        if not row:
            raise ValueError("alliance_not_found")
        mode = _alliance_recruitment_mode(dict(row))
        if not allows_direct_join(mode):
            if mode == "application_only":
                raise ValueError("recruitment_application_only")
            raise ValueError("recruitment_closed")
        aid = int(row["id"])
        if _member_count(aid, conn) >= int(row["member_limit"] or BASE_MEMBER_LIMIT):
            raise ValueError("alliance_full")
        cur.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, 'member', ?)
            ON CONFLICT(alliance_id, player_id) DO NOTHING;
            """,
            (aid, int(player_id), now),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def respond_application(
    officer_id: int,
    application_id: int,
    *,
    accept: bool,
    conn=None,
) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(officer_id, conn=conn)
        if not membership or not can_manage_applications(membership.get("role")):
            raise ValueError("forbidden")
        aid = int(membership["alliance_id"])
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM alliance_applications WHERE id = ? AND alliance_id = ? LIMIT 1;",
            (int(application_id), aid),
        )
        app = cur.fetchone()
        if not app or str(app["status"]) != "pending":
            raise ValueError("application_not_found")
        now = _now()
        begin_write_transaction(conn)
        if accept:
            row = _load_alliance_row(aid, conn) or {}
            if _member_count(aid, conn) >= int(row.get("member_limit") or BASE_MEMBER_LIMIT):
                raise ValueError("alliance_full")
            if get_player_alliance(int(app["player_id"]), conn=conn):
                raise ValueError("player_already_allied")
            conn.execute(
                """
                INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
                VALUES (?, ?, 'member', ?)
                ON CONFLICT(alliance_id, player_id) DO NOTHING;
                """,
                (aid, int(app["player_id"]), now),
            )
            conn.execute(
                """
                UPDATE alliance_applications SET status = 'accepted', responded_at = ?
                WHERE id = ?;
                """,
                (now, int(application_id)),
            )
            conn.execute(
                """
                UPDATE alliance_applications SET status = 'withdrawn', responded_at = ?
                WHERE player_id = ? AND status = 'pending' AND id != ?;
                """,
                (now, int(app["player_id"]), int(application_id)),
            )
        else:
            conn.execute(
                """
                UPDATE alliance_applications SET status = 'declined', responded_at = ?
                WHERE id = ?;
                """,
                (now, int(application_id)),
            )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def update_alliance_description(player_id: int, description: str, conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    desc = str(description or "").strip()[:512]
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership or not is_officer_role(membership.get("role")):
            raise ValueError("forbidden")
        if own:
            begin_write_transaction(conn)
        conn.execute(
            "UPDATE alliances SET description = ?, updated_at = ? WHERE id = ?;",
            (desc, _now(), int(membership["alliance_id"])),
        )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def _try_spend_planet(conn, planet_id: int, metal: int, crystal: int, fuel_cells: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal - ?,
            crystal = crystal - ?,
            fuel_cells = fuel_cells - ?
        WHERE id = ?
          AND metal >= ?
          AND crystal >= ?
          AND fuel_cells >= ?;
        """,
        (
            int(metal),
            int(crystal),
            float(fuel_cells),
            int(planet_id),
            int(metal),
            int(crystal),
            float(fuel_cells),
        ),
    )
    return cur.rowcount == 1


def _donation_xp_today(player_id: int, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(xp_granted), 0) AS xp
        FROM alliance_donations
        WHERE player_id = ? AND created_at >= ?;
        """,
        (int(player_id), _day_start()),
    )
    return int(cur.fetchone()["xp"])


def donate_to_alliance(player_id: int, resource: str, amount: int, conn=None) -> None:
    res = str(resource or "").strip().lower()
    amt = int(amount or 0)
    if res not in VALID_DONATION_RESOURCES or amt <= 0:
        raise ValueError("invalid_donation")
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership:
            raise ValueError("not_in_alliance")
        aid = int(membership["alliance_id"])
        planet = get_context_planet(player_id=int(player_id), conn=conn)
        pid = int(planet["id"])
        alliance_row = _load_alliance_row(aid, conn) or {}
        pool_data = _pool_snapshot(alliance_row, conn)
        cap = pool_data["cap"]
        pool = pool_data["pool"]
        if int(pool.get(res) or 0) + amt > int(cap.get(res) or 0):
            raise ValueError("pool_cap_exceeded")

        xp_today = _donation_xp_today(player_id, conn)
        xp_room = max(0, DONATION_XP_DAILY_CAP - xp_today)
        xp_grant = min(
            xp_room,
            min(DONATION_XP_MAX_PER_DONATION, max(1, amt // DONATION_XP_DIVISOR)),
        )

        begin_write_transaction(conn)
        metal = amt if res == "metal" else 0
        crystal = amt if res == "crystal" else 0
        fuel = amt if res == "fuel_cells" else 0
        if not _try_spend_planet(conn, pid, metal, crystal, fuel):
            raise ValueError("insufficient_resources")

        col = {"metal": "pool_metal", "crystal": "pool_crystal", "fuel_cells": "pool_fuel_cells"}[res]
        conn.execute(
            f"UPDATE alliances SET {col} = {col} + ?, updated_at = ? WHERE id = ?;",
            (amt, _now(), aid),
        )
        conn.execute(
            """
            INSERT INTO alliance_donations (alliance_id, player_id, resource, amount, xp_granted, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (aid, int(player_id), res, amt, int(xp_grant), _now()),
        )
        if xp_grant > 0:
            _grant_alliance_xp(conn, aid, int(xp_grant))
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def _grant_alliance_xp(conn, alliance_id: int, xp: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT alliance_xp FROM alliances WHERE id = ? LIMIT 1;",
        (int(alliance_id),),
    )
    row = cur.fetchone()
    if not row:
        return
    new_xp = int(row["alliance_xp"] or 0) + max(0, int(xp))
    new_level = alliance_level_from_xp(new_xp)
    conn.execute(
        """
        UPDATE alliances SET alliance_xp = ?, alliance_level = ?, updated_at = ?
        WHERE id = ?;
        """,
        (new_xp, new_level, _now(), int(alliance_id)),
    )


def _deduct_pool(conn, alliance_id: int, cost: Mapping[str, int]) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE alliances
        SET pool_metal = pool_metal - ?,
            pool_crystal = pool_crystal - ?,
            pool_fuel_cells = pool_fuel_cells - ?,
            updated_at = ?
        WHERE id = ?
          AND pool_metal >= ?
          AND pool_crystal >= ?
          AND pool_fuel_cells >= ?;
        """,
        (
            int(cost.get("metal") or 0),
            int(cost.get("crystal") or 0),
            int(cost.get("fuel_cells") or 0),
            _now(),
            int(alliance_id),
            int(cost.get("metal") or 0),
            int(cost.get("crystal") or 0),
            int(cost.get("fuel_cells") or 0),
        ),
    )
    if cur.rowcount != 1:
        raise ValueError("insufficient_pool")


def start_alliance_project(player_id: int, project_kind: str, target_key: str, conn=None) -> None:
    kind = str(project_kind or "").strip().lower()
    key = str(target_key or "").strip()
    if kind not in ("building", "tech"):
        raise ValueError("invalid_project")
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership or not is_officer_role(membership.get("role")):
            raise ValueError("forbidden")
        aid = int(membership["alliance_id"])
        if _active_project(aid, conn):
            raise ValueError("project_active")

        alliance_row = _load_alliance_row(aid, conn) or {}
        buildings = _load_buildings(aid, conn)
        techs = _load_techs(aid, conn)
        level = alliance_level_from_xp(int(alliance_row.get("alliance_xp") or 0))
        trade_lvl = tech_level(techs, "trade_coordination")

        if kind == "building":
            cur_lvl = building_level(buildings, key)
            cfg = ALLIANCE_BUILDINGS.get(key)
        else:
            cur_lvl = tech_level(techs, key)
            cfg = ALLIANCE_TECHNOLOGIES.get(key)
        if not cfg:
            raise ValueError("invalid_project")
        target_level = cur_lvl + 1
        if target_level > int(cfg.get("max_level") or 1):
            raise ValueError("max_level")

        from .alliance_catalog import _requirements_met

        if not _requirements_met(
            cfg.get("requires"),
            alliance_level=level,
            buildings=buildings,
            techs=techs,
        ):
            raise ValueError("requirements_not_met")

        cost, duration = project_cost_and_duration(kind, key, target_level, trade_coord_level=trade_lvl)
        now = _now()
        if own:
            begin_write_transaction(conn)
        _deduct_pool(conn, aid, cost)
        conn.execute(
            """
            INSERT INTO alliance_projects (
                alliance_id, project_kind, target_key, target_level, status,
                started_at, finish_at, cost_metal, cost_crystal, cost_fuel_cells, created_by
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?);
            """,
            (
                aid,
                kind,
                key,
                target_level,
                now,
                now + int(duration),
                int(cost["metal"]),
                int(cost["crystal"]),
                int(cost["fuel_cells"]),
                int(player_id),
            ),
        )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def finish_due_alliance_projects(conn=None, *, alliance_id: Optional[int] = None) -> int:
    """Complete alliance projects whose timer elapsed. Separate from planet queue_engine."""
    own = conn is None
    if own:
        conn = db()
    if not alliance_hub_schema_ready(conn):
        return 0
    now = _now()
    finished = 0
    try:
        if own:
            begin_write_transaction(conn)
        cur = conn.cursor()
        if alliance_id is not None:
            cur.execute(
                """
                SELECT * FROM alliance_projects
                WHERE alliance_id = ? AND status = 'active' AND finish_at <= ?
                ORDER BY id ASC;
                """,
                (int(alliance_id), now),
            )
        else:
            cur.execute(
                """
                SELECT * FROM alliance_projects
                WHERE status = 'active' AND finish_at <= ?
                ORDER BY id ASC;
                """,
                (now,),
            )
        rows = [dict(r) for r in cur.fetchall()]
        for proj in rows:
            aid = int(proj["alliance_id"])
            kind = str(proj["project_kind"])
            key = str(proj["target_key"])
            lvl = int(proj["target_level"])
            if kind == "building":
                conn.execute(
                    """
                    INSERT INTO alliance_buildings (alliance_id, building_key, level)
                    VALUES (?, ?, ?)
                    ON CONFLICT(alliance_id, building_key) DO UPDATE SET level = excluded.level;
                    """,
                    (aid, key, lvl),
                )
                if key == "alliance_headquarters":
                    buildings = _load_buildings(aid, conn)
                    _sync_member_limit(conn, aid, buildings)
            else:
                conn.execute(
                    """
                    INSERT INTO alliance_technologies (alliance_id, tech_key, level)
                    VALUES (?, ?, ?)
                    ON CONFLICT(alliance_id, tech_key) DO UPDATE SET level = excluded.level;
                    """,
                    (aid, key, lvl),
                )
            conn.execute(
                "UPDATE alliance_projects SET status = 'completed' WHERE id = ?;",
                (int(proj["id"]),),
            )
            cost_sum = (
                int(proj.get("cost_metal") or 0)
                + int(proj.get("cost_crystal") or 0)
                + int(proj.get("cost_fuel_cells") or 0)
            )
            xp = max(10, cost_sum // PROJECT_XP_DIVISOR)
            _grant_alliance_xp(conn, aid, xp)
            finished += 1
        if own:
            commit(conn)
        return finished
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def _diplomacy_pair(a: int, b: int) -> Tuple[int, int]:
    x, y = int(a), int(b)
    if x > y:
        x, y = y, x
    return x, y


def get_alliance_relation(alliance_id_a: int, alliance_id_b: int, conn=None) -> str:
    if int(alliance_id_a) == int(alliance_id_b):
        return "alliance"
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "alliance_diplomacy"):
            return "neutral"
        lo, hi = _diplomacy_pair(alliance_id_a, alliance_id_b)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT relation FROM alliance_diplomacy
            WHERE alliance_id_low = ? AND alliance_id_high = ?
            LIMIT 1;
            """,
            (lo, hi),
        )
        row = cur.fetchone()
        return str(row["relation"]) if row else "neutral"
    finally:
        if own:
            conn.close()


def send_diplomacy_request(
    player_id: int,
    target_tag: str,
    request_type: str,
    conn=None,
) -> None:
    rtype = str(request_type or "").strip().lower()
    if rtype not in DIPLOMACY_REQUEST_TYPES:
        raise ValueError("invalid_request")
    tag = str(target_tag or "").strip().upper()
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership or not is_officer_role(membership.get("role")):
            raise ValueError("forbidden")
        from_aid = int(membership["alliance_id"])
        buildings = _load_buildings(from_aid, conn)
        if building_level(buildings, "diplomacy_center") < 1:
            raise ValueError("diplomacy_locked")
        cur = conn.cursor()
        cur.execute("SELECT id FROM alliances WHERE tag = ? LIMIT 1;", (tag,))
        target = cur.fetchone()
        if not target:
            raise ValueError("alliance_not_found")
        to_aid = int(target["id"])
        if to_aid == from_aid:
            raise ValueError("invalid_target")
        now = _now()
        if own:
            begin_write_transaction(conn)
        if rtype == "war":
            lo, hi = _diplomacy_pair(from_aid, to_aid)
            conn.execute(
                """
                INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)
                VALUES (?, ?, 'war', ?)
                ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET
                    relation = 'war', updated_at = excluded.updated_at;
                """,
                (lo, hi, now),
            )
        else:
            conn.execute(
                """
                INSERT INTO alliance_diplomacy_requests (
                    from_alliance_id, to_alliance_id, request_type, status, created_at
                )
                VALUES (?, ?, ?, 'pending', ?);
                """,
                (from_aid, to_aid, rtype, now),
            )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def respond_diplomacy_request(
    player_id: int,
    request_id: int,
    *,
    accept: bool,
    conn=None,
) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership or not is_officer_role(membership.get("role")):
            raise ValueError("forbidden")
        to_aid = int(membership["alliance_id"])
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM alliance_diplomacy_requests
            WHERE id = ? AND to_alliance_id = ? AND status = 'pending'
            LIMIT 1;
            """,
            (int(request_id), to_aid),
        )
        req = cur.fetchone()
        if not req:
            raise ValueError("request_not_found")
        now = _now()
        if own:
            begin_write_transaction(conn)
        if accept:
            relation = "alliance" if str(req["request_type"]) == "alliance" else "nap"
            if relation not in DIPLOMACY_RELATIONS:
                relation = "nap"
            lo, hi = _diplomacy_pair(int(req["from_alliance_id"]), to_aid)
            conn.execute(
                """
                INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET
                    relation = excluded.relation, updated_at = excluded.updated_at;
                """,
                (lo, hi, relation, now),
            )
            conn.execute(
                """
                UPDATE alliance_diplomacy_requests
                SET status = 'accepted', responded_at = ?, responded_by = ?
                WHERE id = ?;
                """,
                (now, int(player_id), int(request_id)),
            )
        else:
            conn.execute(
                """
                UPDATE alliance_diplomacy_requests
                SET status = 'declined', responded_at = ?, responded_by = ?
                WHERE id = ?;
                """,
                (now, int(player_id), int(request_id)),
            )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def get_alliance_effect_modifiers(player_id: int, conn=None) -> Dict[str, float]:
    """EffectResolver extension — only for alliance members."""
    own = conn is None
    if own:
        conn = db()
    mods: Dict[str, float] = {
        "research_time_speed": 1.0,
        "metal_prod_factor": 1.0,
        "crystal_prod_factor": 1.0,
        "fuel_prod_factor": 1.0,
        "armor_bonus": 0.0,
        "shield_bonus": 0.0,
        "expedition_loot_mult": 1.0,
    }
    try:
        if not alliance_hub_schema_ready(conn):
            return mods
        membership = get_player_alliance(player_id, conn=conn)
        if not membership:
            return mods
        techs = _load_techs(int(membership["alliance_id"]), conn)

        rn = tech_level(techs, "research_network")
        if rn > 0:
            cfg = ALLIANCE_TECHNOLOGIES["research_network"]
            pct = min(float(cfg["bonus_max_pct"]), float(cfg["bonus_pct_per_level"]) * rn)
            mods["research_time_speed"] *= 1.0 + pct / 100.0

        il = tech_level(techs, "industrial_logistics")
        if il > 0:
            cfg = ALLIANCE_TECHNOLOGIES["industrial_logistics"]
            pct = min(float(cfg["bonus_max_pct"]), float(cfg["bonus_pct_per_level"]) * il)
            factor = 1.0 + pct / 100.0
            mods["metal_prod_factor"] *= factor
            mods["crystal_prod_factor"] *= factor
            mods["fuel_prod_factor"] *= factor

        dp = tech_level(techs, "defensive_protocols")
        if dp > 0:
            cfg = ALLIANCE_TECHNOLOGIES["defensive_protocols"]
            pct = min(float(cfg["bonus_max_pct"]), float(cfg["bonus_pct_per_level"]) * dp)
            mods["armor_bonus"] += pct / 100.0
            mods["shield_bonus"] += pct / 100.0

        ec = tech_level(techs, "expedition_coordination")
        if ec > 0:
            cfg = ALLIANCE_TECHNOLOGIES["expedition_coordination"]
            pct = min(float(cfg["bonus_max_pct"]), float(cfg["bonus_pct_per_level"]) * ec)
            mods["expedition_loot_mult"] *= 1.0 + pct / 100.0

        return mods
    finally:
        if own:
            conn.close()


def get_alliance_expedition_loot_multiplier(player_id: int, conn=None) -> float:
    return float(get_alliance_effect_modifiers(player_id, conn=conn).get("expedition_loot_mult") or 1.0)


def get_player_alliance_diplomacy_label(player_id: int, conn=None) -> str:
    """Short label for player card."""
    own = conn is None
    if own:
        conn = db()
    try:
        membership = get_player_alliance(player_id, conn=conn)
        if not membership:
            return ""
        tag = str(membership.get("tag") or "")
        name = str(membership.get("name") or "")
        if tag:
            return f"[{tag}] {name}".strip()
        return name
    finally:
        if own:
            conn.close()
