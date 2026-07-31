"""
EPIC-27 — Commander Classes & Skill Trees.

Owner: game/commander_classes.py · Catalog: commander_class_catalog.py
Docs: docs/COMMANDER_CLASSES.md
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .commander_class_catalog import (
    ADDITIVE_MOD_KEYS,
    CLASSES,
    CLASS_KEYS,
    SP_MILESTONES,
    class_preview_mods,
    get_class,
    get_skill,
    is_valid_class,
    preview_chips_for_class,
    role_icon_path,
    skill_image_path,
    skill_per_rank_effect_chips,
    skill_rank_effect_chips,
    skills_for_class,
    swap_cost_sec,
)
from .db import table_exists

logger = logging.getLogger(__name__)


def schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, "player_commander")
        and table_exists(conn, "player_commander_skills")
        and table_exists(conn, "player_commander_sp_claims")
    )


def _now() -> float:
    return float(time.time())


def _ensure_row(player_id: int, *, conn) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT player_id FROM player_commander WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    if cur.fetchone():
        return
    cur.execute(
        """
        INSERT INTO player_commander (
            player_id, class_key, chosen_at, swap_count,
            skill_points_unspent, skill_points_earned, updated_at
        ) VALUES (?, NULL, NULL, 0, 0, 0, ?);
        """,
        (int(player_id), _now()),
    )


def _record_event(player_id: int, event_type: str, detail: Dict[str, Any], *, conn) -> None:
    if not table_exists(conn, "player_commander_events"):
        return
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_commander_events (player_id, event_type, detail_json, created_at)
        VALUES (?, ?, ?, ?);
        """,
        (
            int(player_id),
            str(event_type)[:64],
            json.dumps(detail or {}, separators=(",", ":"))[:4000],
            _now(),
        ),
    )


def get_commander_row(player_id: int, *, conn) -> Dict[str, Any]:
    _ensure_row(int(player_id), conn=conn)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT player_id, class_key, chosen_at, swap_count,
               skill_points_unspent, skill_points_earned, updated_at
        FROM player_commander WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else {
        "player_id": int(player_id),
        "class_key": None,
        "chosen_at": None,
        "swap_count": 0,
        "skill_points_unspent": 0,
        "skill_points_earned": 0,
        "updated_at": 0,
    }


def get_skill_ranks(player_id: int, *, conn) -> Dict[str, int]:
    if not schema_ready(conn):
        return {}
    cur = conn.cursor()
    cur.execute(
        "SELECT skill_key, rank FROM player_commander_skills WHERE player_id = ?;",
        (int(player_id),),
    )
    out: Dict[str, int] = {}
    for row in cur.fetchall() or []:
        out[str(row["skill_key"])] = max(0, int(row["rank"] or 0))
    return out


def _player_score_total(player_id: int, *, conn) -> int:
    if not table_exists(conn, "player_scores"):
        return 0
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(score_total, 0) AS s FROM player_scores WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    return max(0, int((row["s"] if row else 0) or 0))


def _claimed_milestones(player_id: int, *, conn) -> set:
    cur = conn.cursor()
    cur.execute(
        "SELECT milestone_key FROM player_commander_sp_claims WHERE player_id = ?;",
        (int(player_id),),
    )
    return {str(r["milestone_key"]) for r in (cur.fetchall() or [])}


def _prereq_satisfied(skill: Dict[str, Any], ranks: Dict[str, int]) -> bool:
    prereq = skill.get("prereq_skill")
    if not prereq:
        return True
    cfg = get_skill(str(prereq))
    if not cfg:
        return False
    need = int(cfg.get("max_rank") or 1)
    return int(ranks.get(str(prereq), 0) or 0) >= need


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
    return int(cur.rowcount or 0) == 1


def pick_class(player_id: int, class_key: str, *, conn) -> Tuple[bool, str, Dict[str, Any]]:
    if not schema_ready(conn):
        return False, "schema_unavailable", {}
    ck = str(class_key or "").strip()
    if not is_valid_class(ck):
        return False, "invalid_class", {}
    row = get_commander_row(int(player_id), conn=conn)
    if row.get("class_key"):
        return False, "class_already_set", serialize_for_client(int(player_id), conn=conn)
    cur = conn.cursor()
    now = _now()
    cur.execute(
        """
        UPDATE player_commander
        SET class_key = ?, chosen_at = ?, updated_at = ?
        WHERE player_id = ? AND class_key IS NULL;
        """,
        (ck, now, now, int(player_id)),
    )
    if int(cur.rowcount or 0) <= 0:
        return False, "class_already_set", serialize_for_client(int(player_id), conn=conn)
    _record_event(int(player_id), "pick", {"class_key": ck}, conn=conn)
    return True, "ok", serialize_for_client(int(player_id), conn=conn)


