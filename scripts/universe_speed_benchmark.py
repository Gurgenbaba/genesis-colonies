#!/usr/bin/env python3
"""GC-829 — Universe speed benchmark (authoritative formulas).

Generates docs/UNIVERSE_SPEED_BENCHMARK.md from EffectResolver + economy_balance.

Usage:
  python scripts/universe_speed_benchmark.py
  python scripts/universe_speed_benchmark.py --stdout
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.economy_balance import NEUTRAL_BALANCE_SLOT, mine_upgrade_roi_hours
from game.effects import EffectResolver
from game.fleet_calc import calculate_flight_seconds
from game.models import DEFAULT_GAME_SETTINGS

# ---------------------------------------------------------------------------
# Benchmark axes (GC-829)
# ---------------------------------------------------------------------------

RESEARCH_TECHS: Tuple[Tuple[str, str], ...] = (
    ("energy_tech", "Energieeffizienz"),
    ("mining_tech", "Metallveredelung"),
    ("buildtime_tech", "Bauoptimierung"),
    ("navigation_tech", "Hyperraumnavigation"),
    ("weapon_tech", "Waffentechnik"),
)

RESEARCH_LEVELS: Tuple[int, ...] = (1, 5, 10, 20, 30, 40, 50)
RESEARCH_SPEEDS_TABLE: Tuple[int, ...] = (1, 10, 100, 1000)
RESEARCH_SPEEDS_CHART: Tuple[int, ...] = (1, 10, 100, 1000)
RESEARCH_SPEEDS_FULL: Tuple[float, ...] = (1, 2, 5, 10, 25, 50, 100, 250, 500, 1000)

BUILD_SPEEDS_FULL: Tuple[float, ...] = (1, 2, 5, 10, 25, 50, 100)
BUILD_SPEEDS_CHART: Tuple[float, ...] = (1, 10, 50, 100)
BUILD_LEVELS: Tuple[int, ...] = (1, 5, 10, 20, 30, 40, 50)

PRODUCTION_SPEEDS_FULL: Tuple[float, ...] = (1, 1.25, 1.5, 1.75, 2, 3, 5)
PRODUCTION_SPEEDS_CHART: Tuple[float, ...] = (1, 1.5, 2, 3)
ROI_LEVELS: Tuple[int, ...] = (1, 5, 10, 20, 30, 40, 50)

LAB_LEVELS: Tuple[int, ...] = (1, 5, 10, 20, 50)

# Progressive lab — mirrors a player who upgrades the lab with research depth.
LAB_FOR_LEVEL: Dict[int, int] = {1: 1, 5: 3, 10: 5, 20: 10, 30: 20, 40: 50, 50: 50}

REFERENCE_BUILDING = "metal_mine"
FLEET_REFERENCE_SHIP_SPEED = 1500  # slow hauler tier — meaningful flight times
FLEET_DISTANCES = (500, 2000, 8000)
FLEET_SPEEDS: Tuple[float, ...] = (1, 2, 3, 5, 10)


def _settings(**overrides: float) -> Dict[str, float]:
    base = {
        "production_speed": 1.0,
        "build_speed": 1.0,
        "research_speed": 1.0,
    }
    base.update(overrides)
    return base


def research_seconds(
    tech_key: str,
    level: int,
    *,
    lab: int,
    research_speed: float,
    build_speed: float = 1.0,
) -> int:
    er = EffectResolver(
        {"research_lab": int(lab)},
        {},
        settings=_settings(research_speed=research_speed, build_speed=build_speed),
    )
    return er.get_research_time_seconds(tech_key, level)


def build_seconds(level: int, *, build_speed: float) -> int:
    er = EffectResolver({}, {}, settings=_settings(build_speed=build_speed))
    return er.get_build_time_seconds(REFERENCE_BUILDING, level)


def roi_hours(level: int, *, production_speed: float) -> float:
    return mine_upgrade_roi_hours(
        REFERENCE_BUILDING,
        level,
        slot=NEUTRAL_BALANCE_SLOT,
        production_speed=production_speed,
    )


def fmt_duration(seconds: int) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return "instant"
    if s < 3600:
        m, ss = divmod(s, 60)
        if ss == 0:
            return f"{m}min"
        return f"{m}:{ss:02d}"
    if s < 86400:
        h = s // 3600
        rem_m = (s % 3600) // 60
        if rem_m == 0:
            return f"{h}h"
        return f"{h}h {rem_m}min"
    d = s // 86400
    rem_h = (s % 86400) // 3600
    if rem_h == 0:
        return f"{d}d"
    return f"{d}d {rem_h}h"


def fmt_hours(hours: float) -> str:
    if not math.isfinite(hours):
        return "∞"
    return fmt_duration(int(hours * 3600))


def fmt_roi(hours: float) -> str:
    if not math.isfinite(hours) or hours <= 0:
        return "∞"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _md_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---:" if h else "---" for h in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _research_table(tech_key: str, title: str) -> str:
    rows = []
    for lvl in RESEARCH_LEVELS:
        lab = LAB_FOR_LEVEL[lvl]
        row = [str(lvl), str(lab)]
        for spd in RESEARCH_SPEEDS_TABLE:
            sec = research_seconds(tech_key, lvl, lab=lab, research_speed=spd)
            row.append(fmt_duration(sec))
        rows.append(row)
    hdr = ["Level", "Lab"] + [f"Speed {s}" for s in RESEARCH_SPEEDS_TABLE]
    return f"### {title}\n\n{_md_table(hdr, rows)}\n"


def _lab_effect_table(tech_key: str, title: str, *, level: int = 20) -> str:
    rows = []
    for lab in LAB_LEVELS:
        row = [str(level), str(lab)]
        for spd in RESEARCH_SPEEDS_TABLE:
            sec = research_seconds(tech_key, level, lab=lab, research_speed=spd)
            row.append(fmt_duration(sec))
        rows.append(row)
    hdr = ["Level", "Lab"] + [f"Speed {s}" for s in RESEARCH_SPEEDS_TABLE]
    return f"#### {title} — Labor-Effekt (Level {level})\n\n{_md_table(hdr, rows)}\n"


def _xychart(title: str, x_labels: Sequence[str], series: Dict[str, Sequence[float]], y_max: float, y_label: str = "Stunden") -> str:
    lines = [
        "```mermaid",
        "xychart-beta",
        f'    title "{title}"',
        f"    x-axis [{', '.join(x_labels)}]",
        f'    y-axis "{y_label}" 0 --> {max(1, int(math.ceil(y_max)))}',
    ]
    for name, values in series.items():
        rounded = [round(v, 2) for v in values]
        lines.append(f'    line "{name}" [{", ".join(str(v) for v in rounded)}]')
    lines.append("```")
    return "\n".join(lines)


def _research_chart(tech_key: str, label: str) -> str:
    x_labels = [str(l) for l in RESEARCH_LEVELS]
    series: Dict[str, List[float]] = {}
    y_max = 0.0
    for spd in RESEARCH_SPEEDS_CHART:
        pts = []
        for lvl in RESEARCH_LEVELS:
            lab = LAB_FOR_LEVEL[lvl]
            sec = research_seconds(tech_key, lvl, lab=lab, research_speed=spd)
            h = sec / 3600.0
            pts.append(h)
            y_max = max(y_max, h)
        series[f"research_speed {int(spd)}"] = pts
    return _xychart(
        f"{label} — Forschungszeit (h, progressives Labor)",
        x_labels,
        series,
        y_max,
    )


def _build_chart() -> str:
    x_labels = [str(l) for l in BUILD_LEVELS]
    series: Dict[str, List[float]] = {}
    y_max = 0.0
    for spd in BUILD_SPEEDS_CHART:
        pts = []
        for lvl in BUILD_LEVELS:
            sec = build_seconds(lvl, build_speed=spd)
            mins = sec / 60.0
            pts.append(mins)
            y_max = max(y_max, mins)
        series[f"build_speed {int(spd)}"] = pts
    return _xychart(
        f"{REFERENCE_BUILDING} — Bauzeit (Minuten)",
        x_labels,
        series,
        y_max,
        y_label="Minuten",
    )


def _roi_chart() -> str:
    x_labels = [str(l) for l in ROI_LEVELS]
    series: Dict[str, List[float]] = {}
    y_max = 0.0
    for ps in PRODUCTION_SPEEDS_CHART:
        pts = []
        for lvl in ROI_LEVELS:
            h = roi_hours(lvl, production_speed=ps)
            if not math.isfinite(h):
                h = 0.0
            pts.append(h)
            y_max = max(y_max, h)
        series[f"production_speed {ps}"] = pts
    return _xychart(
        f"{REFERENCE_BUILDING} — ROI Payback (h, Slot {NEUTRAL_BALANCE_SLOT})",
        x_labels,
        series,
        y_max,
    )


def _speed_sweep_research() -> str:
    lvl, lab = 20, 10
    rows = []
    for spd in RESEARCH_SPEEDS_FULL:
        sec = research_seconds("energy_tech", lvl, lab=lab, research_speed=spd)
        rows.append([str(int(spd) if spd == int(spd) else spd), fmt_duration(sec), f"{sec / 3600:.2f}h"])
    return _md_table(
        ["research_speed", "Dauer L20 Energie (Lab 10)", "Stunden"],
        rows,
    )


def _speed_sweep_build() -> str:
    lvl = 20
    rows = []
    for spd in BUILD_SPEEDS_FULL:
        sec = build_seconds(lvl, build_speed=spd)
        rows.append([str(int(spd) if spd == int(spd) else spd), fmt_duration(sec), f"{sec / 3600:.2f}h"])
    return _md_table(
        ["build_speed", f"Dauer {REFERENCE_BUILDING} L{lvl}", "Stunden"],
        rows,
    )


def _speed_sweep_production() -> str:
    lvl = 20
    rows = []
    for ps in PRODUCTION_SPEEDS_FULL:
        h = roi_hours(lvl, production_speed=ps)
        rows.append([str(ps), fmt_roi(h), f"{h:.1f}h" if math.isfinite(h) else "∞"])
    return _md_table(
        ["production_speed", f"ROI {REFERENCE_BUILDING} L{lvl}", "Stunden"],
        rows,
    )


def _fleet_table() -> str:
    rows = []
    for dist in FLEET_DISTANCES:
        for fs in FLEET_SPEEDS:
            # Peaceful missions use fleet_speed_peaceful admin key.
            admin_mult = fs  # benchmark: direct multiplier on flight formula
            sec = calculate_flight_seconds(
                dist,
                FLEET_REFERENCE_SHIP_SPEED,
                100,
                admin_speed_multiplier=admin_mult,
            )
            rows.append([str(dist), str(int(fs) if fs == int(fs) else fs), fmt_duration(sec)])
    return _md_table(
        ["Distanz", "fleet_speed (×)", f"Flugzeit (speed {FLEET_REFERENCE_SHIP_SPEED}, 100%)"],
        rows,
    )


def _alpha_verdict() -> str:
    """Data-driven recommendation block."""
    # Key probe points
    probes = {
        "research_s1_l30": research_seconds("energy_tech", 30, lab=20, research_speed=1) / 3600,
        "research_s25_l30": research_seconds("energy_tech", 30, lab=20, research_speed=25) / 3600,
        "research_s100_l30": research_seconds("energy_tech", 30, lab=20, research_speed=100) / 3600,
        "build_s5_l20": build_seconds(20, build_speed=5) / 3600,
        "build_s10_l20": build_seconds(20, build_speed=10) / 3600,
        "roi_ps1_l20": roi_hours(20, production_speed=1),
        "roi_ps2_l20": roi_hours(20, production_speed=2),
    }
    current = {
        "production_speed": float(DEFAULT_GAME_SETTINGS.get("production_speed", 1)),
        "build_speed": float(DEFAULT_GAME_SETTINGS.get("build_speed", 1)),
        "research_speed": float(DEFAULT_GAME_SETTINGS.get("research_speed", 1)),
        "fleet_speed_peaceful": float(DEFAULT_GAME_SETTINGS.get("fleet_speed_peaceful", 1)),
    }

    return f"""## Empfehlung (Alpha)

