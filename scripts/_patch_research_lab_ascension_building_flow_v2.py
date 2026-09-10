from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}: got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


research = ROOT / "templates/research.html"
replace_once(
    research,
    '''        {% if next_unlock.kind == 'ascension' and next_unlock.ready %}
          {% set tribute_m = network.next_tribute_metal if network.next_tribute_metal is defined else 0 %}
          {% set tribute_c = network.next_tribute_crystal if network.next_tribute_crystal is defined else 0 %}
          <button type="button" class="gc-btn gc-bld-evo-btn" data-research-network-ascend>
            {{ T('research_network_ascend', rank=next_unlock.roman) }}
          </button>
        {% endif %}
''',
    '''        {% if next_unlock.kind == 'ascension' and next_unlock.ready %}
          <div class="hint">{{ T('research_network_ready', rank=next_unlock.roman) }}</div>
        {% endif %}
''',
)
replace_once(
    research,
    '''{% block extra_scripts %}
{{ super() }}
<script src="{{ url_for('static', filename='js/pages/research_network.js') }}?v={{ GC_ASSET_VERSION }}"></script>
{% endblock %}''',
    '''{% block extra_scripts %}
{{ super() }}
{% endblock %}''',
)

buildings = ROOT / "templates/buildings.html"
replace_once(
    buildings,
    '''          {% if building_type == 'research_lab' and b.research_lab_ascension is defined and b.research_lab_ascension %}
          <div class="gc-bld-evo-block" data-research-lab-ascension>
            <div class="gc-bld-evo-progress" role="status">
              <span class="gc-bld-evo-progress-label">{{ T('research_network_title') }}</span>
              <span class="gc-mono gc-bld-evo-progress-vals">{{ T('research_network_capacity', slots=b.research_queue_capacity) }}</span>
            </div>
            {% if (b.research_lab_ascension_rank|default(0)|int) > 0 %}
            <div class="gc-bld-evo-bonus gc-mono">
              {{ T('research_network_rank_speed', rank=b.research_lab_ascension_roman, pct=b.research_lab_ascension_speed_bonus_pct) }}
            </div>
            {% endif %}
            {% if b.research_lab_ascension_ready %}
            <div class="hint">{{ T('research_network_ready', rank=b.research_lab_next_roman) }}</div>
            {% elif (b.research_lab_next_rank|default(0)|int) > 0 %}
            <div class="hint">{{ T('research_network_requires', rank=b.research_lab_next_roman, level=b.research_lab_ascension_required_level) }}</div>
            {% endif %}
          </div>
          {% endif %}
''',
    '''          {% if building_type == 'research_lab' and b.research_lab_ascension is defined and b.research_lab_ascension %}
          {% set _lab_asc_rank = (b.research_lab_ascension_rank|default(0)|int) %}
          {% set _lab_asc_next = (b.research_lab_next_rank|default(0)|int) %}
          {% set _lab_asc_req = (b.research_lab_ascension_required_level|default(0)|int) %}
          {% set _lab_asc_progress = ([100, ((b.level|int) * 100 // _lab_asc_req)]|min) if _lab_asc_req > 0 else 100 %}
          <div class="gc-bld-evo-block" data-research-lab-ascension>
            <div class="gc-bld-evo-progress" role="status">
              <span class="gc-bld-evo-progress-label">{{ T('research_network_title') }}</span>
              {% if _lab_asc_next > 0 %}
              <span class="gc-mono gc-bld-evo-progress-vals">{{ b.level|fmt_int }} / {{ _lab_asc_req|fmt_int }}</span>
              {% else %}
              <span class="gc-mono gc-bld-evo-progress-vals">{{ T('research_network_capacity', slots=b.research_queue_capacity) }}</span>
              {% endif %}
            </div>
            {% if _lab_asc_next > 0 %}
            <div class="gc-bld-evo-bar" aria-hidden="true">
              <span class="gc-bld-evo-bar-fill" style="width: {{ _lab_asc_progress }}%;"></span>
            </div>
            {% endif %}
            <div class="gc-bld-evo-bonus gc-mono">
              {% if _lab_asc_rank > 0 %}
                {{ T('research_network_rank_speed', rank=b.research_lab_ascension_roman, pct=b.research_lab_ascension_speed_bonus_pct) }} ·
              {% endif %}
              {{ T('research_network_capacity', slots=b.research_queue_capacity) }}
            </div>
            {% if b.research_lab_ascension_ready %}
            <div class="hint">{{ T('research_network_ready', rank=b.research_lab_next_roman) }}</div>
            <button type="button"
                    class="gc-btn gc-bld-evo-btn"
                    data-research-lab-ascend
                    data-asc-name="{{ T('building_' ~ building_type) }}"
                    data-asc-rank="{{ b.research_lab_next_roman }}"
                    data-asc-required="{{ _lab_asc_req }}"
                    data-asc-tribute-metal="{{ b.research_lab_ascension_tribute_metal|fmt_int }}"
                    data-asc-tribute-crystal="{{ b.research_lab_ascension_tribute_crystal|fmt_int }}"
                    data-asc-benefit="{{ T('research_network_rank_speed', rank=b.research_lab_next_roman, pct=(b.research_lab_ascension_speed_bonus_pct|int + 2)) }} · {{ T('research_network_capacity', slots=(b.research_queue_capacity|int + 1)) }}">
              {{ T('research_network_ascend', rank=b.research_lab_next_roman) }}
            </button>
            {% elif _lab_asc_next > 0 %}
            <div class="hint">{{ T('research_network_requires', rank=b.research_lab_next_roman, level=_lab_asc_req) }}</div>
            {% endif %}
          </div>
          {% endif %}
''',
)

