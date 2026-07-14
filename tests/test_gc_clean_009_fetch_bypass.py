"""
GC-CLEAN-009 — gameplay action fetches must use GC.fetchGameAction.

Run: python -m pytest tests/test_gc_clean_009_fetch_bypass.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# Documented raw-fetch exceptions in static/main.js (non-mutation or infra).
RAW_FETCH_ALLOWLIST = {
    "fetchGameAction_impl": r"GC\.fetchGameAction = async function fetchGameAction",
    "fetchJSON_impl": r"GC\.fetchJSON = async function fetchJSON",
    "hud_game_state_poll": r'fetch\("/api/game-state"',
    "alliance_profile_read": r'fetch\(`/api/alliance/profile/\$\{aid\}`',
    "galaxy_pjax_prefetch": r"fetchGalaxyPjaxIntoCache",
    "galaxy_pjax_nav": r'Accept: "text/html"',
    "command_map_telemetry": r'fetch\("/api/command-map/telemetry"',
    "news_whats_new_read": r'fetch\("/api/news/whats-new"',
    "support_tickets": r'fetch\(`/api/support/tickets',
    "player_card_html": r"fetchPlayerCardHtml",
    "ship_detail_html": r"fetchShipDetailHtml",
    "defense_detail_html": r"fetchDefenseDetailHtml",
}


def test_inventory_actions_use_fetch_game_action():
    src = _read("static/main.js")
    block = src.split("async function runInventoryAction(buttons, url, payload, onSuccess)")[1].split(
        "function findDepositableLegacyTimeItem"
    )[0]
    assert "GC.fetchGameAction(url" in block
    assert re.search(r"\bfetch\s*\(", block) is None


def test_alliance_logo_upload_uses_fetch_game_action():
    src = _read("static/main.js")
    block = src.split('const logoInput = ev.target.closest("[data-alliance-logo-upload]")')[1].split(
        'document.addEventListener("click", async (ev) => {'
    )[0]
    assert 'GC.fetchGameAction("/api/alliance/logo"' in block
    assert re.search(r"\bfetch\s*\(", block) is None


def test_locale_switch_uses_fetch_game_action():
    src = _read("static/main.js")
    block = src.split("root.classList.add(\"is-busy\")")[1].split("} finally {")[0]
    assert "GC.fetchGameAction(apiUrl" in block
    assert re.search(r"\bfetch\s*\(", block) is None


def test_player_card_mutations_use_fetch_game_action():
    src = _read("static/main.js")
    avatar = src.split("async function uploadPlayerCardAvatar(form, file, fileInput)")[1].split(
        "async function savePlayerCardForm(form)"
    )[0]
    save = src.split("async function savePlayerCardForm(form)")[1].split(
        "async function fetchShipDetailHtml"
    )[0]
    assert 'GC.fetchGameAction("/api/player-card/me/avatar"' in avatar
    assert 'GC.fetchGameAction("/api/player-card/me"' in save
    assert re.search(r"\bfetch\s*\(", avatar) is None
    assert re.search(r"\bfetch\s*\(", save) is None


def test_no_undocumented_mutation_fetch_bypasses_in_main_js():
    src = _read("static/main.js")
    mutation_patterns = [
        r'fetch\([^)]*method:\s*"POST"',
        r"fetch\([^)]*method:\s*'POST'",
    ]
    allow_substrings = (
        "fetchGameAction",
        "fetchJSON",
        "/api/support/tickets",
        "fetchGalaxyPjaxIntoCache",
        "/api/command-map/telemetry",
    )
    hits = []
    for pat in mutation_patterns:
        for m in re.finditer(pat, src, flags=re.IGNORECASE):
            start = max(0, m.start() - 160)
            end = min(len(src), m.end() + 120)
            snippet = src[start:end]
            if any(token in snippet for token in allow_substrings):
                continue
            hits.append(snippet.strip())
    assert not hits, "undocumented POST fetch bypasses:\n" + "\n---\n".join(hits[:5])
