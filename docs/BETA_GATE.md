# Genesis Colonies — Beta Gate

> **Beta ist kein Feature-Label. Beta ist der Punkt, an dem die Core Architecture zur Plattform wird.**

Dieses Dokument definiert die Bedingungen für den Übergang von Alpha zu Beta sowie die Regeln, die ab Beta dauerhaft gelten. Es ist ein Governance-Dokument mit demselben Rang wie `CORE_ARCHITECTURE.md`, `ARCHITECTURE.md` und `QUEUE_STATE_RULES.md`.

---

## 1. Purpose

Genesis Colonies darf erst als Beta bezeichnet werden, wenn die Grundsysteme stehen, die Architekturregeln eingehalten werden und das Projekt objektiv testbar stabil ist.

Dieses Dokument verhindert, dass der Alpha-Exit durch Wartungs-Schulden oder neue Grundsatzdebatten endlos verschoben wird. Ab Beta werden kanonische Systeme erweitert und verbessert, nicht ersetzt.

---

## 2. Alpha Exit Criteria

Der Versionswechsel zu `v1.0.0-beta.1` ist erst erlaubt, wenn alle Gates abgeschlossen sind:

- [ ] **Alliance MVP abgeschlossen** — Hub, Mitglieder, Bewerbungen, Spenden, Projekte, Tech, Diplomatie-MVP und Logo-Upload sind spielbar; Combat-/Fleet-Diplomatie-Hooks sind bewusst post-Beta.
- [ ] **GC-BETA-001 — Architecture & CI Green** — Architektur- und PJAX-Regressionstests grün; keine neuen Reload-/Href-Verstöße; GC-000 eingehalten.
- [ ] **GC-BETA-002 — Documentation Reality Sync** — Master-Docs spiegeln den tatsächlichen Stand wider; keine bekannten Reality-Gaps.
- [ ] **GC-BETA-003 — Alpha Exit Validation** — manueller Smoke-Test bestätigt, dass die Kernsysteme zusammen funktionieren.

Erst danach:

```text
v0.9.x
    ↓
v1.0.0-beta.1
```

---

## 3. Core Architecture Freeze

Ab `v1.0.0-beta.1` gilt der **Core Architecture Freeze**.

Das Spiel ist nicht eingefroren. Eingefroren sind die Grundsatzentscheidungen und kanonischen Owner:

- Fleet Engine
- Queue Engine
- Planet Scope
- EffectResolver
- Economy / Ressourcen
- Live State / `/api/game-state`
- PJAX Navigation Shell
- Owner-Struktur aus `CORE_ARCHITECTURE.md`

Verbindliche Regeln ab Beta:

- Keine neuen Kernsysteme.
- Keine zweiten Implementierungen bestehender Systeme.
- Keine Greenfield-Rewrites kanonischer Owner.
- Keine Grundsatzänderungen an Planet Scope, Queue Engine, Fleet Engine, Economy, EffectResolver, Live State oder Navigation.
- Neue Features bauen ausschließlich auf bestehenden Ownern auf.
- Server Authority bleibt unverändert.
- GC-000 bleibt bindend.

---

## 4. Allowed Changes

| Erlaubt | Verboten |
|---------|----------|
| Neue Allianzrechte in `game/alliance.py` | Zweite Allianz-Domäne |
| Allianzkriege auf bestehender Allianz-, Fleet- und Combat-Architektur | Parallel-System für Diplomatie/Fleet-Hold |
| Neue Expeditionsevents über bestehende Expedition-/Fleet-Owner | Zweite Expedition-Engine |
| Neue Schiffe in `fleet_defs` + bestehender Shipyard/Fleet-Flow | Zweite Fleet-Engine |
| Neue Planet-Evolution-Trees im bestehenden Planet-Evolution-System | Neues Planetensystem neben `active_planet_id` |
| Neue Effekte im `EffectResolver` | Frontend-Produktionsformeln |
| Neue Queue-Typen über `queue_engine` und Queue-Regeln | Eigene Finish-/Cancel-Logik pro Modul |
| Battle Pass, XP, Daily/Weekly Missions als Features auf bestehenden Ownern | Neues globales State- oder Polling-Konzept |
| Performance-, UX-, Balancing- und Bugfixes | Greenfield-Rewrite bestehender Kernmechaniken |