Berechnet mit kanonischen Formeln (`EffectResolver`, GC-825/821). Referenzplanet: Slot {NEUTRAL_BALANCE_SLOT}.

### Leitfragen

| Frage | Datenpunkt | Einschätzung |
|-------|------------|--------------|
| Ist `research_speed = 1` spielbar? | Energie L30, Lab 20 → **{probes['research_s1_l30']:.1f} h** (~{probes['research_s1_l30']/24:.1f} d) | Technisch ja, für Alpha zu träge |
| Ist `research_speed = 100` zu schnell? | Gleiches Szenario → **{probes['research_s100_l30']:.2f} h** | Midgame-Forschung wird Trivialzeit — zu schnell für Progressionsgefühl |
| Ist `build_speed = 10` sinnvoll? | `{REFERENCE_BUILDING}` L20 → **{fmt_duration(int(probes['build_s10_l20']*3600))}** | Gute Alpha-Fluidität ohne Instant-Bau |
| Ist `production_speed = 1` zu langsam? | ROI L20 → **{fmt_roi(probes['roi_ps1_l20'])}** | Passt zu GC-821 Mine-Balance — **nicht** anheben ohne Economy-Rebalance |
| Flotte | siehe Flugtabelle | `fleet_speed` 3 → Distanz 2000 ~{fmt_duration(calculate_flight_seconds(2000, FLEET_REFERENCE_SHIP_SPEED, 100, admin_speed_multiplier=3))} (speed {FLEET_REFERENCE_SHIP_SPEED}) |

