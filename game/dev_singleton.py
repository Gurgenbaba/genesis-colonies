"""Local dev single-instance helper: free the Flask bind port before start.

Production is never touched. Used only from ``python app.py`` (__main__).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Iterable, Set


def pids_listening_on_port(port: int, *, netstat_output: str | None = None) -> Set[int]:
    """Return PIDs with a TCP LISTEN socket on ``port`` (best-effort)."""
    port_i = int(port)
    if port_i <= 0:
        return set()

    raw = netstat_output
    if raw is None:
        try:
            raw = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                errors="replace",
                timeout=10,
            )
        except Exception:
            return set()

    pids: Set[int] = set()
    port_token = f":{port_i}"
    for line in str(raw).splitlines():
        upper = line.upper()
        # EN: LISTENING · DE: ABHÖREN (often mojibake as ABH*REN)
        if "LISTEN" not in upper and "ABH" not in upper:
            continue
        if port_token not in line:
            continue
        # Prefer local address column containing :port (avoid remote :port matches).
        parts = line.split()
        if len(parts) < 2:
            continue
        local = parts[1] if len(parts) > 1 else ""
        if not (local.endswith(port_token) or local.endswith(f":{port_i}]")):
            # IPv6 forms vary; fall back to any :port then PID column.
            if port_token not in local:
                continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return pids


def _kill_pid(pid: int) -> bool:
    pid_i = int(pid)
    if pid_i <= 0:
        return False
    try:
        if sys.platform == "win32":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid_i), "/F", "/T"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return completed.returncode == 0
        os.kill(pid_i, signal.SIGTERM)
        return True
    except Exception:
        return False


def ensure_dev_port_available(
    port: int,
    *,
    enabled: bool | None = None,
    exclude_pids: Iterable[int] | None = None,
) -> list[int]:
    """
    Kill foreign listeners on ``port`` so a new local ``app.py`` can bind.

    Skips production and when ``GC_SINGLE_INSTANCE=0``.
    Returns the list of PIDs that were signaled.
    """
    from .config import is_production

    if is_production():
        return []

    if enabled is None:
        raw = os.environ.get("GC_SINGLE_INSTANCE", "1").strip().lower()
        enabled = raw not in ("0", "false", "no", "off")
    if not enabled:
        return []

    exclude = {int(x) for x in (exclude_pids or []) if int(x) > 0}
    exclude.add(os.getpid())
    try:
        ppid = os.getppid()
        if ppid > 0:
            exclude.add(int(ppid))
    except Exception:
        pass

    victims = sorted(pid for pid in pids_listening_on_port(int(port)) if pid not in exclude)
    killed: list[int] = []
    for pid in victims:
        if _kill_pid(pid):
            killed.append(pid)
            print(f"[GC] Stopped previous local server on port {int(port)} (pid {pid})")

    if killed:
        # Brief wait so the OS releases the bind before Flask starts.
        time.sleep(0.35)
    return killed
