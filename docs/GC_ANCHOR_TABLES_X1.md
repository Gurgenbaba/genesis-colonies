# Genesis Colonies — Ankerkurven (Code-Stand, Universum-Speed ×1)

**Referenz:** Galaxieslot 9 · Energie 100% · Forschung 0 · `production_speed=1` · `build_speed=1` · `research_speed=1`

## 1) Produktionsformel (GC-820)

```
Produktion/h = Basis × production_speed × Level^Exponent × Slot × Temperatur × Forschung × Energie × …
```

| Ressource | Basis | Exponent | Gebäude |
|-----------|-------|----------|---------|
| Ferronit | 24.0 | 1.55 | metal_mine |
| Crytite | 16.0 | 1.5 | crystal_mine |
| Brennzellen | 8.0 | 1.42 | fuel_cell_plant |

### Produktion/h (Slot 9, Speed ×1)

| Mine-Stufe | Ferronit/h | Crytite/h | Brennzellen/h |
|------------|------------|-----------|---------------|
| 10 | 852 | 506 | 242 |
| 20 | 2.5k | 1.4k | 647 |
| 30 | 4.7k | 2.6k | 1.2k |
| 40 | 7.3k | 4.0k | 1.7k |
| 60 | 14k | 7.4k | 3.1k |
| 80 | 21k | 11k | 4.6k |
| 100 | 30k | 16k | 6.4k |
| 120 | 40k | 21k | 8.2k |

### Produktionsgewinn pro Upgrade (+1 Stufe, Delta/h)

| Ziel-Stufe | Ferronit +/h | Crytite +/h | Brennzellen +/h |
|------------|--------------|-------------|-----------------|
| 10 | 128 | 74 | 34 |
| 20 | 191 | 106 | 45 |
| 30 | 239 | 130 | 54 |
| 40 | 281 | 151 | 61 |
| 60 | 352 | 185 | 73 |
| 80 | 413 | 214 | 82 |
| 100 | 467 | 239 | 90 |
| 120 | 517 | 262 | 97 |

## 2) Forschung — Ankerkurven (GC-825, vor Speed-Boni)

### Basis-Dauer (Energieeffizienz-Tier = 1,0)

| Forschungsstufe | Anker (h) | Dauer Speed ×1 |
|-----------------|-----------|----------------|
| 10 | 1.5 | 1.5 h |
| 20 | 5 | 5.0 h |
| 30 | 24 | 1.0 Tage |
| 40 | 72 | 3.0 Tage |
| 60 | 336 | 2.0 Wochen |
| 80 | 1080 | 1.5 Monate |
| 100 | 2160 | 3.0 Monate |
| 120 | 4320 | 6.0 Monate |

### Basis-Kosten (Energieeffizienz-Tier = 1,0)

| Forschungsstufe | Gesamt (Anker) | Ferronit | Crytite |
|-----------------|----------------|----------|---------|
| 10 | 2.5k | 1.7k | 834 |
| 20 | 10k | 6.7k | 3.3k |
| 30 | 22k | 15k | 7.3k |
| 40 | 40k | 27k | 13k |
| 60 | 120k | 80k | 40k |
| 80 | 400k | 267k | 133k |
| 100 | 1.20 Mio | 800k | 400k |
| 120 | 2.40 Mio | 1.60 Mio | 800k |

### Alle Technologien — Stufe 30 (Speed ×1, Labor L1, ohne Tech-Boni auf Zeit)

