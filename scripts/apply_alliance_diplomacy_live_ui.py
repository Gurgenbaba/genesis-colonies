from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one marker, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Preserve the user's active Alliance tab across canonical PJAX hub refreshes.
replace_once(
    "static/main.js",
    '''  async function allianceReloadHub(reason) {\n    const cleanUrl = "/alliance";\n''',
    '''  async function allianceReloadHub(reason) {\n    const currentPage = document.getElementById("alliance-page");\n    const activeTab =\n      currentPage?.querySelector("[data-alliance-tab].is-active")?.dataset.allianceTab || "";\n    const cleanUrl = "/alliance";\n''',
)
replace_once(
    "static/main.js",
    '''    if (window.history?.replaceState) {\n      window.history.replaceState(null, "", cleanUrl);\n    }\n    void reason;\n  }\n\n  /** In-hub field updates: allianceAction already applied state + patchAllianceDom. */\n''',
    '''    if (window.history?.replaceState) {\n      window.history.replaceState(null, "", cleanUrl);\n    }\n    const refreshedPage = document.getElementById("alliance-page");\n    if (activeTab && refreshedPage) switchAllianceTab(refreshedPage, activeTab);\n    void reason;\n  }\n\n  /** In-hub field updates: allianceAction already applied state + patchAllianceDom. */\n''',
)

# 2) Diplomacy is structurally server-rendered (relations, requests, WAR panel/actions).
# It must not be treated as patch-only: successful sends now execute allianceReloadHub().
replace_once(
    "static/main.js",
    '''    "alliance_profile",\n    "alliance_recruitment",\n    "alliance_diplomacy",\n    "alliance_donate",\n''',
    '''    "alliance_profile",\n    "alliance_recruitment",\n    "alliance_donate",\n''',
)

# 3) Diplomacy visual contract: square Evo/Genesis geometry, scoped to this tab only.
css = Path("static/style.css")
css_text = css.read_text(encoding="utf-8")
marker = "/* GC-AL-UX-04: diplomacy uses square Evo/Genesis geometry. */"
if marker in css_text:
    raise SystemExit("static/style.css: GC-AL-UX-04 marker already present")
css_text += f'''\n\n{marker}\n#alliance-page [data-alliance-panel="diplomacy"] input,\n#alliance-page [data-alliance-panel="diplomacy"] select,\n#alliance-page [data-alliance-panel="diplomacy"] button,\n#alliance-page [data-alliance-panel="diplomacy"] .gc-input,\n#alliance-page [data-alliance-panel="diplomacy"] .gc-btn,\n#alliance-page [data-alliance-panel="diplomacy"] .alliance-hub-dip-badge,\n#alliance-page [data-alliance-panel="diplomacy"] .alliance-hub-war-meta,\n#alliance-page [data-alliance-panel="diplomacy"] .alliance-hub-diplomacy-row,\n#alliance-page [data-alliance-panel="diplomacy"] .alliance-hub-dip-row {{\n  border-radius: 0 !important;\n}}\n'''
css.write_text(css_text, encoding="utf-8")

# 4) Small source-contract regression: protects live refresh + square diplomacy UI.
test = Path("tests/test_alliance_diplomacy_live_ui.py")
if test.exists():
    raise SystemExit(f"{test}: already exists")
test.write_text(
    '''from pathlib import Path\n\n\ndef _source(path: str) -> str:\n    return Path(path).read_text(encoding="utf-8")\n\n\ndef test_diplomacy_send_is_not_patch_only_and_uses_canonical_refresh():\n    js = _source("static/main.js")\n    start = js.index("const ALLIANCE_PATCH_ONLY = new Set([")\n    end = js.index("]);", start)\n    patch_only = js[start:end]\n    assert '"alliance_diplomacy"' not in patch_only\n\n    send = js.index('"/api/alliance/diplomacy/send"')\n    tail = js[send : send + 900]\n    assert 'allianceFinalizeSuccess("alliance_diplomacy", out)' in tail\n\n\ndef test_diplomacy_respond_uses_canonical_refresh():\n    js = _source("static/main.js")\n    assert js.count('"/api/alliance/diplomacy/respond"') >= 2\n    assert js.count('allianceFinalizeSuccess("alliance_diplomacy_respond", out)') >= 2\n\n\ndef test_alliance_reload_preserves_active_tab_without_hard_reload():\n    js = _source("static/main.js")\n    start = js.index("async function allianceReloadHub(reason)")\n    end = js.index("const ALLIANCE_PATCH_ONLY", start)\n    block = js[start:end]\n    assert 'dataset.allianceTab || ""' in block\n    assert "switchAllianceTab(refreshedPage, activeTab)" in block\n    assert "GC.navigateTo" in block\n    assert "location.reload" not in block\n    assert "location.assign" not in block\n    assert "location.href" not in block\n\n\ndef test_diplomacy_geometry_is_square_and_scoped():\n    css = _source("static/style.css")\n    marker = "/* GC-AL-UX-04: diplomacy uses square Evo/Genesis geometry. */"\n    start = css.index(marker)\n    block = css[start : start + 1400]\n    assert '[data-alliance-panel="diplomacy"]' in block\n    assert ".alliance-hub-war-meta" in block\n    assert ".alliance-hub-dip-badge" in block\n    assert "border-radius: 0 !important;" in block\n''',
    encoding="utf-8",
)

# 5) Reality-sync architecture docs.
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    '''- Alle Mutations-Actions: `allianceAction()` → `GC.fetchGameAction` + `applyActionState(res, reason)`\n- Hub-Refresh nach strukturellen Änderungen: `allianceReloadHub()` → `GC.navigateTo("/alliance", { push: false, force: true })` oder `GC.reloadCurrentPage({ force: true })`\n''',
    '''- Alle Mutations-Actions: `allianceAction()` → `GC.fetchGameAction` + `applyActionState(res, reason)`\n- Hub-Refresh nach strukturellen Änderungen: `allianceReloadHub()` → `GC.navigateTo("/alliance", { push: false, force: true })` oder `GC.reloadCurrentPage({ force: true })`; der aktive Hub-Tab wird über den PJAX-Refresh hinweg wiederhergestellt.\n- **GC-AL-UX-04:** Diplomatie ist strukturelles SSR-Markup (Relationen, Requests, WAR-Score/Actions) und daher **nicht** `ALLIANCE_PATCH_ONLY`; erfolgreiche Diplomatie-Mutationen refreshen den Hub sofort ohne Browser-Reload. Der Diplomatie-Tab verwendet eckige Evo/Genesis-Geometrie (`border-radius: 0`).\n''',
)

print("GC-AL-UX-04 patch applied")