def claim_skill_points(player_id: int, *, conn) -> Tuple[bool, str, Dict[str, Any]]:
    if not schema_ready(conn):
        return False, "schema_unavailable", {}
    uid = int(player_id)
    _ensure_row(uid, conn=conn)
    score = _player_score_total(uid, conn=conn)
    claimed = _claimed_milestones(uid, conn=conn)
    granted = 0
    newly: List[str] = []
    cur = conn.cursor()
    now = _now()
    for ms in SP_MILESTONES:
        key = str(ms["key"])
        if key in claimed:
            continue
        if score < int(ms["min_score"]):
            continue
        pts = int(ms["points"])
        cur.execute(
            """
            INSERT INTO player_commander_sp_claims
                (player_id, milestone_key, claimed_at, points_granted)
            VALUES (?, ?, ?, ?);
            """,
            (uid, key, now, pts),
        )
        granted += pts
        newly.append(key)
    if granted > 0:
        cur.execute(
            """
            UPDATE player_commander
            SET skill_points_unspent = skill_points_unspent + ?,
                skill_points_earned = skill_points_earned + ?,
                updated_at = ?
            WHERE player_id = ?;
            """,
            (granted, granted, now, uid),
        )
        _record_event(
            uid,
            "sp_claim",
            {"points": granted, "milestones": newly, "score": score},
            conn=conn,
        )
    payload = serialize_for_client(uid, conn=conn)
    payload["claimed_points"] = granted
    payload["claimed_milestones"] = newly
    return True, "ok", payload


