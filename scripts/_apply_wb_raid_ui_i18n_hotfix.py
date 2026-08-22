from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = ROOT / "templates" / "world_boss.html"
CSS = ROOT / "static" / "style.css"

BLOCK = '''                {% if raid %}
                <section class="gc-world-boss-raid-strip" data-wb-raid-state
                         aria-label="{{ T('wb_raid_status', 'Raid-Status') }}">
                  <div class="gc-world-boss-raid-strip__head">
                    <strong class="gc-world-boss-raid-strip__title gc-mono">{{ T("wb_raid_status", "Raid-Status") }}</strong>
                    <div class="gc-world-boss-raid-strip__badges">
                      {% if raid.containment and raid.containment.active %}
                      <span class="gc-world-boss-status-badge" data-wb-containment>
                        🛡 {{ T("wb_raid_containment", "Eindämmung") }} ·
                        <span data-countdown-at="{{ raid.containment.ends_at|int }}" data-countdown-format="eta">—</span>
                      </span>
                      {% endif %}
                      {% if raid.last_stand and raid.last_stand.active %}
                      <span class="gc-world-boss-status-badge gc-world-boss-status-badge--active" data-wb-last-stand>
                        🚨 {{ T("wb_raid_last_stand", "Letztes Aufgebot") }} +25%
                      </span>
                      {% endif %}
                    </div>
                  </div>

                  {% if raid.resonance %}
                  <div class="gc-world-boss-raid-strip__meter">
                    <div class="gc-world-boss-raid-strip__label-row">
                      {% if raid.resonance.active %}
                      <span class="gc-world-boss-status-badge gc-world-boss-status-badge--active" data-wb-resonance-active>
                        ⚡ {{ T("wb_raid_resonance", "Flottenresonanz") }} +50% ·
                        <span data-countdown-at="{{ raid.resonance.ends_at|int }}" data-countdown-format="eta">—</span>
                      </span>
                      {% else %}
                      <span class="gc-world-boss-raid-strip__label">⚡ {{ T("wb_raid_resonance", "Flottenresonanz") }}</span>
                      <span class="gc-mono" data-wb-resonance-label>{{ raid.resonance.points }} / {{ raid.resonance.threshold }}</span>
                      {% endif %}
                    </div>
                    <div class="gc-world-boss-hp gc-world-boss-raid-strip__bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{{ raid.resonance.progress_pct|int }}" data-wb-resonance-meter>
                      <div class="gc-world-boss-hp-fill" data-wb-resonance-fill style="width:{{ raid.resonance.progress_pct }}%;"></div>
                    </div>
                  </div>
                  {% endif %}

                  {% if raid.target_lock %}
                  <div class="gc-world-boss-raid-strip__meter">
                    <div class="gc-world-boss-raid-strip__label-row">
                      <span class="gc-world-boss-raid-strip__label">🎯 {{ T("wb_raid_target_lock", "Zielerfassung") }}</span>
                      <span class="gc-mono">{{ raid.target_lock.charge }}%</span>
                    </div>
                    <div class="gc-world-boss-hp gc-world-boss-raid-strip__bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{{ raid.target_lock.charge|int }}" data-wb-target-lock-meter>
                      <div class="gc-world-boss-hp-fill" data-wb-target-lock-fill style="width:{{ raid.target_lock.charge }}%;"></div>
                    </div>
                  </div>
                  {% endif %}
                </section>
                {% endif %}

'''

CSS_BLOCK = r'''

/* GC-WB-RAID-HUD-CANONICAL */
.gc-world-boss-raid-strip {
  position: relative;
  z-index: 4;
  display: grid;
  gap: .7rem;
  margin: .7rem 0 .8rem;
  padding: .8rem .9rem;
  border: 1px solid rgba(89, 221, 255, .34);
  border-radius: 0;
  background: rgba(3, 14, 27, .96);
  box-shadow: none;
}
.gc-world-boss-raid-strip__head,
.gc-world-boss-raid-strip__label-row { display:flex; gap:.6rem; align-items:center; justify-content:space-between; flex-wrap:wrap; min-width:0; }
.gc-world-boss-raid-strip__badges { display:flex; gap:.45rem; align-items:center; flex-wrap:wrap; }
.gc-world-boss-raid-strip__title { color:#74e8ff; font-size:.76rem; letter-spacing:.09em; text-transform:uppercase; }
.gc-world-boss-raid-strip__meter { display:grid; gap:.35rem; }
.gc-world-boss-raid-strip__label { color:#a9deea; font-weight:700; }
.gc-world-boss-raid-strip__bar { height:.72rem; min-height:.72rem; }
.gc-world-boss-raid-strip,
.gc-world-boss-raid-strip .gc-world-boss-status-badge,
.gc-world-boss-raid-strip .gc-world-boss-hp,
.gc-world-boss-raid-strip .gc-world-boss-hp-fill { border-radius:0 !important; }
'''

