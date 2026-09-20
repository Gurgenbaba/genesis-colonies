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

## UNI 1 launch isolation

Fresh public universes may run without synthetic player activity. For UNI 1:

- `GC_INACTIVE_AUTOPLAY_ENABLED=0` — hard-off for dormant-human autoplay.
- `GC_PIRATE_AI_ENABLED=0` — deployment hard-off for Pirate AI/play-loop even in production.
- Disabled Pirate maintenance ticks are intentionally silent; they do not append recurring
  `ai_disabled` Bot-Log rows. This keeps downstream operator/Discord log bridges quiet.
- The hard-offs are universe-local Railway variables; DEV may keep different LiveOps behavior.

Do not use `GC_PIRATE_PLAY_BOTS_PER_TICK=0` as a kill-switch: that knob is clamped to
at least one bot and only controls batch size. Use `GC_PIRATE_AI_ENABLED=0`.


## Production readiness guard

Production multi-universe deployments fail closed when the Network layer is configured but unsafe.

Required invariants:

- `GC_UNIVERSE_KEY` is explicit on every universe.
- `GC_NETWORK_AUTH_SECRET` has at least 32 characters.
- Authority and UNI 1 browser handoff URLs are explicit HTTPS URLs.
- An open non-authority universe has a live maintenance path:
  `GC_MAINTENANCE_WORKER=1` or `GC_EMBEDDED_CRON=1`.

This prevents a Railway environment named “production” from silently running the app with development semantics or opening UNI 1 without fleet/live-ops maintenance.


## DEV → UNI 1 promotion

`main` is the DEV/canary code line. Railway UNI 1 continues to deploy from
`u2/staging-runtime`, but that branch is not advanced by hand during normal
operation.

`.github/workflows/promote-u2-after-dev.yml` listens for the Railway commit
status **`Genesis-Colonies - genesis-colonies`**. Only a **successful DEV
Railway deployment** may promote, and the candidate SHA must still be the
current `main` HEAD. The workflow then performs a **fast-forward-only** push
to `u2/staging-runtime`.

Fail closed:

- failed/pending DEV deployment → no UNI 1 promotion
- stale SHA that is no longer `main` → reject
- diverged `u2/staging-runtime` → reject; no force push
- manual fallback uses the same current-main and fast-forward checks

This makes DEV the runtime canary while keeping both universes on the same
reviewed code after a successful canary deployment.