def unlock_skill(
    player_id: int,
    skill_key: str,
    *,
    planet_id: Optional[int] = None,
    conn,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not schema_ready(conn):
        return False, "schema_unavailable", {}
    uid = int(player_id)
    sk = str(skill_key or "").strip()
    cfg = get_skill(sk)
    if not cfg:
        return False, "unknown_skill", {}
    row = get_commander_row(uid, conn=conn)
    class_key = str(row.get("class_key") or "")
    if not class_key:
        return False, "no_class", {}
    if str(cfg["class_key"]) != class_key:
        return False, "wrong_class_skill", {}

    ranks = get_skill_ranks(uid, conn=conn)
    current = int(ranks.get(sk, 0) or 0)
    max_rank = int(cfg.get("max_rank") or 1)
    if current >= max_rank:
        return False, "already_maxed", serialize_for_client(uid, conn=conn)
    if not _prereq_satisfied(cfg, ranks):
        return False, "prereq_missing", {}

    sp_cost = int(cfg.get("sp_cost") or 0)
    is_capstone = bool(cfg.get("is_capstone"))
    resource_cost = cfg.get("resource_cost") or None

    if sp_cost > 0:
        unspent = int(row.get("skill_points_unspent") or 0)
        if unspent < sp_cost:
            return False, "insufficient_skill_points", serialize_for_client(uid, conn=conn)

    spent_planet_id = None
    if resource_cost:
        from .shipyard import resolve_owned_planet_id

        pid, planet_err = resolve_owned_planet_id(uid, planet_id, conn=conn)
        if planet_err or pid is None:
            return False, planet_err or "no_planet", {}
        metal = int(resource_cost.get("metal") or 0)
        crystal = int(resource_cost.get("crystal") or 0)
        fuel = int(resource_cost.get("fuel_cells") or 0)
        if not _try_spend_planet(conn, int(pid), metal, crystal, fuel):
            return False, "insufficient_resources", serialize_for_client(uid, conn=conn)
        spent_planet_id = int(pid)

    now = _now()
    cur = conn.cursor()
    if sp_cost > 0:
        cur.execute(
            """
            UPDATE player_commander
            SET skill_points_unspent = skill_points_unspent - ?,
                updated_at = ?
            WHERE player_id = ? AND skill_points_unspent >= ?;
            """,
            (sp_cost, now, uid, sp_cost),
        )
        if int(cur.rowcount or 0) <= 0:
            return False, "insufficient_skill_points", serialize_for_client(uid, conn=conn)

    new_rank = current + 1
    if current <= 0:
        cur.execute(
            """
            INSERT INTO player_commander_skills (player_id, skill_key, rank, unlocked_at)
            VALUES (?, ?, ?, ?);
            """,
            (uid, sk, new_rank, now),
        )
    else:
        cur.execute(
            """
            UPDATE player_commander_skills
            SET rank = ?, unlocked_at = ?
            WHERE player_id = ? AND skill_key = ?;
            """,
            (new_rank, now, uid, sk),
        )
    cur.execute(
        "UPDATE player_commander SET updated_at = ? WHERE player_id = ?;",
        (now, uid),
    )
    _record_event(
        uid,
        "capstone_unlock" if is_capstone else "skill_unlock",
        {
            "skill_key": sk,
            "rank": new_rank,
            "sp_cost": sp_cost,
            "planet_id": spent_planet_id,
            "resource_cost": resource_cost,
        },
        conn=conn,
    )
    return True, "ok", serialize_for_client(uid, conn=conn)


def swap_class(player_id: int, *, conn) -> Tuple[bool, str, Dict[str, Any]]:
    """Clear class + refund spent SP via Timekeeper debit. Re-pick required."""
    if not schema_ready(conn):
        return False, "schema_unavailable", {}
    uid = int(player_id)
    row = get_commander_row(uid, conn=conn)
    if not row.get("class_key"):
        return False, "no_class", serialize_for_client(uid, conn=conn)

    from .timekeeper import InsufficientTimekeeperBalance, debit, get_balance, schema_ready as tk_ready

    if not tk_ready(conn):
        return False, "timekeeper_unavailable", {}

    swap_n = int(row.get("swap_count") or 0)
    cost = swap_cost_sec(swap_n)
    try:
        debit(uid, cost, f"class_swap:{swap_n}", conn=conn)
    except InsufficientTimekeeperBalance:
        return False, "insufficient_timekeeper", {
            **serialize_for_client(uid, conn=conn),
            "swap_cost_sec": cost,
            "timekeeper_balance_sec": get_balance(uid, conn=conn),
        }

    earned = int(row.get("skill_points_earned") or 0)
    now = _now()
    cur = conn.cursor()
    cur.execute("DELETE FROM player_commander_skills WHERE player_id = ?;", (uid,))
    cur.execute(
        """
        UPDATE player_commander
        SET class_key = NULL,
            chosen_at = NULL,
            swap_count = swap_count + 1,
            skill_points_unspent = ?,
            updated_at = ?
        WHERE player_id = ?;
        """,
        (earned, now, uid),
    )
    _record_event(
        uid,
        "swap",
        {
            "previous_class": row.get("class_key"),
            "cost_sec": cost,
            "refunded_sp": earned,
            "swap_count_after": swap_n + 1,
        },
        conn=conn,
    )
    payload = serialize_for_client(uid, conn=conn)
    payload["swap_cost_sec"] = cost
    try:
        from .timekeeper import serialize_for_client as tk_serialize

        payload["timekeeper"] = tk_serialize(uid, conn=conn)
    except Exception:
        pass
    return True, "ok", payload


def get_commander_effect_modifiers(player_id: int, *, conn) -> Dict[str, float]:
    """Merged additive/multiplicative mods for EffectResolver (no meta keys)."""
    if not schema_ready(conn):
        return {}
    row = get_commander_row(int(player_id), conn=conn)
    class_key = str(row.get("class_key") or "")
    if not class_key:
        return {}
    ranks = get_skill_ranks(int(player_id), conn=conn)
    if not ranks:
        return {}

    out: Dict[str, float] = {}
    for skill in skills_for_class(class_key):
        sk = str(skill["key"])
        rank = int(ranks.get(sk, 0) or 0)
        if rank <= 0:
            continue
        per = skill.get("effect_mods_per_rank") or {}
        for k, raw in per.items():
            key = str(k)
            val = float(raw)
            if key in ADDITIVE_MOD_KEYS:
                out[key] = float(out.get(key, 0.0)) + val * rank
            else:
                base = float(out.get(key, 1.0))
                out[key] = base * (val ** rank)
    return out


def iter_commander_effect_sources(player_id: int, *, conn) -> List[Tuple[str, str, float]]:
    """Yield (mod_key, source_label, delta_or_mult) for admin/ER source entries."""
    if not schema_ready(conn):
        return []
    row = get_commander_row(int(player_id), conn=conn)
    class_key = str(row.get("class_key") or "")
    if not class_key:
        return []
    ranks = get_skill_ranks(int(player_id), conn=conn)
    out: List[Tuple[str, str, float]] = []
    for skill in skills_for_class(class_key):
        sk = str(skill["key"])
        rank = int(ranks.get(sk, 0) or 0)
        if rank <= 0:
            continue
        label = f"class:{class_key}:{sk}"
        per = skill.get("effect_mods_per_rank") or {}
        for k, raw in per.items():
            key = str(k)
            val = float(raw)
            if key in ADDITIVE_MOD_KEYS:
                out.append((key, label, val * rank))
            else:
                out.append((key, label, val ** rank))
    return out


def _skill_ui_rows(class_key: str, ranks: Dict[str, int], unspent: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for skill in skills_for_class(class_key):
        sk = str(skill["key"])
        current = int(ranks.get(sk, 0) or 0)
        max_rank = int(skill.get("max_rank") or 1)
        prereq_ok = _prereq_satisfied(skill, ranks)
        sp_cost = int(skill.get("sp_cost") or 0)
        can_afford_sp = sp_cost <= 0 or unspent >= sp_cost
        available = current < max_rank and prereq_ok and can_afford_sp
        if skill.get("resource_cost") and current < max_rank and prereq_ok:
            # Capstones: available if prereq ok (resource check at unlock time).
            available = prereq_ok and (sp_cost <= 0 or can_afford_sp)
        status = "maxed" if current >= max_rank else ("available" if available else "locked")
        rows.append(
            {
                "key": sk,
                "order": int(skill["order"]),
                "name_key": skill["name_key"],
                "desc_key": skill["desc_key"],
                "icon_key": skill.get("icon_key"),
                "image": skill_image_path(sk),
                "rank": current,
                "max_rank": max_rank,
                "sp_cost": sp_cost,
                "is_capstone": bool(skill.get("is_capstone")),
                "resource_cost": skill.get("resource_cost"),
                "prereq_skill": skill.get("prereq_skill"),
                "effect_mods_per_rank": skill.get("effect_mods_per_rank") or {},
                "effect_chips_per_rank": skill_per_rank_effect_chips(skill),
                "effect_chips": skill_rank_effect_chips(skill, current),
                "status": status,
            }
        )
    return rows


def serialize_for_client(player_id: int, *, conn) -> Dict[str, Any]:
    if not schema_ready(conn):
        return {
            "ready": False,
            "class_key": None,
            "classes": [],
            "skills": [],
            "skill_points_unspent": 0,
            "skill_points_earned": 0,
        }
    uid = int(player_id)
    row = get_commander_row(uid, conn=conn)
    ranks = get_skill_ranks(uid, conn=conn)
    class_key = row.get("class_key")
    unspent = int(row.get("skill_points_unspent") or 0)
    earned = int(row.get("skill_points_earned") or 0)
    swap_n = int(row.get("swap_count") or 0)
    score = _player_score_total(uid, conn=conn)
    claimed = _claimed_milestones(uid, conn=conn)

    pending_sp = 0
    pending_milestones: List[Dict[str, Any]] = []
    for ms in SP_MILESTONES:
        key = str(ms["key"])
        if key in claimed:
            continue
        if score >= int(ms["min_score"]):
            pending_sp += int(ms["points"])
            pending_milestones.append(
                {"key": key, "min_score": int(ms["min_score"]), "points": int(ms["points"])}
            )

    class_list = []
    for ck in CLASS_KEYS:
        meta = CLASSES[ck]
        icons = list(meta.get("icons") or ())
        class_list.append(
            {
                "key": ck,
                "name_key": meta["name_key"],
                "desc_key": meta["desc_key"],
                "tagline_key": meta["tagline_key"],
                "officer_key": meta.get("officer_key"),
                "title_key": meta.get("title_key"),
                "epithet_key": meta.get("epithet_key"),
                "portrait": meta.get("portrait"),
                "theme": meta.get("theme") or ck,
                "icons": [
                    {
                        "key": ik,
                        "label_key": f"commander_icon_{ik}",
                        "path": role_icon_path(ik),
                    }
                    for ik in icons
                ],
                "preview_chips": preview_chips_for_class(ck, limit=4),
                "playstyle": meta["playstyle"],
                "preview_mods": class_preview_mods(ck),
                "selected": ck == class_key,
            }
        )

    skills = _skill_ui_rows(str(class_key), ranks, unspent) if class_key else []
    next_swap = swap_cost_sec(swap_n)

    return {
        "ready": True,
        "class_key": class_key,
        "class_meta": get_class(str(class_key)) if class_key else None,
        "chosen_at": row.get("chosen_at"),
        "swap_count": swap_n,
        "swap_cost_sec": next_swap,
        "skill_points_unspent": unspent,
        "skill_points_earned": earned,
        "score_total": score,
        "pending_sp": pending_sp,
        "pending_milestones": pending_milestones,
        "classes": class_list,
        "skills": skills,
        "ranks": ranks,
    }


def get_skilltree_page_context(player_id: int, *, conn) -> Dict[str, Any]:
    claim_skill_points(int(player_id), conn=conn)
    return {"commander": serialize_for_client(int(player_id), conn=conn)}
