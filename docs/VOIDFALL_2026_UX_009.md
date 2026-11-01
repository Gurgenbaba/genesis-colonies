# GC-VOIDFALL-009 — compact post-event archive (2026-11-01)

## Product decision
VOIDFALL uses its full mission/convergence/alignment surface only during the event. After its canonical end (2026-11-07 23:59:59 UTC), the Login Rewards page should return to its normal clean appearance, with just one discreet, **closed-by-default** disclosure for the personal event recap.

## Implementation
- Server state `ended = now > END_AT`: return a compact, read-only archive from the **existing verified reward-claim ledger**, including personal contributions, community signal total, claimed milestones, discoveries and selected one-time alignment (if any).
- Skip expired daily activity count and current-day reward lookups entirely. No extra SQL, no migrations and no additional image requests.
- `partials/voidfall_daily_ops.html` selects the archive **instead of** the full event panel after expiry. The new `voidfall_archive.html` uses native HTML `<details>`, initially collapsed, no forms, no disabled buttons, no artwork, no JS listener.
- Keep existing full experience for running or temporarily paused events. `voidfall_claim` still denies all post-expiry requests server-side; claim ledger and inventory are untouched.
- Existing GC-VOIDFALL-008 UTC-midnight PJAX refresh replaces the running event panel with the archive when the event ends. No polling is added.
- Archive text is translated in DE and EN; other supported languages use the project's existing English fallback for these three new short strings. Other labels reuse existing native localized strings.

## Guards
- At UTC end boundary, the event remains active through END_AT, then immediately becomes read-only.
- Archive is collapsed by default and does not render any welcome, daily mission, community milestones, alignment claim UI, discovery card or form.
- The normal 30-day login reward panel/calendar remains untouched.
- 20/40/70, rare discovery odds, one-time grants, event start/end, prelaunch reset settings and all claims are unchanged.

## Verification
Targeted unit, end-to-end Jinja/CSRF, i18n, PostgreSQL, smoke and browser gates must pass on both branches before merges. DEV should roll out first, then UNI1. No UNI1 reset.
