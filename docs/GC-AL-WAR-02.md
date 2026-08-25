# GC-AL-WAR-02 — Alliance War Meta

**Status:** ✅ Implemented on feature branch · Owner: `game/alliance.py` (lifecycle) + `game/alliance_war.py` (derived combat meta)

WAR-02 extends the WAR-01 peace lifecycle with a real campaign scoreboard. It does **not** introduce a second diplomacy or combat engine.

## Rules

- The active war remains authoritative in `alliance_diplomacy`.
- `alliance_diplomacy.updated_at` is the identity/start timestamp of the current war campaign.
- Only battles where both players belong to different alliances whose current relation is `war` count.
- War Score reuses `scoring.compute_destroyed_raw_from_losses()` exactly; there is no second score formula.
- `fleet_id` is the combat-event idempotency key. A retried fleet tick can never add the same battle twice.
- Peace immediately stops new war statistics because the relation is no longer `war`.
- A later declaration between the same alliances gets a new `updated_at`, therefore a fresh 0:0 campaign.
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

## Tests

```bash
python -m pytest tests/test_alliance_war_meta.py tests/test_alliance.py tests/test_combat.py -q
```

Critical regressions: canonical score parity, fleet-id idempotency, peace stop, re-war reset, >64-bit scores, report renderer integration.
