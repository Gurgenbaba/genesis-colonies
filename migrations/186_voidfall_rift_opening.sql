-- VOIDFALL Release 1: time-boxed, gameplay-only rift opening.
-- Extends the canonical server_events / EffectResolver hooks.
-- UTC 2026-10-31 00:00:00 through 2026-11-07 23:59:59.
-- Never change an operator-edited event on re-run.
-- No shop promotions, premium currency, resource injections, or wipe.

INSERT INTO server_events (
    slug, title, starts_at, ends_at, enabled, effects_json,
    created_at, updated_at, created_by
)
SELECT
    'voidfall-rift-opening-2026',
    'VOIDFALL: Rift Opening',
    1793404800,
    1794095999,
    1,
    '[{"kind":"expedition_hold_mult","mult":0.85},{"kind":"research_time_speed","mult":1.10}]',
    1793404800,
    1793404800,
    NULL
WHERE NOT EXISTS (
    SELECT 1 FROM server_events WHERE slug = 'voidfall-rift-opening-2026'
);
