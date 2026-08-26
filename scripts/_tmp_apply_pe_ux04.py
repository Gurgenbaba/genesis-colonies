#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Dashboard: next-action consumes the already-normalized economy payload and
# carries the canonical research impact through to the decision card.
dashboard = ROOT / "game" / "planet_evolution" / "dashboard.py"
replace_once(
    dashboard,
    "    warnings: List[Dict[str, Any]],\n    mechanics: Dict[str, Any],\n",
    "    warnings: List[Dict[str, Any]],\n    economy: Dict[str, Any],\n",
)
replace_once(
    dashboard,
    '''        extra: Dict[str, Any] = {\n            "tech_key": tech_key,\n            "tech_label_key": first.get("label_key"),\n        }\n''',
    '''        extra: Dict[str, Any] = {\n            "tech_key": tech_key,\n            "tech_label_key": first.get("label_key"),\n            "impact": first.get("impact") or {"rows": [], "scopes": []},\n        }\n''',
)
replace_once(
    dashboard,
    '''    deficits = mechanics.get("import_deficits") or []\n    if deficits:\n        return _cta(\n            priority="economy",\n            title_key="pe_action_economy_title",\n            body_key="pe_action_economy_body",\n            cta_label_key="pe_action_economy_cta",\n            cta_target="economy",\n            cta_action="focus_section",\n            cta_highlight="pe-section-economy",\n        )\n''',
    '''    deficits = economy.get("deficits") or []\n    if deficits:\n        return _cta(\n            priority="economy",\n            title_key="pe_action_economy_title",\n            body_key="pe_action_economy_body",\n            cta_label_key="pe_action_economy_cta",\n            cta_target="economy",\n            cta_action="focus_section",\n            cta_highlight="pe-section-economy",\n            deficit=dict(deficits[0]),\n        )\n''',
)
replace_once(
    dashboard,
    "            warnings=warnings,\n            mechanics=mechanics,\n",
    "            warnings=warnings,\n            economy=economy,\n",
)

