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
- Authority: `PUBLIC_BASE_URL=https://www.genesis-colonies.de`
- Authority: `GC_PUBLIC_ALIAS_HOSTS=genesis-colonies.com`
- UNI 1: `PUBLIC_BASE_URL=https://genesis-colonies-u2-production.up.railway.app`

The shared auth secret must exist only in deployment secrets and must never be committed.

### Public-origin rule

`genesis-colonies.com` is intentionally retained as the stable public/toplist address, but it is **not a second browser session origin**. Browser/page requests on that host are canonicalized to `www.genesis-colonies.de` before Network auth or Flask session handling. API postback routes stay directly reachable on aliases so TopG/GTop100/GameToor/Arena/PayPal integrations are not coupled to redirect support.

## UNI 1 launch contract

The binding public-release checklist (true x1, Economy V2, Nodebuster Ascension,
starter bundle, Shop and open-gate requirements) lives in
[UNI1_LAUNCH_CONTRACT.md](UNI1_LAUNCH_CONTRACT.md).

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
- Authority and UNI 1 browser handoff URLs are explicit HTTPS URLs and use different hosts.
- `PUBLIC_BASE_URL` must match the URL owned by the current `GC_UNIVERSE_KEY`.
  - `dev`/authority → host must match `GC_NETWORK_AUTHORITY_URL`.
  - `uni1` → host must match `GC_NETWORK_UNI1_URL`.
- The canonical `PUBLIC_BASE_URL` host may not also appear in `GC_PUBLIC_ALIAS_HOSTS`.
- An open non-authority universe has a live maintenance path:
  `GC_MAINTENANCE_WORKER=1` or `GC_EMBEDDED_CRON=1`.

A wrong universe role on the authority deployment therefore fails during bootstrap instead of turning `/login` into a self-redirect loop. Runtime auth also retains a second fail-safe that refuses same-host authority redirects.


## DEV → UNI 1 promotion

`main` is the continuously changing DEV/canary code line. Railway UNI 1 deploys
only from the separate release branch `u2/staging-runtime`.

**UNI 1 does not follow DEV automatically.** Changes merged to `main` may deploy
to DEV immediately, but they remain isolated from UNI 1 until an operator
explicitly runs `.github/workflows/promote-u2-after-dev.yml` via
`workflow_dispatch`.

The intended release cadence is a deliberate bundled promotion (for example,
once per week after DEV validation). The manual workflow promotes the current
`main` HEAD with a **fast-forward-only** push to `u2/staging-runtime`.

Fail closed:

- no scheduled or Railway-status-triggered promotion exists
- no manual workflow run → UNI 1 stays on its current release SHA
- stale SHA that is no longer current `main` → reject
- diverged `u2/staging-runtime` → reject; no force push

This keeps DEV suitable for daily development while UNI 1 remains a stable,
operator-controlled release line.
