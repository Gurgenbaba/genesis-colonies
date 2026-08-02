# Admin Control Center — UX Contract

Hard-load page: `GET /admin` (`admin_panel`). **No PJAX** into/out of admin (intentional).

## Assets

- `static/admin.css` + `static/admin.js` load **only** on `/admin` (`templates/admin_panel.html` blocks).
- Leave-hooks (`teardownHudSelectPortals`, hard-nav) live in `static/main.js`.

## Navigation IA

Grouped rail + filtered tab pills:

| Group | Tabs |
|-------|------|
| LiveOps | world_boss, pirates, inactive_autoplay, events, diplomacy, votes |
| Players | players, planets |
| Economy | balance, lootboxes, queues, fleets |
| Moderation | chat, support, messages |
| System | health, server, runtime, migrations, audit |

Deep-link: `?tab=pirates`. Last tab persisted in `sessionStorage`.

## Visual Contract

| Baustein | Pattern |
|----------|---------|
| KPI | `.admin-metrics-grid` / `.admin-metric-card` |
| Section | `.admin-section` + title/hint |
| Toolbar | `.admin-toolbar` |
| Tables | `renderAdminTable` / `.admin-table-wrap` |
| Selects | `data-gc-hud-select` + `syncAdminHudSelects` |
| Danger | `.admin-section-danger` / confirm before Soft/Hard AI, wipe, ban |

Industrial UI: radius 0–2px (`--gc-radius-*`), no pills.

## APIs

Canonical: JSON `/api/admin/*` (`game/admin_api.py`).  
Legacy HTML POSTs `/admin/update|resources|wipe|ban|unban` are **deprecated stubs** (flash + redirect, no mutation).

## Tickets

EPIC Admin UX: GC-A01–A07 (Foundation → LiveOps → Entities → Moderation → Economy → System → Cleanup).
