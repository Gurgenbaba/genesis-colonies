-- GC-974B: Deep-Core parity — mantle T2 tech + mantle_alloy base rate

INSERT OR IGNORE INTO pe_research_definitions VALUES
(
    'mantle_t2_deep_core_refinery',
    'MANTLE',
    2,
    1,
    2800,
    1800,
    1100,
    1.6,
    '{"locked_choices":{"mining_path":"deep_core"}}',
    NULL,
    NULL,
    '{"chain_output_bonus":{"mantle_alloy":0.15}}',
    '{}',
    'pe_mantle_t2',
    'desc_pe_mantle_t2'
);

UPDATE pe_production_chain_definitions
SET base_output_per_hour = 90
WHERE chain_key = 'mantle_alloy';
