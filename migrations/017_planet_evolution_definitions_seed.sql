-- Planet Evolution — definition seeds + game settings

INSERT OR IGNORE INTO game_settings (key, value) VALUES
    ('planet_research_queue_limit', '2'),
    ('planet_research_speed', '1.0'),
    ('planet_event_base_chance', '0.001'),
    ('planet_conversion_speed', '1.0'),
    ('max_colonies_per_player', '9'),
    ('colonization_cooldown_hours', '24'),
    ('discovery_global_announce', '1'),
    ('special_resource_decay_global', '0.02'),
    ('ascension_max_per_player', '1'),
    ('planet_evolution_server_salt', 'genesis_colonies_v1');

-- Traits (explicit columns — order-safe)
INSERT OR IGNORE INTO pe_trait_definitions (trait_key, category, rarity, weight, planet_class_weights_json, effects_json, unlocks_json, blocks_json, risk_json, lore_key) VALUES
('ferronit_rich_crust','geology','common',1.2,'{}','{"unlocks":["research:industry_t1_automation"],"affinity":{"industry":15}}','[]','[]','{"event_rate_mult":1.0}','trait_ferronit_rich_crust'),
('crytite_veins','geology','common',1.0,'{}','{"affinity":{"science":10}}','[]','[]','{}','trait_crytite_veins'),
('unstable_mantle','geology','uncommon',0.6,'{}','{"unlocks":["research:industry_t2_mining_path"],"affinity":{"industry":10}}','[]','[]','{"event_rate_mult":1.15,"mantle_quake":0.05}','trait_unstable_mantle'),
('deep_core_pressure','geology','rare',0.4,'{}','{"unlocks":["choice:deep_core"],"affinity":{"industry":20}}','[]','[]','{}','trait_deep_core_pressure'),
('plasma_winds','atmosphere','uncommon',0.7,'{}','{"unlocks":["research:energy_t2_plasma_harness"],"affinity":{"energy":20}}','[]','[]','{"energy_variance":0.2}','trait_plasma_winds'),
('cryogenic_atmosphere','atmosphere','uncommon',0.6,'{}','{"affinity":{"science":15,"ecology":10}}','[]','["research:energy_t2_plasma_harness"]','{}','trait_cryogenic_atmosphere'),
('aetherion_storms','atmosphere','rare',0.3,'{}','{"affinity":{"energy":25}}','[]','[]','{"storm_outage":0.08}','trait_aetherion_storms'),
('radioactive_ocean','environment','rare',0.35,'{}','{"unlocks":["research:ecology_t2_containment"],"affinity":{"ecology":10}}','[]','[]','{"contamination":0.06}','trait_radioactive_ocean'),
('organic_subsurface_network','environment','uncommon',0.5,'{}','{"unlocks":["research:ecology_t1_biomass"],"affinity":{"ecology":20}}','[]','[]','{}','trait_organic_subsurface'),
('high_gravity','environment','uncommon',0.45,'{}','{"affinity":{"military":15}}','[]','["research:orbital_t2_zero_g_foundry"]','{}','trait_high_gravity'),
('ancient_ruins','anomaly','rare',0.25,'{}','{"unlocks":["research:ancient_t1_ruins_survey"],"affinity":{"ancient":30}}','[]','[]','{"discovery_bonus":0.02}','trait_ancient_ruins'),
('dark_matter_residue','anomaly','epic',0.08,'{}','{"unlocks":["research:experimental_t1_dark_matter"],"affinity":{"experimental":25}}','[]','[]','{"event_rate_mult":1.25}','trait_dark_matter'),
('quantum_echo_field','anomaly','epic',0.06,'{}','{"affinity":{"science":25,"experimental":15}}','[]','[]','{}','trait_quantum_echo'),
('subsurface_vault_hint','hidden','rare',0.2,'{}','{"unlocks":["discovery:alien_vault"]}','[]','[]','{}','trait_vault_hint');

