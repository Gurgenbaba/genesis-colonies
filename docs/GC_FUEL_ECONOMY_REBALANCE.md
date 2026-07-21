# GC-FUEL — Brennzellen als dritte strategische Ressource

> **Status:** Audit freigegeben (2026-07-19)  
> Epic-Kontext: EPIC-04 Economy · Parent: GC-FUEL-ECONOMY-REBALANCE-001  
> **Keine Live-Werte ändern**, bis das jeweilige Ticket explizit gestartet wird.

---

## Freigegebene Diagnose

Brennzellen sind nicht „zu stark wegen eines falschen Einzelwerts“. Sie sind zu stark, weil:

1. **Gebäude, Account-Forschung und Planet-Forschung** live praktisch **0 Fuel** verbrauchen.
2. **Early-/Expo-Schiffe** (u. a. Odyssey) oft **0 Bau-Fuel** haben.
3. **Flugkosten** im Verhältnis zu Produktion und Expo-Loot winzig sind.
4. **Expeditionen** netto Fuel **erzeugen** können (`fuel_cache`, Fuel-Splits).
5. **`fuel_efficiency`** die ohnehin schwache laufende Senke weiter senkt.
6. Einzelwerte wie `eclipse_runner` Bau-Fuel **62** nicht ernsthaft balanciert sind.

Simulierte Ist-Utilisation aktiver Profile: ca. **0–28 %** der Tagesproduktion.

---

## Locked Decisions

| # | Entscheidung |
|---|--------------|
| D1 | Wertbasis **3∶2∶1 behalten** — Owner `game/resource_score.py` / Trader-Defaults. Kein 20/14. |
| D2 | `resource_value = metal + crystal × 1.5 + fuel_cells × 3` überall als kanonische Vergleichsbasis. |
| D3 | Kosten **umschichten**, nicht pauschal aufschlagen (siehe § Umschichtung). |
| D4 | Strikte Phasenreihenfolge A→B→C→D; keine parallelen Live-Hebel. |
| D5 | Expo erst **nach** Units messen und retunen (Phase D). |
| D6 | Keine permanente Flottenwartung in dieser Serie. |
| D7 | Kein Wipe, keine Bestands-Entwertung, keine Zwangskonvertierung. |
| D8 | Hull-Fuel in **Defs**, nicht an Tech-Stufen koppeln. |
| D9 | Standard-Fuelproduktion: erst **Simulation A vs B**, nicht parallel zu allen Kostenänderungen. |

### Umschichtung (verbindlich für Buildings/Research)

```text
alter Gesamtwert (resource_value): 100 % aus Metal/Crytite

neuer Gesamtwert: ≈ gleicher resource_value
  z. B. 80 % Metal/Crytite-Wert + 20 % Fuel-Wert
```

Fuel wird aus dem bestehenden Wert herausgeschnitten, nicht obendrauf addiert — sonst Progressions-Nerf.

### Erste Zielphase Utilisation (Patch 1)

| Profil | Ziel Utilisation |
|--------|-----------------:|
| Early | 10–30 % |
| Standard Mid | 45–70 % |
| Fleet-/Expo-heavy | 70–110 % |
| Endgame-Massenbau | 90–130 % |

Endziel Standard-Mid 65–90 % erst nach Live-Daten / zweitem Pass.

### Early-Schiffe (Policy für GC-FUEL-UNITS-001)

| Gruppe | Fuel-Bau |
|--------|----------|
| Starter (z. B. spark_drone) | 0 |
| Frühe Transporter / Probe | sehr wenig |
| Odyssey (`solar_skiff`) | **relevant** |
| Erstes echtes Kampfschiff | moderat |
| Mid-/High-Tier | deutlich |
| Voidrunner (`eclipse_runner`) | hoch (62 → ernsthaft) |
| Recycler | moderat |
| Seed Ark | hoch |

---

## Produktions-Gate (vor/neben Phase B)

