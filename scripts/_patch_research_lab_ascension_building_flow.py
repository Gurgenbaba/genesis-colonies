from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match in {path}: got {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# /research is status-only. Ascension is a building progression action.
research = ROOT / "templates/research.html"
replace_once(
    research,
    """        {% if next_unlock.kind == 'ascension' and next_unlock.ready %}\n          {% set tribute_m = network.next_tribute_metal if network.next_tribute_metal is defined else 0 %}\n          {% set tribute_c = network.next_tribute_crystal if network.next_tribute_crystal is defined else 0 %}\n          <button type=\"button\" class=\"gc-btn gc-bld-evo-btn\" data-research-network-ascend>\n            {{ T('research_network_ascend', rank=next_unlock.roman) }}\n          </button>\n        {% endif %}\n""",
    """        {% if next_unlock.kind == 'ascension' and next_unlock.ready %}\n          <div class=\"hint\">{{ T('research_network_ready', rank=next_unlock.roman) }}</div>\n        {% endif %}\n""",
)
replace_once(
    research,
    """{% block extra_scripts %}\n{{ super() }}\n<script src=\"{{ url_for('static', filename='js/pages/research_network.js') }}?v={{ GC_ASSET_VERSION }}\"></script>\n{% endblock %}""",
    """{% block extra_scripts %}\n{{ super() }}\n{% endblock %}""",
)

# Research Lab card uses the same progression/tribute affordance as Mine Ascension.
buildings = ROOT / "templates/buildings.html"
old_block = """          {% if building_type == 'research_lab' and b.research_lab_ascension is defined and b.research_lab_ascension %}\n          <div class=\"gc-bld-evo-block\" data-research-lab-ascension>\n            <div class=\"gc-bld-evo-progress\" role=\"status\">\n              <span class=\"gc-bld-evo-progress-label\">{{ T('research_network_title') }}</span>\n              <span class=\"gc-mono gc-bld-evo-progress-vals\">{{ T('research_network_capacity', slots=b.research_queue_capacity) }}</span>\n            </div>\n            {% if (b.research_lab_ascension_rank|default(0)|int) > 0 %}\n            <div class=\"gc-bld-evo-bonus gc-mono\">\n              {{ T('research_network_rank_speed', rank=b.research_lab_ascension_roman, pct=b.research_lab_ascension_speed_bonus_pct) }}\n            </div>\n            {% endif %}\n            {% if b.research_lab_ascension_ready %}\n            <div class=\"hint\">{{ T('research_network_ready', rank=b.research_lab_next_roman) }}</div>\n            {% elif (b.research_lab_next_rank|default(0)|int) > 0 %}\n            <div class=\"hint\">{{ T('research_network_requires', rank=b.research_lab_next_roman, level=b.research_lab_ascension_required_level) }}</div>\n            {% endif %}\n          </div>\n          {% endif %}\n"""
new_block = """          {% if building_type == 'research_lab' and b.research_lab_ascension is defined and b.research_lab_ascension %}\n          {% set _lab_asc_rank = (b.research_lab_ascension_rank|default(0)|int) %}\n          {% set _lab_asc_next = (b.research_lab_next_rank|default(0)|int) %}\n          {% set _lab_asc_req = (b.research_lab_ascension_required_level|default(0)|int) %}\n          {% set _lab_asc_progress = ([100, ((b.level|int) * 100 // _lab_asc_req)]|min) if _lab_asc_req > 0 else 100 %}\n          <div class=\"gc-bld-evo-block\" data-research-lab-ascension>\n            <div class=\"gc-bld-evo-progress\" role=\"status\">\n              <span class=\"gc-bld-evo-progress-label\">{{ T('research_network_title') }}</span>\n              {% if _lab_asc_next > 0 %}\n              <span class=\"gc-mono gc-bld-evo-progress-vals\">{{ b.level|fmt_int }} / {{ _lab_asc_req|fmt_int }}</span>\n              {% else %}\n              <span class=\"gc-mono gc-bld-evo-progress-vals\">{{ T('research_network_capacity', slots=b.research_queue_capacity) }}</span>\n              {% endif %}\n            </div>\n            {% if _lab_asc_next > 0 %}\n            <div class=\"gc-bld-evo-bar\" aria-hidden=\"true\">\n              <span class=\"gc-bld-evo-bar-fill\" style=\"width: {{ _lab_asc_progress }}%;\"></span>\n            </div>\n            {% endif %}\n            <div class=\"gc-bld-evo-bonus gc-mono\">\n              {% if _lab_asc_rank > 0 %}\n                {{ T('research_network_rank_speed', rank=b.research_lab_ascension_roman, pct=b.research_lab_ascension_speed_bonus_pct) }} ·\n              {% endif %}\n              {{ T('research_network_capacity', slots=b.research_queue_capacity) }}\n            </div>\n            {% if b.research_lab_ascension_ready %}\n            <div class=\"hint\">{{ T('research_network_ready', rank=b.research_lab_next_roman) }}</div>\n            <button type=\"button\"\n                    class=\"gc-btn gc-bld-evo-btn\"\n                    data-research-lab-ascend\n                    data-asc-name=\"{{ T('building_' ~ building_type) }}\"\n                    data-asc-rank=\"{{ b.research_lab_next_roman }}\"\n                    data-asc-required=\"{{ _lab_asc_req }}\"\n                    data-asc-tribute-metal=\"{{ b.research_lab_ascension_tribute_metal|fmt_int }}\"\n                    data-asc-tribute-crystal=\"{{ b.research_lab_ascension_tribute_crystal|fmt_int }}\"\n                    data-asc-benefit=\"{{ T('research_network_rank_speed', rank=b.research_lab_next_roman, pct=(b.research_lab_ascension_speed_bonus_pct|int + 2)) }} · {{ T('research_network_capacity', slots=(b.research_queue_capacity|int + 1)) }}\">\n              {{ T('research_network_ascend', rank=b.research_lab_next_roman) }}\n            </button>\n            {% elif _lab_asc_next > 0 %}\n            <div class=\"hint\">{{ T('research_network_requires', rank=b.research_lab_next_roman, level=_lab_asc_req) }}</div>\n            {% endif %}\n          </div>\n          {% endif %}\n"""
replace_once(buildings, old_block, new_block)

mine_modal_end = """</div>\n\n<div id=\"gc-stellar-forge-modal\""" 
research_modal = """</div>\n\n<div id=\"gc-research-lab-ascension-confirm-modal\"\n     class=\"gc-player-card-modal gc-bld-evo-confirm-modal\"\n     hidden\n     aria-hidden=\"true\">\n  <div class=\"gc-player-card-overlay\" data-research-lab-ascension-cancel tabindex=\"-1\"></div>\n  <div class=\"gc-player-card-dialog gc-bld-evo-confirm-dialog\"\n       role=\"dialog\"\n       aria-modal=\"true\"\n       aria-labelledby=\"gc-research-lab-ascension-confirm-title\">\n    <header class=\"gc-player-card-head\">\n      <h2 id=\"gc-research-lab-ascension-confirm-title\" class=\"gc-player-card-head-title\">\n        {{ T('research_network_title') }}\n      </h2>\n      <button type=\"button\"\n              class=\"gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close\"\n              data-research-lab-ascension-cancel\n              aria-label=\"{{ T('close', 'Schließen') }}\">×</button>\n    </header>\n    <div class=\"gc-player-card-body gc-bld-evo-confirm-body\">\n      <p class=\"gc-bld-evo-confirm-lead\" id=\"gc-research-lab-ascension-confirm-lead\"></p>\n      <div class=\"gc-bld-evo-confirm-rank-chip\" id=\"gc-research-lab-ascension-confirm-rank\"></div>\n      <section class=\"gc-bld-evo-confirm-section\" aria-labelledby=\"gc-research-lab-ascension-benefit-label\">\n        <h3 class=\"gc-bld-evo-confirm-section-title\" id=\"gc-research-lab-ascension-benefit-label\">\n          {{ T('buildings_mine_evo_modal_benefit_label', 'Permanenter Vorteil') }}\n        </h3>\n        <p class=\"gc-bld-evo-confirm-benefit\" id=\"gc-research-lab-ascension-benefit\"></p>\n      </section>\n      <section class=\"gc-bld-evo-confirm-section\" aria-labelledby=\"gc-research-lab-ascension-tribute-label\">\n        <h3 class=\"gc-bld-evo-confirm-section-title\" id=\"gc-research-lab-ascension-tribute-label\">\n          {{ T('buildings_mine_evo_modal_tribute_label', 'Tribute') }}\n        </h3>\n        <ul class=\"gc-bld-evo-confirm-tribute-list\">\n          <li id=\"gc-research-lab-ascension-tribute-metal\"></li>\n          <li id=\"gc-research-lab-ascension-tribute-crystal\"></li>\n        </ul>\n      </section>\n      <div class=\"gc-bld-evo-confirm-actions\">\n        <button type=\"button\" class=\"gc-btn gc-btn-primary\" id=\"gc-research-lab-ascension-confirm-submit\">\n          {{ T('research_network_ascend') }}\n        </button>\n        <button type=\"button\" class=\"gc-btn gc-btn-secondary\" data-research-lab-ascension-cancel>\n          {{ T('buildings_mine_evo_modal_cancel', 'Abbrechen') }}\n        </button>\n      </div>\n    </div>\n  </div>\n</div>\n\n<div id=\"gc-stellar-forge-modal\""" 
replace_once(buildings, mine_modal_end, research_modal)
replace_once(
    buildings,
    """{% block extra_scripts %}\n<script src=\"{{ url_for('static', filename='js/pages/buildings.js') }}?v={{ GC_ASSET_VERSION }}\"></script>\n{% endblock %}""",
    """{% block extra_scripts %}\n<script src=\"{{ url_for('static', filename='js/pages/buildings.js') }}?v={{ GC_ASSET_VERSION }}\"></script>\n<script src=\"{{ url_for('static', filename='js/pages/research_lab_ascension.js') }}?v={{ GC_ASSET_VERSION }}\"></script>\n{% endblock %}""",
)

# Dedicated building-page behavior. Costs stay display-only; server recomputes tribute.
js = ROOT / "static/js/pages/research_lab_ascension.js"
js.write_text(r'''(function () {
  "use strict";

  var GC = window.GC = window.GC || {};
  var modal = document.getElementById("gc-research-lab-ascension-confirm-modal");
  var submit = document.getElementById("gc-research-lab-ascension-confirm-submit");
  var lead = document.getElementById("gc-research-lab-ascension-confirm-lead");
  var rank = document.getElementById("gc-research-lab-ascension-confirm-rank");
  var benefit = document.getElementById("gc-research-lab-ascension-benefit");
  var metal = document.getElementById("gc-research-lab-ascension-tribute-metal");
  var crystal = document.getElementById("gc-research-lab-ascension-tribute-crystal");
  var activeTrigger = null;

  function requestId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return "research-lab-asc-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function text(key, fallback, vars) {
    if (typeof GC.t === "function") return GC.t(key, fallback, vars || {});
    return fallback;
  }

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || "research_ascension_failed");
    if (typeof GC.t === "function") {
      return GC.t("research_network_error_" + reason, GC.t("research_network_error_generic", "Research ascension failed."));
    }
    return reason;
  }

  function openModal(btn) {
    if (!modal || !btn) return;
    activeTrigger = btn;
    var name = btn.dataset.ascName || "";
    var roman = btn.dataset.ascRank || "";
    var required = btn.dataset.ascRequired || "";
    if (lead) lead.textContent = name + (required ? " · Level " + required : "");
    if (rank) rank.textContent = "Ascension " + roman;
    if (benefit) benefit.textContent = btn.dataset.ascBenefit || "";
    if (metal) metal.textContent = "Ferronit · " + (btn.dataset.ascTributeMetal || "0");
    if (crystal) crystal.textContent = "Crytite · " + (btn.dataset.ascTributeCrystal || "0");
    modal.hidden = false;
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("gc-modal-open");
    if (submit) submit.focus();
  }

  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("gc-modal-open");
    var focusTarget = activeTrigger;
    activeTrigger = null;
    if (focusTarget && document.contains(focusTarget)) focusTarget.focus();
  }

  async function ascend() {
    if (!submit || submit.disabled || submit.dataset.busy === "1") return;
    submit.dataset.busy = "1";
    submit.disabled = true;
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("fetchGameAction missing");
      var res = await GC.fetchGameAction("/api/research/ascend-lab", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ request_id: requestId() })
      });
      if (!res || !res.ok) {
        if (typeof GC.toast === "function") GC.toast(messageFor(res), "error");
        return;
      }
      closeModal();
      if (typeof GC.applyActionState === "function") GC.applyActionState(res, "research_lab_ascension");
      if (typeof GC.reloadCurrentPage === "function") {
        await GC.reloadCurrentPage({ force: true });
      } else {
        window.location.reload();
      }
    } catch (err) {
      if (typeof GC.toast === "function") GC.toast(messageFor(null), "error");
      else if (window.console && console.error) console.error(err);
    } finally {
      submit.dataset.busy = "0";
      submit.disabled = false;
    }
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target && event.target.closest ? event.target.closest("[data-research-lab-ascend]") : null;
    if (trigger) {
      event.preventDefault();
      openModal(trigger);
      return;
    }
    if (event.target && event.target.closest && event.target.closest("[data-research-lab-ascension-cancel]")) {
      event.preventDefault();
      closeModal();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  if (submit) submit.addEventListener("click", ascend);
}());
''', encoding="utf-8")

old_js = ROOT / "static/js/pages/research_network.js"
if old_js.exists():
    old_js.unlink()

# Static contract now explicitly pins the interaction to the building surface.
test_path = ROOT / "tests/test_research_lab_ascension.py"
test_text = test_path.read_text(encoding="utf-8")
old_test = '''    template = (root / "templates/research.html").read_text(encoding="utf-8")\n\n    assert "research_queue_capacity" in research\n    assert 'building_type == "research_lab"' in buildings\n    assert "max_lab_level_for_rank" in buildings\n    assert "_research_lab_ascension_rank_cache" in effects\n    assert '/api/research/ascend-lab' in app\n    assert "data-research-network-ascend" in template\n    assert "js/pages/research_network.js" in template\n'''
new_test = '''    research_template = (root / "templates/research.html").read_text(encoding="utf-8")\n    buildings_template = (root / "templates/buildings.html").read_text(encoding="utf-8")\n    building_script = (root / "static/js/pages/research_lab_ascension.js").read_text(encoding="utf-8")\n\n    assert "research_queue_capacity" in research\n    assert 'building_type == "research_lab"' in buildings\n    assert "max_lab_level_for_rank" in buildings\n    assert "_research_lab_ascension_rank_cache" in effects\n    assert '/api/research/ascend-lab' in app\n    assert "data-research-network-ascend" not in research_template\n    assert "js/pages/research_network.js" not in research_template\n    assert "data-research-lab-ascend" in buildings_template\n    assert "gc-research-lab-ascension-confirm-modal" in buildings_template\n    assert "js/pages/research_lab_ascension.js" in buildings_template\n    assert '/api/research/ascend-lab' in building_script\n'''
if old_test not in test_text:
    raise SystemExit("research static test anchor changed")
test_path.write_text(test_text.replace(old_test, new_test, 1), encoding="utf-8")

# Keep system documentation explicit about where progression is activated.
doc = ROOT / "docs/RESEARCH_SYSTEM.md"
doc_text = doc.read_text(encoding="utf-8")
doc_text = doc_text.replace(
    "- Rank V ist Endpunkt dieses Prestige-Pfads; die allgemeine Research-Queue bleibt dennoch sequenziell.\n",
    "- Rank V ist Endpunkt dieses Prestige-Pfads; die allgemeine Research-Queue bleibt dennoch sequenziell.\n- Ascension wird wie andere Gebäude-Ascensions **am Forschungslabor in der Gebäude-UI** aktiviert; `/research` zeigt das Forschungsnetzwerk nur read-only an.\n",
    1,
)
doc_text = doc_text.replace(
    "| `/api/research/lab-ascend` | POST | Research-Lab-Ascension der aktiven/context world |",
    "| `/api/research/ascend-lab` | POST | Research-Lab-Ascension der aktiven/context world |",
    1,
)
doc_text = doc_text.replace(
    "- **Forschungsnetzwerk-Header:** belegte/gesamte Slots, stärkstes Labor, Ascension-Rang, nächster Unlock/Tribute.\n- Gebäude-UI: Forschungslabor zeigt Rank, Queue-Kapazität, nächsten Gate-Level, Research-Speedbonus und Ascension-Aktion.\n",
    "- **Forschungsnetzwerk-Header auf `/research`:** read-only; belegte/gesamte Slots, stärkstes Labor, Ascension-Rang und nächster Unlock.\n- **Gebäude-UI:** Forschungslabor zeigt Rank, Queue-Kapazität, Gate-Fortschritt und Research-Speedbonus; bei erreichtem Gate läuft die Ascension dort über Tribute-CTA + Bestätigungsdialog.\n",
    1,
)
doc.write_text(doc_text, encoding="utf-8")

print("research lab ascension building flow patched")
