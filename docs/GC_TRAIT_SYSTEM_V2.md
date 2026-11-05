# Genesis Colonies — Trait System 2.0

**Status:** Release 1 (#547/#548) auf `main` gemerged und auf dem Main-Service ausgerollt. Release 2 wird in getrennten PRs aufgebaut; Scans und Resonanzen sind noch nicht aktiv.
Die Ausbaustufen unten sind ein Releaseplan, keine Behauptung bereits aktivierter Spielmechanik.

## Designziel

Planet-DNA muss eine strategische Weltidentität sein, nicht eine zufällige
Sackgasse. Der Spieler versteht: Was habe ich? Was ist verborgen? Was ermöglicht
der Trait? Wo in meinem Imperium gibt es eine passende Welt? Welchen Pfad
kann ich wählen, wenn ich ihn nicht finde?

## Bestehende Wahrheit (Owner)

- **DNA-Erzeugung:** `game/planet_evolution/dna.py`; deterministisch durch
  Koordinaten, Seed, Server-Salt und Planet-Klasse, gespeicherte Daten in `planet_dna`.
- **Definitionen:** `pe_trait_definitions` / `game/planet_evolution/definitions.py`.
- **Trait-Gates:** `requirements.py` (`traits_any` = mindestens eines aus Liste).
- **Spezialisierungen:** `specialization.py` (Trait-Gate *und* Mindest-Affinities).
- **Effekte:** nur kanonische Resolver und bestehende Planet-Mechanik-Consumer.
- **Offenlegung:** zuerst Etablierung, Level 3 und 15 für die regulären DNA-Stufen.
  Ein Trait wird nicht durch normales Forschen erschaffen. Keine freie DNA-Reroll-API.
- **Galaktische Traits** aus `galactic_diplomacy/` sind ein anderes System.

## Release 1 — Klarheit und Atlas (in PR #547 / Trait-Atlas-V2-Branch)

1. Gesperrte Planet-Techs nennen exakt die erforderlichen Traits, nicht nur
   "matching planet trait"; eine Alternativliste bedeutet **ODER**, nicht UND.
2. Die Planet-Übersicht zeigt offengelegte Traits und die bestehenden Effekte.
3. Ein ausklappbarer Trait-Atlas zeigt **alle definierbaren** Traits mit
   Seltenheit, Kategorie, effektiver Beschreibung, gebundenen Planet-Techs und
   Spezialisierungen.
4. Pro Trait wird unterschieden: auf aktiver Welt bekannt / auf eigener anderer
   Welt bekannt / derzeit im Imperium nicht entdeckt.
5. Fundortnamen beziehen sich **ausschließlich auf bekannte, bereits enthüllte
   Traits eigener Kolonien**. Kein Offenlegen fremder Spieler-DNA oder
   nicht enthüllter Traits. Leere / noch nicht etablierte Welten bleiben geschützt.
6. Ein serverseitiger Bulk-Read über alle eigenen Planeten vermeidet N×M Queries
   und der Atlas nutzt bereits geladene Definition-Caches.
7. Alle acht Lokalisierungen erhalten identische Keys.
8. Planet-State und Spezialisierungs-Synergievorschau maskieren DNA bis zur
   Etablierung auch **in der API**, nicht nur im Template.
9. Vor DNA-Enthüllung (Tier 0) dürfen Trait-Forschungs-Gates,
   Spezialisierungsbewertungen und der kompilierte Trait-Flag-State keine
   versteckten DNA-Schlüssel verwenden. Ab Tier 1 gilt die bestehende
   kanonische Trait-Logik; bestehende DNA bleibt unverändert.

## Release 2 — Entdeckungsloop (in Schritten, teils implementiert)

- **R2A (dieser PR):** Auf dem Planeten zeigt der Trait-Atlas einen serverseitigen Level-3-bis-15-Fortschritt mit nativem, zugänglichem `<progress>`-Element. Vor Etablierung/Tier 0 gibt es **keinen Prozentwert**, damit die Oberfläche keine noch gesperrte DNA-Analyse suggeriert. Die Level-15-Anzeige benutzt ausschließlich vorhandene Planet-Level und Reveal-Stufe, keine neue Mechanik/DB-Abfrage.
- Auf der Command Map: optionale **grobe** Potenzialhinweise je Sektortyp,
  ohne konkrete Seed-Traits vor Kolonisierung zu verraten.
- Externe Expeditions-/Galaxiescans bleiben getrennt geplant; der erste Laborscan ist deterministisch, kostet lokale Ressourcen und unterliegt einem 24-Stunden-Cooldown.
- **R2B (dieser PR):** Bekannte, bereits enthüllte eigene Kolonien im Atlas als zugängliche Buttons. Der Klick löst die vorhandene Planet-Registry-Karte aus, die weiterhin exklusiv Planet-Switch, State-Abgleich und PJAX-Refresh verantwortet. Aktiver Planet ist nur markiert; unrevealed/fremde Welt-IDs bleiben unsichtbar. Acht lokalisierte Beschriftungen, kein weiterer Poller oder Endpunkt.
- Alt-Kolonien und Kartenwechsel müssen identisch behandelt werden.

### R2C — Kostenpflichtige DNA-Laboranalyse (PR dieses Slices)

- Pro **eigener enthüllter** Kolonie ab Planet-Level 3: einmal je **rollierenden 24 Stunden**.
- Kosten: `10.000 × Planeten-Level` Metall und `5.000 × Planeten-Level` Kristall, **120 Planeten-XP** je Analyse. Keine Echtgeld-/Premium-Abkürzung.
- Server-Autorität: `game/planet_evolution/dna_analysis.py`; Migration 188 hält nur den letzten Scan und die Anzahl je Planet fest. Planet-Row-Lock und eine DB-Transaktion schützen die Kosten, XP und Quittung gegen Doppelklick und Parallel-Requests.
- **Keine** Änderung oder Neuwürfelung der `planet_dna`; Enthüllungen nur über `add_planet_xp` und die bereits bestehenden Level-Meilensteine 3/15. Mechaniken bei einem Level-Aufstieg neu kompilieren.
- Keine Analyse vor DNA-Freischaltung oder auf Planet-Level 30; bei Ressourcenmangel und Cooldown werden weder XP noch Ressourcen verändert.
- Status/Preis über den autorisierten Planet-Dashboard-Read, eine zusätzliche gezielte Abfrage; UI ohne neuen Poller, nur kanonischer Action-Client/PJAX-Refresh. Fehlermeldungen und Kosten in acht Sprachen.
- **Absichtlich nicht enthalten:** Scans fremder Galaxiepositionen, schätzen verborgener DNA, neue synergetische Effekte, Upgrades ohne Cooldown und eine globale Scan-Leaderboard-Währung.
- Der erste Live-Rollout setzt die neuen Migrationen voraus und erfordert alle Tests/PG-Sentinel/Live-Healthcheck. UNI1 bleibt ein gesonderter Release.

## Release 3 — Aktive Synergien (geplant, NICHT implementiert)

- Ein passender Trait kombiniert mit aktiver Spezialisierung kann eine **begrenzte**
  aktive Resonanz erzeugen (z. B. Fertigungs- oder Planet-Forschungs-Tempo).
- Werte nach 6-/12-Monats-Simulation balancieren; keine ungebremsten exponentiellen
  Faktoren, keine Client-Math und keine zweiten EffectResolver.
- Negative Traits bleiben echte Tradeoffs und sollten teilweise mitigierbar
  sein (Forschung/Policy), nicht ersatzlos gelöscht.
- Bestehende `planet_mechanics`-Rows brauchen definierte Recompile-/Backfill-
  Semantik vor Release, damit alte Spezialisierungen nicht benachteiligt werden.
- Boni müssen stets in Trait-Cards, Formeln und Server-Payload übereinstimmen.

## Release 4 — Fairness und Langzeitprogression (geplant, NICHT implementiert)

- Endgame-Kernpfade dürfen nicht allein durch seltene DNA erreichbar sein:
  prüfbare alternative, teurere Forschungs-/Discovery-Routen für grundlegende
  Mechaniken; Rare-Traits geben Spezialisierung/Vorteil statt globaler Pflicht.
- Keine unendlichen kostenlosen Rerolls über Kolonisierung/Abbruch.
- Gleiche Regeln für Bestands- und neue Accounts, keine stillen rückwirkenden
  DNA-Neuwürfe.
- Einführung neuer Traits nur mit Seed-Migration, Einflussevaluation und
  Rückwärtskompatibilität von gespeicherten `planet_dna`-JSON-Daten.
- Admin darf Traits nur auditierbar verändern; kein freier Premium-"best trait"
  Kaufpfad.

## QA-Gates

- 1 Planet und 11/11 Kolonien; mehrere gleiche Traits; Unterschied zw.
  offenbart/versteckt; keine fremden Fundorte.
- Heimwelt/Outpost Stufe 0 sowie Etablierung, Level 3 und 15.
- Trait-Bedingungen für Forschung, Spezialisation und Ascension unverändert.
- DE/EN/FR sowie Locale-Key-/Placeholder-Parität aller acht Sprachen.
- Mobile 390px, PJAX-Navigation, Planetwechsel, ohne Reload und ohne
  zusätzliche periodische Poller.
- PG: genau eine zusätzliche Bulk-Query auf der Planet-Evolution-Seite
  (Atlas in derselben Request-Connection), keine N+1-Reads.
- Messung/Simulation vor aktiven Produktion-, Risiko- oder Forschungs-Boni.
