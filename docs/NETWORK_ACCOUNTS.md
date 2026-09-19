# Genesis Network Accounts

**Status:** GC-NETWORK-AUTH-001

Genesis Colonies uses one account identity across isolated universe databases.

## Ownership

- **DEV** is the identity authority: username, password, registration and recovery.
- Each universe keeps its own `users.id == players.id` row for runtime compatibility.
- Non-authority universes never accept local interactive credentials; `/login` and `/register` redirect to DEV.
- A short-lived HMAC handoff creates or resumes the local commander and maps it through `network_account_links`.

## Isolation

Only identity is shared. Resources, planets, research, fleets, rankings, alliances, messages, queues and economy remain in the target universe database.

## First entry bundle

Configured per universe:

- `GC_NETWORK_START_RESOURCE_MULTIPLIER`
- `GC_NETWORK_START_TIMEKEEPER_SECONDS`

For UNI 1 launch the intended values are `10` and `259200` (72h). The bundle is granted only when the network link is created for the first time.

## Runtime configuration

- `GC_UNIVERSE_KEY=dev|uni1`
- `GC_NETWORK_AUTHORITY_KEY=dev`
- `GC_NETWORK_AUTHORITY_URL=https://www.genesis-colonies.de`
- `GC_NETWORK_UNI1_URL=<universe URL>`
- `GC_NETWORK_UNI1_OPEN=0|1`
- `GC_NETWORK_AUTH_SECRET=<shared 32+ character secret>`

The shared auth secret must exist only in deployment secrets and must never be committed.


## Production readiness guard

Production multi-universe deployments fail closed when the Network layer is configured but unsafe.

Required invariants:

- `GC_UNIVERSE_KEY` is explicit on every universe.
- `GC_NETWORK_AUTH_SECRET` has at least 32 characters.
- Authority and UNI 1 browser handoff URLs are explicit HTTPS URLs.
- An open non-authority universe has a live maintenance path:
  `GC_MAINTENANCE_WORKER=1` or `GC_EMBEDDED_CRON=1`.

This prevents a Railway environment named “production” from silently running the app with development semantics or opening UNI 1 without fleet/live-ops maintenance.
