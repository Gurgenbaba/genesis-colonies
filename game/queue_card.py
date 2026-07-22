"""
GC-536A — Queue Card presentation adapter.

Maps existing queue payloads into a canonical card-job shape for future Card UX.
Does not mutate DB, schedule jobs, or replace queue_engine / *_for_client owners.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

OWNER_BUILDING = "building"
OWNER_RESEARCH = "research"
OWNER_SHIPYARD = "shipyard"
OWNER_DEFENSE = "defense"
OWNER_PLANET_RESEARCH = "planet_research"
OWNER_ASCENSION = "ascension"

STATUS_ACTIVE = "active"
STATUS_QUEUED = "queued"


def is_queue_job_client_visible(
    job: Mapping[str, Any],
    *,
    now: Optional[float] = None,
) -> bool:
    """
    GC-833: Forbidden client state — active job at 100 % / 0 s remaining.
    Due jobs must be finished server-side; never expose them in card/HUD payloads.
    """
    ts = float(now if now is not None else time.time())
    finish = _safe_float(job.get("finish_at"))
    if finish > 0 and finish <= ts:
        return False
    if str(job.get("status") or "") == STATUS_ACTIVE:
        remaining = _safe_int(job.get("remaining_seconds"), 0)
        if remaining <= 0:
            return False
    return True


def filter_client_visible_card_jobs(
    jobs: Sequence[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    ts = float(now if now is not None else time.time())
    return [dict(j) for j in jobs if is_queue_job_client_visible(j, now=ts)]


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
    label_str = str(label or owner_key)
    if label_str:
        job["label_key"] = label_str
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


def card_queue_jobs_for_item(
    jobs_by_key: Mapping[str, Sequence[Mapping[str, Any]]],
    owner_key: str,
) -> List[Dict[str, Any]]:
    """All card jobs for one owner key (e.g. multiple same-type unit orders)."""
    rows = jobs_by_key.get(str(owner_key))
    if not rows:
        return []
    return [dict(row) for row in rows]


def card_queue_job_identity(job: Mapping[str, Any]) -> str:
    """Stable patch identity — never type-only."""
    return ":".join(
        [
            str(job.get("owner_type") or ""),
            str(job.get("owner_key") or ""),
            str(_safe_int(job.get("job_id"), 0)),
            str(job.get("status") or ""),
            str(_safe_int(job.get("queue_position"), 0)),
            str(int(_safe_float(job.get("start_at")))),
            str(int(_safe_float(job.get("finish_at")))),
            str(_safe_int(job.get("target_amount"), 0)),
        ]
    )


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
    return reconcile_card_queue_jobs(out, now=ts)


def _apply_queued_wait_remaining(job: Dict[str, Any], *, finish_at: Any, now: float) -> None:
    """Kanonische Queue-Regel: wartende Jobs zeigen finish_at − now (Vorgänger + eigene Dauer)."""
    if job.get("status") != STATUS_QUEUED:
        return
    finish_f = _safe_float(finish_at)
    if finish_f > 0:
        job["remaining_seconds"] = max(0, int(finish_f - now))
    job["progress_pct"] = 0


def reconcile_card_queue_jobs(
    jobs: Sequence[Mapping[str, Any]],
    *,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    GC-537: exactly one active job per queue list (lowest queue_position).
    Queued jobs always show finish_at − now; never inherit active status.
    """
    if not jobs:
        return []

    ts = float(now if now is not None else time.time())
    ordered = sorted(
        [dict(j) for j in jobs],
        key=lambda j: (_safe_int(j.get("queue_position"), 9999), _safe_int(j.get("job_id"), 0)),
    )
    min_pos = min(_safe_int(j.get("queue_position"), 9999) for j in ordered)
    active_job: Optional[Dict[str, Any]] = None
    for job in ordered:
        if _safe_int(job.get("queue_position"), 9999) == min_pos:
            active_job = job
            break
    if active_job is None:
        active_job = ordered[0]

    out: List[Dict[str, Any]] = []
    for job in ordered:
        is_active = job is active_job
        job["status"] = STATUS_ACTIVE if is_active else STATUS_QUEUED
        finish = _safe_float(job.get("finish_at"))
        if is_active:
            if finish > 0:
                rem = max(0, int(finish - ts))
            else:
                rem = max(0, _safe_int(job.get("remaining_seconds"), 0))
            job["remaining_seconds"] = rem
            job["progress_pct"] = compute_progress_pct(
                status=STATUS_ACTIVE,
                remaining_seconds=rem,
                duration_seconds=max(1, _safe_int(job.get("duration_seconds"), 1)),
            )
        else:
            _apply_queued_wait_remaining(job, finish_at=finish, now=ts)
        out.append(job)
    return filter_client_visible_card_jobs(out, now=ts)


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
        label_key = str(raw.get("label_key") or owner_key)
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
                label=label_key,
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
    return reconcile_card_queue_jobs(out, now=ts)


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
    return reconcile_card_queue_jobs(out, now=ts)


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
    return reconcile_card_queue_jobs(out, now=ts)


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
    return reconcile_card_queue_jobs(out, now=ts)


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
    return reconcile_card_queue_jobs(out, now=ts)


