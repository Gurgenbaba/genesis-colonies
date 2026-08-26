from __future__ import annotations

from pathlib import Path
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/gc-pe-clarity-ui-apply.yml"


def extract_here_doc(start_marker: str, end_marker: str) -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    active = False
    for line in lines:
        stripped = line.strip()
        if not active and start_marker in stripped:
            active = True
            continue
        if active and stripped == end_marker:
            break
        if active:
            out.append(line[10:] if line.startswith("          ") else line)
    if not out:
        raise SystemExit(f"could not extract {start_marker}")
    return "\n".join(out) + "\n"


apply_src = extract_here_doc("cat > /tmp/apply_pe_clarity_ui.py <<'PY'", "PY")
start = apply_src.index("# Crisis clarity lives above decisions in the goal panel.")
end = apply_src.index("# Scoped square UI; no global geometry changes.")

middle = textwrap.dedent("""
# Crisis clarity: insert into the current goal body without disturbing the next-step copy.
old='''        <div class="pe-goal-body">\n'''
crisis=old+'''      {% set crisis = dash.crisis_ux if dash.crisis_ux is defined else {} %}\n      {% if crisis.active %}\n      <section class="pe-crisis-clarity" aria-label="{{ T('pe_crisis_clarity_title', 'Aktive Krise') }}">\n        <div class="pe-crisis-clarity-head">\n          <strong>{{ T('pe_crisis_clarity_title', 'Aktive Krise') }}</strong>\n          <span>{{ T('pe_crisis_clarity_body', 'Diese Zustände verändern den Planeten, bis ihre Erholung abgeschlossen ist.') }}</span>\n        </div>\n        <ul class="pe-crisis-list">\n          {% for failure in crisis.failures %}\n          <li>\n            <strong>{{ T('pe_failure_' ~ failure.failure_key, pe_humanize_key(failure.failure_key)) }}</strong>\n            {% if failure.remaining_seconds is not none %}<span>{{ T('pe_impact_recovery', 'Erholung') }}: {{ render_prog_duration(failure.remaining_seconds) }}</span>{% endif %}\n          </li>\n          {% endfor %}\n        </ul>\n        {{ pe_impact_contract({'rows': crisis.rows, 'scopes': crisis.scopes}, true) }}\n        <p class="pe-crisis-recovery-hint">{{ T('pe_crisis_recovery_hint', 'Nach Ablauf der Erholung wird der Krisenzustand automatisch neu bewertet.') }}</p>\n      </section>\n      {% endif %}\n'''
if src.count(old)!=1: raise SystemExit(f'crisis UI anchor={src.count(old)}')
src=src.replace(old,crisis,1)

# Event choices: preserve the live JS hook and show exact impact before click.
old='''              <div class="pe-event-actions pe-goal-event-actions" id="pe-event-choices" data-event-id="{{ ps.active_event.id }}" data-planet-id="{{ ps.planet_id }}">\n                {% for c in ps.active_event.choices or [] %}\n                <button type="button" class="gc-btn gc-btn-primary gc-btn-sm pe-event-choice-btn" data-choice-key="{{ c.key }}">{{ T('pe_event_choice_' ~ c.key, c.key) }}</button>\n                {% endfor %}\n              </div>\n'''
new='''              <div class="pe-event-actions pe-goal-event-actions pe-event-choice-grid" id="pe-event-choices" data-event-id="{{ ps.active_event.id }}" data-planet-id="{{ ps.planet_id }}">\n                {% for c in ps.active_event.choices or [] %}\n                <article class="pe-event-choice-card">\n                  <h4>{{ T('pe_event_choice_' ~ c.key, pe_humanize_key(c.key)) }}</h4>\n                  {{ pe_impact_contract(c.impact, true) }}\n                  <button type="button" class="gc-btn gc-btn-primary gc-btn-sm pe-event-choice-btn" data-choice-key="{{ c.key }}">{{ T('pe_event_choice_commit', 'Entscheidung ausführen') }}</button>\n                </article>\n                {% endfor %}\n              </div>\n'''
if src.count(old)!=1: raise SystemExit(f'event choice anchor={src.count(old)}')
src=src.replace(old,new,1)

# Policy options: preserve planet/slot/policy JS data while showing impact first.
old='''              {% for opt in slot.options if opt.eligible %}\n              <button type="button" class="gc-btn gc-btn-sm pe-policy-btn {% if slot.active and slot.active.policy_key == opt.policy_key %}gc-btn-primary{% else %}gc-btn-secondary{% endif %}"\n                      data-planet-id="{{ ps.planet_id }}" data-slot="{{ slot.slot }}" data-policy-key="{{ opt.policy_key }}"\n                      {% if slot.active and slot.active.policy_key == opt.policy_key %}disabled{% endif %}>{{ T(opt.label_key, opt.policy_key) }}</button>\n              {% endfor %}\n'''
new='''              {% for opt in slot.options if opt.eligible %}\n              <article class="pe-policy-option-card{% if slot.active and slot.active.policy_key == opt.policy_key %} pe-policy-option-card--active{% endif %}">\n                <h4>{{ T(opt.label_key, pe_humanize_key(opt.policy_key)) }}</h4>\n                {{ pe_impact_contract(opt.impact, true) }}\n                <button type="button" class="gc-btn gc-btn-sm pe-policy-btn {% if slot.active and slot.active.policy_key == opt.policy_key %}gc-btn-primary{% else %}gc-btn-secondary{% endif %}"\n                        data-planet-id="{{ ps.planet_id }}" data-slot="{{ slot.slot }}" data-policy-key="{{ opt.policy_key }}"\n                        {% if slot.active and slot.active.policy_key == opt.policy_key %}disabled{% endif %}>\n                  {% if slot.active and slot.active.policy_key == opt.policy_key %}{{ T('pe_impact_current', 'Aktuell') }}{% else %}{{ T('pe_policy_activate', 'Policy aktivieren') }}{% endif %}\n                </button>\n              </article>\n              {% endfor %}\n'''
if src.count(old)!=1: raise SystemExit(f'policy option anchor={src.count(old)}')
src=src.replace(old,new,1)

# Ascension: enrich the current data-hooked card without changing lifecycle ownership.
old='''            <h4 class="gc-ascension-card-title">{{ T(card.label_key, card.ascension_key) }}</h4>\n'''
new='''            <h4 class="gc-ascension-card-title">{{ T(card.label_key, pe_humanize_key(card.ascension_key)) }}</h4>\n            {{ pe_impact_contract(card.impact, true) }}\n'''
if src.count(old)!=1: raise SystemExit(f'ascension anchor={src.count(old)}')
src=src.replace(old,new,1)
template.write_text(src,encoding='utf-8')

""")