replace_once(
    buildings,
    '</div>\n\n<div id="gc-stellar-forge-modal"',
    '''</div>

<div id="gc-research-lab-ascension-confirm-modal"
     class="gc-player-card-modal gc-bld-evo-confirm-modal"
     hidden
     aria-hidden="true">
  <div class="gc-player-card-overlay" data-research-lab-ascension-cancel tabindex="-1"></div>
  <div class="gc-player-card-dialog gc-bld-evo-confirm-dialog"
       role="dialog"
       aria-modal="true"
       aria-labelledby="gc-research-lab-ascension-confirm-title">
    <header class="gc-player-card-head">
      <h2 id="gc-research-lab-ascension-confirm-title" class="gc-player-card-head-title">{{ T('research_network_title') }}</h2>
      <button type="button"
              class="gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close"
              data-research-lab-ascension-cancel
              aria-label="{{ T('close', 'Schließen') }}">×</button>
    </header>
    <div class="gc-player-card-body gc-bld-evo-confirm-body">
      <p class="gc-bld-evo-confirm-lead" id="gc-research-lab-ascension-confirm-lead"></p>
      <div class="gc-bld-evo-confirm-rank-chip" id="gc-research-lab-ascension-confirm-rank"></div>
      <section class="gc-bld-evo-confirm-section" aria-labelledby="gc-research-lab-ascension-benefit-label">
        <h3 class="gc-bld-evo-confirm-section-title" id="gc-research-lab-ascension-benefit-label">{{ T('buildings_mine_evo_modal_benefit_label', 'Permanenter Vorteil') }}</h3>
        <p class="gc-bld-evo-confirm-benefit" id="gc-research-lab-ascension-benefit"></p>
      </section>
      <section class="gc-bld-evo-confirm-section" aria-labelledby="gc-research-lab-ascension-tribute-label">
        <h3 class="gc-bld-evo-confirm-section-title" id="gc-research-lab-ascension-tribute-label">{{ T('buildings_mine_evo_modal_tribute_label', 'Tribute') }}</h3>
        <ul class="gc-bld-evo-confirm-tribute-list">
          <li id="gc-research-lab-ascension-tribute-metal"></li>
          <li id="gc-research-lab-ascension-tribute-crystal"></li>
        </ul>
      </section>
      <div class="gc-bld-evo-confirm-actions">
        <button type="button" class="gc-btn gc-btn-primary" id="gc-research-lab-ascension-confirm-submit">{{ T('research_network_ascend') }}</button>
        <button type="button" class="gc-btn gc-btn-secondary" data-research-lab-ascension-cancel>{{ T('buildings_mine_evo_modal_cancel', 'Abbrechen') }}</button>
      </div>
    </div>
  </div>
</div>

<div id="gc-stellar-forge-modal"''',
)
replace_once(
    buildings,
    '''{% block extra_scripts %}
<script src="{{ url_for('static', filename='js/pages/buildings.js') }}?v={{ GC_ASSET_VERSION }}"></script>
{% endblock %}''',
    '''{% block extra_scripts %}
<script src="{{ url_for('static', filename='js/pages/buildings.js') }}?v={{ GC_ASSET_VERSION }}"></script>
<script src="{{ url_for('static', filename='js/pages/research_lab_ascension.js') }}?v={{ GC_ASSET_VERSION }}"></script>
{% endblock %}''',
)

