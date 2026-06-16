# GC-570 — World Map Direction & Role-Based Location Actions

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **H** — strategische Korrektur, neues Zielbild für `/galaxy`  
> **Status:** ✅ Implementiert  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-560–567B ✅

Design: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Map-Stack: [GC-564B_SPATIAL_COMMAND_MAP.md](GC-564B_SPATIAL_COMMAND_MAP.md)

---

## Strategische Korrektur

Die Weltkarte ist **nicht länger** ein optionaler Command-Hub neben der OGame-Galaxie.

Sie ist die **neue Galaxy-Hauptansicht** — langfristiger Ersatz für die klassische Slot-Ansicht.

```text
/galaxy?view=command_map   → Weltkarte (Ziel: Default)
/galaxy?view=system        → Legacy / Fallback („Klassische Ansicht“)
/empire                      → unverändert (Wirtschaft, nicht Navigation)
```

**Nicht:** alle alten Systeme löschen. **Nicht:** `/empire` umbauen.  
**Ja:** ab GC-570 ist jede Map-Entwicklung am **World-Map-Zielbild** ausgerichtet.

---

## Product-Ziel — „Die Stämme im Sci-Fi“

```text
Ort hat Rolle → Ort hat passende Funktionen
```

Nicht mehr: jeder Planet kann alles.  
Sondern: Spezialisierte Kolonien mit **sichtbaren Aktionen auf der Karte**.

### Klick-Flow (Ziel)

```text
Spieler klickt Ort auf Weltkarte
        ↓
active_planet_id wird gesetzt (Kolonien + Genesis Ark)
        ↓
Ort-Panel zeigt rollenbasierte Aktionen
        ↓
Aktion navigiert PJAX zu passender Shell-Route
```

### Rollen → Aktionen (MVP-Zielbild)

| Rolle (`empire_role_key`) | Primäre Aktionen | Sekundär |
|---------------------------|------------------|----------|
| `homeworld` (Genesis Ark) | Übersicht, Evolution, Gebäude, Forschung, Werft | Flotte, Defense |
| `mining` | Minen / Gebäude (Prod.), Lager, Defense | Handel |
| `research` | Planet-Tech / Forschung, Defense | Gebäude |
| `shipyard` | Werft, Flotte, Defense | Gebäude |
| `fortress` | Defense, Schild, Radar | Gebäude |
| `trade` | Handel, Lager, Routen | Gebäude |
| `frontier` / `general` | Gebäude, Defense | — |

Expansion Sites / Landmarks: **Inspector only** (GC-567/567B) — noch nicht spielbar bis GC-567C+.

---

## Scope (GC-570 MVP)

### 1. Navigation & Default-Vorbereitung

- `/galaxy` ohne `view=` → **perspektivisch** `command_map` (Feature-Flag oder schrittweise; MVP kann Tab-Reihenfolge + Label ändern)
- Tab **„Weltkarte“** (primär) + **„Klassische Ansicht“** (Legacy)
- Session/Default dokumentiert in [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)

### 2. Location Action Panel (neu)

Nach Klick auf **eigene Kolonie** oder **Genesis Ark**:

- Panel unter/neben Map (Reuse Inspector-Shell)
- Zeigt: Name, Rolle, Koordinaten, **Action-Buttons**
- Buttons = PJAX-Links (`GC.navigateTo`) zu bestehenden Routen — **keine neuen Mechaniken**

Beispiel Mining-Kolonie:

```text
⛏ Vega Prime · Mining Colony
[ Minen ]  [ Lager ]  [ Verteidigung ]
```

Mapping-Owner: **`game/planet_evolution/location_actions.py`** (neu)

```python
def build_location_actions(planet_id, role_key, *, conn) -> List[ActionLink]:
    # returns { label_key, href, icon } — static role → route map
```

### 3. Planet Switch (bestehend erweitern)

- Kolonie-Klick: `POST /api/planets/active` + `applyActionState()` (wie GC-560 Identity Switch)
- Danach Action-Panel füllen — **ohne** Full Reload
- `data-empire-identity-switch` bleibt; Panel ergänzt Actions

### 4. Template

- `galaxy_command_map_panel.html` — Action-Panel für Kolonien (neben Site/Landmark-Inspector)
- Oder: unified **Location Drawer** mit Modi `colony | expansion_site | landmark`

### 5. Frontend

- `initCommandMapLocationActions()` in `static/main.js`
- Cleanup via `GC.registerCleanup()`

### 6. Locales — `location_action_*`, `world_map_tab_*`

### 7. Tests — `tests/test_location_actions.py`, UI smoke auf `/galaxy?view=command_map`

---

## Explizit nicht (GC-570)

| Verboten | Ticket |
|----------|--------|
| `/empire` umbauen | — |
| Klassische Galaxy entfernen | — |
| Expansion Sites spielbar machen | GC-567C |
| Fremde Spieler auf Karte | GC-571 |
| Dynamic Influence | GC-566B (nach 570) |
| Neue Gebäude-/Prod-Mechaniken | Domänen-Owner |

---

## Technische Leitplanken

| Modul | Verantwortung |
|-------|---------------|
| **`location_actions.py`** (neu) | Rolle → Action-Links (Presentation only) |
| **`empire_identity.py`** | Rolle-Quelle (bestehend) |
| **`command_map.py`** | Nodes unverändert; optional `actions` im Payload |
| **`galaxy.py` / `app.py`** | Default view, Tab-Labels |
| **`galaxy_command_map_panel.html`** | Action-Panel |
| **`static/main.js`** | Klick → Switch + Panel |

**GC-000:** Kein paralleles Planet-Switch-System. `get_context_planet()` bleibt Wahrheit.

---

## Akzeptanzkriterien

- [x] Tab „Weltkarte“ ist visuell primär; „Klassische Ansicht“ als Legacy erkennbar
- [x] Klick auf Kolonie setzt `active_planet_id` und zeigt rollenbasierte Actions
- [x] Mining-Kolonie zeigt Minen/Lager/Defense-Links (PJAX)
- [x] Genesis Ark zeigt Kernfunktionen (Evolution, Gebäude, …)
- [x] Expansion Site / Landmark: Inspector ohne Spiel-Actions (wie heute)
- [x] `/empire` + `/galaxy?view=system` funktionieren unverändert
- [x] `pytest tests/test_location_actions.py -v` grün

---

## Cursor-Prompt (Implementierung)

```md
Implementiere GC-570 exakt nach docs/GC-570_WORLD_MAP_DIRECTION.md.

Strategische Korrektur: /galaxy?view=command_map ist Zielbild für Haupt-Galaxy.

Ziel:
1. location_actions.py — Rolle → PJAX-Action-Links (Presentation)
2. Kolonie-Klick → active_planet_id + Action-Panel mit passenden Links
3. galaxy.html Tabs: Weltkarte primär, Klassische Ansicht Legacy
4. Kein /empire anfassen, klassische Galaxy nicht entfernen
5. Tests test_location_actions.py

Akzeptanz: Mining-Kolonie zeigt Minen/Lager/Defense; Ark zeigt Kern-Routen.
```

---

## EPIC-15 — neue Reihenfolge

```text
GC-567B  Region Landmarks              ✅
GC-570   World Map + Role Actions      ⬅ nächster Schritt
GC-566B  Dynamic Influence
GC-571   Shared World Presence
GC-568   Territorial Warfare
```

GC-569 Presence Layer → **ersetzt durch GC-571** (gemeinsame Weltkarte, siehe [GC-571_SHARED_WORLD_PRESENCE.md](GC-571_SHARED_WORLD_PRESENCE.md)).

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
