#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Explicit server-rendered state for the compact research layout.
template = ROOT / "templates" / "planet_evolution.html"
replace_once(
    template,
    '    <div class="pe-core-row">',
    '    <div class="pe-core-row{% if not pe_visible_tech_cards %} pe-core-row--research-idle{% endif %}">',
)

# 2) Shell-owned stylesheet: must survive PJAX navigation because only #main-content is swapped.
base = ROOT / "templates" / "base.html"
style_anchor = '  <link rel="stylesheet" href="{{ url_for(\'static\', filename=\'style.css\') }}?v={{ GC_ASSET_VERSION }}">\n'
style_link = (
    style_anchor
    + '  {# GC-PE-UX-02: shell-owned so Planet Evolution stays styled across PJAX navigation. #}\n'
    + '  <link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/planet_evolution_clarity.css\') }}?v={{ GC_ASSET_VERSION }}">\n'
)
replace_once(base, style_anchor, style_link)

# 3) Page-specific overrides, intentionally loaded after the global stylesheet.
css = ROOT / "static" / "css" / "planet_evolution_clarity.css"
css.write_text(r'''/* GC-PE-UX-02 — decision-first Planet Evolution layout.
   Shell-owned by base.html so the rules are present after PJAX navigation. */

.planet-evolution-page .pe-core-row {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(260px, 0.82fr);
  grid-template-areas: "goal tech";
  align-items: start;
  gap: 12px;
}

.planet-evolution-page .pe-zone--goal {
  grid-area: goal;
  min-width: 0;
  border-color: rgba(255, 190, 72, 0.56);
  box-shadow: 0 0 22px rgba(255, 170, 40, 0.08);
}

.planet-evolution-page .pe-zone--tech {
  grid-area: tech;
  min-width: 0;
}

/* When there is nothing actionable in Research, do not let an empty state
   compete with the player's actual next move. */
.planet-evolution-page .pe-core-row--research-idle {
  grid-template-columns: minmax(0, 1.58fr) minmax(235px, 0.42fr);
}

.planet-evolution-page .pe-core-row--research-idle .pe-zone--tech {
  align-self: start;
}

.planet-evolution-page .pe-core-row--research-idle .pe-zone--tech .pe-zone-head {
  padding-bottom: 0.48rem;
}

.planet-evolution-page .pe-core-row--research-idle .pe-zone-empty {
  min-height: 0;
  margin: 0.42rem 0 0.28rem;
  padding: 0.72rem 0.78rem;
  border: 1px dashed rgba(88, 218, 239, 0.28);
  background: rgba(3, 15, 25, 0.52);
  line-height: 1.35;
}

.planet-evolution-page .pe-core-row--research-idle .pe-research-later {
  margin-top: 0.36rem;
}

/* The goal is the decision card, not a secondary info box. Keep its content
   dense enough that the primary CTA remains above the persistent footer. */
.planet-evolution-page .pe-zone--goal .pe-zone-head {
  padding-bottom: 0.5rem;
}

.planet-evolution-page .pe-goal-body {
  padding-top: 0.68rem;
  padding-bottom: 0.35rem;
}

.planet-evolution-page .pe-goal-kicker {
  margin: 0 0 0.22rem;
}

.planet-evolution-page .pe-goal-text {
  margin: 0.18rem 0 0.42rem;
  line-height: 1.38;
}

.planet-evolution-page .pe-goal-benefits-btn {
  margin-top: 0.2rem;
}

.planet-evolution-page .pe-goal-unlock,
.planet-evolution-page .pe-goal-xp-line {
  margin-top: 0.22rem;
  margin-bottom: 0.22rem;
}

.planet-evolution-page .pe-goal-events {
  margin-top: 0.42rem;
}

.planet-evolution-page .pe-goal-cta {
  width: 100%;
  min-height: 38px;
  margin-top: 0.58rem;
}

/* 1080p desktop density pass: keep the holographic identity, but give the
   actual decision row enough vertical room to be visible at the same time. */
@media (min-width: 1180px) and (min-height: 820px) {
  .planet-evolution-page .pe-hero-monolith {
    margin-bottom: 10px;
  }

  .planet-evolution-page .pe-theater-head {
    padding-top: 0.58rem;
    padding-bottom: 0.38rem;
  }

  .planet-evolution-page .pe-theater-stage {
    min-height: 286px;
    padding-top: 2px;
    padding-bottom: 0;
  }

  .planet-evolution-page .pe-hero-visual-col,
  .planet-evolution-page .pe-holo-stage {
    min-height: 266px;
  }

  .planet-evolution-page .pe-hero-visual {
    width: min(100%, 286px);
    min-height: 266px;
    height: 266px;
  }

  .planet-evolution-page .pe-theater-foot {
    padding-top: 0.42rem;
    padding-bottom: 0.48rem;
    gap: 0.42rem;
  }

  .planet-evolution-page .pe-xp-labels {
    margin-bottom: 0.22rem;
  }
}

/* At narrower shell widths the two decision zones stack, but the goal remains
   first so the visual hierarchy stays identical on tablet/mobile. */
@media (max-width: 1100px) {
  .planet-evolution-page .pe-core-row,
  .planet-evolution-page .pe-core-row--research-idle {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "goal"
      "tech";
  }
}

@media (max-width: 720px) {
  .planet-evolution-page .pe-core-row {
    gap: 9px;
  }

  .planet-evolution-page .pe-goal-body {
    padding-top: 0.55rem;
  }
}
''', encoding="utf-8")

# 4) Source regression: decision hierarchy + PJAX-safe asset ownership.
tests = ROOT / "tests" / "test_gc_pe_clarity.py"
text = tests.read_text(encoding="utf-8")
marker = "\ndef test_impact_locale_contract_has_exact_parity():\n"
if marker not in text:
    raise SystemExit("clarity test insertion anchor missing")
new_test = r'''

def test_planet_evolution_decision_first_layout_is_shell_owned():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "planet_evolution_clarity.css").read_text(encoding="utf-8")

    assert "pe-core-row--research-idle" in template
    assert "css/planet_evolution_clarity.css" in base
    assert 'grid-template-areas: "goal tech"' in css
    assert ".pe-core-row--research-idle" in css
    assert "grid-template-columns: minmax(0, 1.58fr)" in css
    assert 'grid-template-areas:\n      "goal"\n      "tech"' in css
    assert ".pe-goal-cta" in css

'''
if "test_planet_evolution_decision_first_layout_is_shell_owned" in text:
    raise SystemExit("clarity layout regression already exists")
tests.write_text(text.replace(marker, new_test + marker, 1), encoding="utf-8")

print("GC-PE-UX-02 product patch applied")
