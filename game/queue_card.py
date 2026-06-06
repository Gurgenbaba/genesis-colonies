"""
GC-536A — Queue Card presentation adapter.

Maps existing queue payloads into a canonical card-job shape for future Card UX.
Does not mutate DB, schedule jobs, or replace queue_engine / *_for_client owners.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

OWNER_BUILDING = "building"
OWNER_RESEARCH = "research"
OWNER_SHIPYARD = "shipyard"
OWNER_DEFENSE = "defense"
OWNER_PLANET_RESEARCH = "planet_research"
OWNER_ASCENSION = "ascension"

STATUS_ACTIVE = "active"
STATUS_QUEUED = "queued"


def _safe_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed:  # NaN
        return 0.0
    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def compute_progress_pct(
    *,
    status: str,
    remaining_seconds: int,
    duration_seconds: int,
) -> int:
    """Server-side progress for card display. Queued / invalid → 0."""
    if status != STATUS_ACTIVE:
        return 0
    duration = max(1, int(duration_seconds))
    remaining = max(0, int(remaining_seconds))
    elapsed = max(0, duration - remaining)
    pct = int(round(100.0 * elapsed / duration))
    return max(0, min(100, pct))


def normalize_card_queue_job(
    *,
    owner_type: str,
    owner_key: str,
    job_id: int,
    queue_position: int,
    start_at: Any,
    finish_at: Any,
    now: Optional[float] = None,
    label: str = "",
    target_level: Optional[int] = None,
    target_amount: Optional[int] = None,
    remaining_seconds: Optional[int] = None,
    duration_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build one canonical card-queue job dict from domain fields.
    Never raises on bad/missing timer input.
    """
    ts = float(now if now is not None else time.time())
    position = max(1, _safe_int(queue_position, 1))
    status = STATUS_ACTIVE if position == 1 else STATUS_QUEUED

    finish = _safe_float(finish_at)
    start = _safe_float(start_at)

    if duration_seconds is not None and int(duration_seconds) > 0:
        duration = max(1, int(duration_seconds))
    elif finish > 0 and start > 0 and finish >= start:
        duration = max(1, int(finish - start))
    else:
        duration = 1

    if remaining_seconds is not None:
        remaining = max(0, int(remaining_seconds))
    elif finish > 0:
        remaining = max(0, int(finish - ts))
    else:
        remaining = 0

    if start <= 0 and finish > 0:
        start = max(0.0, finish - duration)

    if finish <= 0:
        progress_pct = 0
    else:
        progress_pct = compute_progress_pct(
            status=status,
            remaining_seconds=remaining,
            duration_seconds=duration,
        )

    job: Dict[str, Any] = {
        "owner_type": str(owner_type),
        "owner_key": str(owner_key),
        "job_id": int(job_id),
        "status": status,
        "queue_position": position,
        "start_at": start if start > 0 else 0.0,
        "finish_at": finish if finish > 0 else 0.0,
        "duration_seconds": duration,
        "remaining_seconds": remaining,
        "progress_pct": progress_pct,
        "label": str(label or owner_key),
    }
    if target_level is not None:
        job["target_level"] = int(target_level)
    if target_amount is not None:
        job["target_amount"] = int(target_amount)
    return job


