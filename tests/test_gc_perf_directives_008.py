"""GC-PERF-DIRECTIVES-008 — claim hotpath + definition bulk-read contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _route_block(name: str, next_route: str) -> str:
    src = _read("app.py")
    return src.split(f"def {name}():", 1)[1].split(next_route, 1)[0]


def test_directive_claims_use_hud_slim_state_not_full_panel_state():
    single = _route_block(
        "api_imperial_directives_claim",
        '@app.route("/api/imperial-directives/claim-all"',
    )
    claim_all = _route_block(
        "api_imperial_directives_claim_all",
        "# --------------------------------------------------------------------------\n"
        "# IMPERIAL DIRECTIVES",
    )

    for block, source in (
        (single, "api_imperial_directives_claim"),
        (claim_all, "api_imperial_directives_claim_all"),
    ):
        assert f'_hud_only_game_state("{source}")' in block
        assert "_build_game_state_payload(" not in block
        assert "include_panel=True" not in block
        assert "conn2 = db()" not in block


def test_directive_claims_reuse_mutation_connection_for_page_state():
    single = _route_block(
        "api_imperial_directives_claim",
        '@app.route("/api/imperial-directives/claim-all"',
    )
    claim_all = _route_block(
        "api_imperial_directives_claim_all",
        "# --------------------------------------------------------------------------\n"
        "# IMPERIAL DIRECTIVES",
    )

    assert "imperial_directives = get_imperial_directives_state(user_id, conn=conn)" in single
    assert "imperial_directives = get_imperial_directives_state(user_id, conn=conn)" in claim_all

    for block, source in (
        (single, "api_imperial_directives_claim"),
        (claim_all, "api_imperial_directives_claim_all"),
    ):
        success = block.rsplit("    else:\n", 1)[1].split("    finally:", 1)[0]
        hud_pos = success.index(f'_hud_only_game_state("{source}")')
        cards_pos = success.index(
            "get_imperial_directives_state(user_id, conn=conn)"
        )
        assert hud_pos < cards_pos


def test_directives_state_bulk_loads_definitions_once():
    src = _read("game/directives/service.py")
    block = src.split("def get_imperial_directives_state(", 1)[1]

    assert "definitions = get_definitions(" in block
    assert "definitions.get(" in block
    assert "get_definition(" not in block


def test_directive_generation_reuses_existing_definition_snapshot():
    src = _read("game/directives/generator.py")
    block = src.split("def generate_directives_for_cadence(", 1)[1].split(
        "\ndef _fetch_player_directives(",
        1,
    )[0]

    assert "existing_definitions = get_definitions(" in block
    assert "definitions=existing_definitions" in block
    assert 'existing_definitions.get(str(row.get("definition_key") or ""))' in block

    stale = src.split("def _directive_row_stale(", 1)[1].split(
        "\ndef generate_directives_for_cadence(",
        1,
    )[0]
    assert "definitions: Optional[Mapping" in stale
    assert "definitions.get(definition_key)" in stale


def test_bulk_definition_lookup_keeps_existing_disabled_definitions():
    src = _read("game/directives/definitions.py")
    block = src.split("def get_definitions(", 1)[1].split(
        "\ndef get_definition(",
        1,
    )[0]

    assert "WHERE key IN" in block
    assert "weight" in block
    assert "weight) <= 0" not in block
    assert "definition_is_rollable" not in block


def test_action_diet_registry_knows_directive_claim_sources():
    src = _read("app.py")
    block = src.split("def _uses_action_state_diet(", 1)[1].split(
        "\ndef _hud_only_game_state",
        1,
    )[0]

    assert '"api_imperial_directives_claim"' in block
    assert '"api_imperial_directives_claim_all"' in block
