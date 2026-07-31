# Technical Card UX — Aussage statt Prozent (GC-TECHCARD-UX-001)

Kanonischer UX-Contract für technische Modals (Gebäude + Forschung). Owner: [`game/technical_data.py`](technical_data.py) (`impact` on `summary`). Renderer: `static/main.js` → `renderTechnicalImpactSummary`. Display math remains server-side ([GC-823_TECHNICAL_DATA.md](GC-823_TECHNICAL_DATA.md)).

## Four questions

Every technical detail summary answers:

1. **What does it do?** — `impact.blurb_key` (locale description)
2. **What do I have now?** — `impact.current` (gameplay unit)
3. **What does the next level give?** — `impact.next` from → to + delta (+ optional `delta_pct`)
4. **Where does it apply?** — `impact.affects[]` (locale keys)

Percent alone is forbidden as the primary statement. Percent may appear only as `delta_pct` / secondary hint.

## Payload

```json
{
  "impact": {
    "blurb_key": "desc_metal_mine",
    "current": { "label_key": "techcard_current", "value": "18540", "unit": "/h", "display": "18.540/h" },
    "next": {
      "label_key": "techcard_next_level",
      "from": "18540",
      "to": "19096",
      "delta": "556",
      "delta_pct": 3.0,
      "unit": "/h",
      "from_display": "18.540/h",
      "to_display": "19.096/h",
      "delta_display": "+556/h"
    },
    "affects": [{ "label_key": "building_metal_mine" }, { "label_key": "nav_overview" }],
    "example": { "kind": "rate|duration|capacity|slots|unlock|energy", "...": "domain fields" }
  }
}
```

## Domain rules

| Domain | Primary unit | Notes |
|--------|--------------|--------|
| Mines | `/h` | Planet-context production |
| Storage | capacity | Same as HUD caps |
| Energy (solar) | energy points | Generation |
| Yard / defense factory | ships or units / cycle | Not bare `%` |
| Nanofactory | build seconds (longest next upgrade on planet) | Marginal vs cumulative; excludes nanofactory self-upgrade |
| Command Center | nanofactory upgrade seconds only | Never mine times |
| Research eco | production / storage / build seconds | Via EffectResolver |
| Research fleet | slots / speed factor / fuel | Via fleet helpers |
| Research combat | reference ship stats | Via combat bonus |
| Interstellar / PE reach | unlock / reach label | No bare “+2 DNA” as sole line |

## Forbidden

- Frontend production / fleet / combat / queue formulas
- Parallel display engine beside `technical_data`
- Mixing Command Center into normal-building nano previews

## Effective unit stats (GC-EFFSTAT)

Ship/defense/fleet catalog surfaces follow the same contract: **effective value first**, net total `%` as secondary badge (`build_effective_stat`). See [EFFECTS.md](EFFECTS.md) § Effective Stat Display.

## Tests

```bash
python -m pytest tests/test_gc_techcard_ux.py tests/test_gc_effstat.py -q
```
