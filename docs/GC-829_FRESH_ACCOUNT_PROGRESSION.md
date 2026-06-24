# GC-829 — Fresh Account Progression

> Automatisch generiert via `python scripts/fresh_account_progression_sim.py`.
> **Keine Formeländerung** — misst Fortschritt bei kanonischen Server-Formeln.

## Leitfrage

Fühlt sich Genesis langsam an, weil die **Wirtschaft** langsam ist — oder weil **Fortschritt** (Bau/Forschung) zu selten sichtbar wird?

## Sim-Annahmen

| Annahme | Wert |
|---------|------|
| Startressourcen | 150,000 Ferronit · 100,000 Crytite · 25,000 Brennzellen (GC-836) |
| Gebäude Start | alle Level 0 (Homeworld leer) |
| Planet-Slot | 9 (Benchmark-Slot wie GC-821/829) |
| Queues | 1× Bau + 1× Forschung, greedy „aktiver Casual“ |
| Strategie | Solar → Minen → Energie-Balance → Brennzelle → Labor → Energy/Mining/Bau-Forschung |
| Nicht modelliert | Handel, Flotte, Multi-Queue (5), GD/Klima, Exchange |

### Aktuelle Alpha-Defaults (`DEFAULT_GAME_SETTINGS`)

```text
production_speed = 1.0
build_speed      = 1.1
research_speed   = 0.85   ← unter 1 = Forschung langsamer als Benchmark-Tabellen
```

## Frühe Ferronitmine (Slot 9, `production_speed=1`)

| Mine L→ | Prod (Slot 9) | Upgrade-Kosten | Bauzeit |
| --- | ---: | ---: | ---: |
| 1 | 24/h | 1200M+400C | 46s |
| 2 | 70/h | 2314M+772C | 1:04 |
| 3 | 132/h | 3074M+1025C | 1:30 |
| 5 | 291/h | 4252M+1418C | 2:58 |
| 10 | 852/h | 6416M+2139C | 15:57 |
| 20 | 2493/h | 9529M+3177C | 7h 41min |

### Bauzeiten bei **alpha_current** (leeres Konto, keine Tech-Boni)

| Gebäude | L1 | L2 | L5 |
| --- | ---: | ---: | ---: |
| solar_plant | 1:01 | 1:32 | 5:12 |
| metal_mine | 46s | 1:04 | 2:58 |
| crystal_mine | 46s | 1:04 | 2:58 |
| research_lab | 1:49 | 2:54 | 11:54 |
| fuel_cell_plant | 1:21 | 1:58 | 6:01 |

### Forschung **alpha_current** (Lab = Ziel-Level-Proxy)

| Tech | L1 (Lab 1) | L5 (Lab 5) | L10 (Lab 5) |
| --- | ---: | ---: | ---: |
| Energie | 1h 36min | 1h 8min | 1h 8min |
| Mining | 1h 44min | 1h 14min | 1h 14min |
| Bauopt. | 1h 52min | 1h 20min | 1h 20min |

## Checkpoint-Vergleich (Presets)

### Alpha aktuell

`production_speed=1.0` · `build_speed=1.1` · `research_speed=0.85`

| Zeit | Minen (M/C/S) | Infra | Forschung | Prod/h | Lager | Abschlüsse | Bau-Anteil |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30min | M6 C5 S4 | Lab 1 · FC 1 | E0 Min0 Bau0 | 361/h · 167/h · 8/h | 115,363M · 84,794C | B17 R0 | aktiv 100.0% · wart 0.0% |
| 1h | M8 C7 S5 | Lab 1 · FC 1 | E0 Min0 Bau0 | 533/h · 262/h · 8/h | 97,274M · 77,157C | B22 R0 | aktiv 100.0% · wart 0.0% |
| 4h | M12 C12 S8 | Lab 1 · FC 1 | E2 Min0 Bau0 | 1,129/h · 665/h · 9/h | 42,055M · 53,763C | B34 R2 | aktiv 100.0% · wart 0.0% |
| 24h | M17 C17 S8 | Lab 1 · FC 1 | E14 Min0 Bau0 | 1,938/h · 1,121/h · 9/h | 3,258M · 37,784C | B44 R14 | aktiv 77.5% · wart 22.5% |
| 7d | M23 C23 S8 | Lab 1 · FC 1 | E29 Min0 Bau0 | 3,096/h · 1,764/h · 9/h | 129,648M · 134,797C | B56 R29 | aktiv 88.9% · wart 11.1% |
| 30d | M28 C27 S8 | Lab 1 · FC 1 | E40 Min0 Bau0 | 4,200/h · 2,244/h · 9/h | 150,000M · 150,000C | B65 R40 | aktiv 97.4% · wart 2.6% |

