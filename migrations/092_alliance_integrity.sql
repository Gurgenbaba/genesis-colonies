-- GC-AL-MVP-01: integrity indexes for alliance hub (no new tables)

CREATE UNIQUE INDEX IF NOT EXISTS idx_alliance_projects_one_active
    ON alliance_projects(alliance_id)
    WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS idx_alliance_diplomacy_requests_pending
    ON alliance_diplomacy_requests(from_alliance_id, to_alliance_id, request_type)
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_alliance_applications_player_pending
    ON alliance_applications(player_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_alliance_donations_player_day
    ON alliance_donations(player_id, created_at);
