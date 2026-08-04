-- 139_reset_stage_layout_lower_yard.sql
-- Clear per-planet stage overrides so lowered BUILDING_STAGE_LAYOUT defaults apply.

DELETE FROM planet_building_stage_layout;
