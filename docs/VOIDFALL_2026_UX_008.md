# GC-VOIDFALL-008 — UTC rollover and claim feedback (2026-10-31)

## Confirmed player problems
- A player who leaves `/login-rewards` open across 00:00 UTC sees the previous UTC day's mission counts and claim buttons until navigating away/back.
- The existing AJAX claim wrapper catches a **PJAX refresh error** together with an API claim error. If the server has already granted an item but navigating fails, it incorrectly tells the player the claim failed and re-enables the button.

## Implemented
1. The existing authoritative VOIDFALL page state exposes `server_now` and `next_reset_at`, computed from the same activity day bucket as the claim ledger.
2. The event root includes those timestamps; the persistent JS schedules **one timer** to refresh the existing PJAX page at midnight UTC, using the server's clock offset to tolerate local device clock skew. Tab visibility changes and PJAX main-content swaps re-arm it. Failed reloads are throttled to one attempt per minute.
3. After a successful API response, a later PJAX error **does not** re-enable the claim button or present a failed-claim message. The player sees the already-localized success message.
4. Existing tests verify exact UTC boundaries and the refresh/no-extra-poll contract.

## Constraints
No new image assets or network polling, no DB migration, no player wipe, no change to missions, XP sources, rewards, 20/40/70 thresholds, alignment, rare discoveries, expiry or claim IDs. No extra database reads on the hot path. The server remains authoritative after any midnight refresh.

## Release checks
Run targeted LiveOps tests plus i18n, Smoke, Browser Sentinel, PostgreSQL and deployment safety gates. Deploy DEV and verify runtime before UNI1; never run UNI1 prelaunch reset.
