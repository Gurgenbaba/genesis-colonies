-- GC-WB-TAME: companion capacity (base 1 + shop bonus, max 4)

CREATE TABLE IF NOT EXISTS player_boss_capacity (
    player_id INTEGER PRIMARY KEY,
    bonus_slots INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