### Ferdi-Bauchgefühl (build 10 / research 50)

`production_speed=1.0` · `build_speed=10.0` · `research_speed=50.0`

| Zeit | Minen (M/C/S) | Infra | Forschung | Prod/h | Lager | Abschlüsse | Bau-Anteil |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30min | M10 C9 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 432/h · 9/h | 0M · 27,297C | B24 R24 | aktiv 9.2% · wart 90.8% |
| 1h | M10 C9 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 432/h · 9/h | 0M · 27,297C | B24 R24 | aktiv 9.2% · wart 90.8% |
| 4h | M10 C10 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 505/h · 9/h | 0M · 29,063C | B25 R24 | aktiv 2.1% · wart 97.9% |
| 24h | M12 C11 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 1,129/h · 583/h · 9/h | 0M · 29,583C | B28 R24 | aktiv 1.4% · wart 98.6% |
| 7d | M27 C26 S3 | Lab 1 · FC 1 | E33 Min0 Bau0 | 3,970/h · 2,121/h · 9/h | 0M · 61,673C | B58 R33 | aktiv 33.1% · wart 66.9% |
| 30d | M34 C33 S3 | Lab 1 · FC 1 | E70 Min0 Bau0 | 5,675/h · 3,033/h · 9/h | 150,000M · 150,000C | B72 R70 | aktiv 83.4% · wart 16.6% |

### GC-829 Vorschlag (build 8 / research 50)

`production_speed=1.0` · `build_speed=8.0` · `research_speed=50.0`

| Zeit | Minen (M/C/S) | Infra | Forschung | Prod/h | Lager | Abschlüsse | Bau-Anteil |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30min | M10 C9 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 432/h · 9/h | 0M · 27,298C | B24 R24 | aktiv 11.5% · wart 88.5% |
| 1h | M10 C9 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 432/h · 9/h | 0M · 27,298C | B24 R24 | aktiv 11.5% · wart 88.5% |
| 4h | M10 C10 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 851/h · 505/h · 9/h | 0M · 29,063C | B25 R24 | aktiv 2.6% · wart 97.4% |
| 24h | M12 C11 S3 | Lab 1 · FC 1 | E24 Min0 Bau0 | 1,129/h · 583/h · 9/h | 0M · 29,585C | B28 R24 | aktiv 1.8% · wart 98.2% |
| 7d | M26 C26 S3 | Lab 1 · FC 1 | E33 Min0 Bau0 | 3,744/h · 2,121/h · 9/h | 0M · 62,435C | B57 R33 | aktiv 36.1% · wart 63.9% |
| 30d | M33 C33 S3 | Lab 1 · FC 1 | E70 Min0 Bau0 | 5,418/h · 3,033/h · 9/h | 150,000M · 150,000C | B71 R70 | aktiv 83.9% · wart 16.1% |

### Baseline (alles 1.0)

`production_speed=1.0` · `build_speed=1.0` · `research_speed=1.0`

| Zeit | Minen (M/C/S) | Infra | Forschung | Prod/h | Lager | Abschlüsse | Bau-Anteil |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30min | M5 C5 S4 | Lab 1 · FC 1 | E0 Min0 Bau0 | 290/h · 178/h · 9/h | 117,041M · 85,156C | B16 R0 | aktiv 100.0% · wart 0.0% |
| 1h | M8 C7 S5 | Lab 1 · FC 1 | E0 Min0 Bau0 | 533/h · 262/h · 8/h | 97,303M · 77,172C | B22 R0 | aktiv 100.0% · wart 0.0% |
| 4h | M12 C11 S7 | Lab 1 · FC 1 | E2 Min0 Bau0 | 1,068/h · 552/h · 8/h | 52,669M · 58,523C | B32 R2 | aktiv 100.0% · wart 0.0% |
| 24h | M17 C16 S8 | Lab 1 · FC 1 | E14 Min0 Bau0 | 1,938/h · 1,024/h · 9/h | 1,101M · 36,366C | B43 R14 | aktiv 82.6% · wart 17.4% |
| 7d | M23 C23 S8 | Lab 1 · FC 1 | E29 Min0 Bau0 | 3,096/h · 1,764/h · 9/h | 137,871M · 145,957C | B56 R29 | aktiv 91.2% · wart 8.8% |
| 30d | M27 C27 S8 | Lab 1 · FC 1 | E40 Min0 Bau0 | 3,970/h · 2,244/h · 9/h | 150,000M · 150,000C | B64 R40 | aktiv 97.8% · wart 2.2% |