| Technologie | Ferronit | Crytite | Dauer | Tier Zeit | Tier Kosten |
|-------------|----------|---------|-------|-----------|-------------|
| armor_tech | 28k | 16k | 1.4 Tage | 1.42 | 2.00 |
| buildtime_tech | 22k | 12k | 11.6 h | 1.17 | 1.53 |
| drone_tech | 22k | 13k | 1.2 Tage | 1.25 | 1.60 |
| energy_tech | 15k | 7.3k | 1.0 Tage | 1.00 | 1.00 |
| engine_tech | 32k | 23k | 1.6 Tage | 1.58 | 2.53 |
| fuel_efficiency | 35k | 18k | 1.7 Tage | 1.67 | 2.40 |
| mining_tech | 18k | 8.8k | 1.1 Tage | 1.08 | 1.20 |
| navigation_tech | 29k | 22k | 1.5 Tage | 1.50 | 2.33 |
| shield_tech | 32k | 19k | 1.6 Tage | 1.58 | 2.33 |
| storage_tech | 12k | 12k | 22.0 h | 0.92 | 1.07 |
| weapon_tech | 26k | 13k | 1.3 Tage | 1.33 | 1.80 |

## 3) Minen-Upgrades — Kosten & Ziel-Amortisation (live)

Amortisation = Payback in **Produktionsstunden** der jeweiligen Ressource (Slot 9, Speed ×1).

### Ferronit-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 6.4k | 2.1k | 8.6k | 50 h |
| 20 | 9.5k | 3.2k | 13k | 50 h |
| 30 | 17k | 5.6k | 23k | 71 h |
| 40 | 28k | 9.4k | 37k | 100 h |
| 60 | 70k | 23k | 94k | 200 h |
| 80 | 206k | 69k | 275k | 500 h |
| 100 | 467k | 156k | 623k | 1000 h |
| 120 | 1.03 Mio | 344k | 1.38 Mio | 2000 h |

### Crytite-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 3.4k | 2.4k | 5.7k | 32 h |
| 20 | 5.0k | 3.5k | 8.5k | 33 h |
| 30 | 8.9k | 6.2k | 15k | 48 h |
| 40 | 15k | 10k | 25k | 68 h |
| 60 | 37k | 26k | 63k | 139 h |
| 80 | 109k | 76k | 185k | 354 h |
| 100 | 246k | 171k | 418k | 715 h |
| 120 | 545k | 379k | 924k | 1444 h |

### Brennzellen-Anlage

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 3.8k | 2.5k | 6.3k | 186 h |
| 20 | 5.6k | 3.7k | 9.3k | 204 h |
| 30 | 9.9k | 6.6k | 17k | 305 h |
| 40 | 16k | 11k | 27k | 448 h |
| 60 | 41k | 27k | 69k | 945 h |
| 80 | 121k | 81k | 201k | 2454 h |
| 100 | 273k | 182k | 456k | 5053 h |
| 120 | 605k | 403k | 1.01 Mio | 10350 h |

### Minen ROI-Anker (explizite Zielwerte GC-821F)

| Stufe | Ziel-Amortisation |
|-------|-------------------|
| 20 | 50 h |
| 40 | 100 h |
| 60 | 200 h |
| 80 | 500 h |
| 100 | 1000 h |
| 120 | 2000 h |

## 4) Alle Gebäude — Upgrade-Kosten gesamt (F+C, live)

| Stufe | metal_mine | crystal_mine | solar_plant | fuel_cell_plant | metal_storage | crystal_storage | fuel_storage | research_lab | academy | command_center | orbital_shipyard | defense_factory | barracks | radar_array | shield_generator | terraformer | nanofactory | geothermal_nexus | planet_core_nexus |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 8.6k | 5.7k | 5.6k | 6.3k | 13k | 13k | 11k | 22k | 30k | 36k | 35k | 41k | 21k | 23k | 60k | 83k | 114k | 128k | 174k |
| 20 | 13k | 8.5k | 15k | 9.3k | 38k | 38k | 32k | 62k | 85k | 101k | 98k | 116k | 59k | 63k | 171k | 242k | 332k | 374k | 514k |
| 30 | 23k | 15k | 28k | 17k | 69k | 69k | 58k | 114k | 158k | 184k | 181k | 214k | 107k | 115k | 317k | 452k | 623k | 701k | 967k |
| 40 | 37k | 25k | 42k | 27k | 106k | 106k | 89k | 177k | 245k | 282k | 278k | 329k | 164k | 176k | 490k | 704k | 974k | 1.10 Mio | 1.52 Mio |
| 50 | 60k | 40k | 58k | 44k | 148k | 148k | 124k | 249k | 344k | 392k | 389k | 460k | 229k | 245k | 688k | 992k | 1.38 Mio | 1.55 Mio | 2.15 Mio |