TR = {
    "de": {"wb_raid_status":"Raid-Status","wb_raid_containment":"Eindämmung","wb_raid_resonance":"Flottenresonanz","wb_raid_target_lock":"Zielerfassung","wb_raid_last_stand":"Letztes Aufgebot"},
    "en": {"wb_raid_status":"Raid Status","wb_raid_containment":"Containment","wb_raid_resonance":"Fleet Resonance","wb_raid_target_lock":"Target Lock","wb_raid_last_stand":"Last Stand"},
    "fr": {"wb_raid_status":"Statut du raid","wb_raid_containment":"Confinement","wb_raid_resonance":"Résonance de flotte","wb_raid_target_lock":"Verrouillage de cible","wb_raid_last_stand":"Dernier rempart"},
    "es": {"wb_raid_status":"Estado de incursión","wb_raid_containment":"Contención","wb_raid_resonance":"Resonancia de flota","wb_raid_target_lock":"Fijación de objetivo","wb_raid_last_stand":"Última resistencia"},
    "pl": {"wb_raid_status":"Status rajdu","wb_raid_containment":"Powstrzymanie","wb_raid_resonance":"Rezonans floty","wb_raid_target_lock":"Namierzanie celu","wb_raid_last_stand":"Ostatni bastion"},
    "tr": {"wb_raid_status":"Baskın Durumu","wb_raid_containment":"Sınırlama","wb_raid_resonance":"Filo Rezonansı","wb_raid_target_lock":"Hedef Kilidi","wb_raid_last_stand":"Son Direniş"},
    "ru": {"wb_raid_status":"Статус рейда","wb_raid_containment":"Сдерживание","wb_raid_resonance":"Резонанс флота","wb_raid_target_lock":"Захват цели","wb_raid_last_stand":"Последний рубеж"},
    "pt": {"wb_raid_status":"Estado da incursão","wb_raid_containment":"Contenção","wb_raid_resonance":"Ressonância da frota","wb_raid_target_lock":"Travamento de alvo","wb_raid_last_stand":"Última resistência"},
}


def add_locale_keys(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    missing = [k for k in values if k not in data]
    if not missing:
        return
    body = text.rstrip()
    assert body.endswith("}")
    body = body[:-1].rstrip()
    sep = "\n" if body.endswith(",") else ",\n"
    lines = []
    for i, key in enumerate(missing):
        comma = "," if i < len(missing)-1 else ""
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(values[key], ensure_ascii=False)}{comma}")
    path.write_text(body + sep + "\n".join(lines) + "\n}\n", encoding="utf-8")


def main() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index('                {% if raid %}\n      <section class="gc-world-boss-raid-strip" data-wb-raid-state')
    end = text.index('                {% if is_active %}', start)
    TEMPLATE.write_text(text[:start] + BLOCK + text[end:], encoding="utf-8")

    css = CSS.read_text(encoding="utf-8")
    if "/* GC-WB-RAID-HUD-CANONICAL */" not in css:
        CSS.write_text(css.rstrip() + CSS_BLOCK + "\n", encoding="utf-8")

    for locale, values in TR.items():
        add_locale_keys(ROOT / "locales" / f"{locale}.json", values)

    for locale, values in TR.items():
        data = json.loads((ROOT / "locales" / f"{locale}.json").read_text(encoding="utf-8"))
        for key, value in values.items():
            assert data.get(key) == value, (locale, key)

    rendered = TEMPLATE.read_text(encoding="utf-8")
    rs = rendered.index('<section class="gc-world-boss-raid-strip"')
    re = rendered.index('</section>', rs)
    raid = rendered[rs:re]
    for forbidden in ("border-radius", "Fleet Resonance", "Target Lock", "Containment", "Last Stand", 'style="position:'):
        assert forbidden not in raid, forbidden

if __name__ == "__main__":
    main()
