"""
GC-PERF-AUTO — Automatic Performance Intelligence.

In-memory request aggregation, pressure state, hotspots, and rule-based diagnosis.
Not game-state. No DB writes per request. Bounded memory.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RING_MAX = 2048
_HISTORY_MINUTES = 60
_SLOW_MS = 500.0
_VERY_SLOW_MS = 1000.0
_CRITICAL_MS = 2500.0
_SLOW_QUERY_MS = 100.0

_PHASE_ALIASES = {
    "queue_finish": "finish_ms",
    "resource_tick": "resource_sync_ms",
    "fleet_tick": "fleet_tick_ms",
    "finish_fleet": "finish_fleet_ms",
    "state_build": "payload_ms",
    "live_context": "live_context_ms",
    "database": "db_query_ms",
    "template": "template_ms",
    # GC-PERF-AUTO-007A payload / page children
    "payload.nav_badges": "payload_nav_badges_ms",
    "payload.fleets_hud": "payload_fleets_hud_ms",
    "payload.score": "payload_score_ms",
    "payload.active_planet": "payload_active_planet_ms",
    "payload.panel": "payload_panel_ms",
    "payload.notifications": "payload_notifications_ms",
    "payload.liveops": "payload_liveops_ms",
    "page_context.overview": "page_context_overview_ms",
    "page_context.shipyard": "page_context_shipyard_ms",
    "page_context.fleet": "page_context_fleet_ms",
    # GC-PERF-AUTO-007B — fleets_hud / live_context children
    "fleets.dirty_tick": "fleets_dirty_tick_ms",
    "fleets.alerts": "fleets_alerts_ms",
    "fleets.radar": "fleets_radar_ms",
    "fleets.active": "fleets_active_ms",
    "fleets.slots": "fleets_slots_ms",
    "live.hud_reads": "live_hud_reads_ms",
    "hud.build_queue": "hud_build_queue_ms",
    "hud.research": "hud_research_ms",
    "hud.prod": "hud_prod_ms",
    "panel.overview_rows": "panel_overview_rows_ms",
    "panel.overview_status": "panel_overview_status_ms",
    "panel.buildings_rows": "panel_buildings_rows_ms",
    "panel.buildings_delta": "panel_buildings_delta_ms",
}

_COMPONENT_DISPLAY = {
    "finish_ms": "queue_finish",
    "resource_sync_ms": "resource_tick",
    "fleet_tick_ms": "fleet_tick",
    "finish_fleet_ms": "finish_fleet",
    "payload_ms": "state_build",
    "payload_nav_badges_ms": "payload.nav_badges",
    "payload_fleets_hud_ms": "payload.fleets_hud",
    "payload_score_ms": "payload.score",
    "payload_active_planet_ms": "payload.active_planet",
    "payload_panel_ms": "payload.panel",
    "payload_notifications_ms": "payload.notifications",
    "payload_liveops_ms": "payload.liveops",
    "panel_overview_rows_ms": "panel.overview_rows",
    "panel_overview_status_ms": "panel.overview_status",
    "panel_buildings_rows_ms": "panel.buildings_rows",
    "panel_buildings_delta_ms": "panel.buildings_delta",
    "fleets_dirty_tick_ms": "fleets.dirty_tick",
    "fleets_alerts_ms": "fleets.alerts",
    "fleets_radar_ms": "fleets.radar",
    "fleets_active_ms": "fleets.active",
    "fleets_slots_ms": "fleets.slots",
    "live_hud_reads_ms": "live.hud_reads",
    "hud_build_queue_ms": "hud.build_queue",
    "hud_research_ms": "hud.research",
    "hud_prod_ms": "hud.prod",
    "live_context_ms": "live_context",
    "page_context_ms": "page_context",
    "page_context_overview_ms": "page_context.overview",
    "page_context_shipyard_ms": "page_context.shipyard",
    "page_context_fleet_ms": "page_context.fleet",
    "live_state_ms": "live_state",
    "db_query_ms": "database",
    "template_ms": "template",
    "template_render_ms": "template",
}

# Parent / envelope phases — include wall time of children; never treat as root cause.
_PARENT_PHASE_KEYS = frozenset(
    {
        "handler_ms",
        "before_request_ms",
        "after_request_ms",
        # GC-PERF-AUTO-007A/B: envelope around payload children (same wall as children sum)
        "payload_ms",
        # Diet live refresh wall (finish + resource + hud_reads) — prefer children
        "live_context_ms",
        # HUD queue/research/prod wall — prefer hud.* children
        "live_hud_reads_ms",
        # Fleet HUD rebuild wall — prefer fleets.* children
        "payload_fleets_hud_ms",
        # Full panel wall — prefer panel.* children
        "payload_panel_ms",
    }
)
_PARENT_COMPONENT_NAMES = frozenset(
    {
        "handler",
        "before_request",
        "after_request",
        "state_build",
        "live_context",
        "live.hud_reads",
        "payload.fleets_hud",
        "payload.panel",
    }
)
_SPIKE_RING_MAX = 48

_SKIP_PATH_PREFIXES = ("/healthz", "/health", "/static/")
_PRESSURE_MIN_SAMPLES = 8

_SQL_LITERAL_RE = re.compile(r"'([^']|'')*'")
_SQL_NUM_RE = re.compile(r"\b\d+\b")
_SQL_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def is_perf_intel_enabled() -> bool:
    try:
        from game.config import is_perf_intel_enabled as _cfg

        return bool(_cfg())
    except Exception:
        val = os.environ.get("GC_PERF_INTEL", "1")
        return str(val).strip().lower() not in ("0", "false", "no", "off")


def get_perf_intel_sample() -> float:
    try:
        from game.config import get_perf_intel_sample as _cfg

        return float(_cfg())
    except Exception:
        return 1.0


def get_slow_query_ms() -> float:
    try:
        from game.config import get_perf_slow_query_ms as _cfg

        return float(_cfg())
    except Exception:
        return _SLOW_QUERY_MS


def get_slow_request_ms() -> float:
    """Threshold for intel slow/spike classification.

    Debug often sets ``GC_REQUEST_PERF_SLOW_MS=0`` to log every request — that must
    **not** flood the spike ring or mark 40ms polls as slow.
    """
    try:
        from game.config import get_request_perf_slow_ms as _cfg

        configured = float(_cfg())
    except Exception:
        return _SLOW_MS
    if configured <= 0:
        return _SLOW_MS
    return configured


def get_spike_request_ms() -> float:
    """Alias — spike ring uses the same floor-safe threshold as slow classification."""
    return get_slow_request_ms()


# ---------------------------------------------------------------------------
# SQL signature
# ---------------------------------------------------------------------------


def normalize_sql_signature(sql: str, *, max_len: int = 120) -> str:
    """Normalize SQL for aggregation — no user literals."""
    s = str(sql or "").strip()
    if not s:
        return ""
    s = _SQL_LITERAL_RE.sub("?", s)
    s = _SQL_NUM_RE.sub("?", s)
    s = _SQL_WS_RE.sub(" ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


# ---------------------------------------------------------------------------
# Process metrics
# ---------------------------------------------------------------------------

_psutil = None
_psutil_checked = False
_proc_cpu_last: Optional[Tuple[float, float]] = None  # (wall, cpu_time)


def _try_psutil():
    global _psutil, _psutil_checked
    if _psutil_checked:
        return _psutil
    _psutil_checked = True
    try:
        import psutil as _ps

        _psutil = _ps
    except Exception:
        _psutil = None
    return _psutil


def collect_process_metrics() -> Dict[str, Any]:
    """Best-effort process/system snapshot. Never raises."""
    out: Dict[str, Any] = {
        "pid": os.getpid(),
        "cpu_percent": None,
        "rss_mb": None,
        "thread_count": None,
        "loadavg": None,
        "open_db_hint": None,
        "source": "fallback",
    }
    try:
        out["thread_count"] = int(threading.active_count())
    except Exception:
        pass

    ps = _try_psutil()
    if ps is not None:
        try:
            proc = ps.Process(os.getpid())
            out["cpu_percent"] = float(proc.cpu_percent(interval=None))
            mem = proc.memory_info()
            out["rss_mb"] = round(float(mem.rss) / (1024.0 * 1024.0), 1)
            out["thread_count"] = int(proc.num_threads())
            try:
                out["loadavg"] = list(os.getloadavg())  # type: ignore[attr-defined]
            except Exception:
                pass
            out["source"] = "psutil"
            return out
        except Exception:
            logger.debug("psutil process metrics failed", exc_info=True)

    # Stdlib fallbacks
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # ru_maxrss: Linux KB, macOS bytes — approximate
        rss = float(usage.ru_maxrss)
        if rss > 10_000_000:  # likely bytes (macOS)
            out["rss_mb"] = round(rss / (1024.0 * 1024.0), 1)
        else:
            out["rss_mb"] = round(rss / 1024.0, 1)
        global _proc_cpu_last
        now = time.time()
        cpu_time = float(usage.ru_utime) + float(usage.ru_stime)
        if _proc_cpu_last is not None:
            wall_d = max(1e-6, now - _proc_cpu_last[0])
            cpu_d = max(0.0, cpu_time - _proc_cpu_last[1])
            out["cpu_percent"] = round(100.0 * cpu_d / wall_d, 1)
        _proc_cpu_last = (now, cpu_time)
        out["source"] = "resource"
    except Exception:
        pass
    try:
        out["loadavg"] = list(os.getloadavg())  # type: ignore[attr-defined]
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------


def percentile(sorted_values: List[float], p: float) -> float:
    """Nearest-rank percentile for a pre-sorted non-empty list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    p = max(0.0, min(100.0, float(p)))
    if p <= 0:
        return float(sorted_values[0])
    if p >= 100:
        return float(sorted_values[-1])
    k = math.ceil((p / 100.0) * len(sorted_values)) - 1
    k = max(0, min(len(sorted_values) - 1, k))
    return float(sorted_values[k])