-- Planet research
INSERT OR IGNORE INTO pe_research_definitions VALUES
('industry_t1_automation','INDUSTRY',1,1,800,400,480,1.5,'{"buildings":{"research_lab":1}}',NULL,NULL,'{"unlock_queue":{"conversion":1}}','{}','pe_industry_t1_automation','desc_pe_industry_t1_automation'),
('industry_t2_mining_path','INDUSTRY',2,1,2000,1000,900,1.6,'{"planet_research":{"industry_t1_automation":1}}','mining_path','["orbital_mining","deep_core"]','{"choice_required":true}','{}','pe_industry_t2_mining_path','desc_pe_industry_t2_mining_path'),
('industry_t3_orbital_refinery','INDUSTRY',3,1,3500,2000,1200,1.6,'{"locked_choices":{"mining_path":"orbital_mining"}}',NULL,NULL,'{"unlock_chain":"refined_ferronit","required_unlock":"chain:refined_ferronit"}','{}','pe_industry_t3_orbital','desc_pe_industry_t3_orbital'),
('industry_t3_mantle_tap','INDUSTRY',3,1,3500,2000,1200,1.6,'{"locked_choices":{"mining_path":"deep_core"}}',NULL,NULL,'{"unlock_chain":"mantle_alloy","required_unlock":"chain:mantle_alloy"}','{}','pe_industry_t3_mantle','desc_pe_industry_t3_mantle'),
('industry_t4_mass_foundry','INDUSTRY',4,1,6000,3500,1800,1.7,'{"planet_research":{"industry_t3_orbital_refinery":1,"industry_t3_mantle_tap":1}}',NULL,NULL,'{"conversion_batch_bonus":1}','{}','pe_industry_t4_foundry','desc_pe_industry_t4_foundry'),
('industry_t5_overdrive','INDUSTRY',5,1,12000,8000,3600,1.8,'{"planet_level_min":18,"specialization_tier_min":2}',NULL,NULL,'{"enable_policy":"mandatory_overtime","risk_event":"forge_reactor_overload"}','{"experimental_failure":0.05}','pe_industry_t5_overdrive','desc_pe_industry_t5_overdrive'),
('science_t1_field_labs','SCIENCE',1,1,900,600,500,1.5,'{"buildings":{"research_lab":2}}',NULL,NULL,'{"planet_research_speed_flag":0.10}','{}','pe_science_t1','desc_pe_science_t1'),
('science_t2_quantum_mapping','SCIENCE',2,1,2500,1500,1000,1.6,'{"planet_research":{"science_t1_field_labs":1}}',NULL,NULL,'{"unlock_chain":"quantum_data","required_unlock":"chain:quantum_data"}','{}','pe_science_t2','desc_pe_science_t2'),
('science_t3_breakthrough_lab','SCIENCE',3,1,4500,3000,1500,1.7,'{"planet_research":{"science_t2_quantum_mapping":1}}',NULL,NULL,'{"enable_event_pool":"science_breakthrough"}','{}','pe_science_t3','desc_pe_science_t3'),
('science_t5_experimental_gate','SCIENCE',5,1,15000,10000,4000,1.8,'{"planet_level_min":22}',NULL,NULL,'{"enable_experimental":true}','{"experimental_failure":0.08}','pe_science_t5','desc_pe_science_t5'),
('energy_t2_plasma_harness','ENERGY',2,1,2200,1200,950,1.6,'{"traits_any":["plasma_winds"]}',NULL,NULL,'{"unlock_chain":"dark_plasma","required_unlock":"chain:dark_plasma"}','{}','pe_energy_t2','desc_pe_energy_t2'),
('ecology_t1_biomass','ECOLOGY',1,1,1000,800,520,1.5,'{}',NULL,NULL,'{"unlock_chain":"living_crystal","required_unlock":"chain:living_crystal"}','{}','pe_ecology_t1','desc_pe_ecology_t1'),
('trade_t2_market_protocols','TRADE',2,1,1800,1200,800,1.5,'{"buildings":{"command_center":3}}',NULL,NULL,'{"trade_route_bonus":0.10}','{}','pe_trade_t2','desc_pe_trade_t2'),
('governance_t1_civil_admin','GOVERNANCE',1,1,1200,600,600,1.5,'{}',NULL,NULL,'{"unlock_policy_tier":1}','{}','pe_gov_t1','desc_pe_gov_t1'),
('ancient_t1_ruins_survey','ANCIENT TECH',1,1,3000,2500,1400,1.6,'{"traits_any":["ancient_ruins"]}',NULL,NULL,'{"unlock_chain":"ancient_alloy","required_unlock":"chain:ancient_alloy"}','{}','pe_ancient_t1','desc_pe_ancient_t1'),
('experimental_t1_dark_matter','EXPERIMENTAL',1,1,5000,4000,2000,1.7,'{"traits_any":["dark_matter_residue"]}',NULL,NULL,'{"enable_experimental":true}','{"experimental_failure":0.10}','pe_experimental_t1','desc_pe_experimental_t1'),
('military_t2_fortification','MILITARY',2,1,2000,1500,900,1.6,'{"buildings":{"defense_factory":2}}',NULL,NULL,'{"unlock_chain":"phase_crystal","required_unlock":"chain:phase_crystal"}','{}','pe_military_t2','desc_pe_military_t2'),
('orbital_t2_zero_g_foundry','ORBITAL',2,1,2800,1800,1100,1.6,'{"locked_choices":{"mining_path":"orbital_mining"}}',NULL,NULL,'{"chain_output_bonus":{"refined_ferronit":0.15}}','{}','pe_orbital_t2','desc_pe_orbital_t2');