def _mini_queue_image_url(domain: str, owner_key: str) -> str:
    key = str(owner_key or "").strip()
    if not key:
        return ""
    dom = str(domain or "").strip().lower()
    if dom in (OWNER_SHIPYARD, "shipyard"):
        from .fleet_defs import ship_icon_static_path

        return ship_icon_static_path(key)
    if dom in (OWNER_DEFENSE, "defense"):
        from .defense_defs import defense_icon_static_path

        return defense_icon_static_path(key)
    if dom in (OWNER_BUILDING, "building", "build"):
        from .buildings import BUILDING_ICON

        path = str(BUILDING_ICON.get(key) or f"img/buildings/{key}.png")
        if path.startswith("/static/"):
            return path
        if path.startswith("img/"):
            return f"/static/{path}"
        return f"/static/img/buildings/{path}"
    if dom in (OWNER_RESEARCH, "research"):
        from .research import RESEARCH_TECHS

        cfg = RESEARCH_TECHS.get(key) or {}
        icon = str(cfg.get("icon") or f"{key}.png")
        if icon.startswith("/static/"):
            return icon
        if icon.startswith("img/"):
            return f"/static/{icon}"
        return f"/static/img/research/{icon}"
    return ""


def map_card_jobs_to_mini_queue_jobs(
    card_jobs: Sequence[Mapping[str, Any]],
    *,
    domain: str,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    GC-QUEUE-MINI-CARDS — horizontal mini-queue strip jobs (shipyard / defense).
    Built from reconciled card jobs; server remains source of truth for timers.
    """
    ts = float(now if now is not None else time.time())
    visible = filter_client_visible_card_jobs(card_jobs, now=ts)
    ordered = sorted(
        visible,
        key=lambda j: (_safe_int(j.get("queue_position"), 9999), _safe_int(j.get("job_id"), 0)),
    )
    dom = str(domain or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(ordered):
        job = dict(raw)
        owner_key = str(job.get("owner_key") or "")
        if not owner_key:
            continue
        status = str(job.get("status") or "")
        is_active = status == STATUS_ACTIVE
        position = _safe_int(job.get("queue_position"), idx + 1)
        amount = _safe_int(job.get("target_amount"), 0)
        target_level = _safe_int(job.get("target_level"), 0)
        if dom in (OWNER_BUILDING, "building", "build", OWNER_RESEARCH, "research"):
            amount = 0
        remaining = _safe_int(job.get("remaining_seconds"), 0)
        finish = _safe_float(job.get("finish_at"))
        if remaining <= 0 and finish > 0 and finish <= ts:
            continue
        label = str(
            job.get("ship_label_key")
            or job.get("defense_label_key")
            or job.get("label_key")
            or job.get("label")
            or owner_key
        )
        out.append(
            {
                "job_id": _safe_int(job.get("job_id"), 0),
                "domain": dom,
                "owner_key": owner_key,
                "label": label,
                "amount": amount,
                "target_level": int(target_level) if target_level > 0 else None,
                "position": position,
                "is_active": is_active,
                "remaining_seconds": remaining,
                "start_at": _safe_float(job.get("start_at")),
                "finish_at": finish if finish > 0 else 0.0,
                "progress_pct": _safe_int(job.get("progress_pct"), 0),
                "duration_seconds": max(1, _safe_int(job.get("duration_seconds"), 1)),
                "image_url": _mini_queue_image_url(dom, owner_key),
                "cancelable": True,
            }
        )
        if job.get("batch_size") is not None:
            out[-1]["batch_size"] = max(1, _safe_int(job.get("batch_size"), 1))
    return out


def enrich_mini_queue_jobs_batch_size(
    jobs: Sequence[Mapping[str, Any]],
    *,
    domain: str,
    shipyard_level: int,
) -> List[Dict[str, Any]]:
    """Attach per-job batch_size for shipyard/defense mini-queue display."""
    dom = str(domain or "").strip().lower()
    lvl = max(1, int(shipyard_level or 1))
    out: List[Dict[str, Any]] = []
    for raw in jobs:
        job = dict(raw)
        owner_key = str(job.get("owner_key") or "")
        if dom in (OWNER_SHIPYARD, "shipyard") and owner_key:
            from .shipyard import base_unit_seconds_for_ship, unit_batch_capacity

            job["batch_size"] = unit_batch_capacity(lvl, base_unit_seconds_for_ship(owner_key))
        elif dom in (OWNER_DEFENSE, "defense") and owner_key:
            from .defense import _batch_capacity_for_defense

            job["batch_size"] = _batch_capacity_for_defense(owner_key, lvl)
        out.append(job)
    return out