js = ROOT / "static/js/pages/research_lab_ascension.js"
js.write_text("""(function () {
  \"use strict\";

  var GC = window.GC = window.GC || {};
  var modal = document.getElementById(\"gc-research-lab-ascension-confirm-modal\");
  var submit = document.getElementById(\"gc-research-lab-ascension-confirm-submit\");
  var lead = document.getElementById(\"gc-research-lab-ascension-confirm-lead\");
  var rank = document.getElementById(\"gc-research-lab-ascension-confirm-rank\");
  var benefit = document.getElementById(\"gc-research-lab-ascension-benefit\");
  var metal = document.getElementById(\"gc-research-lab-ascension-tribute-metal\");
  var crystal = document.getElementById(\"gc-research-lab-ascension-tribute-crystal\");
  var activeTrigger = null;

  function requestId() {
    if (typeof crypto !== \"undefined\" && typeof crypto.randomUUID === \"function\") return crypto.randomUUID();
    return \"research-lab-asc-\" + Date.now() + \"-\" + Math.random().toString(16).slice(2);
  }

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || \"research_ascension_failed\");
    if (typeof GC.t === \"function\") {
      return GC.t(\"research_network_error_\" + reason, GC.t(\"research_network_error_generic\", \"Research ascension failed.\"));
    }
    return reason;
  }

  function openModal(btn) {
    if (!modal || !btn) return;
    activeTrigger = btn;
    var name = btn.dataset.ascName || \"\";
    var roman = btn.dataset.ascRank || \"\";
    var required = btn.dataset.ascRequired || \"\";
    if (lead) lead.textContent = name + (required ? \" · Level \" + required : \"\");
    if (rank) rank.textContent = \"Ascension \" + roman;
    if (benefit) benefit.textContent = btn.dataset.ascBenefit || \"\";
    if (metal) metal.textContent = \"Ferronit · \" + (btn.dataset.ascTributeMetal || \"0\");
    if (crystal) crystal.textContent = \"Crytite · \" + (btn.dataset.ascTributeCrystal || \"0\");
    modal.hidden = false;
    modal.setAttribute(\"aria-hidden\", \"false\");
    document.body.classList.add(\"gc-modal-open\");
    if (submit) submit.focus();
  }

  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute(\"aria-hidden\", \"true\");
    document.body.classList.remove(\"gc-modal-open\");
    var focusTarget = activeTrigger;
    activeTrigger = null;
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
  }

  async function ascend() {
    if (!submit || submit.disabled || submit.dataset.busy === \"1\") return;
    submit.dataset.busy = \"1\";
    submit.disabled = true;
    try {
      if (typeof GC.fetchGameAction !== \"function\") throw new Error(\"fetchGameAction missing\");
      var res = await GC.fetchGameAction(\"/api/research/ascend-lab\", {
        method: \"POST\",
        headers: { \"Content-Type\": \"application/json\", Accept: \"application/json\" },
        body: JSON.stringify({ request_id: requestId() })
      });
      if (!res || !res.ok) {
        if (typeof GC.toast === \"function\") GC.toast(messageFor(res), \"error\");
        return;
      }
      closeModal();
      if (typeof GC.applyActionState === \"function\") GC.applyActionState(res, \"research_lab_ascension\");
      if (typeof GC.reloadCurrentPage === \"function\") await GC.reloadCurrentPage({ force: true });
      else window.location.reload();
    } catch (err) {
      if (typeof GC.toast === \"function\") GC.toast(messageFor(null), \"error\");
      else if (window.console && console.error) console.error(err);
    } finally {
      submit.dataset.busy = \"0\";
      submit.disabled = false;
    }
  }

  document.addEventListener(\"click\", function (event) {
    var trigger = event.target && event.target.closest ? event.target.closest(\"[data-research-lab-ascend]\") : null;
    if (trigger) {
      event.preventDefault();
      openModal(trigger);
      return;
    }
    if (event.target && event.target.closest && event.target.closest(\"[data-research-lab-ascension-cancel]\")) {
      event.preventDefault();
      closeModal();
    }
  });
  document.addEventListener(\"keydown\", function (event) {
    if (event.key === \"Escape\" && modal && !modal.hidden) closeModal();
  });
  if (submit) submit.addEventListener(\"click\", ascend);
}());
""", encoding="utf-8")

