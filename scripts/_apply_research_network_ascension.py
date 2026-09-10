from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def append_json_keys(rel: str, values: dict[str, str]) -> None:
    text = read(rel)
    marker = "\n}"
    pos = text.rfind(marker)
    if pos < 0:
        raise RuntimeError(f"{rel}: closing object marker missing")
    prefix = text[:pos].rstrip()
    if not prefix.endswith(","):
        prefix += ","
    lines = []
    for idx, (key, value) in enumerate(values.items()):
        comma = "," if idx < len(values) - 1 else ""
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    write(rel, prefix + "\n" + "\n".join(lines) + "\n}" + text[pos + len(marker):])


# ---------------------------------------------------------------------------
# research.py — capacity resolver is the one truth for start, MAX and state.
# ---------------------------------------------------------------------------
rel = "game/research.py"
text = read(rel)
old = '''RESEARCH_QUEUE_LIMIT = 2
RESEARCH_QUEUE_LIMIT_AT_LAB4 = 3
RESEARCH_QUEUE_LAB_LEVEL_FOR_BONUS = 4
'''
new = '''RESEARCH_QUEUE_LIMIT = 2
# GC-RESEARCH-NET-ASC-001: lab/Ascension queue capacity is resolved centrally
# in game.research_lab_ascension.  Keep the constant as settings fallback only.
'''
text = replace_once(text, old, new, "research constants")
start = text.index("def _resolve_research_queue_limit(")
end = text.index("\n\n# ======================================================================\n# QUEUE START", start)
new_func = '''def _resolve_research_queue_limit(
    settings: Optional[Dict[str, Any]] = None,
    *,
    player_id: Optional[int] = None,
    conn=None,
) -> int:
    if player_id is not None:
        from .research_lab_ascension import research_queue_capacity

        return int(
            research_queue_capacity(
                int(player_id),
                conn=conn,
                settings=settings,
            )["limit"]
        )

    if settings is None:
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()
    raw_limit = settings.get("research_queue_limit", RESEARCH_QUEUE_LIMIT)
    try:
        queue_limit = int(raw_limit)
    except (ValueError, TypeError):
        try:
            queue_limit = int(float(raw_limit))
        except (ValueError, TypeError):
            queue_limit = RESEARCH_QUEUE_LIMIT
    return max(queue_limit, 1)
'''
text = text[:start] + new_func + text[end:]
old = '''    research_queue_limit = _resolve_research_queue_limit(player_id=uid, conn=conn)
    queue_free_slots = max(0, research_queue_limit - len(queue_list))
'''
new = '''    from .research_lab_ascension import research_queue_capacity

    network = research_queue_capacity(uid, conn=conn)
    research_queue_limit = int(network["limit"])
    queue_free_slots = max(0, research_queue_limit - len(queue_list))
'''
text = replace_once(text, old, new, "research status capacity")
old = '''        "summary": summary,
        "lab_level": lab_level,
        "card_jobs_by_owner": card_jobs_by_owner,
'''
new = '''        "summary": summary,
        "lab_level": int(network.get("lab_level") or lab_level),
        "network": network,
        "card_jobs_by_owner": card_jobs_by_owner,
'''
text = replace_once(text, old, new, "research status payload")
write(rel, text)


# ---------------------------------------------------------------------------
# EffectResolver — +2% speed per rank from strongest lab, cached per resolver.
# ---------------------------------------------------------------------------
rel = "game/effects/effect_resolver.py"
text = read(rel)
old = '''    def research_lab_bonus(self) -> float:
        lab = _bld(self.buildings, "research_lab")
        return 1.0 + max(0, lab - 1) * 0.10
'''
new = '''    def research_lab_bonus(self) -> float:
        lab = _bld(self.buildings, "research_lab")
        base = 1.0 + max(0, lab - 1) * 0.10

        # GC-RESEARCH-NET-ASC-001: small prestige speed bonus.  The rank lookup
        # is cached on this resolver because one research catalog reuses it for
        # many target-level time calculations.
        rank = getattr(self, "_research_lab_ascension_rank_cache", None)
        if rank is None:
            rank = 0
            if self.player_id is not None and self._conn is not None:
                try:
                    from ..research_lab_ascension import research_queue_capacity

                    rank = int(
                        research_queue_capacity(
                            int(self.player_id),
                            conn=self._conn,
                            include_external_bonus=False,
                        ).get("ascension_rank", 0)
                        or 0
                    )
                except Exception:
                    rank = 0
            self._research_lab_ascension_rank_cache = int(rank)
        return base * (1.0 + 0.02 * max(0, min(5, int(rank))))
'''
text = replace_once(text, old, new, "effect resolver lab bonus")
write(rel, text)


