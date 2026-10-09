"""Regression guards for live research resource requirement presentation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_research_card_uses_hud_balance_for_tooltip_have_values():
    page = (ROOT / "templates/research.html").read_text(encoding="utf-8")
    js = (ROOT / "static/js/pages/research_live_requirements.js").read_text(encoding="utf-8")
    assert "research_live_requirements.js" in page
    assert '.res-value.' in js
    assert 'item.have = have' in js
    assert 'button.setAttribute("data-req-items", JSON.stringify(items))' in js
    assert 'new MutationObserver(schedule)' in js


def test_research_refresh_stays_server_authoritative_and_page_scoped():
    js = (ROOT / "static/js/pages/research_live_requirements.js").read_text(encoding="utf-8")
    assert 'GC.reloadCurrentPage({ force: true })' in js
    assert 'GC.registerCleanup(cleanup)' in js
    assert 'observer.disconnect()' in js
    assert 'fetch(' not in js
    assert '.disabled = false' not in js
