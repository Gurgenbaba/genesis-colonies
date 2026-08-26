#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


template = ROOT / "templates" / "planet_evolution.html"
old_empty = '''        {% else %}
        <p class="pe-zone-empty">{{ T("pe_research_empty", "Keine Forschung verfügbar — baue deinen Planeten weiter aus.") }}</p>
        {% endif %}
'''
new_empty = '''        {% else %}
        {% set pe_next_locked = rdx.locked[0] if rdx.locked else none %}
        <div class="pe-research-idle-guide">
          <p class="pe-zone-empty">{{ T("pe_research_empty", "Keine Forschung verfügbar — baue deinen Planeten weiter aus.") }}</p>
          {% if pe_next_locked %}
          <div class="pe-research-next-unlock">
            <span class="pe-research-next-kicker">{{ T("pe_research_later", "Später verfügbar") }}</span>
            <strong class="pe-research-next-name">{{ T(pe_next_locked.label_key, pe_next_locked.tech_key) }}</strong>
            {% if pe_next_locked.missing_human %}
            <ul class="pe-research-next-blockers">
              {% for line in pe_next_locked.missing_human[:2] %}
              <li>{{ line }}</li>
              {% endfor %}
            </ul>
            {% endif %}
          </div>
          {% endif %}
        </div>
        {% endif %}
'''
replace_once(template, old_empty, new_empty)

css = ROOT / "static" / "css" / "planet_evolution_clarity.css"
css_text = css.read_text(encoding="utf-8")
css_append = r'''

/* GC-PE-UX-03 — an idle research state must explain the next unlock instead
   of forcing the player to open the full locked-tech archive. */
.planet-evolution-page .pe-research-idle-guide {
  display: grid;
  gap: 0.52rem;
}

.planet-evolution-page .pe-research-idle-guide .pe-zone-empty {
  margin-bottom: 0;
}

.planet-evolution-page .pe-research-next-unlock {
  padding: 0.68rem 0.72rem;
  border: 1px solid rgba(var(--gc-id-rgb), 0.26);
  border-left: 2px solid var(--gc-primary);
  background: linear-gradient(90deg, rgba(var(--gc-id-rgb), 0.09), rgba(3, 15, 25, 0.34));
}

.planet-evolution-page .pe-research-next-kicker {
  display: block;
  margin-bottom: 0.16rem;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--gc-muted, #8499a8);
}

.planet-evolution-page .pe-research-next-name {
  display: block;
  color: var(--gc-primary);
  line-height: 1.3;
}

.planet-evolution-page .pe-research-next-blockers {
  margin: 0.42rem 0 0;
  padding-left: 1rem;
  display: grid;
  gap: 0.2rem;
  color: var(--gc-text-muted, #a9bdc9);
  font-size: 0.78rem;
  line-height: 1.32;
}

.planet-evolution-page .pe-research-next-blockers li::marker {
  color: var(--gc-primary);
}
'''
if "GC-PE-UX-03" in css_text:
    raise SystemExit("GC-PE-UX-03 CSS already present")
css.write_text(css_text.rstrip() + css_append.rstrip() + "\n", encoding="utf-8")

tests = ROOT / "tests" / "test_gc_pe_clarity.py"
test_text = tests.read_text(encoding="utf-8")
marker = "\ndef test_impact_locale_contract_has_exact_parity():\n"
if marker not in test_text:
    raise SystemExit("clarity test insertion anchor missing")
new_test = r'''

def test_idle_research_surfaces_next_locked_tech_requirements():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "planet_evolution_clarity.css").read_text(encoding="utf-8")

    assert "pe_next_locked = rdx.locked[0] if rdx.locked else none" in template
    assert "T(pe_next_locked.label_key, pe_next_locked.tech_key)" in template
    assert "pe_next_locked.missing_human[:2]" in template
    assert "pe-research-next-unlock" in template
    assert "pe-research-next-blockers" in css

'''
if "test_idle_research_surfaces_next_locked_tech_requirements" in test_text:
    raise SystemExit("GC-PE-UX-03 regression already present")
tests.write_text(test_text.replace(marker, new_test + marker, 1), encoding="utf-8")

print("GC-PE-UX-03 product patch applied")
