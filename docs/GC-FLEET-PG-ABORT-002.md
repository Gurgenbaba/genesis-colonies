# GC-FLEET-PG-ABORT-002 — Request-pinned PostgreSQL SAVEPOINT ownership

## Incident

Production showed a transaction cascade while due Fleet work ran inside a request-owned write transaction:

- `InvalidSavepointSpecification: savepoint "gc_fleet_arrival_<id>" does not exist`
- queue-engine recovery SAVEPOINTs disappeared afterwards
- PostgreSQL entered `InFailedSqlTransaction`
- the original action then failed later in unrelated SQL (for example research queue recalculation)
- Admin Fleet force-advance reproduced the same failure class

The trigger is the request-pinned PostgreSQL connection. Deep legacy helpers can call `db()` and receive the same physical request checkout. A nested helper that calls `commit()` therefore does **not** own an independent transaction: the real commit commits the outer request transaction and destroys every active SAVEPOINT.

## Hotfix invariant

While the request-pinned PostgreSQL checkout has an active SAVEPOINT:

- nested direct `commit()` is non-destructive and does not commit the outer transaction;
- nested direct `rollback()` rewinds to the current owner SAVEPOINT but leaves that SAVEPOINT alive;
- `ROLLBACK TO SAVEPOINT` keeps the target and discards newer tracked SAVEPOINTs;
- `RELEASE SAVEPOINT` removes the target and any nested SAVEPOINTs;
- request teardown always uses the original real rollback/close methods so no open transaction can leak back to the pool.

The SAVEPOINT owner (`queue_engine`, Fleet shared-step, etc.) remains responsible for release and the outer mutation remains responsible for the final commit.

## Scope

This is a transaction-ownership repair, not a gameplay change. SQLite behavior is unchanged. Dedicated Fleet short-TX workers are unchanged.

A follow-up can continue reducing cross-domain work inside action transactions (`include_fleet=False`, relocation isolation), but this hotfix removes the production 500 cascade at the DB ownership boundary first.

## Regression gates

`tests/test_gc_pg_request_savepoint_guard_002.py` verifies:

1. nested commit cannot destroy a Fleet SAVEPOINT;
2. nested rollback rewinds without destroying the owner SAVEPOINT;
3. request teardown performs a real full rollback despite tracked SAVEPOINTs;
4. nested SAVEPOINT stack bookkeeping matches PostgreSQL rollback/release semantics.
