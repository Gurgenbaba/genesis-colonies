"""
Ranking / Score Helper für Genesis Colonies.

Ziel:
- Score aus player_scores liefern
- bei fehlendem Score automatisch berechnen (recompute_and_upsert_score)
- optionales Mini-Cache (in-memory) für schnelle Header-Reads

Hinweis:
- Cache ist rein In-Memory (pro Prozess). Bei mehreren Gunicorn-Workern
  ist das normal: jeder Worker hat seinen eigenen Mini-Cache.
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

from .models import (
    get_player_score_row,
    recompute_and_upsert_score,
)

# player_id -> (timestamp, data)
_CACHE: Dict[int, Tuple[float, Dict[str, int]]] = {}
CACHE_TTL_SECONDS: float = 2.0


def invalidate_player_score_cache(player_id: int) -> None:
    """Cache-Eintrag löschen (z.B. nach Queue-Finish / Admin-Wipe / Start-Aktionen)."""
    try:
        _CACHE.pop(int(player_id), None)
    except Exception:
        pass


def invalidate_all_score_cache() -> None:
    """Optional: kompletter Cache-Flush (z.B. nach Universe-Wipe)."""
    try:
        _CACHE.clear()
    except Exception:
        pass


def _zero() -> Dict[str, int]:
    return {"total": 0, "buildings": 0, "research": 0}


def _normalize_row(row: Optional[dict]) -> Dict[str, int]:
    """
    Normalisiert DB-Row (player_scores.*) auf UI-Format.
    Erwartete DB-Keys: score_total, score_buildings, score_research
    """
    if not row:
        return _zero()

    return {
        "total": int(row.get("score_total", 0) or 0),
        "buildings": int(row.get("score_buildings", 0) or 0),
        "research": int(row.get("score_research", 0) or 0),
    }


def _normalize_recompute_payload(data: Optional[dict]) -> Dict[str, int]:
    """
    Normalisiert Payload aus recompute_and_upsert_score auf UI-Format.
    Erwartete Keys: score_total, score_buildings, score_research
    """
    if not data:
        return _zero()

    return {
        "total": int(data.get("score_total", 0) or 0),
        "buildings": int(data.get("score_buildings", 0) or 0),
        "research": int(data.get("score_research", 0) or 0),
    }


def get_player_score_cached(player_id: int, force_recompute: bool = False) -> Dict[str, int]:
    """
    Liefert Score-Dict:
      { total, buildings, research }

    Regeln:
    - Wenn Score noch nicht existiert -> berechnet + upsert (einmalig)
    - force_recompute nur für Admin/Debug oder wenn du "jetzt sofort" fresh willst
    - Score kommt aus DB / recompute (kein Tick-Score)
    """
    if not player_id:
        return _zero()

    pid = int(player_id)
    now = time.time()

    # Force-Recompute: garantiert frisch
    if force_recompute:
        invalidate_player_score_cache(pid)
        try:
            data = recompute_and_upsert_score(pid)
            out = _normalize_recompute_payload(data)
        except Exception:
            out = _zero()

        _CACHE[pid] = (now, out)
        return out

    # Normal: Cache nutzen (TTL)
    cached = _CACHE.get(pid)
    if cached:
        ts, data = cached
        if (now - ts) <= CACHE_TTL_SECONDS:
            return data

    # Normal: DB lesen
    try:
        row = get_player_score_row(pid)
    except Exception:
        row = None

    # Neuer Spieler / keine Row -> einmalig berechnen + upsert
    if not row:
        try:
            data = recompute_and_upsert_score(pid)
            out = _normalize_recompute_payload(data)
        except Exception:
            out = _zero()

        _CACHE[pid] = (now, out)
        return out

    out = _normalize_row(row)
    _CACHE[pid] = (now, out)
    return out
