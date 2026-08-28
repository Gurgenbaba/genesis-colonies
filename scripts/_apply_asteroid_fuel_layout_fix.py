#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 1) Board: reserve the fuel slot from first paint so hover can never change geometry.
path = ROOT / "templates/partials/galaxy_asteroid_board.html"
text = path.read_text(encoding="utf-8")
needle = '''                {% if harvest_locked %}data-harvest-locked="1"{% endif %}>\n            <button type="button"'''
replacement = '''                {% if harvest_locked %}data-harvest-locked="1"{% endif %}>\n            <span class="galaxy-asteroid-board-fuel gc-mono"\n                  data-galaxy-asteroid-flight-preview>⛽ — BZ</span>\n            <button type="button"'''
if needle not in text:
    raise SystemExit("board harvest wrapper insertion point not found")
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding="utf-8")

# 2) Slot inspector: same rule — fixed preview slot, no DOM insertion on hover.
path = ROOT / "templates/partials/galaxy_asteroid_block.html"
text = path.read_text(encoding="utf-8")
needle = '''  </dl>\n  <button type="button"'''
replacement = '''  </dl>\n  <span class="galaxy-asteroid-inline-fuel gc-mono"\n        data-galaxy-asteroid-flight-preview>⛽ — BZ</span>\n  <button type="button"'''
if needle not in text:
    raise SystemExit("asteroid block preview insertion point not found")
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding="utf-8")

# 3) JS: visible row shows ONLY fuel. HR/time remain in the tooltip.
#    Never create a visible element dynamically: absent slot => tooltip-only.
path = ROOT / "static/js/galaxy-quick-action.js"
text = path.read_text(encoding="utf-8")
old = '''      const short = `⛽ ${formatNumber(fuelCost)} BZ · 🚀 ${formatNumber(count)} HR · ⏱ ${this.formatAsteroidFlightDuration(flightSeconds)}`;\n      const missing = Math.max(0, fuelCost - fuelAvailable);\n      const full = missing > 0\n        ? `${short} · ⚠ ${formatNumber(missing)} BZ`\n        : short;\n\n      const trigger = wrap.querySelector("[data-galaxy-ring-asteroid-recycle]");\n      if (trigger) {\n        trigger.title = full;\n        trigger.setAttribute("aria-description", full);\n      }\n\n      // Ring markers are intentionally tiny: keep their preview in the native\n      // tooltip. Board rows and the slot inspector get a compact visible line.\n      if (wrap.classList.contains("galaxy-ring-asteroid-wrap")) return;\n      let line = wrap.querySelector("[data-galaxy-asteroid-flight-preview]");\n      if (!line) {\n        line = document.createElement("span");\n        line.className = "galaxy-asteroid-flight-preview hint gc-mono";\n        line.setAttribute("data-galaxy-asteroid-flight-preview", "");\n        if (trigger) wrap.insertBefore(line, trigger);\n        else wrap.appendChild(line);\n      }\n      line.textContent = full;\n      line.classList.toggle("is-blocked", missing > 0);'''
new = '''      const details = `⛽ ${formatNumber(fuelCost)} BZ · 🚀 ${formatNumber(count)} HR · ⏱ ${this.formatAsteroidFlightDuration(flightSeconds)}`;\n      const missing = Math.max(0, fuelCost - fuelAvailable);\n      const full = missing > 0\n        ? `${details} · ⚠ ${formatNumber(missing)} BZ`\n        : details;\n\n      const trigger = wrap.querySelector("[data-galaxy-ring-asteroid-recycle]");\n      if (trigger) {\n        trigger.title = full;\n        trigger.setAttribute("aria-description", full);\n      }\n\n      // Ring markers stay tooltip-only. Board/inspector slots are present from\n      // first paint so preview updates can never cause a layout shift.\n      if (wrap.classList.contains("galaxy-ring-asteroid-wrap")) return;\n      const line = wrap.querySelector("[data-galaxy-asteroid-flight-preview]");\n      if (!line) return;\n      line.textContent = `⛽ ${formatNumber(fuelCost)} BZ${missing > 0 ? " ⚠" : ""}`;\n      line.classList.toggle("is-blocked", missing > 0);'''
if old not in text:
    raise SystemExit("asteroid preview render block not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

# 4) Regression contract: fixed slot in markup, no dynamic preview insertion,
#    visible content is fuel-only while server preview remains canonical.
path = ROOT / "tests/test_asteroid_value_preview.py"
text = path.read_text(encoding="utf-8")
needle = '''    assert "calculate_fuel_cost" not in js\n'''
replacement = '''    assert "calculate_fuel_cost" not in js\n\n\ndef test_galaxy_asteroid_fuel_preview_has_stable_reserved_layout_slot():\n    root = Path(__file__).resolve().parents[1]\n    js = (root / "static/js/galaxy-quick-action.js").read_text(encoding="utf-8")\n    board = (root / "templates/partials/galaxy_asteroid_board.html").read_text(encoding="utf-8")\n    block = (root / "templates/partials/galaxy_asteroid_block.html").read_text(encoding="utf-8")\n\n    assert "data-galaxy-asteroid-flight-preview>⛽ — BZ</span>" in board\n    assert "data-galaxy-asteroid-flight-preview>⛽ — BZ</span>" in block\n    assert 'if (!line) return;' in js\n    assert 'line.textContent = `⛽ ${formatNumber(fuelCost)} BZ${missing > 0 ? " ⚠" : ""}`;' in js\n    assert 'line = document.createElement("span")' not in js\n'''
if needle not in text:
    raise SystemExit("test insertion point not found")
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding="utf-8")

print("asteroid fuel preview layout fix applied")