def summarize_latencies(values: List[float]) -> Dict[str, float]:
    if not values:
        return {
            "count": 0,
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }
    ordered = sorted(float(v) for v in values)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "avg_ms": round(total / len(ordered), 2),
        "p50_ms": round(percentile(ordered, 50), 2),
        "p95_ms": round(percentile(ordered, 95), 2),
        "p99_ms": round(percentile(ordered, 99), 2),
        "max_ms": round(ordered[-1], 2),
    }


# ---------------------------------------------------------------------------
# Sample + store
# ---------------------------------------------------------------------------


@dataclass
class RequestSample:
    ts: float
    method: str
    route: str
    path: str
    status: int
    total_ms: float
    error: bool
    phases: Dict[str, float] = field(default_factory=dict)
    sql_count: int = 0
    db_connection_open_count: int = 0
    db_query_ms: float = 0.0
    slow_queries: List[Dict[str, Any]] = field(default_factory=list)
    payload_bytes: int = 0
    slow_class: str = ""
    panels_built: str = ""
    panel_page: str = ""


@dataclass
class MinuteBucket:
    minute: int  # epoch // 60
    count: int = 0
    error_count: int = 0
    total_ms_sum: float = 0.0
    max_ms: float = 0.0
    latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=256))


class PerfIntelStore:
    """Process-local bounded metrics store."""

    def __init__(
        self,
        *,
        ring_max: int = _RING_MAX,
        history_minutes: int = _HISTORY_MINUTES,
        spike_max: int = _SPIKE_RING_MAX,
    ) -> None:
        self._lock = threading.RLock()
        self._ring: Deque[RequestSample] = deque(maxlen=max(32, int(ring_max)))
        self._spikes: Deque[Dict[str, Any]] = deque(maxlen=max(8, int(spike_max)))
        self._history_minutes = max(5, int(history_minutes))
        self._buckets: Dict[int, MinuteBucket] = {}
        self._active = 0
        self._pressure_state = "normal"
        self._pressure_since = time.time()
        self._was_elevated = False

    def reset(self) -> None:
        with self._lock:
            self._ring.clear()
            self._spikes.clear()
            self._buckets.clear()
            self._active = 0
            self._pressure_state = "normal"
            self._was_elevated = False
            self._pressure_since = time.time()

    def begin_request(self) -> None:
        with self._lock:
            self._active += 1

    def end_request(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active_requests(self) -> int:
        with self._lock:
            return int(self._active)

    @property
    def ring_len(self) -> int:
        with self._lock:
            return len(self._ring)

    def record(self, sample: RequestSample) -> None:
        with self._lock:
            self._ring.append(sample)
            # Defense: only true wall-clock slow requests (never debug threshold 0).
            if sample.slow_class and float(sample.total_ms) >= get_spike_request_ms():
                self._spikes.appendleft(self._spike_from_sample_unlocked(sample))
            minute = int(sample.ts) // 60
            bucket = self._buckets.get(minute)
            if bucket is None:
                bucket = MinuteBucket(minute=minute)
                self._buckets[minute] = bucket
            bucket.count += 1
            if sample.error:
                bucket.error_count += 1
            bucket.total_ms_sum += float(sample.total_ms)
            bucket.max_ms = max(bucket.max_ms, float(sample.total_ms))
            bucket.latencies.append(float(sample.total_ms))
            self._prune_buckets_unlocked(now_minute=minute)
            self._update_pressure_unlocked()

    def _spike_from_sample_unlocked(self, sample: RequestSample) -> Dict[str, Any]:
        phases_sorted = sorted(
            (
                (_COMPONENT_DISPLAY.get(k, k.replace("_ms", "")), round(float(v), 1))
                for k, v in sample.phases.items()
                if k not in _PARENT_PHASE_KEYS and float(v) > 0
            ),
            key=lambda kv: -kv[1],
        )[:8]
        return {
            "ts": round(float(sample.ts), 3),
            "route": sample.route or sample.path,
            "path": sample.path,
            "method": sample.method,
            "status": sample.status,
            "total_ms": round(float(sample.total_ms), 1),
            "slow_class": sample.slow_class,
            "top_costs": [{"name": n, "ms": ms} for n, ms in phases_sorted],
            "sql_count": int(sample.sql_count),
            "db_connection_open_count": int(sample.db_connection_open_count),
            "db_query_ms": round(float(sample.db_query_ms), 1),
            "slow_queries": list(sample.slow_queries or [])[:5],
            "concurrent": int(self._active),
            "payload_bytes": int(sample.payload_bytes or 0),
            "panels_built": str(sample.panels_built or ""),
            "panel_page": str(sample.panel_page or ""),
        }

    def recent_spikes(self, limit: int = 20) -> List[Dict[str, Any]]:
        lim = max(1, min(64, int(limit)))
        with self._lock:
            return list(self._spikes)[:lim]

    def _prune_buckets_unlocked(self, *, now_minute: Optional[int] = None) -> None:
        if now_minute is None:
            now_minute = int(time.time()) // 60
        cutoff = now_minute - self._history_minutes
        stale = [m for m in self._buckets if m < cutoff]
        for m in stale:
            del self._buckets[m]

    def samples_since(self, window_sec: float) -> List[RequestSample]:
        cutoff = time.time() - max(0.0, float(window_sec))
        with self._lock:
            return [s for s in self._ring if s.ts >= cutoff]

    def all_samples(self) -> List[RequestSample]:
        with self._lock:
            return list(self._ring)

    def get_pressure_state(self) -> str:
        with self._lock:
            return str(self._pressure_state)

    def _window_p95_cpu(self, window_sec: float = 60.0) -> Tuple[float, Optional[float]]:
        samples = [s for s in self._ring if s.ts >= time.time() - window_sec]
        if not samples:
            return 0.0, None
        ordered = sorted(s.total_ms for s in samples)
        p95 = percentile(ordered, 95)
        # CPU from latest process snapshot is applied outside; store uses latency only here
        return p95, None

    def _update_pressure_unlocked(self) -> None:
        """Hysteresis on p95 (1m window). CPU applied in snapshot builder."""
        now = time.time()
        samples = [s for s in self._ring if s.ts >= now - 60.0]
        if len(samples) < _PRESSURE_MIN_SAMPLES:
            # Too few samples — p95 ≈ max of one cold SSR; do not escalate.
            if self._pressure_state in ("pressure", "critical") and self._was_elevated:
                self._pressure_state = "recovery"
            elif self._pressure_state == "warm" and len(samples) < 3:
                self._pressure_state = "normal"
            return
        ordered = sorted(s.total_ms for s in samples)
        p95 = percentile(ordered, 95)
        p50 = percentile(ordered, 50)
        cpu = None
        try:
            snap = collect_process_metrics()
            cpu = snap.get("cpu_percent")
        except Exception:
            cpu = None

        state = self._pressure_state
        # Enter thresholds (stricter)
        enter_critical = p95 >= _CRITICAL_MS or (cpu is not None and cpu >= 95.0)
        enter_pressure = p95 >= 1500.0 or (cpu is not None and cpu >= 85.0)
        enter_warm = p95 >= 750.0 or (cpu is not None and cpu >= 70.0)
        # Exit thresholds (hysteresis — lower). Healthy p50 + idle CPU means
        # cold/outlier tails must not pin CRITICAL (Bobby dashboard: p50~45, CPU 0%).
        idle_cpu = cpu is None or float(cpu) < 40.0
        healthy_median = p50 < 150.0
        exit_critical = (
            (p95 < 2000.0 or (healthy_median and idle_cpu))
            and (cpu is None or float(cpu) < 90.0)
        )
        exit_pressure = p95 < 1200.0 and (cpu is None or cpu < 80.0)
        exit_warm = p95 < 500.0 and (cpu is None or cpu < 65.0)

        new_state = state
        if state == "normal":
            if enter_critical:
                new_state = "critical"
            elif enter_pressure:
                new_state = "pressure"
            elif enter_warm:
                new_state = "warm"
        elif state == "warm":
            if enter_critical:
                new_state = "critical"
            elif enter_pressure:
                new_state = "pressure"
            elif exit_warm:
                new_state = "normal"
        elif state == "pressure":
            if enter_critical:
                new_state = "critical"
            elif exit_pressure:
                new_state = "recovery"
                self._was_elevated = True
        elif state == "critical":
            if exit_critical:
                new_state = "recovery"
                self._was_elevated = True
        elif state == "recovery":
            if enter_critical:
                new_state = "critical"
            elif enter_pressure:
                new_state = "pressure"
            elif exit_warm:
                new_state = "normal"
                self._was_elevated = False
            elif enter_warm:
                new_state = "warm"
                self._was_elevated = False

        if new_state in ("pressure", "critical"):
            self._was_elevated = True

        if new_state != state:
            self._pressure_state = new_state
            self._pressure_since = now

    def route_stats(self, window_sec: float) -> List[Dict[str, Any]]:
        samples = self.samples_since(window_sec)
        by_route: Dict[str, List[RequestSample]] = defaultdict(list)
        for s in samples:
            key = s.route or s.path or "unknown"
            by_route[key].append(s)
        out: List[Dict[str, Any]] = []
        window = max(1.0, float(window_sec))
        for route, rows in by_route.items():
            lats = [r.total_ms for r in rows]
            summary = summarize_latencies(lats)
            errors = sum(1 for r in rows if r.error)
            db_ms = [r.db_query_ms for r in rows if r.db_query_ms > 0]
            qcounts = [r.sql_count for r in rows]
            out.append(
                {
                    "route": route,
                    "request_count": len(rows),
                    "requests_per_second": round(len(rows) / window, 3),
                    "avg_ms": summary["avg_ms"],
                    "p50_ms": summary["p50_ms"],
                    "p95_ms": summary["p95_ms"],
                    "p99_ms": summary["p99_ms"],
                    "max_ms": summary["max_ms"],
                    "error_rate": round(errors / max(1, len(rows)), 4),
                    "avg_db_ms": round(sum(db_ms) / len(db_ms), 2) if db_ms else 0.0,
                    "avg_query_count": round(sum(qcounts) / len(qcounts), 2) if qcounts else 0.0,
                }
            )
        out.sort(key=lambda r: (-float(r["p95_ms"]), -int(r["request_count"])))
        return out

    def component_stats(self, window_sec: float) -> List[Dict[str, Any]]:
        samples = self.samples_since(window_sec)
        totals: Dict[str, float] = defaultdict(float)
        counts: Dict[str, int] = defaultdict(int)
        grand = 0.0
        for s in samples:
            for phase, ms in s.phases.items():
                if ms <= 0 or phase in _PARENT_PHASE_KEYS:
                    continue
                name = _COMPONENT_DISPLAY.get(phase, phase.replace("_ms", ""))
                if name in _PARENT_COMPONENT_NAMES:
                    continue
                totals[name] += float(ms)
                counts[name] += 1
                grand += float(ms)
        out: List[Dict[str, Any]] = []
        for name, total in totals.items():
            out.append(
                {
                    "component": name,
                    "total_ms": round(total, 2),
                    "avg_ms": round(total / max(1, counts[name]), 2),
                    "share": round(total / grand, 4) if grand > 0 else 0.0,
                    "samples": counts[name],
                }
            )
        out.sort(key=lambda c: -float(c["total_ms"]))
        return out

    def slow_query_stats(self, window_sec: float, *, limit: int = 20) -> List[Dict[str, Any]]:
        samples = self.samples_since(window_sec)
        by_sig: Dict[str, List[float]] = defaultdict(list)
        for s in samples:
            for q in s.slow_queries:
                sig = str(q.get("signature") or "")
                if not sig:
                    continue
                by_sig[sig].append(float(q.get("ms") or 0.0))
        out: List[Dict[str, Any]] = []
        for sig, lats in by_sig.items():
            summary = summarize_latencies(lats)
            out.append(
                {
                    "signature": sig,
                    "count": summary["count"],
                    "avg_ms": summary["avg_ms"],
                    "p95_ms": summary["p95_ms"],
                    "max_ms": summary["max_ms"],
                }
            )
        out.sort(key=lambda q: (-float(q["p95_ms"]), -int(q["count"])))
        return out[: max(1, int(limit))]

    def history_60m(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._prune_buckets_unlocked()
            now_minute = int(time.time()) // 60
            rows: List[Dict[str, Any]] = []
            for offset in range(self._history_minutes - 1, -1, -1):
                minute = now_minute - offset
                b = self._buckets.get(minute)
                if b is None:
                    rows.append(
                        {
                            "minute": minute,
                            "ts": minute * 60,
                            "request_count": 0,
                            "error_count": 0,
                            "avg_ms": 0.0,
                            "p95_ms": 0.0,
                            "max_ms": 0.0,
                        }
                    )
                    continue
                lats = list(b.latencies)
                summary = summarize_latencies(lats) if lats else {
                    "avg_ms": round(b.total_ms_sum / max(1, b.count), 2),
                    "p95_ms": 0.0,
                    "max_ms": b.max_ms,
                }
                rows.append(
                    {
                        "minute": minute,
                        "ts": minute * 60,
                        "request_count": b.count,
                        "error_count": b.error_count,
                        "avg_ms": summary.get("avg_ms", 0.0),
                        "p95_ms": summary.get("p95_ms", 0.0),
                        "max_ms": float(summary.get("max_ms") or b.max_ms),
                    }
                )
            return rows

    def build_diagnosis(self, window_sec: float = 300.0) -> Dict[str, Any]:
        routes = self.route_stats(window_sec)
        components = self.component_stats(window_sec)
        slow_queries = self.slow_query_stats(window_sec, limit=5)
        hot_route = routes[0] if routes else None
        hot_comp = components[0] if components else None
        hot_query = slow_queries[0] if slow_queries else None

        # Slow-request attribution
        samples = self.samples_since(window_sec)
        slow = [s for s in samples if s.total_ms >= get_slow_request_ms()]
        comp_slow: Dict[str, float] = defaultdict(float)
        for s in slow:
            for phase, ms in s.phases.items():
                if phase in _PARENT_PHASE_KEYS:
                    continue
                name = _COMPONENT_DISPLAY.get(phase, phase.replace("_ms", ""))
                if name in _PARENT_COMPONENT_NAMES:
                    continue
                comp_slow[name] += float(ms)
        top_slow_comp = None
        top_slow_share = 0.0
        if comp_slow:
            top_slow_comp = max(comp_slow.items(), key=lambda kv: kv[1])
            total_slow = sum(comp_slow.values()) or 1.0
            top_slow_share = top_slow_comp[1] / total_slow

        cause = "insufficient_data"
        recommendation = "Collect more traffic; keep GC_PERF_INTEL enabled."
        details: Dict[str, Any] = {}

        if len(slow) < 2 and (not hot_route or int(hot_route.get("request_count") or 0) < 3):
            cause = "insufficient_data"
            recommendation = (
                "Too few slow samples for a reliable diagnosis. "
                "Browse a few pages / wait for polls, then refresh."
            )
        elif top_slow_comp and slow:
            cause = top_slow_comp[0]
            details = {
                "share_of_slow": round(top_slow_share, 4),
                "p95_component_hint_ms": round(
                    next((c["avg_ms"] for c in components if c["component"] == cause), 0.0),
                    2,
                ),
                "affected_route": (hot_route or {}).get("route"),
            }
            if cause == "queue_finish":
                recommendation = (
                    "Inspect queue finish on diet poll / worker primary; "
                    "do not duplicate finish engines."
                )
            elif cause in ("fleet_tick", "finish_fleet"):
                recommendation = (
                    "Analyze per-player fleet tick inside finish_due_work; "
                    "global tick already skipped on /api/game-state."
                )
            elif cause == "database":
                recommendation = "Review slow query signatures and N+1 patterns on hot routes."
            elif cause == "resource_tick":
                recommendation = "Check resource persist interval and EffectResolver cost on poll."
            elif cause in ("page_context", "live_context", "live_state"):
                recommendation = (
                    f"SSR/live context cost on '{(hot_route or {}).get('route')}' — "
                    "measure which panel/query inside the page load; cold first hit is common."
                )
            elif cause.startswith("panel."):
                recommendation = (
                    f"Panel section '{cause}' dominates include_panel builds — "
                    "profile buildings rows vs overview status before trimming."
                )
            elif cause.startswith("fleets."):
                recommendation = (
                    f"Fleet HUD section '{cause}' dominates — "
                    "check dirty re-tick vs radar vs active list before trimming."
                )
            elif cause == "live.hud_reads":
                recommendation = (
                    "Post-finish HUD read envelope is hot — "
                    "check hud.build_queue / hud.research / hud.prod children."
                )
            elif cause.startswith("hud."):
                recommendation = (
                    f"HUD section '{cause}' dominates live.hud_reads — "
                    "profile that helper on diet before trimming live fields."
                )
            elif cause.startswith("payload."):
                recommendation = (
                    f"Game-state payload section '{cause}' dominates slow requests — "
                    "profile that helper before trimming HUD fields."
                )
            elif cause.startswith("page_context."):
                recommendation = (
                    f"SSR page builder '{cause}' is hot — "
                    "reuse live_context stash where possible (see OVERVIEW-TTFB pattern)."
                )
            else:
                recommendation = f"Profile component '{cause}' on the hot route before changing gameplay."
        elif hot_route and float(hot_route.get("p95_ms") or 0) >= get_slow_request_ms():
            cause = "hot_route"
            details = {"route": hot_route.get("route"), "p95_ms": hot_route.get("p95_ms")}
            recommendation = f"Hot route {hot_route.get('route')} — instrument phases before optimizing."

        return {
            "cause": cause,
            "recommendation": recommendation,
            "details": details,
            "hot_route": hot_route,
            "hot_component": hot_comp,
            "hot_query": hot_query,
            "slow_request_count": len(slow),
        }

    def snapshot(self) -> Dict[str, Any]:
        process = collect_process_metrics()
        with self._lock:
            self._update_pressure_unlocked()
            status = self._pressure_state
            active = self._active
            pressure_since = self._pressure_since

        windows = {
            "1m": 60.0,
            "5m": 300.0,
            "15m": 900.0,
            "1h": 3600.0,
        }
        requests_out: Dict[str, Any] = {}
        for label, sec in windows.items():
            samples = self.samples_since(sec)
            lats = [s.total_ms for s in samples]
            summary = summarize_latencies(lats)
            errors = sum(1 for s in samples if s.error)
            requests_out[label] = {
                **summary,
                "request_count": len(samples),
                "requests_per_second": round(len(samples) / max(1.0, sec), 3),
                "error_rate": round(errors / max(1, len(samples)), 4) if samples else 0.0,
            }

        routes = self.route_stats(300.0)
        components = self.component_stats(300.0)
        slow_queries = self.slow_query_stats(300.0)
        diagnosis = self.build_diagnosis(300.0)
        spikes = self.recent_spikes(20)

        return {
            "ok": True,
            "status": status,
            "pressure_since": pressure_since,
            "process": process,
            "active_requests": active,
            "requests": requests_out,
            "routes": routes[:25],
            "components": components[:25],
            "slow_queries": slow_queries,
            "spikes": spikes,
            "diagnosis": diagnosis,
            "history_60m": self.history_60m(),
            "ring_size": self.ring_len,
            "ring_capacity": self._ring.maxlen,
        }


_STORE = PerfIntelStore()


def get_store() -> PerfIntelStore:
    return _STORE


def reset_perf_intel_for_tests() -> None:
    _STORE.reset()


def get_pressure_state() -> str:
    return _STORE.get_pressure_state()


def classify_slow(total_ms: float) -> str:
    ms = float(total_ms)
    if ms >= _CRITICAL_MS:
        return "critical"
    if ms >= _VERY_SLOW_MS:
        return "very_slow"
    if ms >= get_slow_request_ms():
        return "slow"
    return ""


def should_skip_path(path: str) -> bool:
    p = str(path or "")
    for prefix in _SKIP_PATH_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return True
    return False


def resolve_phase_name(name: str) -> str:
    """Map friendly span names to RequestPerf phase keys."""
    key = str(name or "").strip()
    if not key:
        return ""
    if key in _PHASE_ALIASES:
        return _PHASE_ALIASES[key]
    if key.endswith("_ms"):
        return key
    return key if key.endswith("_ms") else f"{key}_ms"


def record_request_sample(
    *,
    method: str = "",
    route: str = "",
    path: str = "",
    status: int = 200,
    total_ms: float = 0.0,
    phases: Optional[Dict[str, float]] = None,
    sql_count: int = 0,
    db_connection_open_count: int = 0,
    db_query_ms: float = 0.0,
    slow_queries: Optional[List[Dict[str, Any]]] = None,
    payload_bytes: int = 0,
    error: bool = False,
    panels_built: str = "",
    panel_page: str = "",
) -> None:
    if not is_perf_intel_enabled():
        return
    if should_skip_path(path):
        return
    try:
        slow_class = classify_slow(total_ms)
        sample = RequestSample(
            ts=time.time(),
            method=str(method or ""),
            route=str(route or path or ""),
            path=str(path or ""),
            status=int(status or 0),
            total_ms=max(0.0, float(total_ms)),
            error=bool(error) or int(status or 0) >= 500,
            phases=dict(phases or {}),
            sql_count=int(sql_count or 0),
            db_connection_open_count=int(db_connection_open_count or 0),
            db_query_ms=max(0.0, float(db_query_ms or 0.0)),
            slow_queries=list(slow_queries or [])[:20],
            payload_bytes=int(payload_bytes or 0),
            slow_class=slow_class,
            panels_built=str(panels_built or ""),
            panel_page=str(panel_page or ""),
        )
        _STORE.record(sample)
        if slow_class:
            _emit_slow_request_log(sample)
    except Exception:
        logger.debug("record_request_sample failed", exc_info=True)


def _emit_slow_request_log(sample: RequestSample) -> None:
    try:
        label = sample.slow_class.upper()
        phases_sorted = sorted(
            (
                (_COMPONENT_DISPLAY.get(k, k.replace("_ms", "")), v)
                for k, v in sample.phases.items()
                if k not in _PARENT_PHASE_KEYS and v > 0
            ),
            key=lambda kv: -kv[1],
        )[:6]
        top_lines = " ".join(f"{n}={round(v, 1)}ms" for n, v in phases_sorted)
        proc = collect_process_metrics()
        cpu = proc.get("cpu_percent")
        rss = proc.get("rss_mb")
        logger.info(
            "[GC PERF] %s REQUEST route=%s path=%s total=%.1fms status=%s "
            "TOP_COSTS %s CPU=%s RSS=%sMB concurrent=%s sql=%s conn_opens=%s db_ms=%.1f",
            label,
            sample.route or sample.path,
            sample.path,
            sample.total_ms,
            sample.status,
            top_lines or "-",
            cpu if cpu is not None else "n/a",
            rss if rss is not None else "n/a",
            _STORE.active_requests,
            sample.sql_count,
            sample.db_connection_open_count,
            sample.db_query_ms,
        )
    except Exception:
        pass


def build_admin_performance_payload() -> Dict[str, Any]:
    if not is_perf_intel_enabled():
        return {
            "ok": True,
            "status": "disabled",
            "process": collect_process_metrics(),
            "requests": {},
            "routes": [],
            "components": [],
            "slow_queries": [],
            "spikes": [],
            "diagnosis": {"cause": "disabled", "recommendation": "Set GC_PERF_INTEL=1"},
            "history_60m": [],
        }
    return _STORE.snapshot()