# Goal card: concrete actions show concrete evidence. The broad benefits
# explainer remains only for the neutral Explore fallback.
template = ROOT / "templates" / "planet_evolution.html"
old_benefits = '''          <button type="button"\n                  class="pe-goal-benefits-btn pe-info-trigger"\n                  aria-expanded="false"\n                  aria-controls="pe-goal-benefits-source">{{ T('pe_goal_benefits_btn', 'Was bringt mir das?') }}</button>\n          <div id="pe-goal-benefits-source" class="pe-goal-benefits-source" hidden>\n            <p class="pe-info-popover-title">{{ T('pe_goal_benefits_title', 'Was bringt Planet Evolution?') }}</p>\n            <ul class="pe-info-popover-bullets">\n              <li>{{ T('pe_goal_benefits_research', 'Planet-Techs sind die Hauptquelle für Planet-XP.') }}</li>\n              <li>{{ T('pe_goal_benefits_level', 'Mehr Planet-Level schalten Eigenschaften, Spezialisierungen und Policies frei.') }}</li>\n              <li>{{ T('pe_goal_benefits_traits', 'Neue Planet-Eigenschaften werden sichtbar und wirksam.') }}</li>\n              <li>{{ T('pe_goal_benefits_expansion', 'Expansion und Imperiums-Boni bauen auf dieser Progression auf.') }}</li>\n              <li>{{ T('pe_goal_benefits_activity', 'Expeditionen, Events und Discoveries geben Zusatz-XP.') }}</li>\n            </ul>\n          </div>\n'''
new_benefits = '''          {% if action.priority == 'research' and action.impact %}\n          <div class="pe-goal-context pe-goal-context--impact">\n            {{ pe_impact_contract(action.impact, true) }}\n          </div>\n          {% elif action.priority == 'economy' and action.deficit %}\n          <div class="pe-goal-context pe-goal-supply-evidence" title="{{ T('pe_warn_import_deficit', 'Import reicht nicht') }}">\n            <div class="pe-goal-supply-head">\n              <strong>{{ T(action.deficit.label_key, pe_humanize_key(action.deficit.resource_key)) }}</strong>\n              <span class="gc-mono">{{ action.deficit.pct|int }}%</span>\n            </div>\n            <div class="pe-goal-supply-meter" aria-hidden="true">\n              <span style="width: {{ action.deficit.pct|int }}%"></span>\n            </div>\n            <p class="pe-goal-supply-values gc-mono">{{ action.deficit.received|int }} / {{ action.deficit.required|int }}</p>\n          </div>\n          {% elif action.priority == 'explore' %}\n          <button type="button"\n                  class="pe-goal-benefits-btn pe-info-trigger"\n                  aria-expanded="false"\n                  aria-controls="pe-goal-benefits-source">{{ T('pe_goal_benefits_btn', 'Was bringt mir das?') }}</button>\n          <div id="pe-goal-benefits-source" class="pe-goal-benefits-source" hidden>\n            <p class="pe-info-popover-title">{{ T('pe_goal_benefits_title', 'Was bringt Planet Evolution?') }}</p>\n            <ul class="pe-info-popover-bullets">\n              <li>{{ T('pe_goal_benefits_research', 'Planet-Techs sind die Hauptquelle für Planet-XP.') }}</li>\n              <li>{{ T('pe_goal_benefits_level', 'Mehr Planet-Level schalten Eigenschaften, Spezialisierungen und Policies frei.') }}</li>\n              <li>{{ T('pe_goal_benefits_traits', 'Neue Planet-Eigenschaften werden sichtbar und wirksam.') }}</li>\n              <li>{{ T('pe_goal_benefits_expansion', 'Expansion und Imperiums-Boni bauen auf dieser Progression auf.') }}</li>\n              <li>{{ T('pe_goal_benefits_activity', 'Expeditionen, Events und Discoveries geben Zusatz-XP.') }}</li>\n            </ul>\n          </div>\n          {% endif %}\n'''
replace_once(template, old_benefits, new_benefits)

# Add small evidence blocks to the existing shell-owned PE stylesheet.
css = ROOT / "static" / "css" / "planet_evolution_clarity.css"
css_text = css.read_text(encoding="utf-8")
if "GC-PE-UX-04" in css_text:
    raise SystemExit("GC-PE-UX-04 CSS already present")
css_append = r'''

/* GC-PE-UX-04 — concrete next actions show concrete gameplay evidence. */
.planet-evolution-page .pe-goal-context {
  margin-top: 0.42rem;
}

.planet-evolution-page .pe-goal-context--impact .pe-impact-contract {
  margin: 0;
}

.planet-evolution-page .pe-goal-supply-evidence {
  padding: 0.62rem 0.7rem;
  border: 1px solid rgba(var(--gc-id-rgb), 0.28);
  border-left: 2px solid var(--gc-primary);
  background: rgba(3, 15, 25, 0.48);
}

.planet-evolution-page .pe-goal-supply-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.planet-evolution-page .pe-goal-supply-head strong {
  min-width: 0;
  color: var(--gc-primary);
}

.planet-evolution-page .pe-goal-supply-meter {
  height: 5px;
  margin-top: 0.42rem;
  overflow: hidden;
  border: 1px solid rgba(var(--gc-id-rgb), 0.24);
  background: rgba(2, 11, 18, 0.72);
}

.planet-evolution-page .pe-goal-supply-meter > span {
  display: block;
  height: 100%;
  min-width: 2px;
  background: var(--gc-primary);
}

.planet-evolution-page .pe-goal-supply-values {
  margin: 0.32rem 0 0;
  color: var(--gc-text-muted, #a9bdc9);
  font-size: 0.76rem;
  text-align: right;
}
'''
css.write_text(css_text.rstrip() + css_append.rstrip() + "\n", encoding="utf-8")

