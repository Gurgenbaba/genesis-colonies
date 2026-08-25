from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_diplomacy_send_is_not_patch_only_and_uses_canonical_refresh():
    js = _source("static/main.js")
    start = js.index("const ALLIANCE_PATCH_ONLY = new Set([")
    end = js.index("]);", start)
    patch_only = js[start:end]
    assert '"alliance_diplomacy"' not in patch_only

    send = js.index('"/api/alliance/diplomacy/send"')
    tail = js[send : send + 900]
    assert 'allianceFinalizeSuccess("alliance_diplomacy", out)' in tail


def test_diplomacy_respond_uses_canonical_refresh():
    js = _source("static/main.js")
    assert js.count('"/api/alliance/diplomacy/respond"') >= 2
    assert js.count('allianceFinalizeSuccess("alliance_diplomacy_respond", out)') >= 2


def test_alliance_reload_preserves_active_tab_without_hard_reload():
    js = _source("static/main.js")
    start = js.index("async function allianceReloadHub(reason)")
    end = js.index("const ALLIANCE_PATCH_ONLY", start)
    block = js[start:end]
    assert 'dataset.allianceTab || ""' in block
    assert "switchAllianceTab(refreshedPage, activeTab)" in block
    assert "GC.navigateTo" in block
    assert "location.reload" not in block
    assert "location.assign" not in block
    assert "location.href" not in block


def test_diplomacy_geometry_is_square_and_scoped():
    css = _source("static/style.css")
    marker = "/* GC-AL-UX-04: diplomacy uses square Evo/Genesis geometry. */"
    start = css.index(marker)
    block = css[start : start + 1400]
    assert '[data-alliance-panel="diplomacy"]' in block
    assert ".alliance-hub-war-meta" in block
    assert ".alliance-hub-dip-badge" in block
    assert "border-radius: 0 !important;" in block