-- Specializations
INSERT OR IGNORE INTO pe_specialization_definitions VALUES
('forge_world','["ferronit_rich_crust","unstable_mantle","deep_core_pressure"]','{"industry":60}','8','["science_nexus","smuggler_colony"]','{"tier_1":{"unlocks":["export:refined_ferronit"],"import_demands":[{"resource_key":"quantum_data","required_per_hour":5}]},"tier_2":{"unlocks":["chain:mantle_alloy"]},"tier_3":{"unlocks":["policy:mandatory_overtime"]}}','["forge_reactor_overload","forge_rare_metal_vein","forge_worker_revolt"]','["refined_ferronit","mantle_alloy"]','[{"resource_key":"quantum_data","required_per_hour":5}]','spec_forge_world'),
('science_nexus','["cryogenic_atmosphere","quantum_echo_field"]','{"science":65}','8','["forge_world","smuggler_colony"]','{"tier_1":{"unlocks":["export:quantum_data"]},"tier_2":{"unlocks":["enable_event_pool:science_breakthrough"]},"tier_3":{"unlocks":["enable_experimental"]}}','["science_quantum_breach","science_breakthrough","science_ai_incident"]','["quantum_data"]','[]','spec_science_nexus'),
('fortress_planet','["high_gravity","deep_core_pressure"]','{"military":55}','8','["smuggler_colony"]','{"tier_1":{"unlocks":["export:phase_crystal"]},"tier_2":{"unlocks":["chain:phase_crystal"]},"tier_3":{"unlocks":["defense_mechanic"]}}','["fortress_siege_alert","fortress_shield_stress"]','["phase_crystal"]','[{"resource_key":"mantle_alloy","required_per_hour":3}]','spec_fortress_planet'),
('trade_hub','[]','{"trade":50}','8','[]','{"tier_1":{"unlocks":["trade_route_bonus:0.15"]},"tier_2":{"unlocks":["trade_route_max:6"]},"tier_3":{"unlocks":["market_fee_mechanic"]}}','["trade_route_disruption","trade_market_boom"]','[]','[]','spec_trade_hub'),
('smuggler_colony','["radioactive_ocean"]','{"trade":40,"crime":30}','8','["fortress_planet","science_nexus"]','{"tier_1":{"unlocks":["export:contraband","chain:contraband"]},"tier_2":{"unlocks":["crime_sweet_spot_mechanic"]},"tier_3":{"unlocks":["enable_event_pool:smuggler"]}}','["smuggler_authority_raid","smuggler_black_market_boom"]','["contraband"]','[]','spec_smuggler_colony'),
('deep_mining_colony','["ferronit_rich_crust","deep_core_pressure"]','{"industry":70}','8','["science_nexus"]','{"tier_1":{"unlocks":["chain:raw_ferronit_bulk"]},"tier_2":{"unlocks":["export:raw_ferronit_bulk"]},"tier_3":{"unlocks":["deep_core_auto"]}}','["deep_mine_collapse","deep_rare_vein"]','["raw_ferronit_bulk"]','[]','spec_deep_mining'),
('quantum_observatory','["quantum_echo_field","dark_matter_residue"]','{"science":70,"experimental":50}','8','["forge_world"]','{"tier_1":{"unlocks":["discovery_roll_bonus:0.02"]},"tier_2":{"unlocks":["export:phase_crystal"]},"tier_3":{"unlocks":["experimental_slot:1"]}}','["science_quantum_breach","science_field_discovery"]','["phase_crystal"]','[{"resource_key":"quantum_data","required_per_hour":2}]','spec_quantum_observatory'),
('industrial_megacity','["ferronit_rich_crust","plasma_winds"]','{"industry":75}','8','[]','{"tier_1":{"unlocks":["conversion_queue:2"]},"tier_2":{"unlocks":["export:refined_ferronit"]},"tier_3":{"unlocks":["stability_risk_mechanic"]}}','["forge_worker_revolt","forge_industrial_accident"]','["refined_ferronit"]','[{"resource_key":"crytite_gas","required_per_hour":4}]','spec_industrial_megacity'),
('ai_controlled_world','["ancient_ruins","quantum_echo_field"]','{"experimental":60,"governance":40}','8','["smuggler_colony"]','{"tier_1":{"unlocks":["auto_conversion:1"]},"tier_2":{"unlocks":["loyalty_mechanic_bypass"]},"tier_3":{"unlocks":["risk:ai_runaway"]}}','["science_ai_incident","ai_runaway_event"]','["ancient_alloy"]','[{"resource_key":"quantum_data","required_per_hour":8}]','spec_ai_controlled');

