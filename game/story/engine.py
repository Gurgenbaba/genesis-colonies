"""Story arc engine — start, advance, choice, auto-resolve rewards/gates."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..db import table_exists
from .flags import flags_satisfy, get_player_flags, set_flags
from .packs import get_arc, load_all_packs, next_beat_position, resolve_beat
from .rewards import apply_grants

logger = logging.getLogger(__name__)

ARCS_TABLE = "player_story_arcs"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"


def story_schema_ready(conn) -> bool:
    return table_exists(conn, ARCS_TABLE)


def ensure_player_story(
    player_id: int,
    *,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """Start eligible arcs and auto-resolve reward/gate beats."""
    pid = int(player_id)
    if pid <= 0 or not story_schema_ready(conn):
        return {"started": 0, "advanced": 0}

    ts = float(now if now is not None else time.time())
    _repair_false_completions(pid, conn=conn, now=ts)
    started = _start_eligible_arcs(pid, conn=conn, now=ts)
    _repair_out_of_range_arcs(pid, conn=conn, now=ts)
    advanced = 0
    for row in _active_arc_rows(pid, conn=conn):
        for _ in range(12):
            res = try_auto_advance_arc(pid, int(row["id"]), conn=conn, now=ts)
            if not res.get("advanced") and not res.get("completed"):
                break
            advanced += 1
            if res.get("completed"):
                break
            # refresh indices after advance
            fresh = conn.execute(
                "SELECT id, chapter_index, beat_index, status FROM player_story_arcs WHERE id = ?;",
                (int(row["id"]),),
            ).fetchone()
            if not fresh or str(fresh["status"]) != STATUS_ACTIVE:
                break
            row = dict(fresh)
        # also try starting newly unlocked side arcs after flag grants
    started += _start_eligible_arcs(pid, conn=conn, now=ts)
    return {"started": started, "advanced": advanced}


def _completion_flags_from_arc(arc_def: Mapping[str, Any]) -> List[str]:
    """Flags that reward beats should grant when an arc truly finishes."""
    out: List[str] = []
    for ch in arc_def.get("chapters") or []:
        for beat in (ch or {}).get("beats") or []:
            if str((beat or {}).get("type") or "") != "reward":
                continue
            for grant in (beat or {}).get("grants") or []:
                kind = str((grant or {}).get("kind") or "").strip().lower()
                if kind not in ("flag", "codex_flag"):
                    continue
                flag = str((grant or {}).get("flag") or "").strip()
                if flag and flag not in out:
                    out.append(flag)
    return out


def _repair_false_completions(player_id: int, *, conn, now: float) -> None:
    """
    Reopen arcs marked completed without their reward flags.
    Happens after pack migrations / out-of-range 'complete' repairs.
    """
    now_i = int(now)
    rows = conn.execute(
        """
        SELECT id, pack_id, arc_id, status
        FROM player_story_arcs
        WHERE player_id = ? AND status = ?;
        """,
        (int(player_id), STATUS_COMPLETED),
    ).fetchall()
    if not rows:
        return
    flags = get_player_flags(int(player_id), conn=conn)
    for row in rows:
        arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
        if not arc_def:
            continue
        expected = _completion_flags_from_arc(arc_def)
        if not expected:
            continue
        if all(f in flags for f in expected):
            continue
        first = resolve_beat(arc_def, chapter_index=0, beat_index=0) or {}
        target = 0
        if str(first.get("type")) == "objective":
            target = max(1, int(first.get("target") or 1))
        conn.execute(
            """
            UPDATE player_story_arcs
            SET status = ?, chapter_index = 0, beat_index = 0,
                progress_value = 0, target_value = ?,
                completed_at = NULL, updated_at = ?
            WHERE id = ?;
            """,
            (STATUS_ACTIVE, target, now_i, int(row["id"])),
        )
        logger.info(
            "story reopen incomplete arc player=%s pack=%s arc=%s missing=%s",
            player_id,
            row["pack_id"],
            row["arc_id"],
            [f for f in expected if f not in flags],
        )


def _repair_out_of_range_arcs(player_id: int, *, conn, now: float) -> None:
    """If pack chapters changed, clamp invalid active positions — never silent-complete."""
    now_i = int(now)
    for row in _active_arc_rows(player_id, conn=conn):
        arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
        if not arc_def:
            continue
        ci = int(row.get("chapter_index") or 0)
        bi = int(row.get("beat_index") or 0)
        beat = resolve_beat(arc_def, chapter_index=ci, beat_index=bi)
        if beat:
            continue
        chapters = list(arc_def.get("chapters") or [])
        if 0 <= ci < len(chapters) and list((chapters[ci] or {}).get("beats") or []):
            nbi = 0
            target = 0
            first = resolve_beat(arc_def, chapter_index=ci, beat_index=0) or {}
            if str(first.get("type")) == "objective":
                target = max(1, int(first.get("target") or 1))
            conn.execute(
                """
                UPDATE player_story_arcs
                SET beat_index = ?, progress_value = 0, target_value = ?, updated_at = ?
                WHERE id = ?;
                """,
                (nbi, target, now_i, int(row["id"])),
            )
            continue
        # Restart arc at first beat — do not mark completed (would skip rewards).
        if chapters and list((chapters[0] or {}).get("beats") or []):
            first = resolve_beat(arc_def, chapter_index=0, beat_index=0) or {}
            target = 0
            if str(first.get("type")) == "objective":
                target = max(1, int(first.get("target") or 1))
            conn.execute(
                """
                UPDATE player_story_arcs
                SET chapter_index = 0, beat_index = 0, progress_value = 0,
                    target_value = ?, updated_at = ?
                WHERE id = ?;
                """,
                (target, now_i, int(row["id"])),
            )



def _start_eligible_arcs(player_id: int, *, conn, now: float) -> int:
    flags = get_player_flags(player_id, conn=conn)
    existing = {
        (str(r["pack_id"]), str(r["arc_id"]))
        for r in conn.execute(
            "SELECT pack_id, arc_id FROM player_story_arcs WHERE player_id = ?;",
            (int(player_id),),
        ).fetchall()
    }
    started = 0
    now_i = int(now)
    for pack_id, pack in load_all_packs().items():
        for arc in pack.get("arcs") or []:
            arc_id = str(arc.get("arc_id") or "")
            key = (pack_id, arc_id)
            if key in existing:
                continue
            if not _start_when_met(arc.get("start_when") or {}, flags):
                continue
            first = resolve_beat(arc, chapter_index=0, beat_index=0)
            target = 0
            progress = 0
            if first and str(first.get("type")) == "objective":
                target = max(1, int(first.get("target") or 1))
            conn.execute(
                """
                INSERT INTO player_story_arcs (
                    player_id, pack_id, arc_id, status,
                    chapter_index, beat_index, progress_value, target_value,
                    started_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?);
                """,
                (
                    int(player_id),
                    pack_id,
                    arc_id,
                    STATUS_ACTIVE,
                    progress,
                    target,
                    now_i,
                    now_i,
                ),
            )
            existing.add(key)
            started += 1
    return started


def _start_when_met(start_when: Mapping[str, Any], flags: Mapping[str, str]) -> bool:
    if not start_when or start_when.get("always"):
        return True
    return flags_satisfy(
        flags,
        require_all=start_when.get("flags_all"),
        require_any=start_when.get("flags_any"),
    )


def _active_arc_rows(player_id: int, *, conn) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, pack_id, arc_id, chapter_index, beat_index, progress_value, target_value, status
        FROM player_story_arcs
        WHERE player_id = ? AND status = ?
        ORDER BY id ASC;
        """,
        (int(player_id), STATUS_ACTIVE),
    ).fetchall()
    return [dict(r) for r in rows]


