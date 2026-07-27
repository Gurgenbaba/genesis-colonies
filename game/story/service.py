"""Story Ops client state (UI / game-state summary)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..db import table_exists
from ..i18n import tr
from .engine import ensure_player_story
from .flags import get_player_flags
from .packs import get_arc, get_pack, load_all_packs, resolve_beat

ARCS_TABLE = "player_story_arcs"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"


def story_schema_ready(conn) -> bool:
    return table_exists(conn, ARCS_TABLE)


def _t(key: str, fallback: str) -> str:
    """Translate; never leak raw missing keys into UI."""
    k = str(key or "").strip()
    fb = str(fallback or "").strip() or "—"
    if not k:
        return fb
    val = tr(k, fb)
    if not val or val == k:
        return fb
    return str(val)


def count_story_attention(player_id: int, *, conn) -> int:
    if not story_schema_ready(conn):
        return 0
    state = get_story_summary(int(player_id), conn=conn)
    return int(state.get("attention_count") or 0)


def get_story_summary(player_id: int, *, conn, now: float | None = None) -> Dict[str, Any]:
    if not story_schema_ready(conn):
        return {"ready": False, "active_arcs": 0, "attention_count": 0}
    ts = float(now if now is not None else time.time())
    ensure_player_story(int(player_id), conn=conn, now=ts)
    full = get_story_state(int(player_id), conn=conn, now=ts, ensure=False)
    attention = 0
    for arc in full.get("arcs") or []:
        if arc.get("status") != STATUS_ACTIVE:
            continue
        beat = arc.get("beat") or {}
        if beat.get("type") in ("transmission", "choice"):
            attention += 1
    return {
        "ready": True,
        "active_arcs": sum(1 for a in (full.get("arcs") or []) if a.get("status") == STATUS_ACTIVE),
        "attention_count": attention,
        "focus": full.get("focus"),
    }


def get_story_state(
    player_id: int,
    *,
    conn,
    now: float | None = None,
    ensure: bool = True,
    focus_pack_id: str | None = None,
    focus_arc_id: str | None = None,
) -> Dict[str, Any]:
    if not story_schema_ready(conn):
        return {
            "ready": False,
            "arcs": [],
            "flags": {},
            "focus": None,
            "lore_fragments": [],
            "tts": {"neural": False},
        }

    ts = float(now if now is not None else time.time())
    if ensure:
        from ..db import begin_write_transaction, commit, in_transaction, rollback

        already = in_transaction(conn)
        if not already:
            begin_write_transaction(conn)
        try:
            ensure_player_story(int(player_id), conn=conn, now=ts)
            if not already:
                commit(conn)
        except Exception:
            if not already:
                rollback(conn)
            raise

    from .tts import tts_available

    flags = get_player_flags(int(player_id), conn=conn)
    rows = conn.execute(
        """
        SELECT id, pack_id, arc_id, status, chapter_index, beat_index,
               progress_value, target_value, started_at, completed_at
        FROM player_story_arcs
        WHERE player_id = ?
        ORDER BY
          CASE status WHEN 'active' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END,
          id ASC;
        """,
        (int(player_id),),
    ).fetchall()

    arcs_out: List[Dict[str, Any]] = []
    focus: Optional[Dict[str, Any]] = None
    want_pack = str(focus_pack_id or "").strip()
    want_arc = str(focus_arc_id or "").strip()

    for row in rows:
        arc_payload = _serialize_arc(dict(row))
        arcs_out.append(arc_payload)

    # Prefer explicitly requested active arc, else first actionable active arc.
    for arc_payload in arcs_out:
        if arc_payload.get("status") != STATUS_ACTIVE:
            continue
        beat = arc_payload.get("beat") or {}
        if beat.get("type") not in ("transmission", "choice", "objective"):
            continue
        if want_pack and want_arc:
            if arc_payload.get("pack_id") == want_pack and arc_payload.get("arc_id") == want_arc:
                focus = arc_payload
                break
        if focus is None:
            focus = arc_payload

    if focus is None:
        for arc_payload in arcs_out:
            if arc_payload.get("status") == STATUS_ACTIVE:
                focus = arc_payload
                break

    idle = None
    if focus is None:
        completed = [a for a in arcs_out if a.get("status") == STATUS_COMPLETED]
        if completed:
            idle = {
                "title": _t("story_idle_completed_title", "Saga pausiert"),
                "body": _t(
                    "story_idle_completed_body",
                    "Hauptübertragung abgeschlossen. Side Ops öffnen sich, sobald die Belohnungsflags gesetzt sind — sonst starte die Seite neu.",
                ),
            }
        else:
            idle = {
                "title": _t("story_idle_title", "Kanal ruhig"),
                "body": _t(
                    "story_idle_body",
                    "Keine aktive Übertragung. Side Ops öffnen sich, wenn dein Imperium wächst.",
                ),
            }

    from .free_shop import get_free_shop_state

    free_shop = get_free_shop_state(int(player_id), conn=conn)

    return {
        "ready": True,
        "arcs": arcs_out,
        "flags": flags,
        "focus": focus,
        "idle": idle,
        "lore_fragments": _lore_fragments(flags),
        "free_shop": free_shop,
        "tts": {"neural": bool(tts_available()), "provider": "edge-tts" if tts_available() else "none"},
        "packs": [
            {
                "pack_id": pid,
                "version": int(p.get("version") or 1),
                "arc_count": len(p.get("arcs") or []),
            }
            for pid, p in load_all_packs().items()
        ],
    }


def _status_label(status: str) -> str:
    st = str(status or "").strip().lower()
    if st == STATUS_ACTIVE:
        return _t("story_status_active", "Aktiv")
    if st == STATUS_COMPLETED:
        return _t("story_status_completed", "Abgeschlossen")
    return _t("story_status_unknown", "Unbekannt")


def _kind_label(kind: str) -> str:
    k = str(kind or "side").strip().lower()
    if k == "main":
        return _t("story_kind_main", "Hauptgeschichte")
    return _t("story_kind_side", "Nebenhandlung")


_CHAPTER_STATUS_FB = {
    "done": "Abgeschlossen",
    "current": "Aktuell",
    "locked": "Gesperrt",
}

_BEAT_TYPE_FB = {
    "transmission": "Übertragung",
    "objective": "Ziel",
    "choice": "Entscheidung",
    "reward": "Belohnung",
    "gate": "Tor",
}


def _serialize_arc(row: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = str(row["pack_id"])
    arc_id = str(row["arc_id"])
    arc_def = get_arc(pack_id, arc_id) or {}
    chapters_def = list(arc_def.get("chapters") or [])
    ci = int(row.get("chapter_index") or 0)
    bi = int(row.get("beat_index") or 0)
    status = str(row.get("status") or "")

    beat = None
    if status == STATUS_ACTIVE:
        raw = resolve_beat(arc_def, chapter_index=ci, beat_index=bi)
        if raw:
            beat = _serialize_beat(raw, row)

    chapters_out: List[Dict[str, Any]] = []
    for idx, ch in enumerate(chapters_def):
        beats = list((ch or {}).get("beats") or [])
        title_key = str((ch or {}).get("title_key") or "")
        chapter_id = str((ch or {}).get("chapter_id") or f"ch{idx+1}")
        if status == STATUS_COMPLETED or idx < ci:
            ch_status = "done"
        elif status == STATUS_ACTIVE and idx == ci:
            ch_status = "current"
        else:
            ch_status = "locked"
        chapters_out.append(
            {
                "chapter_id": chapter_id,
                "index": idx,
                "title": _t(title_key, chapter_id.replace("_", " ").title()),
                "status": ch_status,
                "status_label": _t(
                    f"story_chapter_status_{ch_status}",
                    _CHAPTER_STATUS_FB.get(ch_status, "—"),
                ),
                "beat_count": len(beats),
                "beat_index": bi if idx == ci and status == STATUS_ACTIVE else (
                    len(beats) if ch_status == "done" else 0
                ),
            }
        )

    title_key = str(arc_def.get("title_key") or "")
    title = _t(title_key, arc_id.replace("_", " ").title())
    pack = get_pack(pack_id) or {}
    season_code = str(pack.get("season_code") or "").strip()
    season_key = str(pack.get("season_key") or "").strip()
    season_label = _t(season_key, season_code) if season_key or season_code else ""

    return {
        "id": int(row["id"]),
        "pack_id": pack_id,
        "arc_id": arc_id,
        "kind": str(arc_def.get("kind") or "side"),
        "kind_label": _kind_label(str(arc_def.get("kind") or "side")),
        "contact_key": str(arc_def.get("contact_key") or "ark"),
        "title_key": title_key,
        "title": title,
        "season_code": season_code,
        "season_key": season_key,
        "season_label": season_label,
        "status": status,
        "status_label": _status_label(status),
        "chapter_index": ci,
        "beat_index": bi,
        "chapter_title": (
            chapters_out[ci]["title"] if 0 <= ci < len(chapters_out) else ""
        ),
        "chapters": chapters_out,
        "progress": int(row.get("progress_value") or 0),
        "target": int(row.get("target_value") or 0),
        "beat": beat,
        "started_at": int(row.get("started_at") or 0),
        "completed_at": int(row["completed_at"]) if row.get("completed_at") is not None else None,
    }


def _serialize_beat(beat: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    btype = str(beat.get("type") or "")
    title_key = str(beat.get("title_key") or "")
    body_key = str(beat.get("body_key") or "")
    cta_key = str(beat.get("cta_key") or "story_cta_continue")
    out: Dict[str, Any] = {
        "beat_id": str(beat.get("beat_id") or ""),
        "type": btype,
        "type_label": _t(f"story_beat_type_{btype}", _BEAT_TYPE_FB.get(btype, "—")),
        "title_key": title_key,
        "body_key": body_key,
        "title": _t(title_key, str(beat.get("beat_id") or "Übertragung")),
        "body": _t(body_key, ""),
        "cta_key": cta_key,
        "cta": _t(cta_key, "Weiter"),
    }
    if btype == "objective":
        out["objective_key"] = str(beat.get("objective_key") or "")
        out["progress"] = int(row.get("progress_value") or 0)
        out["target"] = max(1, int(row.get("target_value") or beat.get("target") or 1))
        out["objective_hint"] = _t(
            "story_waiting_gameplay",
            "Erfülle das Ziel durch normales Spielen — der Fortschritt aktualisiert sich automatisch.",
        )
    if btype == "choice":
        choices = []
        for ch in beat.get("choices") or []:
            lid = str(ch.get("id") or "")
            lkey = str(ch.get("label_key") or "")
            choices.append(
                {
                    "id": lid,
                    "label_key": lkey,
                    "label": _t(lkey, lid.replace("_", " ").title()),
                }
            )
        out["choices"] = choices
    return out


def _lore_fragments(flags: Dict[str, str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for key in sorted(flags.keys()):
        if not key.startswith("codex_"):
            continue
        out.append(
            {
                "flag": key,
                "title": _t(f"story_codex_{key}_title", key.replace("codex_", "").replace("_", " ").title()),
                "body": _t(f"story_codex_{key}_body", ""),
            }
        )
    return out


def admin_preview_packs() -> Dict[str, Any]:
    packs = []
    for pack_id, pack in load_all_packs().items():
        arcs = []
        for arc in pack.get("arcs") or []:
            chapters = []
            for ch in arc.get("chapters") or []:
                chapters.append(
                    {
                        "chapter_id": ch.get("chapter_id"),
                        "title_key": ch.get("title_key"),
                        "beat_count": len(ch.get("beats") or []),
                    }
                )
            arcs.append(
                {
                    "arc_id": arc.get("arc_id"),
                    "kind": arc.get("kind"),
                    "contact_key": arc.get("contact_key"),
                    "title_key": arc.get("title_key"),
                    "chapters": chapters,
                    "beat_count": sum(len(ch.get("beats") or []) for ch in (arc.get("chapters") or [])),
                    "start_when": arc.get("start_when") or {"always": True},
                }
            )
        packs.append(
            {
                "pack_id": pack_id,
                "version": pack.get("version"),
                "season_code": pack.get("season_code"),
                "season_key": pack.get("season_key"),
                "arcs": arcs,
            }
        )
    return {"ready": True, "packs": packs}