-- Policies
INSERT OR IGNORE INTO pe_policy_definitions VALUES
('mandatory_overtime',2,'["industrial_union_state","corporate_syndicate"]','{"chain_output_bonus":0.20}','{"stability_drift":-2.0,"industrial_pressure_drift":3.0}',72,'policy_mandatory_overtime'),
('research_mandate',1,'["scientific_collective"]','{"planet_research_speed_flag":0.15}','{"prosperity_drift":-1.0}',72,'policy_research_mandate'),
('martial_law',2,'["militarized_society"]','{"defense_mechanic":true}','{"crime_drift":-5.0,"prosperity_drift":-2.0}',72,'policy_martial_law'),
('black_market_tolerated',2,'["criminal_underworld","corporate_syndicate"]','{"contraband_output_bonus":0.50}','{"crime_drift":5.0,"loyalty_drift":-2.0}',72,'policy_black_market'),
('closed_borders',1,'["isolationists"]','{"import_penalty_immunity":true}','{"trade_route_bonus":-0.20}',72,'policy_closed_borders'),
('automation_directive',2,'["ai_governance"]','{"auto_conversion":1}','{"loyalty_drift":-3.0}',72,'policy_automation');

-- Special resources
INSERT OR IGNORE INTO pe_special_resource_definitions VALUES
('refined_ferronit',150000,1,0.02,'resource_refined_ferronit'),
('mantle_alloy',80000,1,0.015,'resource_mantle_alloy'),
('quantum_data',50000,1,0.01,'resource_quantum_data'),
('living_crystal',40000,1,0.01,'resource_living_crystal'),
('crytite_gas',60000,1,0.02,'resource_crytite_gas'),
('contraband',30000,1,0.05,'resource_contraband'),
('ancient_alloy',25000,1,0.005,'resource_ancient_alloy'),
('phase_crystal',35000,1,0.01,'resource_phase_crystal'),
('dark_plasma',45000,1,0.015,'resource_dark_plasma'),
('raw_ferronit_bulk',200000,1,0.03,'resource_raw_ferronit_bulk');