*Normaler Max-Level: 50*

## 5) Gebäude-Bauzeit — Design-Kurve (GC-821, vor Speed-Boni)

Formel: `TIME_K × Level^Exponent` · im Spiel ÷ `build_speed`

| Stufe | Ferronit | Crytite | Solar | Brennzellen | Labor | Werft | Command |
|-------|----------|---------|-------|-------------|-------|-------|---------|
| 10 | 43 Min | 43 Min | 48 Min | 55 Min | 1.2 h | 1.8 h | 2.0 h |
| 20 | 1.8 h | 1.8 h | 2.1 h | 2.4 h | 3.1 h | 4.8 h | 5.2 h |
| 30 | 3.1 h | 3.1 h | 3.6 h | 4.1 h | 5.5 h | 8.4 h | 9.1 h |
| 40 | 4.6 h | 4.6 h | 5.3 h | 6.1 h | 8.1 h | 12.6 h | 13.6 h |
| 60 | 8.0 h | 8.0 h | 9.1 h | 10.6 h | 14.2 h | 22.3 h | 1.0 Tage |
| 80 | 11.7 h | 11.7 h | 13.4 h | 15.6 h | 21.1 h | 1.4 Tage | 1.5 Tage |
| 100 | 15.9 h | 15.9 h | 18.1 h | 21.1 h | 1.2 Tage | 1.9 Tage | 2.0 Tage |
| 120 | 20.3 h | 20.3 h | 23.1 h | 1.1 Tage | 1.5 Tage | 2.5 Tage | 2.6 Tage |

## 6) Gebäude-Bauzeit — Live-Queue (Legacy, Speed ×1)

Aktuell serverseitig aktiv: `BUILD_TIME_BASE x Faktor^Stufe / build_speed` — weicht Midgame von Design-Kurve ab.

| Stufe | Ferronit | Crytite | Solar | Brennzellen | Labor | Werft |
|-------|----------|---------|-------|-------------|-------|-------|
| 10 | 18 Min | 18 Min | 44 Min | 42 Min | 2.3 h | 6.6 h |
| 20 | 8.5 h | 8.5 h | 1.7 Tage | 1.2 Tage | 1.5 Wochen | 1.8 Monate |
| 30 | 1.5 Wochen | 1.5 Wochen | 3.4 Monate | 1.7 Monate | 3.2 Jahre | 30.6 Jahre |
| 40 | 9.8 Monate | 9.8 Monate | 15.9 Jahre | 5.6 Jahre | 347.6 Jahre | 6162.1 Jahre |
| 50 | 23.4 Jahre | 23.4 Jahre | 916.6 Jahre | 230.4 Jahre | 38216.8 Jahre | 1242283.0 Jahre |

## 7) Speicher & Tausch

Speicher Basis L1: **150.000** · Wachstum **×1.75**/Stufe

| Lager-Stufe | Kapazität |
|-------------|-----------|
| 1 | 150k |
| 5 | 1.41 Mio |
| 10 | 23.09 Mio |
| 20 | 6220.34 Mio |
| 30 | 1675693.83 Mio |
| 40 | 451414139.08 Mio |
| 50 | 121606179561.53 Mio |

Tausch Tageslimit: min. **500.000** oder **80%** Imperiums-Tagesproduktion

## 8) Code-Anker (Rohwerte)

**Forschung Zeit:** L10=1.5h, L20=5.0h, L30=24.0h, L40=72.0h, L60=336.0h, L80=1080.0h, L100=2160.0h, L120=4320.0h

**Forschung Kosten:** L10=2.5k, L20=10k, L30=22k, L40=40k, L60=120k, L80=400k, L100=1.20 Mio, L120=2.40 Mio

**Minen ROI:** L20=50.0h, L40=100.0h, L60=200.0h, L80=500.0h, L100=1000.0h, L120=2000.0h