# ---------------------------------------------------------------------------
# buildings.py — Research Lab cap is unlocked rank-by-rank; card gets fields.
# ---------------------------------------------------------------------------
rel = "game/buildings.py"
text = read(rel)
needle = '''    """Authoritative enqueue cap: normal hard cap or next Mine Ascension milestone."""
    max_level = max(0, int(base_max_level))
    from .mine_evolution import get_evolution_rank, is_evolvable_mine, required_level_for_evolution
'''
replacement = '''    """Authoritative enqueue cap: normal hard cap or next Ascension milestone."""
    max_level = max(0, int(base_max_level))

    if building_type == "research_lab" and planet_id is not None:
        from .research_lab_ascension import get_planet_ascension_rank, max_lab_level_for_rank

        lab_rank = get_planet_ascension_rank(int(planet_id), conn=conn)
        return int(max_lab_level_for_rank(lab_rank))

    from .mine_evolution import get_evolution_rank, is_evolvable_mine, required_level_for_evolution
'''
text = replace_once(text, needle, replacement, "building cap")
needle = '''    row.update(panel_evolution_fields(pid, building_type, level, ranks=evo_ranks))
    if pid is not None and building_type == "orbital_shipyard":
'''
replacement = '''    row.update(panel_evolution_fields(pid, building_type, level, ranks=evo_ranks))
    if pid is not None and building_type == "research_lab":
        from .research_lab_ascension import panel_fields as research_lab_ascension_panel_fields
        from .research_lab_ascension import research_queue_capacity

        row.update(
            research_lab_ascension_panel_fields(
                int(planet.get("player_id") or 0),
                pid,
                level,
                conn=evo_conn,
            )
        )
        capacity = research_queue_capacity(
            int(planet.get("player_id") or 0),
            conn=evo_conn,
        )
        row["research_queue_capacity"] = int(capacity.get("limit") or 0)
        row["research_queue_prestige_capacity"] = int(capacity.get("prestige_limit") or 0)
    if pid is not None and building_type == "orbital_shipyard":
'''
text = replace_once(text, needle, replacement, "building lab panel fields")
write(rel, text)


# ---------------------------------------------------------------------------
# app.py — idempotent AJAX action, same state contract as research actions.
# ---------------------------------------------------------------------------
rel = "app.py"
text = read(rel)
text = text.replace('"api_research_start": "research",\n', '"api_research_start": "research",\n    "api_research_ascend_lab": "research",\n')
text = text.replace('"api_research_start",\n        "api_research_cancel",', '"api_research_start",\n        "api_research_ascend_lab",\n        "api_research_cancel",')
text = text.replace('"api_research_start",\n        "api_research_cancel",\n        "api_timekeeper_apply",', '"api_research_start",\n        "api_research_ascend_lab",\n        "api_research_cancel",\n        "api_timekeeper_apply",')
marker = '@app.route("/api/research/start", methods=["POST"])\n'
if text.count(marker) != 1:
    raise RuntimeError(f"app research route marker count={text.count(marker)}")
route = '''@app.route("/api/research/ascend-lab", methods=["POST"])
@require_login
def api_research_ascend_lab():
    user_id = int(session.get("user_id") or 0)
    if not user_id:
        return jsonify({"ok": False, "reason": "not_logged_in"}), 401

    data = request.get_json(silent=True) or {}
    request_id = _extract_request_id(data)
    if request_id:
        cached = get_idempotent_action(user_id, request_id)
        if cached is not None:
            return jsonify(cached)

    from game.planet_evolution.repository import get_context_planet
    from game.research_lab_ascension import ascend_research_lab

    conn = db()
    try:
        planet = dict(get_context_planet(user_id, conn=conn))
    finally:
        conn.close()

    ok, reason, payload = ascend_research_lab(user_id, planet)
    resp = _action_json_response(
        ok,
        reason,
        payload=payload if not ok else None,
        job=payload if ok else None,
        finish_source="api_research_ascend_lab",
        include_panel=True,
    )
    body = resp.get_json()
    if request_id and isinstance(body, dict):
        save_idempotent_action(user_id, request_id, body)
    return resp


'''
text = text.replace(marker, route + marker, 1)
write(rel, text)


