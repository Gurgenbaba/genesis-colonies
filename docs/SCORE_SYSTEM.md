# Score System — Progression Ranking & Big-Number Contract

> **Kanonische Regel:** `score_total` misst **dauerhaft investierten Imperiums-Fortschritt**. Liquide Lagerbestände sind ein eigener Wealth-Wert und erhöhen den Hauptrang nicht.

Owner: `game/ranking.py` · Ressourcenbewertung: `game/resource_score.py` · Persistenz: `player_scores`

---

## Hauptscore

```text
score_total
  = score_buildings
  + score_research
  + score_fleet
  + score_defense
  + score_planet_evolution
```

Nicht Bestandteil von `score_total`:

- `score_resources` — aktueller liquider Lagerwert
- `score_destroyed` — Lifetime Combat Prestige
- `score_combat` — aktive Militärstärke (`fleet + defense`)

Damit erzeugt bloßes Horten keine Progressionspunkte. Wer Ressourcen in Gebäude, Forschung, Flotte, Defense oder Planet Evolution investiert, erhöht den Progressionsscore.

---

## Kanonische Ressourcenbewertung (3:2:1)

`game/resource_score.py` bleibt die gemeinsame Umrechnung für Kosten und Liquid Wealth:

| Ressource | Punkte pro Einheit |
|-----------|-------------------:|
| Ferronit (`metal`) | 1 / 1 500 |
| Crytite (`crystal`) | 1 / 1 000 |
| Brennzellen (`fuel_cells`) | 1 / 500 |

```text
score_points(metal, crystal, fuel_cells)
  = floor(metal / 1500)
  + floor(crystal / 1000)
  + floor(fuel_cells / 500)
```

`score_resources` benutzt diese Formel, bleibt aber **außerhalb** von `score_total`.

---

## Komponenten

| Spalte | Bedeutung |
|--------|-----------|
| `score_resources` | Liquider Lagerwert aller Planeten; separates Wealth-Signal |
| `score_buildings` | kumulierte investierte Gebäudekosten |
| `score_research` | kumulierte investierte Forschungskosten |
| `score_fleet` | Schiffsbestand × kanonische Baukosten |
| `score_defense` | Defensebestand × kanonische Baukosten |
| `score_planet_evolution` | investierte Planet-Evolution-Kosten |
| `score_total` | Summe der fünf Progressionskomponenten |
| `score_combat` | `score_fleet + score_defense` |
| `score_destroyed_raw` | rohe Lifetime-Zerstörungsleistung |
| `score_destroyed` | Lifetime Combat Prestige; nicht im Total |

### Ranking-Tabs

| Tab | Inhalt |
|-----|--------|
| Gesamtpunkte | investierter Progressionsscore |
| Ressourcen / Wealth | liquide Ressourcen, separat |
| Gebäude / Forschung / Evolution / Fleet / Defense | Progressionskomponenten |
| Combat / Destroyed / Military | Militär- und Prestige-Signale |
| World Boss | Lifetime Damage; kein Progressionsscore |
| Allianz | Summe der `score_total`-Werte der Mitglieder |

---

## Arbitrary-Precision Contract (GC-SCORE-BIGNUM)

Ranking-Scores haben **keine künstliche Gameplay-Obergrenze**.

### Server

- Python `int` ist die autoritative Repräsentation für Score-Mathematik, Vergleiche, Sortierung und Allianz-Aggregation.
- Es gibt kein `MAX_SCORE = 9_000_000_000_000_000` mehr.
- Score-Sortierung und Score-Summen dürfen nicht über SQLite-Numeric-Coercion entscheiden, sobald arbitrary-precision Werte beteiligt sind.
- Noobschutz benutzt reine Integer-Arithmetik; keine Float-Division aus Score-Werten.
- Pirate-Threat liest Score-Werte als Python `int`, bevor logarithmische, gedeckelte Threat-Werte berechnet werden.

### Persistenz

Migration `154_big_score_ranking.sql` speichert die Score-Felder als dezimale `TEXT`-Werte. Rank-Felder bleiben `INTEGER`.

