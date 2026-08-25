# GC-AL-WAR-02 — Alliance War Meta

**Status:** ✅ Implemented + production-hardened on feature branch · Owner: `game/alliance.py` (lifecycle) + `game/alliance_war.py` (derived combat meta)

WAR-02 extends the WAR-01 peace lifecycle with a real campaign scoreboard. It does **not** introduce a second diplomacy or combat engine.

## Rules

- The active war remains authoritative in `alliance_diplomacy`.
- `alliance_diplomacy.updated_at` is the identity/start timestamp of the current war campaign.
- Only battles where both players belong to different alliances whose current relation is `war` count.
- War Score reuses `scoring.compute_destroyed_raw_from_losses()` exactly; there is no second score formula.
- `fleet_id` is the combat-event idempotency key. A retried fleet tick can never add the same battle twice.
- Peace immediately stops new war statistics because the relation becomes `neutral`.
- Peace preserves the neutral transition row; a later declaration uses a monotonic transition timestamp, so even peace + re-war within the same second starts a fresh 0:0 campaign.
- Score and destroyed-unit totals are persisted as decimal `TEXT`, so values above SQLite signed 64-bit remain exact.

## Schema — migration 155

`alliance_war_stats` stores the current campaign aggregate per normalized alliance pair. `alliance_war_events` stores one immutable combat contribution per `fleet_id` for retry protection and auditability.

Historical event rows keep their `war_started_at`; the hub only reads the campaign matching the currently active relation.

## Combat integration

`messages.dispatch_combat_reports()` enriches the already-authoritative combat report metadata with `alliance_war` before creating attacker/defender inbox rows. The recorder receives the existing combat losses/result/fleet id and never resolves a battle itself.

Combat report UI shows:

- localized WAR badge,
- current War Score for both alliances,
- victories,
- destroyed units,
- total battles and draws.

The Alliance diplomacy tab exposes the same server scoreboard next to each active war.

## Production hardening

- PostgreSQL aggregate updates atomically seed the pair row and serialize concurrent fleet workers with `SELECT ... FOR UPDATE`, while Python keeps arbitrary-precision score arithmetic.
- Same-second peace/re-war transitions cannot reuse a campaign identity.
- Universe reset maps `alliance_war_events` + `alliance_war_stats` to the `combat` domain and clears both FK-safe before `alliances`.
- The legacy diplomacy regression now matches WAR-01: active wars reject NAP/alliance requests with `war_active`.

## Tests

Focused WAR-02 deployment gates cover canonical score parity, fleet-id idempotency, peace stop, same-second re-war reset, >64-bit scores, report renderer integration, PostgreSQL serialization contract and universe-reset ownership/order. Normal PR CI additionally gates Smoke, Big-Score, locale parity, I18N regression and newly introduced visible raw strings.