# ---------------------------------------------------------------------------
# /research UI — server-derived network state only; no client math.
# ---------------------------------------------------------------------------
rel = "templates/research.html"
text = read(rel)
needle = '''{% set lab_level = (rs.lab_level if rs and rs.lab_level is defined else 0) %}
{% set rq_limit = (rq_summary.limit if rq_summary.limit is defined else 3) %}
'''
replacement = '''{% set lab_level = (rs.lab_level if rs and rs.lab_level is defined else 0) %}
{% set network = (rs.network if rs and rs.network is defined and rs.network else {}) %}
{% set rq_limit = (rq_summary.limit if rq_summary.limit is defined else 2) %}
'''
text = replace_once(text, needle, replacement, "research template vars")
needle = '''  <section class="gc-panel research-shell">

    {{ render_page_mini_queue_strip(
'''
replacement = '''  <section class="gc-panel research-shell">

    <div class="gc-bld-evo-block research-network-block" data-research-network>
      <div class="gc-bld-evo-progress" role="status">
        <strong>{{ T('research_network_title') }}</strong>
        <span class="gc-mono">{{ T('research_network_jobs', count=(rq_summary.count if rq_summary.count is defined else 0), limit=rq_limit) }}</span>
      </div>
      <div class="gc-bld-evo-bonus gc-mono">
        {% if (network.ascension_rank if network.ascension_rank is defined else 0)|int > 0 %}
          {{ T('research_network_lab_ascension', level=(network.lab_level if network.lab_level is defined else lab_level), rank=(network.ascension_roman if network.ascension_roman is defined else '')) }}
        {% else %}
          {{ T('research_network_lab_plain', level=(network.lab_level if network.lab_level is defined else lab_level)) }}
        {% endif %}
        {% if (network.research_speed_bonus_pct if network.research_speed_bonus_pct is defined else 0)|int > 0 %}
          · {{ T('research_network_speed', pct=network.research_speed_bonus_pct) }}
        {% endif %}
      </div>
      {% set next_unlock = network.next_unlock if network.next_unlock is defined and network.next_unlock else none %}
      {% if next_unlock %}
        <div class="hint">
          {% if next_unlock.kind == 'ascension' %}
            {{ T('research_network_next_ascension', rank=next_unlock.roman, level=next_unlock.lab_level, slots=next_unlock.slots) }}
          {% else %}
            {{ T('research_network_next_lab', level=next_unlock.lab_level, slots=next_unlock.slots) }}
          {% endif %}
        </div>
        {% if next_unlock.kind == 'ascension' and next_unlock.ready %}
          {% set tribute_m = network.next_tribute_metal if network.next_tribute_metal is defined else 0 %}
          {% set tribute_c = network.next_tribute_crystal if network.next_tribute_crystal is defined else 0 %}
          <button type="button" class="gc-btn gc-bld-evo-btn" data-research-network-ascend>
            {{ T('research_network_ascend', rank=next_unlock.roman) }}
          </button>
        {% endif %}
      {% else %}
        <div class="hint">{{ T('research_network_max') }}</div>
      {% endif %}
    </div>

    {{ render_page_mini_queue_strip(
'''
text = replace_once(text, needle, replacement, "research network block")
append = '''

{% block extra_scripts %}
{{ super() }}
<script src="{{ url_for('static', filename='js/pages/research_network.js') }}?v={{ GC_ASSET_VERSION }}"></script>
{% endblock %}
'''
if "js/pages/research_network.js" not in text:
    text += append
write(rel, text)


# ---------------------------------------------------------------------------
# Building card — compact visibility into capacity + per-planet Ascension gate.
# ---------------------------------------------------------------------------
rel = "templates/buildings.html"
text = read(rel)
needle = '''          {{ render_building_effect_bundle(b) }}

          {% if _evo %}
'''
replacement = '''          {{ render_building_effect_bundle(b) }}

          {% if building_type == 'research_lab' and b.research_lab_ascension is defined and b.research_lab_ascension %}
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

          {% if _evo %}
'''
text = replace_once(text, needle, replacement, "building research lab block")
write(rel, text)


