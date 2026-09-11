"""GC-RANKING-PAGE-004 — ranking exposes page 2+ while keeping 100 visible rows."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_ranking_payload_exposes_all_rows_with_page_metadata(monkeypatch):
    import game.ranking as ranking

    seen = {}

    def fake_raw(player_id, *, limit, refresh):
        seen.update(player_id=player_id, limit=limit, refresh=refresh)
        return {
            "ok": True,
            "current_player": {"player_id": player_id},
            "top_players": [{"rank": i} for i in range(1, 138)],
            "top_alliances": [{"rank": 1}],
            "server_time": 1,
        }

    monkeypatch.setattr(ranking, "_build_ranking_api_payload_raw", fake_raw)
    monkeypatch.setattr(ranking, "_json_safe_bigints", lambda payload: payload)

    payload = ranking.build_ranking_api_payload(7, limit=100, refresh=False)

    assert seen["limit"] == ranking._SQL_ALL_ROWS_LIMIT
    assert len(payload["top_players"]) == 137
    assert payload["pagination"] == {
        "page_size": 100,
        "total_players": 137,
        "total_alliances": 1,
    }


def test_ranking_browser_pager_keeps_exact_100_row_pages():
    js = (ROOT / "static" / "js" / "ranking_page.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "ranking.css").read_text(encoding="utf-8")

    assert "const DEFAULT_PAGE_SIZE = 100" in js
    assert "gc-ranking-pager" in js
    assert "table.gc-ranking-table tbody > tr" in js
    assert ".gc-ranking-mobile .gc-ranking-mobile-card" in js
    assert "node.hidden = index < start || index >= end" in js
    assert "GC-RANKING-PAGE-004" in css
    assert ".gc-ranking-pager-btn" in css