def _load_arc_row(player_id: int, arc_row_id: int, *, conn) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, player_id, pack_id, arc_id, status, chapter_index, beat_index,
               progress_value, target_value
        FROM player_story_arcs
        WHERE id = ? AND player_id = ?;
        """,
        (int(arc_row_id), int(player_id)),
    ).fetchone()
    return dict(row) if row else None


def try_auto_advance_arc(
    player_id: int,
    arc_row_id: int,
    *,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """Auto-complete objective (if done), reward, and gate beats."""
    ts = float(now if now is not None else time.time())
    row = _load_arc_row(player_id, arc_row_id, conn=conn)
    if not row or str(row.get("status")) != STATUS_ACTIVE:
        return {"advanced": False}

    arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
    if not arc_def:
        return {"advanced": False}

    beat = resolve_beat(
        arc_def,
        chapter_index=int(row["chapter_index"] or 0),
        beat_index=int(row["beat_index"] or 0),
    )
    if not beat:
        return _complete_arc(player_id, arc_row_id, conn=conn, now=ts)

    btype = str(beat.get("type") or "")
    if btype == "objective":
        target = max(1, int(row.get("target_value") or beat.get("target") or 1))
        if int(row.get("progress_value") or 0) < target:
            return {"advanced": False}
        return _advance_to_next(player_id, row, arc_def, conn=conn, now=ts)

    if btype == "reward":
        apply_grants(player_id, list(beat.get("grants") or []), conn=conn, now=ts)
        return _advance_to_next(player_id, row, arc_def, conn=conn, now=ts)

    if btype == "gate":
        flags = get_player_flags(player_id, conn=conn)
        if not flags_satisfy(
            flags,
            require_all=beat.get("require_flags_all"),
            require_any=beat.get("require_flags_any"),
        ):
            return {"advanced": False}
        return _advance_to_next(player_id, row, arc_def, conn=conn, now=ts)

    # transmission / choice need player action
    return {"advanced": False}


def advance_active_beat(
    player_id: int,
    *,
    pack_id: str,
    arc_id: str,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """Player continues a transmission beat."""
    ts = float(now if now is not None else time.time())
    ensure_player_story(player_id, conn=conn, now=ts)
    row = _find_active_arc(player_id, pack_id, arc_id, conn=conn)
    if not row:
        return {"ok": False, "error": "arc_not_active"}

    arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
    if not arc_def:
        return {"ok": False, "error": "arc_missing"}

    beat = resolve_beat(
        arc_def,
        chapter_index=int(row["chapter_index"] or 0),
        beat_index=int(row["beat_index"] or 0),
    )
    if not beat or str(beat.get("type")) != "transmission":
        return {"ok": False, "error": "not_transmission"}

    res = _advance_to_next(player_id, row, arc_def, conn=conn, now=ts)
    ensure_player_story(player_id, conn=conn, now=ts)
    return {"ok": True, **res}


def apply_choice(
    player_id: int,
    *,
    pack_id: str,
    arc_id: str,
    choice_id: str,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else time.time())
    ensure_player_story(player_id, conn=conn, now=ts)
    row = _find_active_arc(player_id, pack_id, arc_id, conn=conn)
    if not row:
        return {"ok": False, "error": "arc_not_active"}

    arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
    if not arc_def:
        return {"ok": False, "error": "arc_missing"}

    beat = resolve_beat(
        arc_def,
        chapter_index=int(row["chapter_index"] or 0),
        beat_index=int(row["beat_index"] or 0),
    )
    if not beat or str(beat.get("type")) != "choice":
        return {"ok": False, "error": "not_choice"}

    cid = str(choice_id or "").strip()
    chosen = None
    for ch in beat.get("choices") or []:
        if str((ch or {}).get("id") or "") == cid:
            chosen = dict(ch)
            break
    if not chosen:
        return {"ok": False, "error": "invalid_choice"}

    set_flags(player_id, list(chosen.get("set_flags") or []), conn=conn, now=ts)
    if chosen.get("grants"):
        apply_grants(player_id, list(chosen.get("grants") or []), conn=conn, now=ts)

    res = _advance_to_next(player_id, row, arc_def, conn=conn, now=ts)
    ensure_player_story(player_id, conn=conn, now=ts)
    return {"ok": True, "choice_id": cid, **res}


def _find_active_arc(
    player_id: int,
    pack_id: str,
    arc_id: str,
    *,
    conn,
) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, player_id, pack_id, arc_id, status, chapter_index, beat_index,
               progress_value, target_value
        FROM player_story_arcs
        WHERE player_id = ? AND pack_id = ? AND arc_id = ? AND status = ?
        LIMIT 1;
        """,
        (int(player_id), str(pack_id), str(arc_id), STATUS_ACTIVE),
    ).fetchone()
    return dict(row) if row else None


