# GC-597E — Foreign Node DEV Fallback

## Ziel

Gegner-/fremde Knoten dürfen nicht leer wirken. Solange GC-598/599 noch fehlen, zeigt der World Inspector einen klaren DEV-Fallback.

## Problem

Klick auf gegnerischen Knoten öffnet Modal mit fast leerem Inhalt: nur Name, keine Missionen, kein Kontext, keine Erklärung.

## Lösung

- `shouldShowForeignDevPreview()` — foreign/enemy-Knoten ohne vollständigen Mission-Payload (GC-598 `mission_actions` / `primary_action`)
- `renderForeignDevPreviewModal()` — DEV PREVIEW-Badge, Erklärungstext, Typ/Koordinate/Spieler, CTAs zur klassischen Galaxy
- Keine fake Spy/Attack-Buttons

## Dateien

- `static/main.js` — Fallback-Rendering + Classic-View-CTA
- `static/style.css` — `.gc-world-inspector-shell--foreign-dev`, gestapelte Actions
- `locales/de.json`, `locales/en.json`
- `tests/test_gc597_world_inspector_modal.py`

## Akzeptanz

- Gegner-Knoten öffnet kein leeres Modal mehr
- Spieler versteht: sichtbar, aber noch DEV
- Command Map bleibt DEV Preview; klassische Galaxy bleibt stabiler Weg für Missionen

## Follow-up

- **GC-598** — Mission Actions im Modal (`hasForeignMissionPayload` → kein Fallback)
- **GC-599** — Foreign Worlds / Enemy Nodes vollständig
