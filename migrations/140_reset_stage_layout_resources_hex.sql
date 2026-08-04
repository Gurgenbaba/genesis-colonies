-- 140_reset_stage_layout_resources_hex.sql
-- Clear per-planet stage overrides so player-tuned Resources 2-3-2 defaults apply.

DELETE FROM planet_building_stage_layout;
