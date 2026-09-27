"""Best-effort SystemOS control-plane client for Genesis Colonies.

The game database remains authoritative. SystemOS receives only compact
operational state/events and must never be required for gameplay to work.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 2.5
DEFAULT_HEALTH_INTERVAL_SEC = 300


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _base_url() -> str:
    return (_env("SYSTEMOS_URL") or _env("MAIL_HUB_URL")).rstrip("/")


def _token() -> str:
    return _env("SYSTEMOS_SERVICE_TOKEN")


def configured() -> bool:
    return bool(_base_url() and _token())


def instance_key() -> str:
    return _env("GC_UNIVERSE_KEY", "dev") or "dev"


def _post(path: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    base = _base_url()
    token = _token()
    if not base or not token:
        return False, {"ok": False, "error": "systemos_unavailable"}

    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Genesis-Colonies/SystemOS",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SEC) as response:
            raw = response.read(64 * 1024)
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return bool(data.get("ok")), data
    except urllib.error.HTTPError as exc:
        logger.warning("systemos HTTP %s path=%s", exc.code, path)
        return False, {"ok": False, "error": f"http_{exc.code}"}
    except Exception as exc:
        logger.warning("systemos unavailable path=%s error=%s", path, exc)
        return False, {"ok": False, "error": "systemos_unavailable"}


def emit_event(
    event_type: str,
    summary: str,
    *,
    severity: str = "info",
    metadata: Dict[str, Any] | None = None,
    external_ref: str = "",
    event_id: str | None = None,
) -> Tuple[bool, Dict[str, Any]]:
    stable_id = event_id or f"{instance_key()}:{event_type}:{uuid.uuid4().hex}"
    return _post(
        "/api/v1/events",
        {
            "event_id": stable_id[:160],
            "type": str(event_type or "")[:80],
            "severity": str(severity or "info")[:16],
            "summary": str(summary or "")[:1000],
            "metadata": dict(metadata or {}),
            "external_ref": str(external_ref or "")[:500],
            "schema_version": 1,
        },
    )


def report_health(
    status: str,
    *,
    summary: str = "",
    metadata: Dict[str, Any] | None = None,
) -> Tuple[bool, Dict[str, Any]]:
    return _post(
        "/api/v1/health",
        {
            "status": status,
            "summary": str(summary or "")[:500],
            "metadata": dict(metadata or {}),
        },
    )


def report_incident(
    incident_key: str,
    title: str,
    *,
    status: str = "open",
    severity: str = "error",
    summary: str = "",
    external_ref: str = "",
) -> Tuple[bool, Dict[str, Any]]:
    return _post(
        "/api/v1/incidents",
        {
            "incident_key": str(incident_key or "")[:160],
            "title": str(title or "")[:240],
            "status": status,
            "severity": severity,
            "summary": str(summary or "")[:2000],
            "external_ref": str(external_ref or "")[:500],
        },
    )


def _compact_health_report() -> tuple[str, str, Dict[str, Any]]:
    from game.health import build_health_report

    report = build_health_report()
    source_status = str(report.get("status") or "fail").lower()
    status = {
        "ok": "healthy",
        "degraded": "degraded",
        "fail": "unhealthy",
    }.get(source_status, "unhealthy")
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    database = checks.get("database") if isinstance(checks.get("database"), dict) else {}
    migrations = checks.get("migrations") if isinstance(checks.get("migrations"), dict) else {}
    runtime = checks.get("runtime") if isinstance(checks.get("runtime"), dict) else {}
    metadata = {
        "version": str(report.get("version") or "")[:80],
        "commit": str(report.get("revision") or "")[:80],
        "database_backend": str(database.get("backend") or runtime.get("database_backend") or "")[:32],
        "migrations_current": bool(migrations.get("current")),
        "total_ms": float(report.get("total_ms") or 0.0),
    }
    return status, f"Genesis {instance_key()} readiness: {source_status}", metadata


def report_current_health() -> bool:
    if not configured():
        return False
    try:
        status, summary, metadata = _compact_health_report()
        ok, _ = report_health(status, summary=summary, metadata=metadata)
        return ok
    except Exception:
        logger.exception("systemos health report failed")
        return False


def _health_interval_sec() -> int:
    raw = _env("SYSTEMOS_HEALTH_INTERVAL_SEC", str(DEFAULT_HEALTH_INTERVAL_SEC))
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_HEALTH_INTERVAL_SEC
    return max(60, min(3600, value))


_started = False
_started_lock = threading.Lock()


def start_agent() -> bool:
    """Start one lightweight daemon heartbeat thread per web process."""
    global _started
    if not configured():
        return False
    with _started_lock:
        if _started:
            return True
        _started = True

    from game.config import get_app_version, get_deploy_revision

    revision = get_deploy_revision() or ""
    emit_event(
        "app.started",
        f"Genesis {instance_key()} web process started",
        metadata={
            "version": get_app_version(),
            "commit": revision,
            "role": "web",
        },
        event_id=f"{instance_key()}:app.started:{revision or uuid.uuid4().hex}",
    )

    def loop() -> None:
        while True:
            report_current_health()
            time.sleep(_health_interval_sec())

    thread = threading.Thread(
        target=loop,
        name=f"systemos-health-{instance_key()}",
        daemon=True,
    )
    thread.start()
    return True
