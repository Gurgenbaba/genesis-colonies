"""GC-537: locale key audit — all used keys must exist in locale JSON files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = ROOT / "scripts" / "check_locale_keys.py"


def test_all_used_locale_keys_present():
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
