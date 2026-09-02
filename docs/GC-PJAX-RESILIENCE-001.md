# GC-PJAX-RESILIENCE-001 — Gateway Backoff, PJAX Preloads, Messages Init

## Problem

A browser audit around `cba97850` showed three frontend resilience issues without an application JavaScript crash:

- transient HTTP `502` responses hit several independent live GET endpoints at the same time;
- PJAX navigation recreated image preload links after the DOM swap, producing large numbers of Chrome `preloaded but not used` warnings;
- the Messages page could enter its module initialization path more than once for the same live `#messages-page` root.

## Implementation

Owner: `static/js/core/gc.js` — a shell/core guard extending existing fetch and PJAX lifecycle behavior. It does **not** create another game-state poller or another navigation system.

### Shared 502 backoff

Only same-origin `GET` requests for these existing poll endpoints participate:

- `/api/game-state`
- `/api/world-boss`
- `/api/notifications/summary`
- `/api/chat/messages`

A `502` opens one short shared exponential+jitter backoff window. Each request is retried at most twice. Existing `AbortSignal` cancellation is preserved. POST/action requests are excluded so mutation/idempotency behavior is unchanged.

### PJAX image preload guard

SSR image preloads remain unchanged. They are already present before `js/core/gc.js` executes and can improve first paint.

GC-owned image preloads appended later by PJAX (`data-gc-lcp-preload` / `data-gc-frame-preload`) are suppressed. At that stage the live image request already starts from the swapped DOM, so the late hint adds console noise and can duplicate request scheduling without helping the initial document LCP.

### Messages initialization guard

`GC.modules.messages` and `GC.initMessagesPage` are guarded so the same live `#messages-page` DOM root initializes once. A fresh PJAX root is a new DOM node and initializes normally. `force: true` remains available for an explicit repair path.

## Architecture

This slice follows GC-000:

- one existing global game-state poll remains authoritative;
- no frontend gameplay math is added;
- no second PJAX/navigation implementation is added;
- mutations keep their existing action/idempotency contract;
- the Messages guard only deduplicates lifecycle entry, while `static/js/messages.js` remains the inbox owner.

## Tests

```bash
python -m pytest tests/test_gc_pjax_resilience.py tests/test_gc861b_pjax_lcp_preload.py tests/test_static_live_updates.py -q
```

Manual browser acceptance:

1. Navigate repeatedly through hero-card pages via PJAX and confirm the unused image-preload warning count no longer grows per navigation.
2. Enter `/messages` via PJAX and confirm one page init/render for one root.
3. During a transient gateway restart, confirm affected GET pollers spread retries instead of immediately refiring together; normal actions remain responsive after recovery.