Dadurch können Werte oberhalb von SQLite signed int64 (`9_223_372_036_854_775_807`) exakt gespeichert und wieder gelesen werden.

### API / Browser

JavaScript kann Integer oberhalb von `Number.MAX_SAFE_INTEGER` (`9_007_199_254_740_991`) nicht exakt als `Number` darstellen.

Deshalb gilt:

- JS-sichere Scores dürfen als JSON-Integer gesendet werden.
- JS-unsichere Scores werden als dezimale Strings gesendet.
- Display-Formatting verarbeitet diese Strings mit `BigInt`.
- Gameplay-Timer und andere Number-basierte Frontend-Arithmetik werden dadurch nicht global auf `BigInt` umgestellt.
- Große Scores werden kompakt/scientific dargestellt; ein künstliches `∞` gibt es nicht mehr.

---

## Read-Path / Performance Contract

Ranking bleibt auf der bestehenden Dirty-Batch-Architektur.

- Normale Ranking-Ticks verarbeiten Dirty-Batches.
- Full-Universe-Reconcile bleibt Admin-/Safety-Net-Verhalten und wird nicht wieder zum normalen Tick.
- Ranking-GETs und exakte Rank-Lookups dürfen keine fehlenden `player_scores`-Zeilen erzeugen.
- Vollständige Score-Sets werden read-only geladen und anschließend mit Python-Integern sortiert.
- Bei derzeit rund 122 Live-Spielern ist die exakte Python-Sortierung klein; wichtiger ist, keine lange SQLite-Schreibtransaktion auf dem Request-Pfad einzuführen.

---

## Live-Migrationsregel

`154_big_score_ranking.sql` baut `player_scores` in einer SQLite-Transaktion neu auf:

1. alte Score-Indizes entfernen,
2. neue Tabelle mit decimal `TEXT`-Scorefeldern erstellen,
3. vorhandene Werte per `CAST(... AS TEXT)` kopieren,
4. alte Tabelle ersetzen,
5. Rank-/Updated-Indizes wiederherstellen.

Der Migration Runner verwendet für SQLite `BEGIN IMMEDIATE` und Rollback bei Fehlern. Ein teilweise migriertes `player_scores` darf dadurch nicht als erfolgreicher Deploy gelten.

Nach Deployment muss der normale Score-Reconcile die bestehenden Spieler auf die neue Progressionsformel aktualisieren. Eine Score-Verschiebung gegenüber dem alten Wealth-Total ist dabei **beabsichtigt**, weil liquide Ressourcen nicht mehr im Progressionsranking zählen.

---

## Wichtige Scope-Grenze

GC-SCORE-BIGNUM macht das **Ranking-System** arbitrary-precision. Es ist **keine** vollständige Big-Number-Migration der gesamten Ressourcenökonomie.

`planets.metal`, `planets.crystal` und `planets.fuel_cells` sind derzeit SQLite `REAL`. Bei extrem großen Lagerbeständen können dort weiterhin IEEE-754-Präzisionsgrenzen auftreten. Das ist ein separates Economy-/Storage-Migrationsthema und darf nicht mit dem Ranking-Fix verwechselt werden.

---

## Regression Gates

Der PR-Gate prüft insbesondere:

- Score deutlich oberhalb von JS-safe Integer und SQLite int64,
- exakten Decimal-TEXT-Roundtrip,
- exakte Sortierung riesiger, nah beieinanderliegender Scores,
- 122-Spieler-Rankingszenario,
- Liquid Wealth verändert `score_total` nicht,
- Ranking-Read-Pfade bleiben write-free,
- Combat/Destroyed-Projektion bleibt erhalten,
- Noobschutz arbeitet mit arbitrary-precision Integern,
- Pirate-Threat akzeptiert Scores weit jenseits des Float-Bereichs,
- Browser-JavaScript besteht `node --check`,
- Huge-Number-Formatter erzeugt kein Fake-`∞`.

---

## Verwandte Systeme

- [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md)
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md)
- [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md)
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)
- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md)
- [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md)
- [GC-822_LIVE_ECONOMY_QA.md](GC-822_LIVE_ECONOMY_QA.md)