-- Production chains
INSERT OR IGNORE INTO pe_production_chain_definitions VALUES
('refined_ferronit','refined_ferronit','{"metal":500,"crystal":100}',120,'virtual','chain:refined_ferronit','{"failure":"production_accident","chance":0.02}','chain_refined_ferronit'),
('mantle_alloy','mantle_alloy','{"metal":800,"crystal":200}',60,'virtual','chain:mantle_alloy','{"failure":"mantle_quake","chance":0.03}','chain_mantle_alloy'),
('quantum_data','quantum_data','{"crystal":400}',40,'virtual','chain:quantum_data','{}','chain_quantum_data'),
('living_crystal','living_crystal','{"crystal":300,"metal":100}',25,'virtual','chain:living_crystal','{}','chain_living_crystal'),
('contraband','contraband','{"metal":200,"crystal":50}',80,'virtual','chain:contraband','{"failure":"raid_risk","chance":0.05}','chain_contraband'),
('ancient_alloy','ancient_alloy','{"crystal":600,"metal":400}',15,'virtual','chain:ancient_alloy','{}','chain_ancient_alloy'),
('phase_crystal','phase_crystal','{"crystal":500}',20,'virtual','chain:phase_crystal','{}','chain_phase_crystal'),
('dark_plasma','dark_plasma','{"metal":300,"crystal":300}',35,'virtual','chain:dark_plasma','{"failure":"plasma_instability","chance":0.04}','chain_dark_plasma'),
('raw_ferronit_bulk','raw_ferronit_bulk','{"metal":1000}',200,'virtual','chain:raw_ferronit_bulk','{}','chain_raw_ferronit_bulk'),
('crytite_gas','crytite_gas','{"crystal":350}',45,'virtual','chain:crytite_gas','{}','chain_crytite_gas');