old_js = ROOT / "static/js/pages/research_network.js"
if old_js.exists():
    old_js.unlink()

test_path = ROOT / "tests/test_research_lab_ascension.py"
test_text = test_path.read_text(encoding="utf-8")
replace_test_old = '''    template = (root / "templates/research.html").read_text(encoding="utf-8")

    assert "research_queue_capacity" in research
    assert 'building_type == "research_lab"' in buildings
    assert "max_lab_level_for_rank" in buildings
    assert "_research_lab_ascension_rank_cache" in effects
    assert '/api/research/ascend-lab' in app
    assert "data-research-network-ascend" in template
    assert "js/pages/research_network.js" in template
'''
replace_test_new = '''    research_template = (root / "templates/research.html").read_text(encoding="utf-8")
    buildings_template = (root / "templates/buildings.html").read_text(encoding="utf-8")
    building_script = (root / "static/js/pages/research_lab_ascension.js").read_text(encoding="utf-8")

    assert "research_queue_capacity" in research
    assert 'building_type == "research_lab"' in buildings
    assert "max_lab_level_for_rank" in buildings
    assert "_research_lab_ascension_rank_cache" in effects
    assert '/api/research/ascend-lab' in app
    assert "data-research-network-ascend" not in research_template
    assert "js/pages/research_network.js" not in research_template
    assert "data-research-lab-ascend" in buildings_template
    assert "gc-research-lab-ascension-confirm-modal" in buildings_template
    assert "js/pages/research_lab_ascension.js" in buildings_template
    assert '/api/research/ascend-lab' in building_script
'''
if test_text.count(replace_test_old) != 1:
    raise SystemExit("research static test anchor changed")
test_path.write_text(test_text.replace(replace_test_old, replace_test_new, 1), encoding="utf-8")

doc = ROOT / "docs/RESEARCH_SYSTEM.md"
doc_text = doc.read_text(encoding="utf-8")
for old, new in [
    (
        "- Rank V ist Endpunkt dieses Prestige-Pfads; die allgemeine Research-Queue bleibt dennoch sequenziell.\n",
        "- Rank V ist Endpunkt dieses Prestige-Pfads; die allgemeine Research-Queue bleibt dennoch sequenziell.\n- Ascension wird wie andere Gebäude-Ascensions **am Forschungslabor in der Gebäude-UI** aktiviert; `/research` zeigt das Forschungsnetzwerk nur read-only an.\n",
    ),
    (
        "| `/api/research/lab-ascend` | POST | Research-Lab-Ascension der aktiven/context world |",
        "| `/api/research/ascend-lab` | POST | Research-Lab-Ascension der aktiven/context world |",
    ),
    (
        "- **Forschungsnetzwerk-Header:** belegte/gesamte Slots, stärkstes Labor, Ascension-Rang, nächster Unlock/Tribute.\n- Gebäude-UI: Forschungslabor zeigt Rank, Queue-Kapazität, nächsten Gate-Level, Research-Speedbonus und Ascension-Aktion.\n",
        "- **Forschungsnetzwerk-Header auf `/research`:** read-only; belegte/gesamte Slots, stärkstes Labor, Ascension-Rang und nächster Unlock.\n- **Gebäude-UI:** Forschungslabor zeigt Rank, Queue-Kapazität, Gate-Fortschritt und Research-Speedbonus; bei erreichtem Gate läuft die Ascension dort über Tribute-CTA + Bestätigungsdialog.\n",
    ),
]:
    if old not in doc_text:
        raise SystemExit(f"documentation anchor changed: {old[:40]!r}")
    doc_text = doc_text.replace(old, new, 1)
doc.write_text(doc_text, encoding="utf-8")

print("research lab ascension building flow patched")