# Dashboard regression: canonical impact passthrough + normalized deficit passthrough.
dash_tests = ROOT / "tests" / "test_planet_evolution_dashboard.py"
test_text = dash_tests.read_text(encoding="utf-8")
old_arg = '        mechanics={"import_deficits": []},\n'
arg_count = test_text.count(old_arg)
if arg_count != 3:
    raise SystemExit(f"expected 3 _next_action mechanics test args, found {arg_count}")
test_text = test_text.replace(old_arg, '        economy={"deficits": []},\n')
old_rec = '''            "recommended": [{"tech_key": "industry_t1_automation", "label_key": "pe_industry_t1_automation"}],\n'''
new_rec = '''            "recommended": [{\n                "tech_key": "industry_t1_automation",\n                "label_key": "pe_industry_t1_automation",\n                "impact": {"current": 0, "after": 1, "rows": [{"label_key": "pe_impact_effect_research_speed", "value": "+15%"}], "scopes": ["pe_impact_scope_research"]},\n            }],\n'''
if test_text.count(old_rec) != 1:
    raise SystemExit("research recommendation test anchor missing")
test_text = test_text.replace(old_rec, new_rec, 1)
old_assert = '    assert action["tech_key"] == "industry_t1_automation"\n\n\n'
new_assert = '''    assert action["tech_key"] == "industry_t1_automation"\n    assert action["impact"]["current"] == 0\n    assert action["impact"]["after"] == 1\n    assert action["impact"]["rows"][0]["value"] == "+15%"\n\n\ndef test_next_action_economy_uses_normalized_deficit_evidence():\n    deficit = {\n        "resource_key": "refined_ferronit",\n        "label_key": "resource_refined_ferronit",\n        "received": 30.0,\n        "required": 100.0,\n        "pct": 30,\n        "status": "critical",\n    }\n    action = _next_action(\n        planet={"specialization_key": "forge_world"},\n        level=12,\n        active_event=None,\n        eligible_specs=[],\n        research_ux={"recommended": [], "queue_has_room": True, "active": []},\n        warnings=[],\n        economy={"deficits": [deficit]},\n    )\n    assert action["priority"] == "economy"\n    assert action["cta_target"] == "economy"\n    assert action["deficit"] == deficit\n    assert action["deficit"]["pct"] == 30\n\n\n'''
if test_text.count(old_assert) != 1:
    raise SystemExit("research assertion insertion anchor missing")
test_text = test_text.replace(old_assert, new_assert, 1)
dash_tests.write_text(test_text, encoding="utf-8")

# Clarity source contract: generic benefits only Explore; contextual evidence for
# Research and Economy is visible directly in the goal card.
clarity = ROOT / "tests" / "test_gc_pe_clarity.py"
clarity_text = clarity.read_text(encoding="utf-8")
marker = "\ndef test_impact_locale_contract_has_exact_parity():\n"
if marker not in clarity_text:
    raise SystemExit("clarity test insertion anchor missing")
new_test = r'''

def test_goal_card_uses_contextual_evidence_before_concrete_actions():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "planet_evolution_clarity.css").read_text(encoding="utf-8")

    assert "action.priority == 'research' and action.impact" in template
    assert "pe_impact_contract(action.impact, true)" in template
    assert "action.priority == 'economy' and action.deficit" in template
    assert "action.deficit.received|int" in template
    assert "action.deficit.required|int" in template
    assert "action.deficit.pct|int" in template
    assert "action.priority == 'explore'" in template
    explore_guard = template.index("{% elif action.priority == 'explore' %}")
    benefits = template.index("pe-goal-benefits-btn", explore_guard)
    assert benefits > explore_guard
    assert "pe-goal-supply-meter" in css

'''
if "test_goal_card_uses_contextual_evidence_before_concrete_actions" in clarity_text:
    raise SystemExit("GC-PE-UX-04 clarity regression already exists")
clarity.write_text(clarity_text.replace(marker, new_test + marker, 1), encoding="utf-8")

print("GC-PE-UX-04 product patch applied")
