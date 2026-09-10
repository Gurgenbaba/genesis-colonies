from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match in {path}, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


buildings = ROOT / "templates/buildings.html"
replace_once(
    buildings,
    '''                    data-asc-name="{{ T('building_' ~ building_type) }}"
                    data-asc-rank="{{ b.research_lab_next_roman }}"
                    data-asc-required="{{ _lab_asc_req }}"
                    data-asc-tribute-metal="{{ b.research_lab_ascension_tribute_metal|fmt_int }}"
                    data-asc-tribute-crystal="{{ b.research_lab_ascension_tribute_crystal|fmt_int }}"
                    data-asc-benefit="{{ T('research_network_rank_speed', rank=b.research_lab_next_roman, pct=(b.research_lab_ascension_speed_bonus_pct|int + 2)) }} · {{ T('research_network_capacity', slots=(b.research_queue_capacity|int + 1)) }}">''',
    '''                    data-asc-lead="{{ T('research_network_requires', rank=b.research_lab_next_roman, level=_lab_asc_req) }}"
                    data-asc-rank-label="{{ T('research_network_ready', rank=b.research_lab_next_roman) }}"
                    data-asc-action-label="{{ T('research_network_ascend', rank=b.research_lab_next_roman) }}"
                    data-asc-tribute-metal-label="{{ T('resource_metal') }} · {{ b.research_lab_ascension_tribute_metal|fmt_int }}"
                    data-asc-tribute-crystal-label="{{ T('resource_crystal') }} · {{ b.research_lab_ascension_tribute_crystal|fmt_int }}"
                    data-asc-benefit="{{ T('research_network_rank_speed', rank=b.research_lab_next_roman, pct=(b.research_lab_ascension_speed_bonus_pct|int + 2)) }} · {{ T('research_network_capacity', slots=(b.research_queue_capacity|int + 1)) }}">''',
)
replace_once(
    buildings,
    '''        <button type="button" class="gc-btn gc-btn-primary" id="gc-research-lab-ascension-confirm-submit">{{ T('research_network_ascend') }}</button>''',
    '''        <button type="button" class="gc-btn gc-btn-primary" id="gc-research-lab-ascension-confirm-submit">{{ T('research_network_title') }}</button>''',
)

js = ROOT / "static/js/pages/research_lab_ascension.js"
js.write_text('''(function () {
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

  function messageFor(res) {
    var reason = String((res && (res.reason || res.error)) || "research_ascension_failed");
    if (typeof GC.t === "function") {
      return GC.t("research_network_error_" + reason, GC.t("research_network_error_generic", ""));
    }
    return reason;
  }

  function openModal(btn) {
    if (!modal || !btn) return;
    activeTrigger = btn;
    if (lead) lead.textContent = btn.dataset.ascLead || "";
    if (rank) rank.textContent = btn.dataset.ascRankLabel || "";
    if (benefit) benefit.textContent = btn.dataset.ascBenefit || "";
    if (metal) metal.textContent = btn.dataset.ascTributeMetalLabel || "";
    if (crystal) crystal.textContent = btn.dataset.ascTributeCrystalLabel || "";
    if (submit) submit.textContent = btn.dataset.ascActionLabel || "";
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
      if (typeof GC.reloadCurrentPage === "function") await GC.reloadCurrentPage({ force: true });
      else window.location.reload();
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

print("research lab ascension i18n hardened")
