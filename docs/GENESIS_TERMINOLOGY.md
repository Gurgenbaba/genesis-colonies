# Genesis Colonies — Official Terminology (GC-900)

Single source of truth for player-facing language in **DE** and **EN**.  
Code keys (`metal_mine`, `shipyard`, …) stay stable — only **display strings** use this canon.

---

## Resources

| Concept | Deutsch | English | Forbidden |
|---------|---------|---------|-----------|
| Primary ore | **Ferronit** | **Ferronite** | Metal, Metall (UI) |
| Crystal ore | **Crytite** | **Crytite** | Crystal (UI) |
| Fuel | **Brennzellen** | **Fuel Cells** | Deuterium, Deuterium |
| Power | **Energie** | **Energy** | — |

Short labels: **FN** / **CT** (unchanged).

---

## Core buildings

| Code key | Deutsch | English | Forbidden (DE UI) |
|----------|---------|---------|-------------------|
| `orbital_shipyard` / `shipyard` | **Orbitalwerft** | **Orbital Shipyard** | Shipyard (DE), Werft alone in titles |
| `defense_factory` | **Verteidigungsfabrik** | **Defense Factory** | — |
| `command_center` | **Kommandozentrale** | **Command Center** | HQ |
| `research_lab` | **Forschungslabor** | **Research Lab** | — |
| `shield_generator` | **Planetarer Schildgenerator** | **Planetary Shield Generator** | — |
| `metal_mine` | **Ferronit-Mine** | **Ferronite Mine** | Metal Mine |
| `crystal_mine` | **Crytite-Extraktor** | **Crytite Extractor** | Crystal Mine |

---

## Research (account tech)

| Code key | Deutsch | English | Forbidden |
|----------|---------|---------|-----------|
| `mining_tech` | **Ferronit-Veredelung** | **Ferronite Refinement** | Mining Tech, Metal Refinement |
| `crystal_tech` | **Crytite-Synthese** | **Crytite Synthesis** | Crystal Tech |
| `drone_tech` | **Drohnenoptimierung** | **Drone Optimization** | — |
| Extraction line | **Extraktionstechnologie** | **Extraction Technology** | Mining Tech (generic) |

Effect copy: describe **what improves** (e.g. “Increases Ferronite production on this colony by 10%”), not bare “+10%”.

---

## Planet Evolution

| Concept | Deutsch | English | Forbidden |
|---------|---------|---------|-----------|
| Path choice (industry T2) | **Extraktionspfad** | **Extraction Path** | Abbau-Pfad, Mining Path, Resource Path |
| Permanent branch | **Planetare Spezialisierung** | **Planetary Specialization** | — |
| Industry branch | **Industriezweig** | **Industrial Focus** | Upgrade Path |
| Planet identity | **Planetarer Fokus** | **Planetary Focus** | Dev Path (player text) |
| Orbital branch | **Orbitale Extraktion** | **Orbital Extraction** | Orbitalabbau (legacy) |
| Deep branch | **Tiefkern-Extraktion** | **Deep Core Extraction** | Tiefkern alone |

---

## Style rules

1. **Titles** — short (1–4 words).
2. **Descriptions** — 1–2 sentences, player benefit clear.
3. **Tooltips** — answer: what it does, why build it, what you gain.
4. **EN locale** — natural English only; no German strings, no “Ferronit”.
5. **DE locale** — no OGame loanwords (Metal, Crystal, Deuterium, Shipyard as DE label).
6. **No dev jargon** in UI — no “schema”, “payload”, “migration” (use admin-only phrasing if unavoidable).

---

## HTTP / admin (internal)

| Item | Label |
|------|--------|
| Ranking batch | Ranking aktualisieren / Update Ranking |
| Cron (ops) | `[ranking-http-cron]` logs — not player-facing |

---

## Maintenance

- New UI strings: add **both** `locales/de.json` and `locales/en.json`.
- Run: `python scripts/gc900_harmonize_locales.py` after bulk imports.
- Tests: `python -m pytest tests/test_gc900_terminology.py -q`
