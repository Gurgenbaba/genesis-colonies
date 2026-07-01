# GC-978 — Global Toast / Notification UX

> Epic: EPIC-03 Galaxy / Shell UX  
> Voraussetzung: GC-977A (Galaxy Quick Spy) abgeschlossen.

---

## Problem

Aktuelle Notifys erscheinen teilweise über oder innerhalb von `#main-content`. Wenn der Spieler weiter unten scrollt, sieht er Meldungen nicht zuverlässig — Aktionen wirken so, als wäre nichts passiert.

---

## Ziel

Toasts/Notifys sind **immer sichtbar**, unabhängig von Scroll-Position und PJAX-Seite.

---

## Betroffene Dateien

- `templates/base.html` — globaler Toast-Container (Shell-Layer, außerhalb `#main-content`)
- `static/main.js` — zentrale `showNotify` / Toast-Stack-Logik
- `static/style.css` — fixed Toast-Stack, Sci-Fi-Styling, Mobile
- `tests/test_*` — Contract-Tests (Container, zentrale Funktion)

**Nicht bearbeiten:** Fleet-/Gameplay-Logik, `#main-content`-Layouts pro Seite.

---

## Anforderungen

1. **Globaler Container** in `base.html` — fixed, über Content, PJAX-safe (nicht in `#main-content`).
2. **Position:** Desktop oben rechts oder oben mittig unter Resource-Bar/Header; Mobile unten über Bottom-Dock oder oben unter Resource-Bar ohne wichtigen Content zu verdecken.
3. **Stacking:** Mehrere Toasts kompakt stapeln; ältere ausblenden oder nach oben schieben.
4. **Typen:** Erfolg, Fehler, Warnung, Info visuell unterscheidbar (bestehende Tokens, kein Pill-Look).
5. **Zentralisierung:** `showNotify` und verwandte Helfer in `main.js` auf einen globalen Stack umleiten.
6. **Migration:** Inline-/Page-Notifys soweit möglich auf globalen Toast umstellen — keine Layout-Höhe im Mainframe.
7. **PJAX:** `GC.cleanupPage()` schließt keine aktiven Toasts; Container bleibt in Shell.
8. **Kein Reload** für Toast-Anzeige.

---

## Akzeptanzkriterien

- [x] `base.html` enthält `#gc-toast-stack` außerhalb `#main-content`
- [x] Mehrere Toasts stapeln sich ohne Layout-Shift im Mainframe
- [x] Mobile: Toasts über Bottom-Nav positioniert
- [x] Contract-Tests: Container in base, `showNotify` nutzt Stack
- [ ] Manuell: Galaxy Quick Spy / Fleet-Send bei Scroll unten sichtbar
- [ ] Keine Regression PJAX / `applyActionState`

---

## Referenz-Docs

- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Shell First
- [STATE_AJAX.md](STATE_AJAX.md)

---

## Nicht in Scope

- Push-Benachrichtigungen / Browser-Notifications
- Sound bei Toasts (bleibt GC-951 Notify-Sounds)
- Ingame-Message-Inbox
