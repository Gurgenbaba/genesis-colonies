-- GC-CHRON: player/entry_type index for uncapped chronicle stats scans.

CREATE INDEX IF NOT EXISTS idx_chronicle_entries_player_type_occurred
    ON chronicle_entries (player_id, entry_type, occurred_at DESC);
