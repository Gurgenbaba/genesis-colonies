"""GC-829 — universe speed benchmark generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_benchmark_script_generates_markdown():
    out = ROOT / "docs" / "UNIVERSE_SPEED_BENCHMARK.md"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "universe_speed_benchmark.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    text = out.read_text(encoding="utf-8")
    assert "GC-829" in text
    assert "Energieeffizienz" in text
    assert "research_speed" in text
    assert "build_speed" in text
    assert "production_speed" in text
    assert "xychart-beta" in text
    assert "Empfehlung (Alpha)" in text


def test_research_time_uses_effect_resolver():
    from scripts.universe_speed_benchmark import research_seconds

    s1 = research_seconds("energy_tech", 20, lab=10, research_speed=1)
    s10 = research_seconds("energy_tech", 20, lab=10, research_speed=10)
    assert s10 < s1
    assert s1 // s10 == 10
