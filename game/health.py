"""
Health check assembly for /health and install verification.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from game.config import (
    get_app_version,
    is_debug_enabled,
    is_production,
    validate_config,
)
from game.db import db, resolve_db_path
from game.migrations_util import migrations_are_current


def writable_paths() -> List[Path]:
    db_path = resolve_db_path()
    paths = [
        db_path.parent,
        Path(__file__).resolve().parent.parent / "game",
        Path(__file__).resolve().parent.parent / "locales",
    ]
    unique: List[Path] = []
    seen = set()
    for p in paths:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def check_writable() -> Dict[str, Any]:
    results: Dict[str, Any] = {"ok": True, "paths": {}}
    for path in writable_paths():
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".gc_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            results["paths"][str(path)] = {"ok": True}
        except OSError as exc:
            results["ok"] = False
            results["paths"][str(path)] = {"ok": False, "error": str(exc)}
    return results


def check_database() -> Dict[str, Any]:
    db_path = resolve_db_path()
    info: Dict[str, Any] = {
        "ok": False,
        "backend": os.environ.get("GC_DB_BACKEND", "sqlite"),
        "path": str(db_path),
        "exists": db_path.exists(),
    }
    try:
        conn = db()
        conn.execute("SELECT 1;")
        conn.close()
        info["ok"] = True
    except Exception as exc:
        info["error"] = str(exc)
    return info


def check_migrations() -> Dict[str, Any]:
    current, pending, err = migrations_are_current()
    return {
        "ok": current and err is None,
        "current": current,
        "pending": pending,
        "error": err,
    }


def check_config() -> Dict[str, Any]:
    errors = validate_config(strict=False)
    return {
        "ok": len(errors) == 0 or not is_production(),
        "production": is_production(),
        "debug": is_debug_enabled(),
        "errors": errors,
    }


def build_health_report() -> Dict[str, Any]:
    db_check = check_database()
    mig_check = check_migrations()
    write_check = check_writable()
    cfg_check = check_config()

    critical_ok = db_check["ok"] and mig_check["ok"] and write_check["ok"]
    if is_production() and cfg_check.get("errors"):
        critical_ok = False

    status = "ok"
    if not critical_ok:
        status = "fail"
    elif not cfg_check["ok"]:
        status = "degraded"

    return {
        "status": status,
        "version": get_app_version(),
        "checks": {
            "database": db_check,
            "migrations": mig_check,
            "writable": write_check,
            "config": cfg_check,
        },
    }