### Aktuelle Defaults (`DEFAULT_GAME_SETTINGS`)

| Setting | Wert | Effekt |
|---------|-----:|--------|
| `production_speed` | {current['production_speed']} | ROI-Baseline |
| `build_speed` | {current['build_speed']} | Bau ~{100/current['build_speed']:.0f}% der Tabellen bei speed=1 |
| `research_speed` | {current['research_speed']} | Forschung ~{100/current['research_speed']:.0f}% der Tabellen bei speed=1 |
| `fleet_speed_peaceful` | {current['fleet_speed_peaceful']} | Friedliche Flüge |

### Vorschlag Alpha-Universe

```text
production_speed = 1
build_speed      = 8
research_speed   = 50
fleet_speed      = 3   (peaceful / war / holding einheitlich)
```

**Begründung**

- **production_speed = 1** — GC-821 Mine-ROI ist darauf kalibriert; Erhöhung verkürzt Payback linear und entwertet Upgrades.
- **build_speed = 8** — `{REFERENCE_BUILDING}` L20 in ~{fmt_duration(build_seconds(20, build_speed=8))}; L30 Gebäude bleiben spürbar, aber nicht frustrierend.
- **research_speed = 50** — Energie L30 {fmt_duration(research_seconds('energy_tech', 30, lab=20, research_speed=50))}; L10 {fmt_duration(research_seconds('energy_tech', 10, lab=5, research_speed=50))} — Alpha-taugliches Tempo ohne Instant-Forschung.
- **fleet_speed = 3** — Distanz 2000 {fmt_duration(calculate_flight_seconds(2000, FLEET_REFERENCE_SHIP_SPEED, 100, admin_speed_multiplier=3))}; Distanz 8000 {fmt_duration(calculate_flight_seconds(8000, FLEET_REFERENCE_SHIP_SPEED, 100, admin_speed_multiplier=3))} (Referenzschiff speed {FLEET_REFERENCE_SHIP_SPEED}).

