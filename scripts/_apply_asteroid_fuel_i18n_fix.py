#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for rel in (
    "templates/partials/galaxy_asteroid_board.html",
    "templates/partials/galaxy_asteroid_block.html",
):
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if ">⛽ — BZ</span>" not in text:
        raise SystemExit(f"fuel placeholder not found in {rel}")
    path.write_text(text.replace(">⛽ — BZ</span>", ">⛽ —</span>", 1), encoding="utf-8")

path = ROOT / "static/js/galaxy-quick-action.js"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '''      const details = `⛽ ${formatNumber(fuelCost)} BZ · 🚀 ${formatNumber(count)} HR · ⏱ ${this.formatAsteroidFlightDuration(flightSeconds)}`;\n      const missing = Math.max(0, fuelCost - fuelAvailable);\n      const full = missing > 0\n        ? `${details} · ⚠ ${formatNumber(missing)} BZ`\n        : details;''',
    '''      const short = `⛽ ${formatNumber(fuelCost)} BZ · 🚀 ${formatNumber(count)} HR · ⏱ ${this.formatAsteroidFlightDuration(flightSeconds)}`;\n      const missing = Math.max(0, fuelCost - fuelAvailable);\n      const full = missing > 0\n        ? `${short} · ⚠ ${formatNumber(missing)} BZ`\n        : short;''',
    1,
)
old = '''      line.textContent = `⛽ ${formatNumber(fuelCost)} BZ${missing > 0 ? " ⚠" : ""}`;'''
new = '''      const fuelIcon = String.fromCodePoint(0x26fd);\n      line.textContent = `${fuelIcon} ${formatNumber(fuelCost)}${missing > 0 ? " ⚠" : ""}`;'''
if old not in text:
    raise SystemExit("visible fuel line not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

path = ROOT / "tests/test_asteroid_value_preview.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'assert "data-galaxy-asteroid-flight-preview>⛽ — BZ</span>" in board',
    'assert "data-galaxy-asteroid-flight-preview>⛽ —</span>" in board',
    1,
)
text = text.replace(
    'assert "data-galaxy-asteroid-flight-preview>⛽ — BZ</span>" in block',
    'assert "data-galaxy-asteroid-flight-preview>⛽ —</span>" in block',
    1,
)
old = '''    assert 'line.textContent = `⛽ ${formatNumber(fuelCost)} BZ${missing > 0 ? " ⚠" : ""}`;' in js'''
new = '''    assert "const fuelIcon = String.fromCodePoint(0x26fd);" in js\n    assert 'line.textContent = `${fuelIcon} ${formatNumber(fuelCost)}${missing > 0 ? " ⚠" : ""}`;' in js'''
if old not in text:
    raise SystemExit("fuel line test assertion not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

print("asteroid fuel i18n cleanup applied")