# ---------------------------------------------------------------------------
# Owner payload: include exact next tribute for /research display/API consumers.
# ---------------------------------------------------------------------------
rel = "game/research_lab_ascension.py"
text = read(rel)
needle = '''        elif rank < MAX_ASCENSION_RANK:
            next_rank = rank + 1
            gate = required_level_for_rank(next_rank)
            next_unlock = {
                "kind": "ascension",
                "rank": next_rank,
                "roman": roman_rank(next_rank),
                "lab_level": gate,
                "slots": min(PRESTIGE_SLOT_CAP, BASE_SLOT_CAP + next_rank),
                "ready": level >= gate,
            }

        return {
'''
replacement = '''        elif rank < MAX_ASCENSION_RANK:
            next_rank = rank + 1
            gate = required_level_for_rank(next_rank)
            next_unlock = {
                "kind": "ascension",
                "rank": next_rank,
                "roman": roman_rank(next_rank),
                "lab_level": gate,
                "slots": min(PRESTIGE_SLOT_CAP, BASE_SLOT_CAP + next_rank),
                "ready": level >= gate,
            }

        next_tribute_metal = 0
        next_tribute_crystal = 0
        if next_unlock and next_unlock.get("kind") == "ascension":
            next_tribute_metal, next_tribute_crystal = tribute_cost_for_rank(
                int(next_unlock.get("rank") or 0)
            )

        return {
'''
text = replace_once(text, needle, replacement, "network tribute prep")
needle = '''            "research_speed_bonus_pct": int(rank * 2),
            "next_unlock": next_unlock,
        }
'''
replacement = '''            "research_speed_bonus_pct": int(rank * 2),
            "next_tribute_metal": int(next_tribute_metal),
            "next_tribute_crystal": int(next_tribute_crystal),
            "next_unlock": next_unlock,
        }
'''
text = replace_once(text, needle, replacement, "network tribute payload")
write(rel, text)


# ---------------------------------------------------------------------------
# Locale-only player copy.
# ---------------------------------------------------------------------------
append_json_keys("locales/de.json", {
    "research_network_title": "FORSCHUNGSNETZWERK",
    "research_network_jobs": "{count} / {limit} Forschungsaufträge",
    "research_network_lab_ascension": "Labor {level} · Ascension {rank}",
    "research_network_lab_plain": "Labor {level}",
    "research_network_speed": "Ascension-Forschungsbonus +{pct} %",
    "research_network_next_lab": "Nächster Queue-Slot: Forschungslabor {level} → {slots} Slots",
    "research_network_next_ascension": "Nächster Queue-Slot: Ascension {rank} bei Labor {level} → {slots} Slots",
    "research_network_ascend": "ASCENSION {rank} AKTIVIEREN",
    "research_network_max": "Forschungsnetzwerk vollständig ausgebaut · 10 Prestige-Slots",
    "research_network_capacity": "Queue-Kapazität: {slots}",
    "research_network_rank_speed": "Ascension {rank} · +{pct} % Forschungsgeschwindigkeit",
    "research_network_ready": "Ascension {rank} bereit",
    "research_network_requires": "Ascension {rank} bei Labor {level}",
    "research_network_error_generic": "Forschungsnetzwerk-Ascension fehlgeschlagen.",
    "research_network_error_level_too_low": "Das Forschungslabor hat die benötigte Stufe noch nicht erreicht.",
    "research_network_error_insufficient_resources": "Nicht genug Ressourcen für den Ascension-Tribut.",
    "research_network_error_queue_pending": "Laufende Forschungslabor-Upgrades zuerst abschließen oder abbrechen.",
    "research_network_error_max_ascension": "Ascension V ist bereits erreicht.",
    "research_network_error_ascension_race": "Ascension wurde bereits verarbeitet. Zustand wird aktualisiert."
})
append_json_keys("locales/en.json", {
    "research_network_title": "RESEARCH NETWORK",
    "research_network_jobs": "{count} / {limit} research orders",
    "research_network_lab_ascension": "Lab {level} · Ascension {rank}",
    "research_network_lab_plain": "Lab {level}",
    "research_network_speed": "Ascension research bonus +{pct}%",
    "research_network_next_lab": "Next queue slot: Research Lab {level} → {slots} slots",
    "research_network_next_ascension": "Next queue slot: Ascension {rank} at Lab {level} → {slots} slots",
    "research_network_ascend": "ACTIVATE ASCENSION {rank}",
    "research_network_max": "Research network fully expanded · 10 prestige slots",
    "research_network_capacity": "Queue capacity: {slots}",
    "research_network_rank_speed": "Ascension {rank} · +{pct}% research speed",
    "research_network_ready": "Ascension {rank} ready",
    "research_network_requires": "Ascension {rank} at Lab {level}",
    "research_network_error_generic": "Research network ascension failed.",
    "research_network_error_level_too_low": "The Research Lab has not reached the required level yet.",
    "research_network_error_insufficient_resources": "Not enough resources for the Ascension tribute.",
    "research_network_error_queue_pending": "Finish or cancel pending Research Lab upgrades first.",
    "research_network_error_max_ascension": "Ascension V is already reached.",
    "research_network_error_ascension_race": "Ascension was already processed. Refreshing state."
})

print("research network ascension patch applied")