def group_card_jobs_by_owner_key(
    jobs: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group normalized card jobs by owner_key (stable order per key)."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for job in jobs:
        key = str(job.get("owner_key") or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(dict(job))
    return grouped


def card_queue_job_for_item(
    jobs_by_key: Mapping[str, Sequence[Mapping[str, Any]]],
    owner_key: str,
) -> Optional[Dict[str, Any]]:
    """First card job for an item (active or next queued slot)."""
    rows = jobs_by_key.get(str(owner_key))
    if not rows:
        return None
    return dict(rows[0])


def map_build_queue_to_card_jobs(
    build_queue: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt get_build_queue_status_for_planet payload → card jobs."""
    if not build_queue or not isinstance(build_queue, Mapping):
        return []
    raw_jobs = build_queue.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("building_type") or "")
        if not owner_key:
            continue
        finish = _safe_float(raw.get("finish_time") or raw.get("finish_at"))
        total = max(1, _safe_int(raw.get("total") or raw.get("total_seconds"), 1))
        start = finish - total if finish > 0 else 0.0
        label_key = str(raw.get("label_key") or f"building_{owner_key}")
        job = normalize_card_queue_job(
            owner_type=OWNER_BUILDING,
            owner_key=owner_key,
            job_id=_safe_int(raw.get("id"), 0),
            queue_position=idx + 1,
            start_at=start,
            finish_at=finish,
            now=ts,
            label=label_key,
            target_level=_safe_int(raw.get("target_level"), 0) or None,
            remaining_seconds=_safe_int(raw.get("remaining")),
            duration_seconds=total,
        )
        _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        out.append(job)
    return out


def _apply_queued_wait_remaining(job: Dict[str, Any], *, finish_at: Any, now: float) -> None:
    """Kanonische Queue-Regel: wartende Jobs zeigen finish_at − now (Vorgänger + eigene Dauer)."""
    if job.get("status") != STATUS_QUEUED:
        return
    finish_f = _safe_float(finish_at)
    if finish_f > now:
        job["remaining_seconds"] = max(0, int(finish_f - now))
    job["progress_pct"] = 0


def map_research_queue_to_card_jobs(
    research: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt research status payload (queue list) → card jobs."""
    if not research or not isinstance(research, Mapping):
        return []
    raw_jobs = research.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("tech_key") or raw.get("key") or "")
        if not owner_key:
            continue
        label = str(raw.get("label") or raw.get("label_key") or owner_key)
        position = _safe_int(raw.get("position"), idx + 1)
        start = _safe_float(raw.get("start_at"))
        job = normalize_card_queue_job(
                owner_type=OWNER_RESEARCH,
                owner_key=owner_key,
                job_id=_safe_int(raw.get("id"), 0),
                queue_position=position if position > 0 else idx + 1,
                start_at=start,
                finish_at=raw.get("finish_at") or raw.get("finish_time"),
                now=ts,
                label=label,
                target_level=_safe_int(raw.get("target_level"), 0) or None,
                remaining_seconds=_safe_int(raw.get("remaining") or raw.get("remaining_seconds")),
                duration_seconds=_safe_int(raw.get("total_seconds") or raw.get("total"), 0) or None,
            )
        _apply_queued_wait_remaining(job, finish_at=raw.get("finish_at") or raw.get("finish_time"), now=ts)
        if "current_level" in raw:
            job["current_level"] = _safe_int(raw.get("current_level"))
        elif job.get("target_level") is not None:
            job["current_level"] = max(0, int(job["target_level"]) - 1)
        out.append(job)
    return out


def map_defense_queue_to_card_jobs(
    defense_queue: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt defense_queue_for_client payload → card jobs."""
    if not defense_queue or not isinstance(defense_queue, Mapping):
        return []
    raw_jobs = defense_queue.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("defense_key") or "")
        if not owner_key:
            continue
        label = str(raw.get("label") or raw.get("label_key") or owner_key)
        amount = _safe_int(raw.get("amount_total") or raw.get("amount"), 0) or None
        finish = _safe_float(raw.get("finish_at") or raw.get("finish_time"))
        order_total = _safe_int(
            raw.get("order_total_seconds") or raw.get("total_seconds") or raw.get("total"),
            0,
        )
        start = _safe_float(raw.get("started_at") or raw.get("start_at"))
        if start <= 0 and finish > 0 and order_total > 0:
            start = finish - order_total
        job = normalize_card_queue_job(
            owner_type=OWNER_DEFENSE,
            owner_key=owner_key,
            job_id=_safe_int(raw.get("id"), 0),
            queue_position=idx + 1,
            start_at=start,
            finish_at=finish,
            now=ts,
            label=label,
            target_amount=amount,
            remaining_seconds=_safe_int(
                raw.get("order_remaining") or raw.get("remaining") or raw.get("remaining_seconds")
            ),
            duration_seconds=order_total or None,
        )
        job["defense_label_key"] = f"defense_{owner_key}"
        if amount is not None:
            job["target_amount"] = int(amount)
        if "units_delivered" in raw:
            job["units_delivered"] = _safe_int(raw.get("units_delivered"))
        if "amount_remaining" in raw:
            job["amount_remaining"] = _safe_int(raw.get("amount_remaining"))
        _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        out.append(job)
    return out


def map_shipyard_queue_to_card_jobs(
    shipyard_queue: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt shipyard_queue_for_client payload → card jobs."""
    if not shipyard_queue or not isinstance(shipyard_queue, Mapping):
        return []
    raw_jobs = shipyard_queue.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("ship_key") or raw.get("ship_type") or "")
        if not owner_key:
            continue
        label = str(raw.get("label") or raw.get("label_key") or owner_key)
        amount = _safe_int(raw.get("amount_total") or raw.get("amount"), 0) or None
        finish = _safe_float(raw.get("finish_at") or raw.get("finish_time"))
        order_total = _safe_int(
            raw.get("order_total_seconds") or raw.get("total_seconds") or raw.get("total"),
            0,
        )
        start = _safe_float(raw.get("started_at") or raw.get("start_at"))
        if start <= 0 and finish > 0 and order_total > 0:
            start = finish - order_total
        job = normalize_card_queue_job(
                owner_type=OWNER_SHIPYARD,
                owner_key=owner_key,
                job_id=_safe_int(raw.get("id"), 0),
                queue_position=idx + 1,
                start_at=start,
                finish_at=finish,
                now=ts,
                label=label,
                target_amount=amount,
                remaining_seconds=_safe_int(
                    raw.get("order_remaining") or raw.get("remaining") or raw.get("remaining_seconds")
                ),
                duration_seconds=order_total or None,
            )
        job["ship_label_key"] = f"fleet_ship_{owner_key}"
        if amount is not None:
            job["target_amount"] = int(amount)
        if "units_delivered" in raw:
            job["units_delivered"] = _safe_int(raw.get("units_delivered"))
        if "amount_remaining" in raw:
            job["amount_remaining"] = _safe_int(raw.get("amount_remaining"))
        _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        out.append(job)
    return out


def map_planet_research_queue_to_card_jobs(
    research_status: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt get_planet_research_status payload → planet-tech card jobs."""
    if not research_status or not isinstance(research_status, Mapping):
        return []
    raw_jobs = research_status.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("tech_key") or raw.get("key") or "")
        if not owner_key:
            continue
        try:
            from .planet_evolution.definitions import get_research_def

            cfg = get_research_def(owner_key) or {}
        except Exception:
            cfg = {}
        label_key = str(raw.get("label_key") or cfg.get("label_key") or owner_key)
        target_level = _safe_int(raw.get("target_level"), 0) or None
        start = _safe_float(raw.get("start_at"))
        finish = _safe_float(raw.get("finish_at") or raw.get("finish_time"))
        duration = None
        if finish > start > 0:
            duration = max(1, int(finish - start))
        job = normalize_card_queue_job(
            owner_type=OWNER_PLANET_RESEARCH,
            owner_key=owner_key,
            job_id=_safe_int(raw.get("id"), 0),
            queue_position=idx + 1,
            start_at=start,
            finish_at=finish,
            now=ts,
            label=label_key,
            target_level=target_level,
            remaining_seconds=_safe_int(raw.get("remaining") or raw.get("remaining_seconds")),
            duration_seconds=duration,
        )
        job["label_key"] = label_key
        _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        if target_level is not None:
            job["current_level"] = max(0, int(target_level) - 1)
        out.append(job)
    return out


def map_ascension_queue_to_card_jobs(
    ascension_status: Optional[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Adapt ascension status payload → ascension card jobs."""
    if not ascension_status or not isinstance(ascension_status, Mapping):
        return []
    raw_jobs = ascension_status.get("queue")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        return []

    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_jobs):
        if not isinstance(raw, Mapping):
            continue
        owner_key = str(raw.get("ascension_key") or raw.get("key") or "")
        if not owner_key:
            continue
        label = str(raw.get("label_key") or raw.get("label") or owner_key)
        start = _safe_float(raw.get("start_at"))
        finish = _safe_float(raw.get("finish_at"))
        duration = None
        if finish > 0 and start > 0 and finish >= start:
            duration = max(1, int(finish - start))
        job = normalize_card_queue_job(
            owner_type=OWNER_ASCENSION,
            owner_key=owner_key,
            job_id=_safe_int(raw.get("id"), idx + 1),
            queue_position=idx + 1,
            start_at=start,
            finish_at=finish,
            now=ts,
            label=label,
            remaining_seconds=_safe_int(raw.get("remaining") or raw.get("remaining_seconds")),
            duration_seconds=duration,
        )
        job["label_key"] = label
        phase = _safe_int(raw.get("quest_stage"), -1)
        if phase >= 0:
            job["target_phase"] = int(phase) + 1
        _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        out.append(job)
    return out


def attach_card_jobs_by_owner(
    payload: MutableMapping[str, Any],
    card_jobs: Sequence[Mapping[str, Any]],
    *,
    field_name: str = "card_jobs_by_owner",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Optional helper for future game-state enrichment (536B+).
    Does not remove legacy queue fields.
    """
    grouped = group_card_jobs_by_owner_key(card_jobs)
    payload[field_name] = grouped
    return grouped
