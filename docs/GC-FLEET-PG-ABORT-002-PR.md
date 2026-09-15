# GC-FLEET-PG-ABORT-002 PR checklist

- [x] Request-pinned PG savepoint ownership guarded
- [x] Nested commit cannot destroy queue/fleet savepoints
- [x] Nested rollback rewinds current savepoint without releasing owner scope
- [x] Teardown still performs real full rollback/close
- [x] Regression tests added
- [x] Version bumped to 0.5.9.174
- [ ] CI green
- [ ] Production deploy explicitly approved
