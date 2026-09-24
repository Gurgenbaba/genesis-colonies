"""UI information hierarchy regression contracts.

Locks the full-project duplicate-info / vertical-space cleanup. These are
presentation-only guarantees: primary panels/cards own repeated information,
while page headers remain only where they add distinct context or actions.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_primary_panels_own_search_and_messages_titles():
    search = _read("templates/search.html")
    messages = _read("templates/messages.html")

    assert 'class="section-header search-header"' not in search
    assert 'id="search-panel-title"' in search
    assert 'T("search_title", "Universums-Suche")' in search

    assert '<h1 class="section-title">{{ T("messages.title") }}</h1>' not in messages
    assert 'id="messages-panel-title"' in messages
    assert 'id="messages-unread-label"' in messages
    assert 'id="messages-compose-btn"' in messages


def test_redundant_kickers_and_eyebrows_stay_removed():
    skilltree = _read("templates/skilltree.html")
    politics = _read("templates/galactic_politics.html")
    referrals = _read("templates/referrals.html")
    vote_center = _read("templates/vote_center.html")
    initiation = _read("templates/initiation.html")
    changelog = _read("templates/partials/player_changelog_dialog.html")

    assert "commander_staff_kicker" not in skilltree
    assert skilltree.count("mine_ascension_kicker") == 1
    assert "gd_politics_eyebrow" not in politics
    assert "referral_eyebrow" not in referrals
    assert "vote_center_eyebrow" not in vote_center
    assert "initiation_eyebrow" not in initiation
    assert "gc-player-changelog-eyebrow" not in changelog


def test_repeated_inline_status_rows_stay_collapsed():
    vote_center = _read("templates/vote_center.html")
    planet_evolution = _read("templates/planet_evolution.html")
    news = _read("templates/news.html")

    assert "vote-center-rewards-summary" not in vote_center
    assert "data-vote-pending-count" in vote_center
    assert "data-vote-pending-count-inline" not in vote_center

    assert "pe-research-next-kicker" not in planet_evolution
    assert 'T("pe_research_later", "Später verfügbar")' in planet_evolution

    assert 'motd_banner.title or T("news_live_panel_label", "Aktuelle Meldung")' in news
    assert 'motd_banner.title or T("news_title", "Genesis Timeline")' not in news


def test_progression_surfaces_keep_previous_cleanup_contracts():
    research = _read("templates/research.html")
    shipyard = _read("templates/shipyard.html")
    defense = _read("templates/defense.html")
    buildings = _read("templates/buildings.html")

    assert "research-lab-chip" not in research
    assert "research-network-block" in research

    assert "shipyard-status-panel" not in shipyard
    assert "data-shipyard-level-label" in shipyard
    assert "data-shipyard-batch-capacity" in shipyard

    assert "defense-status-panel" not in defense
    assert "data-defense-factory-label" in defense
    assert "data-defense-batch-capacity" in defense

    assert "else 'cards') %}" in buildings