Zwei Szenarien **nur simulieren**, bevor Produktion live geändert wird:

| Szenario | Produktion | Senken |
|----------|------------|--------|
| **A** | Fuel-Standardboden bleibt (~5 000/h) | Senken steigen (Umschichtung) |
| **B** | Fuel-Standardboden sinkt (Zielband ~1 500–2 500/h); F/C behalten großzügigen Boden | Senken steigen **moderat** |

Entscheidung A vs B ist ein eigenes Freigabe-Gate (`GC-FUEL-PROD-SIM-001`), **nicht** Teil von CORE/BUILDINGS-Live-Zahlen.

---

## Ticket-Serie (Reihenfolge strikt)

```text
GC-FUEL-CORE-001      Infrastruktur (keine Live-Kosten)
GC-FUEL-PROD-SIM-001  Simulation A vs B (keine Live-Änderung)
GC-FUEL-BUILDINGS-001 Gebäude Fuel (Umschichtung)
GC-FUEL-RESEARCH-001  Account + Planet Research Fuel
GC-FUEL-UNITS-001     Schiffe + Defense
GC-FUEL-EXPO-001      Expo-Wert + Quellen-Retune (zuletzt)
```

---

## GC-FUEL-CORE-001 — 3-Resource Queue Infrastructure

> Epic: EPIC-04 · Phase A  
> **Noch keine Live-Kosten verändern.**

### Problem

Gebäude-/Research-/PE-Research-Queues und Spend/Refund können Fuel nicht speichern bzw. refunden. Ohne Infra keine sicheren Kostenänderungen.

### Betroffene Dateien (Richtwert; Scope im Ticket schärfen)

- `game/models.py` — `try_spend_resources(_conn)` um Fuel erweitern (oder kanonischen 3-Resource-Spender; Duplikate entfernen)
- `game/buildings.py` / `game/research.py` / `game/planet_evolution/planet_research.py` — Snapshot/Spend-Hooks vorbereiten
- `game/queue_refund.py` — Fuel-Refund für Build/Research/PE
- `game/economy_balance.py` — Cost-API auf `{metal, crystal, fuel_cells}` vorbereiten (Defaults fuel=0)
- Migration additiv: `build_queue`, `research_queue`, `planet_research_queue` + `cost_fuel_cells` (PE ggf. auch M/C-Snapshots)
- Templates/UI: Fuel-Kostenanzeige wenn > 0 (bereits bei Ship/Defense vorhanden — wiederverwenden)
- Tests

**Nicht:** Balance-Zahlen in Defs/Kurven ändern.

### Anforderungen

1. Kanoniches Spend unterstützt Fuel atomar (kein Teilabbuchung).
2. Queue-Snapshots speichern Fuel; Legacy-Jobs → Fuel 0.
3. Cancel refundiert Fuel aus Snapshot (100 %/50 % wie bestehend).
4. UI zeigt Fuel nur wenn > 0; keine Frontend-Kostenformel.
5. Bestehende Jobs ohne Fuel-Spalte bleiben kompatibel.

### Akzeptanzkriterien

- [ ] Migrationen additiv, keine alten Migrationen editiert
- [ ] Tests: spend / snapshot / refund / insufficient / legacy=0
- [ ] Live-Kosten aller Gebäude/Research bleiben **0 Fuel**
- [ ] Regel 19: kein zweiter Spend-Pfad neben Owner

---

## GC-FUEL-PROD-SIM-001 — Production Floor Simulation

> Phase Gate · **keine Live-Änderung**

### Problem

Standardboden ~5 000 Fuel/h (~120 k/Tag) ohne Plant. Unklar, ob Senken allein reichen (A) oder Boden sinken muss (B).

### Anforderungen