---

## 5. Architecture Exception Process

Ausnahmen sind nicht verboten, aber sie brauchen eine explizite Begründung und einen Migrationsplan.

Jede architekturrelevante Ausnahme braucht ein eigenes Ticket:

```text
Beta Architecture Exception Ticket

Problem:
- Welches konkrete Problem kann nicht durch Erweiterung eines bestehenden Owners gelöst werden?

Betroffene GC-000-Regeln:
- Welche Regel ist betroffen?
- Warum bleibt die Lösung trotzdem konsistent?

Owner-Plan:
- Welcher Owner bleibt kanonisch?
- Welche neuen Dateien oder Tabellen entstehen, falls nötig?

Migration:
- Migration → Alias/Adapter → Remove
- Kein dauerhaftes paralleles System ohne Enddatum

Tests:
- Welche Architektur-, Race-, State- und Domain-Tests sichern den Wechsel?

Docs:
- Welche Master-Docs werden im selben Ticket aktualisiert?
```

Ohne akzeptiertes Exception-Ticket gilt: bestehendes Owner-Modul erweitern.

---

## 6. Semantic Versioning

| Version | Bedeutung |
|---------|-----------|
| `0.9.x` | Alpha — Grundsysteme entstehen noch; Architekturentscheidungen können noch validiert werden. |
| `1.0.0-beta.x` | Core Architecture Freeze; Fokus auf Stabilität, Balancing, UX, Performance und Community-Feedback. |
| `1.0.0` | Offizieller Release; keine P0/P1-Beta-Risiken offen. |
| `1.0.x` | Bugfixes, Performance, kleine Quality-of-Life-Verbesserungen. |
| `1.1.x` | Neue Features auf bestehender Architektur. |
| `2.0` | Nur für fundamentale Architektur- oder Designänderungen mit bewusstem Migrationspfad. |

---

## 7. Beta Success Criteria

Beta endet nicht, weil "wenige Bugs" übrig sind. Beta endet, wenn das Spiel im Betrieb stabil genug für `1.0.0` ist:

- Keine offenen P0-Probleme.
- Keine offenen P1-Probleme ohne akzeptierten Release-Plan.
- CI grün.
- Architektur-Guards grün.
- Keine bekannten State-Desyncs, Queue-Inkonsistenzen oder Planet-Scope-Probleme.
- Performance für normale Spielsessions ausreichend.
- Balancing für Early- und Midgame reviewt.
- Community-Feedback aus Beta-Phase triagiert.
- Master-Docs entsprechen dem Produktstand.

---

## 8. Tech Debt Policy

Wartungs-Schulden sind kein Beta-Blocker, solange sie dokumentiert sind und die Architektur nicht verletzen.

Große Dateien, lange Funktionen oder noch nicht ideale Modulaufteilung blockieren den Alpha-Exit nicht, wenn:

- GC-000 eingehalten wird.
- CI grün ist.
- Keine P0/P1-Probleme offen sind.
- Die Schulden in `ROADMAP.md`, `PROJECT_INVENTORY.md` oder einem spezifischen Follow-up-Ticket dokumentiert sind.
- Es keinen akuten Spieler- oder Betriebsfehler gibt.

Beispiele für **nicht blockierende** Tech Debt:

- `static/main.js` ist zu groß.
- `app.py` enthält noch zu viel HTTP-Orchestrierung.
- `game/fleet.py` hat lange Mission-Handler.
- Legacy-Fallbacks sind dokumentiert und getestet.

Beispiele für **blockierende** Tech Debt:

- Zweite Queue-Engine.
- Paralleler Fleet-State.
- Frontend-Math für Gameplay-Mechanik.
- Full reload für normale Ingame-Navigation.
- Planet Scope wird umgangen.
- Rote Architektur- oder State-Tests.

---

## 9. Go / No-Go Rule

Beta-Go ist nur erlaubt, wenn:

```text
Alliance MVP abgeschlossen
+ GC-BETA-001 bestanden
+ GC-BETA-002 bestanden
+ GC-BETA-003 bestanden
= v1.0.0-beta.1
```

Wenn eines dieser Gates offen ist, bleibt Genesis Colonies `v0.9.x` Alpha.
