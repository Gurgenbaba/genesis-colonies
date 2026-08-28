# GC-PERF-FLEET-IDLE-002

## Goal
Reduce recurring SQLite work caused by high-frequency Fleet due-state probes without changing Fleet gameplay or timer semantics.

## Changes
- `player_fleet_is_dirty()` now uses three phase-specific `EXISTS` branches so SQLite can use a deadline index per Fleet phase.
- Added player-scoped deadline indexes for outbound, holding, and returning movements.
- Added the missing global `(status, holding_until)` deadline index for maintenance processing.
- Regression coverage verifies outbound, holding, and returning due detection and migration of all deadline indexes.

## Canonical timing
Fleet countdown remains timestamp-driven. The server persists Fleet phase timestamps; the browser displays remaining time from those timestamps. This optimization only changes how cheaply the server detects that a persisted deadline has become due.

## Out of scope
- Flight math
- Mission resolution
- Combat
- Recall semantics
- Client countdown math
- Fleet HUD payload/revision architecture