1. Profil-Simulation Early/Mid/End/Expo/PvP für Szenario A und B.
2. Bericht: Utilisation, Engpass, Tage-bis-Lager, Expo-Nettostrom.
3. Empfehlung A oder B zur Freigabe — erst danach Produktionscode anfassen (eigenes Micro-Ticket falls B).

---

## GC-FUEL-BUILDINGS-001 — Technical/Military Building Fuel

> Phase B · hängt an CORE-001

### Problem

Technische/militärische Gebäude verbrauchen kein Fuel, obwohl Identität = Energie/Betrieb.

### Regeln

- Umschichtung auf konstanten `resource_value` (± kleine Toleranz).
- Grundminen, Solar, frühe Lager: **0 Fuel**.
- Tech/Militär ab mittleren Stufen: Fuel-Anteil gemäß Audit-Staffelung (erste Phase konservativ → Mid-Utilisation 45–70 %).
- Owner: `economy_balance.power_upgrade_cost` liefert vollständige `{metal, crystal, fuel_cells}`.

### Nicht

- Pauschale Fuel-Steuer im Consumer
- Produktion gleichzeitig ändern
- Ships/Defense/Expo

---

## GC-FUEL-RESEARCH-001 — Account + Planet Research Fuel

> Phase B · hängt an CORE-001

### Regeln

- Umschichtung, nicht Aufschlag.
- High Fuel-Identität: energy, engine, fuel_efficiency, shield, navigation.
- Mid: weapon, armor, drone, buildtime.
- Low/0 früh: mining, storage.
- Account und Planet getrennt; Ranking-Cumulatives Fuel mitziehen.
- PE-Queue-Snapshots nutzen CORE-Migration.

---

## GC-FUEL-UNITS-001 — Ships + Defense Fuel Rebalance

> Phase C · nach Buildings/Research

### Regeln

- Pro-Hull / pro-Defense in Defs; **kein** Global-Multiplikator.
- Odyssey: relevanter Bau-Fuel; Voidrunner: hoch; Policy Early-Schiffe siehe oben.
- Defense: ballistisch ~0; Plasma/Ion/Flak mid; Barrieren/Orbital hoch.
- Umschichtung bevorzugt (Gesamtwert halten), außer klar unterbewertete Outlier (eclipse_runner).
- Scrapyard/Score folgen Defs automatisch.
- **Expo-Loot nicht in diesem Ticket retunen** — nur messen/loggen falls Tests betroffen.

---

## GC-FUEL-EXPO-001 — Expo Value + Fuel-Source Recalibration

> Phase D · **zuletzt**, nach Units + Messdaten

### Problem

`expo_value` nutzt Rohsumme M+C+F; Bau-Fuel-Erhöhung würde Loot mitziehen. Separat: Quellen (`fuel_cache`, Splits) können Surplus erzeugen.

### Anforderungen

1. `expo_hull_value` auf kanonische `resource_value` (3∶2∶1) umstellen — **ein** Owner, keine Parallelformel.
2. Loot-Faktor/Exponent/Caps **neu kalibrieren** (Regressionstabellen vor/nach).
3. Erst dann gezielt `fuel_cache` / Splits / optionale Einsatzkosten — keine Wartung.
4. Messbasis: Utilisation nach UNITS-001.

### Nicht

- Gebäude/Research/Ship-Defs erneut groß ändern
- Trader-Verhältnis ändern

---

## Explizit außerhalb dieser Serie

- Permanente Flottenwartung / Betriebskosten
- Bestands-Wipe / Soft-Delete Alt-Fuel
- Neues Trader-Verhältnis
- Frontend-Duplicate-Math

---

## Referenz

- Audit-Gespräch GC-FUEL-ECONOMY-REBALANCE-001 (2026-07-19)
- `game/resource_score.py` — kanonische Wertbasis
- `game/production_formula.py` — Standardboden + Mine
- `docs/ECONOMY_SYSTEM.md`, `docs/QUEUE_STATE_RULES.md`, `docs/CORE_ARCHITECTURE.md`