Sweet-Spot-Band (aus Sweeps): `build_speed` 5–10, `research_speed` 25–100, `production_speed` 1, `fleet_speed` 2–5.
"""


def generate_markdown() -> str:
    parts: List[str] = [
        "# GC-829 — Universe Speed Benchmark",
        "",
        "> Automatisch generiert via `python scripts/universe_speed_benchmark.py` — **keine Frontend-Math**, nur kanonische Server-Formeln.",
        "",
        "## Formeln (Kurz)",
        "",
        "| Domäne | Owner | Formel |",
        "|--------|-------|--------|",
        "| Forschungszeit | `EffectResolver.get_research_time_seconds` | `anchor_hours × tier ÷ (build_speed × research_speed × lab_bonus × research_time_speed)` |",
        "| Bauzeit | `EffectResolver.get_build_time_seconds` | `BUILD_TIME_BASE × factor^(L-1) ÷ build_speed_effective` |",
        "| Produktion / ROI | `economy_balance.mine_upgrade_roi_hours` | `upgrade_cost ÷ Δprod/h × production_speed` |",
        "| Flugzeit | `fleet_calc.calculate_flight_seconds` | `(35000/speed) × √(dist/10) ÷ admin_fleet_speed` |",
        "",
        "**Annahmen Benchmark:** kein `buildtime_tech`, kein Klima/GD, `build_speed=1` in Forschungstabellen, `research_speed=1` in Bautabellen, progressive Lab-Spalte (`LAB_FOR_LEVEL`).",
        "",
        "## Speed-Sweeps (Überblick)",
        "",
        "### research_speed — Energieeffizienz L20, Lab 10",
        "",
        _speed_sweep_research(),
        "",
        "### build_speed — Ferronitmine L20",
        "",
        _speed_sweep_build(),
        "",
        "### production_speed — Ferronitmine ROI L20 (Slot 9)",
        "",
        _speed_sweep_production(),
        "",
        "## Forschung — Tabellen",
        "",
        "Level-Spalte mit progressivem Labor (siehe `LAB_FOR_LEVEL` im Script).",
        "",
    ]

    for tech_key, title in RESEARCH_TECHS:
        parts.append(_research_table(tech_key, title))
        parts.append(_lab_effect_table(tech_key, title, level=20))

    parts.extend(
        [
            "## Diagramme",
            "",
            "### 1 — Forschungszeit nach Level (Energieeffizienz)",
            "",
            _research_chart("energy_tech", "Energieeffizienz"),
            "",
            "### 2 — Bauzeit nach Level (Ferronitmine)",
            "",
            _build_chart(),
            "",
            "### 3 — Mine-ROI nach Level",
            "",
            _roi_chart(),
            "",
            "## Flotte — `fleet_speed` (Referenz)",
            "",
            f"Schiff-Geschwindigkeit {FLEET_REFERENCE_SHIP_SPEED} (langsamer Frachter-Tier), 100% Reisegeschwindigkeit, Admin-Multiplikator auf `fleet_calc`.",
            "",
            _fleet_table(),
            "",
            _alpha_verdict(),
            "",
        ]
    )
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="GC-829 universe speed benchmark")
    parser.add_argument("--stdout", action="store_true", help="Print markdown to stdout")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "UNIVERSE_SPEED_BENCHMARK.md",
        help="Output markdown path",
    )
    args = parser.parse_args()

    md = generate_markdown()
    if args.stdout:
        print(md)
    else:
        args.out.write_text(md, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
