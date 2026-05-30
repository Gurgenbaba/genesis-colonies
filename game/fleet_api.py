"""Unified JSON helpers for fleet HTTP APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional


def fleet_ok(data: Any = None, *, message_key: str = "fleet_ok", message: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "message": message or message_key,
        "message_key": message_key,
        "data": data if data is not None else {},
    }
    return out


def fleet_err(error: str, *, message_key: str | None = None, message: str = "", data: Any = None) -> Dict[str, Any]:
    key = message_key or f"fleet_error_{error}"
    out: Dict[str, Any] = {
        "ok": False,
        "error": error,
        "message": message or key,
        "message_key": key,
    }
    if data is not None:
        out["data"] = data
    return out