apply_src = apply_src[:start] + middle + apply_src[end:]

locale_old = '''    dup=expected.intersection(parsed)\n    if dup: raise SystemExit(f'locale keys already exist in {lang}: {sorted(dup)[:3]}')\n    idx=text.rfind('\\n}')\n    if idx<0: raise SystemExit(f'bad locale tail {lang}')\n    insertion=',\\n' + ',\\n'.join('  '+json.dumps(k,ensure_ascii=False)+': '+json.dumps(v,ensure_ascii=False) for k,v in data.items())\n    p.write_text(text[:idx]+insertion+text[idx:],encoding='utf-8')\n'''
locale_new = '''    existing=expected.intersection(parsed)\n    if any(not str(parsed[k]).strip() for k in existing):\n        raise SystemExit(f'empty existing locale value in {lang}')\n    missing=[k for k in data if k not in parsed]\n    if not missing:\n        continue\n    idx=text.rfind('\\n}')\n    if idx<0: raise SystemExit(f'bad locale tail {lang}')\n    insertion=',\\n' + ',\\n'.join('  '+json.dumps(k,ensure_ascii=False)+': '+json.dumps(data[k],ensure_ascii=False) for k in missing)\n    p.write_text(text[:idx]+insertion+text[idx:],encoding='utf-8')\n'''
if apply_src.count(locale_old) != 1:
    raise SystemExit(f"locale writer anchor={apply_src.count(locale_old)}")
apply_src = apply_src.replace(locale_old, locale_new, 1)

apply_path = ROOT / "scripts/_tmp_pe_clarity_ui_generated.py"
apply_path.write_text(apply_src, encoding="utf-8")
subprocess.run(["python", str(apply_path)], cwd=ROOT, check=True)

extra_tests = extract_here_doc("cat >> tests/test_gc_pe_clarity.py <<'PYTEST'", "PYTEST")
with (ROOT / "tests/test_gc_pe_clarity.py").open("a", encoding="utf-8") as handle:
    handle.write(extra_tests)
