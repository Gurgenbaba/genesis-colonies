# Migration number reservations

Migrations are recorded by **file name** in `migration_history` and applied in
sorted file-name order (`migrate.py`). The numeric prefix is only an ordering
convention, so two files with the same number both run.

## Reserved for UNI1 only (`u2/staging-runtime`)

| Number | File | What it does |
|---|---|---|
| 183 | `183_trader_hub_dev_parity.sql` | Converges UNI1 `game_settings` for the Trader Hub to the DEV values |
| 184 | `184_uni1_admin_speed_profile.sql` | Seeds the UNI1 admin-controlled universe speeds in `game_settings` |

**These files must never be copied to `main`.** `184` overwrites the speed
settings (`production_speed`, `build_speed`, `speed`, `research_speed`,
`fleet_speed_*`); on the DEV/public service that would change live game speeds.
The same applies to merges in the opposite direction (`u2/staging-runtime` ->
`main`): resolve them so that `183`/`184` stay out of `main`.

New migrations on `main` use **185 or higher**, which UNI1 receives with the next
`main` -> `u2/staging-runtime` sync. `tests/test_migration_number_reservations.py`
checks the target branch: it **rejects both actual UNI1-only filenames on `main`**, and
requires those exact files on `u2/staging-runtime`. The CI smoke workflow runs
this guard on pull requests and pushes. For a detached local checkout, set
`GC_MIGRATION_TEST_BRANCH=u2/staging-runtime` only when testing the UNI1 tree.