def _advance_to_next(
    player_id: int,
    row: Mapping[str, Any],
    arc_def: Mapping[str, Any],
    *,
    conn,
    now: float,
) -> Dict[str, Any]:
    nxt = next_beat_position(
        arc_def,
        chapter_index=int(row["chapter_index"] or 0),
        beat_index=int(row["beat_index"] or 0),
    )
    now_i = int(now)
    if nxt is None:
        return _complete_arc(player_id, int(row["id"]), conn=conn, now=now)

    nci, nbi = nxt
    next_beat = resolve_beat(arc_def, chapter_index=nci, beat_index=nbi) or {}
    target = 0
    progress = 0
    if str(next_beat.get("type")) == "objective":
        target = max(1, int(next_beat.get("target") or 1))
    conn.execute(
        """
        UPDATE player_story_arcs
        SET chapter_index = ?, beat_index = ?, progress_value = ?, target_value = ?,
            updated_at = ?
        WHERE id = ? AND status = ?;
        """,
        (nci, nbi, progress, target, now_i, int(row["id"]), STATUS_ACTIVE),
    )
    # Immediately resolve reward/gate chains
    auto = try_auto_advance_arc(player_id, int(row["id"]), conn=conn, now=now)
    return {"advanced": True, "chapter_index": nci, "beat_index": nbi, **auto}


def _complete_arc(
    player_id: int,
    arc_row_id: int,
    *,
    conn,
    now: float,
) -> Dict[str, Any]:
    now_i = int(now)
    conn.execute(
        """
        UPDATE player_story_arcs
        SET status = ?, completed_at = COALESCE(completed_at, ?), updated_at = ?
        WHERE id = ? AND player_id = ?;
        """,
        (STATUS_COMPLETED, now_i, now_i, int(arc_row_id), int(player_id)),
    )
    _start_eligible_arcs(player_id, conn=conn, now=now)
    return {"advanced": True, "completed": True}
