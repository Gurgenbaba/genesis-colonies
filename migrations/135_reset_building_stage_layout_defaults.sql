-- GC-BST: clear early stage-layout overrides so spaced defaults take effect.
-- Custom arrange positions can be re-saved after this reset.
DELETE FROM planet_building_stage_layout;
