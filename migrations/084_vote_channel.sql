-- 084_vote_channel.sql
-- Vote channel tagging: player (manual/postback) vs reengagement (staggered inactive).

ALTER TABLE vote_rewards ADD COLUMN vote_channel TEXT NOT NULL DEFAULT 'player';

CREATE INDEX IF NOT EXISTS idx_vote_rewards_channel_voted
    ON vote_rewards(vote_channel, voted_at DESC);

CREATE INDEX IF NOT EXISTS idx_vote_rewards_user_channel
    ON vote_rewards(user_id, vote_channel);
