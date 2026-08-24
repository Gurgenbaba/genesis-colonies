-- 154_big_score_ranking.sql
-- GC-SCORE-BIGNUM: arbitrary-precision ranking persistence.
-- Score columns are decimal TEXT. Arithmetic and ordering are authoritative in Python int.

DROP INDEX IF EXISTS idx_player_scores_total;
DROP INDEX IF EXISTS idx_player_scores_updated;
DROP INDEX IF EXISTS idx_player_scores_rank_total;
DROP INDEX IF EXISTS idx_player_scores_rank_fleet;

CREATE TABLE player_scores_bigint (
    player_id INTEGER PRIMARY KEY,
    score_total TEXT NOT NULL DEFAULT '0',
    score_resources TEXT NOT NULL DEFAULT '0',
    score_buildings TEXT NOT NULL DEFAULT '0',
    score_research TEXT NOT NULL DEFAULT '0',
    score_fleet TEXT NOT NULL DEFAULT '0',
    score_defense TEXT NOT NULL DEFAULT '0',
    score_planet_evolution TEXT NOT NULL DEFAULT '0',
    score_destroyed_raw TEXT NOT NULL DEFAULT '0',
    score_combat TEXT NOT NULL DEFAULT '0',
    score_destroyed TEXT NOT NULL DEFAULT '0',
    updated_at INTEGER NOT NULL DEFAULT 0,
    rank_total INTEGER,
    rank_building INTEGER,
    rank_research INTEGER,
    rank_fleet INTEGER,
    rank_combat INTEGER,
    rank_destroyed INTEGER,
    rank_military INTEGER
);

INSERT INTO player_scores_bigint (
    player_id, score_total, score_resources, score_buildings, score_research,
    score_fleet, score_defense, score_planet_evolution, score_destroyed_raw,
    score_combat, score_destroyed, updated_at, rank_total, rank_building,
    rank_research, rank_fleet, rank_combat, rank_destroyed, rank_military
)
SELECT
    player_id,
    CAST(COALESCE(score_total, 0) AS TEXT),
    CAST(COALESCE(score_resources, 0) AS TEXT),
    CAST(COALESCE(score_buildings, 0) AS TEXT),
    CAST(COALESCE(score_research, 0) AS TEXT),
    CAST(COALESCE(score_fleet, 0) AS TEXT),
    CAST(COALESCE(score_defense, 0) AS TEXT),
    CAST(COALESCE(score_planet_evolution, 0) AS TEXT),
    CAST(COALESCE(score_destroyed_raw, 0) AS TEXT),
    CAST(COALESCE(score_combat, 0) AS TEXT),
    CAST(COALESCE(score_destroyed, 0) AS TEXT),
    COALESCE(updated_at, 0),
    rank_total, rank_building, rank_research, rank_fleet,
    rank_combat, rank_destroyed, rank_military
FROM player_scores;

DROP TABLE player_scores;
ALTER TABLE player_scores_bigint RENAME TO player_scores;

CREATE INDEX IF NOT EXISTS idx_player_scores_updated ON player_scores (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_player_scores_rank_total ON player_scores (rank_total ASC);
CREATE INDEX IF NOT EXISTS idx_player_scores_rank_fleet ON player_scores (rank_fleet ASC);
