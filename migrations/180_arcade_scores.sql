-- Arcade easter egg on the developer portfolio: public top-score board.
-- No player link and no IP address; run_nonce makes each signed run token single-use.

CREATE TABLE IF NOT EXISTS arcade_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    score       INTEGER NOT NULL,
    wave        INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    run_nonce   TEXT NOT NULL UNIQUE,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_arcade_scores_rank
    ON arcade_scores(score DESC, created_at ASC);
