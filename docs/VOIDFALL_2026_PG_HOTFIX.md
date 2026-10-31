# GC-VOIDFALL-005 — PostgreSQL LIKE placeholder incident hotfix (2026-10-31)

Incident: `GET /login-rewards` returned HTTP 500 on UNI1 after VOIDFALL Releases 3/4. Railway runtime traceback confirmed `psycopg.ProgrammingError: only '%s', '%b', '%t' are allowed as placeholders, got '%'` at `game/voidfall_community.py:73`. SQL queries contained raw literal `LIKE 'voidfall2026:...:%'` strings, which psycopg parses as malformed percent-based placeholders even when quoted.

Fix: move both community/discovery LIKE patterns into the bound parameter tuples via `LIKE ?`, using the existing cross-dialect `game.db` placeholder adapter. Covers **both**:
1. Community panel lookup for own milestone, choice and discovery receipts (page render)
2. Discovery-cap receipt scan during a completed daily mission claim (write path)

No schema change, migration, game mechanics change, payout, event reset or asset change. New regression test invokes both query paths through an SQL guard, checks that no literal percent-based LIKE patterns appear, and checks bound wildcard arguments. All player progress and existing reward receipts remain intact.

Release gate: CI, LiveOps, PG guard, i18n, browser sentinel on both branch heads. DEV deployment/health before UNI1; 500 page hits must cease, authenticated reward page must render. Prelaunch reset MUST be skipped.
