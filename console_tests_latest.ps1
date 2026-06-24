$failures = @()
Write-Host "Genesis Console Tests" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan

Write-Host "[1] Pytest: python -m pytest tests/test_core_architecture_enforcement.py..." -ForegroundColor Yellow
python -m pytest tests/test_core_architecture_enforcement.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[2] Pytest: python -m pytest tests/test_defense_detail_modal.py..." -ForegroundColor Yellow
python -m pytest tests/test_defense_detail_modal.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[3] Pytest: python -m pytest tests/test_fleet.py..." -ForegroundColor Yellow
python -m pytest tests/test_fleet.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[4] Scripts: scripts/install.py`)..." -ForegroundColor Yellow
scripts/install.py`)
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[5] Queue: scripts/run_queue_tick.py`,..." -ForegroundColor Yellow
scripts/run_queue_tick.py`,
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[6] Pytest: python -m pytest -q..." -ForegroundColor Yellow
python -m pytest -q
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[7] Pytest: python -m pytest tests/test_race_conditions.py..." -ForegroundColor Yellow
python -m pytest tests/test_race_conditions.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[8] Pytest: python -m pytest tests/test_combat.py..." -ForegroundColor Yellow
python -m pytest tests/test_combat.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[9] Pytest: python -m pytest tests/test_ranking.py::test_combat_destruct..." -ForegroundColor Yellow
python -m pytest tests/test_ranking.py::test_combat_destruction_increases_ranking_scores
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[10] Pytest: pytest |..." -ForegroundColor Yellow
pytest |
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[11] Pytest: python -m pytest tests/..." -ForegroundColor Yellow
python -m pytest tests/
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[12] Pytest: python -m pytest tests/test_effects.py..." -ForegroundColor Yellow
python -m pytest tests/test_effects.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[13] Pytest: python -m pytest tests/test_galaxy.py..." -ForegroundColor Yellow
python -m pytest tests/test_galaxy.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[14] Pytest: pytest guards..." -ForegroundColor Yellow
pytest guards
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[15] Pytest: pytest inkl...." -ForegroundColor Yellow
pytest inkl.
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[16] Pytest: python -m pytest tests/test_queue_static_contract.py..." -ForegroundColor Yellow
python -m pytest tests/test_queue_static_contract.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[17] Pytest: pytest Guards)...." -ForegroundColor Yellow
pytest Guards).
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[18] Pytest: pytest ersetzbar...." -ForegroundColor Yellow
pytest ersetzbar.
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[19] Pytest: pytest grün..." -ForegroundColor Yellow
pytest grün
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[20] Pytest: pytest tests/test_queue_card_contract.py..." -ForegroundColor Yellow
pytest tests/test_queue_card_contract.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[21] Pytest: pytest tests/test_queue_card_global_ux.py..." -ForegroundColor Yellow
pytest tests/test_queue_card_global_ux.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[22] Pytest: pytest +..." -ForegroundColor Yellow
pytest +
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[23] Pytest: python -m pytest tests/test_static_live_updates.py..." -ForegroundColor Yellow
python -m pytest tests/test_static_live_updates.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[24] Pytest: pytest 41..." -ForegroundColor Yellow
pytest 41
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[25] Pytest: pytest (41..." -ForegroundColor Yellow
pytest (41
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[26] Scripts: python scripts/gc547_browser_audit.py..." -ForegroundColor Yellow
python scripts/gc547_browser_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[27] Scripts: scripts/gc547_browser_audit.py..." -ForegroundColor Yellow
scripts/gc547_browser_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[28] Pytest: pytest tests/test_static_live_updates.py..." -ForegroundColor Yellow
pytest tests/test_static_live_updates.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[29] Scripts: tools/generate_icons.py..." -ForegroundColor Yellow
tools/generate_icons.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[30] Scripts: tools/generate_icons.py`)...." -ForegroundColor Yellow
tools/generate_icons.py`).
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[31] Scripts: tools/optimize_images.py..." -ForegroundColor Yellow
tools/optimize_images.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[32] Scripts: scripts/optimize_landscapes.py..." -ForegroundColor Yellow
scripts/optimize_landscapes.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[33] Scripts: scripts/optimize_landscapes.py`)..." -ForegroundColor Yellow
scripts/optimize_landscapes.py`)
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[34] Scripts: python tools/optimize_images.py..." -ForegroundColor Yellow
python tools/optimize_images.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[35] Pytest: pytest tests/test_shipyard_assets.py..." -ForegroundColor Yellow
pytest tests/test_shipyard_assets.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[36] Pytest: pytest tests/test_static_live_updates.py::test_main_js_gc549..." -ForegroundColor Yellow
pytest tests/test_static_live_updates.py::test_main_js_gc549_ship_defense_icons_use_png
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[37] Pytest: pytest tests/test_static_live_updates.py::test_main_js_gc548..." -ForegroundColor Yellow
pytest tests/test_static_live_updates.py::test_main_js_gc548_landscape_visible_on_perf_idle_boot
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[38] Pytest: pytest tests/test_defense_detail_modal.py..." -ForegroundColor Yellow
pytest tests/test_defense_detail_modal.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[39] Scripts: tools/audit_assets.py..." -ForegroundColor Yellow
tools/audit_assets.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[40] Scripts: tools/audit_assets_webp.py..." -ForegroundColor Yellow
tools/audit_assets_webp.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[41] Scripts: tools/convert_webp.py..." -ForegroundColor Yellow
tools/convert_webp.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[42] Scripts: python tools/audit_assets.py..." -ForegroundColor Yellow
python tools/audit_assets.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[43] Scripts: python tools/convert_webp.py..." -ForegroundColor Yellow
python tools/convert_webp.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[44] Scripts: python tools/audit_assets_webp.py..." -ForegroundColor Yellow
python tools/audit_assets_webp.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[45] Pytest: python -m pytest tests/test_gc557d_timer_dom_audit.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc557d_timer_dom_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[46] Pytest: python -m pytest tests/test_gc557_global_timer_audit.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc557_global_timer_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[47] Pytest: pytest belegt..." -ForegroundColor Yellow
pytest belegt
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[48] Pytest: pytest tests/test_empire_identity.py..." -ForegroundColor Yellow
pytest tests/test_empire_identity.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[49] Pytest: pytest tests/test_expansion_gates.py..." -ForegroundColor Yellow
pytest tests/test_expansion_gates.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[50] Pytest: pytest ohne..." -ForegroundColor Yellow
pytest ohne
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[51] Pytest: pytest tests/test_command_map_viewport.py..." -ForegroundColor Yellow
pytest tests/test_command_map_viewport.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[52] Pytest: pytest tests/test_command_map.py..." -ForegroundColor Yellow
pytest tests/test_command_map.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[53] Pytest: pytest tests/test_imperium_regions.py..." -ForegroundColor Yellow
pytest tests/test_imperium_regions.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[54] Pytest: pytest tests/test_chokepoints.py..." -ForegroundColor Yellow
pytest tests/test_chokepoints.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[55] Pytest: pytest tests/test_dynamic_influence.py..." -ForegroundColor Yellow
pytest tests/test_dynamic_influence.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[56] Pytest: pytest tests/test_region_landmarks.py..." -ForegroundColor Yellow
pytest tests/test_region_landmarks.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[57] Pytest: pytest tests/test_location_actions.py..." -ForegroundColor Yellow
pytest tests/test_location_actions.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[58] Pytest: pytest tests/test_world_map.py..." -ForegroundColor Yellow
pytest tests/test_world_map.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[59] Pytest: pytest grün,..." -ForegroundColor Yellow
pytest grün,
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[60] Pytest: pytest research..." -ForegroundColor Yellow
pytest research
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[61] Pytest: pytest GC-512C...." -ForegroundColor Yellow
pytest GC-512C.
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[62] Pytest: python -m pytest tests/test_locale_keys.py..." -ForegroundColor Yellow
python -m pytest tests/test_locale_keys.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[63] Pytest: pytest tests/test_expedition_events.py..." -ForegroundColor Yellow
pytest tests/test_expedition_events.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[64] Pytest: pytest (kein..." -ForegroundColor Yellow
pytest (kein
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[65] Pytest: python -m pytest tests/test_game_state_live.py..." -ForegroundColor Yellow
python -m pytest tests/test_game_state_live.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[66] Pytest: python -m pytest tests/test_ranking.py..." -ForegroundColor Yellow
python -m pytest tests/test_ranking.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[67] Pytest: python -m pytest tests/test_gc597_world_inspector_modal.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc597_world_inspector_modal.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[68] Pytest: pytest Performance..." -ForegroundColor Yellow
pytest Performance
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[69] Pytest: pytest tests/test_gc622_integer_overflow.py..." -ForegroundColor Yellow
pytest tests/test_gc622_integer_overflow.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[70] Pytest: python -m pytest tests/test_gc622_integer_overflow.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc622_integer_overflow.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[71] Pytest: pytest tests/test_recycler.py..." -ForegroundColor Yellow
pytest tests/test_recycler.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[72] Pytest: python -m pytest tests/test_gc821f_mine_roi_bulk.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc821f_mine_roi_bulk.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[73] Pytest: python -m pytest tests/test_gc821_economy_rebalance.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc821_economy_rebalance.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[74] Economy: scripts/economy_live_audit.py..." -ForegroundColor Yellow
scripts/economy_live_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[75] Economy: python scripts/economy_live_audit.py..." -ForegroundColor Yellow
python scripts/economy_live_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[76] Pytest: python -m pytest tests/test_gc822_live_economy_audit.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc822_live_economy_audit.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[77] Pytest: python -m pytest tests/test_gc823_technical_data.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc823_technical_data.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[78] Scripts: python scripts/fresh_account_progression_sim.py`...." -ForegroundColor Yellow
python scripts/fresh_account_progression_sim.py`.
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[79] Pytest: python -m pytest tests/test_gc831_queue_refund.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc831_queue_refund.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[80] Scripts: python scripts/fresh_account_progression_sim.py..." -ForegroundColor Yellow
python scripts/fresh_account_progression_sim.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[81] Pytest: python -m pytest tests/test_gc836_starter_resources.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc836_starter_resources.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[82] Pytest: python -m pytest tests/test_fleet_logistics.py..." -ForegroundColor Yellow
python -m pytest tests/test_fleet_logistics.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[83] Pytest: python -m pytest tests/test_planet_evolution.py..." -ForegroundColor Yellow
python -m pytest tests/test_planet_evolution.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[84] Pytest: python -m pytest tests/test_planet_instancing.py..." -ForegroundColor Yellow
python -m pytest tests/test_planet_instancing.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[85] Pytest: python -m pytest tests/test_production_formula.py..." -ForegroundColor Yellow
python -m pytest tests/test_production_formula.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[86] Pytest: pytest optional..." -ForegroundColor Yellow
pytest optional
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[87] Pytest: pytest Allowlist;..." -ForegroundColor Yellow
pytest Allowlist;
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[88] Pytest: python -m pytest tests/test_queue_engine.py..." -ForegroundColor Yellow
python -m pytest tests/test_queue_engine.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[89] Pytest: python -m pytest tests/test_research_requirements.py..." -ForegroundColor Yellow
python -m pytest tests/test_research_requirements.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[90] Pytest: pytest tests/test_….py..." -ForegroundColor Yellow
pytest tests/test_….py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[91] Scripts: python scripts/universe_speed_benchmark.py..." -ForegroundColor Yellow
python scripts/universe_speed_benchmark.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[92] Pytest: python -m pytest tests/test_account_email.py..." -ForegroundColor Yellow
python -m pytest tests/test_account_email.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[93] Pytest: python -m pytest tests/test_admin_balance_settings.py..." -ForegroundColor Yellow
python -m pytest tests/test_admin_balance_settings.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[94] Pytest: python -m pytest tests/test_admin_control_center.py..." -ForegroundColor Yellow
python -m pytest tests/test_admin_control_center.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[95] Pytest: python -m pytest tests/test_auth.py..." -ForegroundColor Yellow
python -m pytest tests/test_auth.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[96] Pytest: python -m pytest tests/test_buildings_card_queue.py..." -ForegroundColor Yellow
python -m pytest tests/test_buildings_card_queue.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[97] Pytest: python -m pytest tests/test_chat.py..." -ForegroundColor Yellow
python -m pytest tests/test_chat.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[98] Pytest: python -m pytest tests/test_db_read_paths.py..." -ForegroundColor Yellow
python -m pytest tests/test_db_read_paths.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[99] Pytest: python -m pytest tests/test_defense_card_queue.py..." -ForegroundColor Yellow
python -m pytest tests/test_defense_card_queue.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[100] Pytest: python -m pytest tests/test_deployment.py..." -ForegroundColor Yellow
python -m pytest tests/test_deployment.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[101] Pytest: python -m pytest tests/test_empire_page.py..." -ForegroundColor Yellow
python -m pytest tests/test_empire_page.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[102] Pytest: python -m pytest tests/test_gc804_research_timer.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc804_research_timer.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[103] Pytest: python -m pytest tests/test_gc821e_production_display_roi.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc821e_production_display_roi.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[104] Pytest: python -m pytest tests/test_gc827_compact_cards.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc827_compact_cards.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[105] Pytest: python -m pytest tests/test_gc833b_queue_cancel_state.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc833b_queue_cancel_state.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[106] Pytest: python -m pytest tests/test_gc833_queue_completion_state.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc833_queue_completion_state.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[107] Pytest: python -m pytest tests/test_gc835_frontend_state_contract.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc835_frontend_state_contract.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[108] Pytest: python -m pytest tests/test_gc838_queue_action_latency.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc838_queue_action_latency.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[109] Pytest: python -m pytest tests/test_gc840_buildings_action_payload.p..." -ForegroundColor Yellow
python -m pytest tests/test_gc840_buildings_action_payload.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[110] Pytest: python -m pytest tests/test_gc_sec_p0.py..." -ForegroundColor Yellow
python -m pytest tests/test_gc_sec_p0.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[111] Pytest: python -m pytest tests/test_messages.py..." -ForegroundColor Yellow
python -m pytest tests/test_messages.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[112] Pytest: python -m pytest tests/test_nexus_building_caps.py..." -ForegroundColor Yellow
python -m pytest tests/test_nexus_building_caps.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[113] Pytest: python -m pytest tests/test_options.py..." -ForegroundColor Yellow
python -m pytest tests/test_options.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[114] Pytest: python -m pytest tests/test_persistence.py..." -ForegroundColor Yellow
python -m pytest tests/test_persistence.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[115] Pytest: python -m pytest tests/test_placeholder_nav.py..." -ForegroundColor Yellow
python -m pytest tests/test_placeholder_nav.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[116] Pytest: python -m pytest tests/test_planet_evolution_card_queue.py..." -ForegroundColor Yellow
python -m pytest tests/test_planet_evolution_card_queue.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[117] Pytest: python -m pytest tests/test_planet_state_scoping.py..." -ForegroundColor Yellow
python -m pytest tests/test_planet_state_scoping.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[118] Pytest: python -m pytest tests/test_playercard.py..." -ForegroundColor Yellow
python -m pytest tests/test_playercard.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[119] Pytest: python -m pytest tests/test_progression_pages.py..." -ForegroundColor Yellow
python -m pytest tests/test_progression_pages.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[120] Pytest: python -m pytest tests/test_queue_card_contract.py..." -ForegroundColor Yellow
python -m pytest tests/test_queue_card_contract.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[121] Pytest: python -m pytest tests/test_queue_card_global_ux.py..." -ForegroundColor Yellow
python -m pytest tests/test_queue_card_global_ux.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[122] Pytest: python -m pytest tests/test_research_card_queue.py..." -ForegroundColor Yellow
python -m pytest tests/test_research_card_queue.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[123] Pytest: python -m pytest tests/test_security_tamper.py..." -ForegroundColor Yellow
python -m pytest tests/test_security_tamper.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[124] Pytest: python -m pytest tests/test_shipyard_card_queue.py..." -ForegroundColor Yellow
python -m pytest tests/test_shipyard_card_queue.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[125] Scripts: tools/generate_icons.py")..." -ForegroundColor Yellow
tools/generate_icons.py")
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[126] Scripts: tools/audit_assets.py")..." -ForegroundColor Yellow
tools/audit_assets.py")
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[127] Scripts: tools/convert_webp.py")..." -ForegroundColor Yellow
tools/convert_webp.py")
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[128] Pytest: python -m pytest tests/test_support.py..." -ForegroundColor Yellow
python -m pytest tests/test_support.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

Write-Host "[129] Pytest: python -m pytest tests/test_techtree.py..." -ForegroundColor Yellow
python -m pytest tests/test_techtree.py
if ($LASTEXITCODE -ne 0) { $failures += "Line $i: $cmd" }

if ($failures.Count -gt 0) {
  Write-Host "FAILED COMMANDS:" -ForegroundColor Red
  $failures | ForEach-Object { Write-Host " - $_" }
  exit 1
} else {
  Write-Host "ALL TESTS PASSED" -ForegroundColor Green
}