-- Events (subset with choices JSON)
INSERT OR IGNORE INTO pe_event_definitions VALUES
('forge_reactor_overload','["spec:forge_world","spec:industrial_megacity"]','major','{"base_chance_per_day":0.06}','[{"key":"shutdown","outcome":"shutdown"},{"key":"overload","outcome":"overload"},{"key":"invest","outcome":"invest"}]','reactor_degraded','survived_reactor_overload','event_forge_reactor_overload'),
('forge_rare_metal_vein','["spec:forge_world","spec:deep_mining"]','normal','{"base_chance_per_day":0.04}','[{"key":"exploit","outcome":"exploit"},{"key":"survey","outcome":"survey"}]',NULL,'rare_metal_found','event_forge_rare_vein'),
('forge_worker_revolt','["spec:forge_world","spec:industrial_megacity"]','major','{"requires_culture":{"stability_lt":50}}','[{"key":"negotiate","outcome":"negotiate"},{"key":"crackdown","outcome":"crackdown"}]','stability_collapse','survived_rebellion','event_forge_worker_revolt'),
('science_quantum_breach','["spec:science_nexus","spec:quantum_observatory"]','major','{"base_chance_per_day":0.05}','[{"key":"contain","outcome":"contain"},{"key":"push","outcome":"push"}]','research_containment_breach','quantum_breach_survived','event_science_quantum_breach'),
('science_breakthrough','["spec:science_nexus"]','normal','{"base_chance_per_day":0.03}','[{"key":"publish","outcome":"publish"},{"key":"classify","outcome":"classify"}]',NULL,'breakthrough_achieved','event_science_breakthrough'),
('science_ai_incident','["spec:ai_controlled_world","spec:science_nexus"]','major','{"base_chance_per_day":0.04}','[{"key":"shutdown_ai","outcome":"shutdown"},{"key":"integrate","outcome":"integrate"}]','ai_runaway','ai_incident_resolved','event_science_ai_incident'),
('smuggler_authority_raid','["spec:smuggler_colony"]','major','{"requires_culture":{"crime_gt":40}}','[{"key":"bribe","outcome":"bribe"},{"key":"hide","outcome":"hide"},{"key":"fight","outcome":"fight"}]','smuggling_crackdown','survived_raid','event_smuggler_raid'),
('smuggler_black_market_boom','["spec:smuggler_colony"]','normal','{"requires_culture":{"crime_range":[40,70]}}','[{"key":"expand","outcome":"expand"},{"key":"consolidate","outcome":"consolidate"}]',NULL,'black_market_expanded','event_smuggler_boom'),
('fortress_siege_alert','["spec:fortress_planet"]','normal','{"base_chance_per_day":0.02}','[{"key":"fortify","outcome":"fortify"},{"key":"evacuate_exports","outcome":"evacuate"}]',NULL,'siege_survived','event_fortress_siege'),
('trade_route_disruption','["spec:trade_hub"]','normal','{"base_chance_per_day":0.03}','[{"key":"reroute","outcome":"reroute"},{"key":"escort","outcome":"escort"}]',NULL,'trade_disruption_handled','event_trade_disruption');

-- Discoveries
INSERT OR IGNORE INTO pe_discovery_definitions VALUES
('alien_vault','epic',0.005,'{"traits_any":["subsurface_vault_hint","ancient_ruins"]}','{"unlock_chain":"ancient_alloy","permanent_flag":"vault_opened"}',1,'discovery_alien_vault'),
('dark_core','rare',0.008,'{"traits_any":["dark_matter_residue"]}','{"enable_experimental":true,"stability_penalty":-10}',0,'discovery_dark_core'),
('ancient_ai','epic',0.003,'{"specialization":"ai_controlled_world"}','{"auto_research_weekly":1,"rebellion_risk":0.05}',1,'discovery_ancient_ai'),
('quantum_rift','legendary',0.001,'{"planet_level_min":20}','{"random_research_complete":true}',1,'discovery_quantum_rift'),
('living_crystal_network','rare',0.006,'{"traits_any":["organic_subsurface_network"]}','{"unlock_chain":"living_crystal","output_bonus":0.25}',0,'discovery_living_crystal');

-- Ascension
INSERT OR IGNORE INTO pe_ascension_definitions VALUES
('machine_ascension','{"planet_level_min":25,"specialization_tier_min":3,"cost":{"metal":5000000,"crystal":3000000}}','{"auto_conversion":2,"loyalty_mechanic_bypass":true,"export_penalty":-0.15}','7','ascension_machine'),
('quantum_ascension','{"planet_level_min":25,"specialization_tier_min":3,"discoveries_any":["quantum_rift","dark_core"]}','{"experimental_slot":2,"quantum_instability":true,"discovery_roll_mult":2.0}','7','ascension_quantum'),
('industrial_ascension','{"planet_level_min":25,"specialization":"forge_world","specialization_tier_min":3}','{"export_slots":2,"chain_output_mult":1.4,"depletion_risk_mult":2.0}','7','ascension_industrial'),
('ancient_ascension','{"planet_level_min":25,"discoveries_any":["alien_vault","ancient_ai"],"traits_any":["ancient_ruins"]}','{"ancient_t6_unlock":true,"high_value_target":true}','7','ascension_ancient');
