from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_shadow_report_cli_bootstraps_repo_root_when_run_as_file(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "endgame_economy_shadow_report.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--max-pair-examples" in result.stdout
