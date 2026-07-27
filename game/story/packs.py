"""Story pack loader + validation (GC-2501 / GC-2505)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PACKS_DIR = Path(__file__).resolve().parent / "packs"

BEAT_TYPES = frozenset({"transmission", "objective", "choice", "reward", "gate"})
ARC_KINDS = frozenset({"main", "side"})
REWARD_KINDS = frozenset({"inventory", "flag", "codex_flag", "notify"})


class PackValidationError(ValueError):
    pass


def packs_dir() -> Path:
    return PACKS_DIR


def list_pack_files() -> List[Path]:
    if not PACKS_DIR.is_dir():
        return []
    return sorted(PACKS_DIR.glob("*.json"))


def clear_pack_cache() -> None:
    load_all_packs.cache_clear()
    _load_pack_file.cache_clear()


@lru_cache(maxsize=32)
def _load_pack_file(path_str: str) -> Dict[str, Any]:
    path = Path(path_str)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PackValidationError(f"{path.name}: root must be object")
    validate_pack(raw, source=path.name)
    return raw


@lru_cache(maxsize=1)
def load_all_packs() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in list_pack_files():
        pack = _load_pack_file(str(path))
        pid = str(pack["pack_id"])
        if pid in out:
            raise PackValidationError(f"duplicate pack_id: {pid}")
        out[pid] = pack
    return out


def get_pack(pack_id: str) -> Optional[Dict[str, Any]]:
    return load_all_packs().get(str(pack_id or ""))


def get_arc(pack_id: str, arc_id: str) -> Optional[Dict[str, Any]]:
    pack = get_pack(pack_id)
    if not pack:
        return None
    for arc in pack.get("arcs") or []:
        if str(arc.get("arc_id") or "") == str(arc_id):
            return dict(arc)
    return None


def iter_beats(arc: Mapping[str, Any]) -> List[Tuple[int, int, Dict[str, Any]]]:
    """Return (chapter_index, beat_index, beat) in order."""
    out: List[Tuple[int, int, Dict[str, Any]]] = []
    chapters = list(arc.get("chapters") or [])
    for ci, chapter in enumerate(chapters):
        beats = list((chapter or {}).get("beats") or [])
        for bi, beat in enumerate(beats):
            out.append((ci, bi, dict(beat or {})))
    return out


def resolve_beat(
    arc: Mapping[str, Any],
    *,
    chapter_index: int,
    beat_index: int,
) -> Optional[Dict[str, Any]]:
    chapters = list(arc.get("chapters") or [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        return None
    beats = list((chapters[chapter_index] or {}).get("beats") or [])
    if beat_index < 0 or beat_index >= len(beats):
        return None
    return dict(beats[beat_index] or {})


def next_beat_position(
    arc: Mapping[str, Any],
    *,
    chapter_index: int,
    beat_index: int,
) -> Optional[Tuple[int, int]]:
    chapters = list(arc.get("chapters") or [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        return None
    beats = list((chapters[chapter_index] or {}).get("beats") or [])
    nxt = beat_index + 1
    if nxt < len(beats):
        return chapter_index, nxt
    nci = chapter_index + 1
    while nci < len(chapters):
        nbeats = list((chapters[nci] or {}).get("beats") or [])
        if nbeats:
            return nci, 0
        nci += 1
    return None


def validate_pack(pack: Mapping[str, Any], *, source: str = "pack") -> None:
    pack_id = str(pack.get("pack_id") or "").strip()
    if not pack_id:
        raise PackValidationError(f"{source}: missing pack_id")
    if int(pack.get("version") or 0) < 1:
        raise PackValidationError(f"{source}: version must be >= 1")
    arcs = pack.get("arcs")
    if not isinstance(arcs, list) or not arcs:
        raise PackValidationError(f"{source}: arcs must be non-empty list")
    seen_arcs: set[str] = set()
    for arc in arcs:
        _validate_arc(arc, source=source, seen_arcs=seen_arcs)


def _validate_arc(arc: Any, *, source: str, seen_arcs: set[str]) -> None:
    if not isinstance(arc, dict):
        raise PackValidationError(f"{source}: arc must be object")
    arc_id = str(arc.get("arc_id") or "").strip()
    if not arc_id:
        raise PackValidationError(f"{source}: missing arc_id")
    if arc_id in seen_arcs:
        raise PackValidationError(f"{source}: duplicate arc_id {arc_id}")
    seen_arcs.add(arc_id)
    kind = str(arc.get("kind") or "side").strip().lower()
    if kind not in ARC_KINDS:
        raise PackValidationError(f"{source}/{arc_id}: invalid kind {kind}")
    chapters = arc.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise PackValidationError(f"{source}/{arc_id}: chapters required")
    seen_beats: set[str] = set()
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise PackValidationError(f"{source}/{arc_id}: chapter must be object")
        beats = chapter.get("beats")
        if not isinstance(beats, list) or not beats:
            raise PackValidationError(f"{source}/{arc_id}: beats required")
        for beat in beats:
            _validate_beat(beat, source=f"{source}/{arc_id}", seen_beats=seen_beats)


def _validate_beat(beat: Any, *, source: str, seen_beats: set[str]) -> None:
    if not isinstance(beat, dict):
        raise PackValidationError(f"{source}: beat must be object")
    beat_id = str(beat.get("beat_id") or "").strip()
    if not beat_id:
        raise PackValidationError(f"{source}: missing beat_id")
    if beat_id in seen_beats:
        raise PackValidationError(f"{source}: duplicate beat_id {beat_id}")
    seen_beats.add(beat_id)
    btype = str(beat.get("type") or "").strip().lower()
    if btype not in BEAT_TYPES:
        raise PackValidationError(f"{source}/{beat_id}: invalid type {btype}")
    if btype == "objective":
        if not str(beat.get("objective_key") or "").strip():
            raise PackValidationError(f"{source}/{beat_id}: objective_key required")
        if int(beat.get("target") or 0) < 1:
            raise PackValidationError(f"{source}/{beat_id}: target must be >= 1")
    if btype == "choice":
        choices = beat.get("choices")
        if not isinstance(choices, list) or len(choices) < 2:
            raise PackValidationError(f"{source}/{beat_id}: choice needs >= 2 choices")
        seen_c: set[str] = set()
        for ch in choices:
            if not isinstance(ch, dict):
                raise PackValidationError(f"{source}/{beat_id}: choice entry must be object")
            cid = str(ch.get("id") or "").strip()
            if not cid or cid in seen_c:
                raise PackValidationError(f"{source}/{beat_id}: invalid/duplicate choice id")
            seen_c.add(cid)
    if btype == "reward":
        grants = beat.get("grants")
        if not isinstance(grants, list) or not grants:
            raise PackValidationError(f"{source}/{beat_id}: reward grants required")
        for g in grants:
            if not isinstance(g, dict):
                raise PackValidationError(f"{source}/{beat_id}: grant must be object")
            kind = str(g.get("kind") or "").strip().lower()
            if kind not in REWARD_KINDS:
                raise PackValidationError(f"{source}/{beat_id}: invalid grant kind {kind}")
    if btype == "gate":
        all_f = beat.get("require_flags_all") or []
        any_f = beat.get("require_flags_any") or []
        if not all_f and not any_f:
            raise PackValidationError(f"{source}/{beat_id}: gate needs flags")


def validate_all_packs() -> List[str]:
    """Return pack_ids; raises PackValidationError on first failure."""
    clear_pack_cache()
    packs = load_all_packs()
    return sorted(packs.keys())