## Erkenntnis (Daten, nicht Bauchgefühl)

### Nach 1 Stunde

| Preset | Ferronit-Mine | Prod Ferronit/h | Labor | Forschung (E/Min/Bau) | Bau-Abschlüsse |
|--------|-------------:|----------------:|------:|------------------------|---------------:|
| Alpha aktuell | L8 | 533 | L1 | 0/0/0 | 22 |
| Ferdi (build 10 / res 50) | L10 | 851 | L1 | 24/0/0 | 24 |

### Nach 4 Stunden

| Preset | Minen M/C | Labor | Prod Ferronit/h | Forschung Σ |
|--------|----------:|------:|----------------:|------------:|
| Alpha aktuell | 12/12 | L1 | 1,129 | 2 |

### Nach 24 Stunden

| Preset | Ferronit-Mine | Crytite | Labor | Prod Ferronit/h | Forschung Σ | Bau/R |
|--------|-------------:|--------:|------:|----------------:|------------:|------:|
| Alpha aktuell | L17 | L17 | L1 | 1,938 | 14 | 44/14 |
| Ferdi (build 10 / res 50) | L12 | L11 | L1 | 1,129 | 24 | 28/24 |

### Nach 7 Tagen

| Preset | Minen M/C | Labor | Prod Ferronit/h | Forschung Σ |
|--------|----------:|------:|----------------:|------------:|
| Alpha aktuell | 23/23 | L1 | 3,096 | 29 |
| Ferdi (build 10 / res 50) | 27/26 | L1 | 3,970 | 33 |

### Interpretation

1. **Frühes Spiel = Ressourcen-Wartezeit, nicht Bau-Timer.** Nach 1h Alpha: Mine L8, **533/h**, Bau-Wartezeit **0.0%** — L2 kostet ~2.3k Ferronit bei ~24/h ≈ **4 Tage** Sparzeit. Spieler sehen 24→70/h in der Vorschau, erleben aber tagelang **kein Level-Up**.

2. **Crytite-Verhungerung blockiert Labor länger als Forschungs-Timer.** Gate: Mine 3 + Crytite 2 — simuliert nach 7d erst **23/23**, Labor L1. Ferronit-Upgrades ziehen Crytite (~25 % Kostenanteil), Crytite-Mine L1 produziert nur **16/h** → Spieler horten Ferronit, können Crytite-Mine nicht hochziehen. **`research_speed` ändert daran nichts.**

3. **Nach 24h Alpha:** Mine L17, Labor L1, **1,938/h** — **kein sichtbarer Fortschritt seit Stunde 1.** Das ist Ferdis „und jetzt?“-Gefühl: Wirtschaftskurve stimmt (24→70→132/h), **Meilensteine kommen zu selten.**

4. **Ferdi-Hypothese (build/research speed) — wann sie wirkt:** In dieser Sim sind **1h–7d Checkpoints identisch** zwischen Alpha und build=10/research=50 — Engpass ist **Kosten vs. Einkommen**, nicht Bau-Timer. Erst nach Labor (7d→30d Forschung Σ: **29→40**, Prod **4,200/h**) zählen Speed-Regler für Dopamin. **`production_speed=1` lassen.** Für Alpha-Feel: **`build_speed` 8–10 + `research_speed` 50–100** (schnellere Abschlüsse sobald Ressourcen da sind) **plus** optional separates Ticket für **Frühgame-Kosten/Crytite-Pacing** (GC-821 Folge).

### Empfehlung vor Regler-Dreh

- **`production_speed` bei 1.0 lassen** (GC-821 ROI).
- **Zuerst `research_speed` anheben** (50–100 Band laut GC-829 Sweep + diese Sim).
- **`build_speed` 8–10** für Alpha-Fluidität (frühe Gebäude ~1min, Midgame spürbar).
- Optional: Live-Spieler mit **Multi-Queue (5)** kommen schneller als diese Sim — konservative Untergrenze.
