#!/usr/bin/env python3
"""Run the existing Genesis Sentinel against a disposable PostgreSQL sandbox."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.browser_postgres_support import start_postgres_sandbox  # noqa: E402


def main() -> int:
    artifact_root = ROOT / "artifacts" / "browser-postgres"
    runtime = None
    try:
        runtime = start_postgres_sandbox(artifact_root)
        env = os.environ.copy()
        env.update(
            {
                "GC_SENTINEL_BASE_URL": runtime.base_url,
                "GC_SENTINEL_USERNAME": runtime.username,
                "GC_SENTINEL_PASSWORD": runtime.password,
            }
        )
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "browser_sentinel.py"),
            "--mode",
            "live",
            "--artifacts",
            "artifacts/browser-postgres",
            "--fail-on",
            "none",
        ]
        result = subprocess.run(cmd, cwd=str(ROOT), env=env)
        return int(result.returncode)
    finally:
        if runtime is not None:
            runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
