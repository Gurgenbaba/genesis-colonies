def test_pjax_omits_inert_shell_json_payloads(game_client):
    client, _pid = game_client
    full = client.get("/buildings?tab=resources")
    pjax = client.get(
        "/buildings?tab=resources",
        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},
    )
    assert full.status_code == 200
    assert pjax.status_code == 200
    full_body = full.get_data()
    pjax_body = pjax.get_data()
    assert b'id="gc-locale"' in full_body
    assert b'id="gc-client-config"' in full_body
    assert b'id="gc-codex-client"' in full_body
    assert b'id="gc-locale"' not in pjax_body
    assert b'id="gc-client-config"' not in pjax_body
    assert b'id="gc-codex-client"' not in pjax_body
    assert b'id="main-content"' in pjax_body
    assert len(pjax_body) + 100_000 < len(full_body)
