"""Dirty score refreshes only rewrite global ranks when rank inputs changed."""
from __future__ import annotations


def _before_row(**overrides):
    row = {
        "score_total": "100",
        "score_resources": "10",
        "score_buildings": "40",
        "score_research": "20",
        "score_fleet": "10",
        "score_defense": "10",
        "score_combat": "20",
        "score_destroyed": "5",
        "score_planet_evolution": "20",
        "rank_total": 1,
    }
    row.update(overrides)
    return row


def _refreshed_scores(**overrides):
    scores = {
        "total_score": 100,
        "resource_score": 999999,
        "building_score": 40,
        "research_score": 20,
        "fleet_score": 10,
        "defense_score": 10,
        "combat_score": 20,
        "destroyed_score": 5,
        "evolution_score": 20,
    }
    scores.update(overrides)
    return scores


class _Conn:
    def commit(self):
        return None


def _install_batch(monkeypatch, ranking_worker, score_events, *, before, refreshed):
    monkeypatch.setattr(
        score_events,
        "list_dirty_score_players",
        lambda *, conn, limit: [
            {"player_id": 7, "dirty_version": 3, "dirty_since": 1.0, "updated_at": 2.0}
        ],
    )
    monkeypatch.setattr(
        score_events,
        "clear_player_score_dirty_if_version",
        lambda player_id, expected_version, *, conn: True,
    )
    monkeypatch.setattr(ranking_worker, "get_player_score_row", lambda player_id, conn=None: before)
    monkeypatch.setattr(ranking_worker, "refresh_player_score", lambda player_id, conn=None: refreshed)
    monkeypatch.setattr(ranking_worker, "begin_write_transaction", lambda conn: None)
    monkeypatch.setattr(ranking_worker, "commit", lambda conn: None)
    monkeypatch.setattr(ranking_worker, "rollback", lambda conn: None)


def test_dirty_resource_only_refresh_skips_global_rank_rewrite(monkeypatch):
    import game.ranking_worker as ranking_worker
    import game.score_events as score_events

    _install_batch(
        monkeypatch,
        ranking_worker,
        score_events,
        before=_before_row(),
        refreshed=_refreshed_scores(),
    )
    rank_calls = []
    monkeypatch.setattr(
        ranking_worker,
        "recalculate_ranks",
        lambda conn=None: rank_calls.append(True) or 135,
    )

    result = ranking_worker.process_dirty_score_batch(conn=_Conn(), limit=1)

    assert result["ok"] is True
    assert result["players_updated"] == 1
    assert result["rank_inputs_changed"] is False
    assert result["rank_rewrites"] == 0
    assert result["ranks_assigned"] == 0
    assert rank_calls == []


def test_dirty_rank_input_change_rewrites_ranks_once(monkeypatch):
    import game.ranking_worker as ranking_worker
    import game.score_events as score_events

    _install_batch(
        monkeypatch,
        ranking_worker,
        score_events,
        before=_before_row(),
        refreshed=_refreshed_scores(total_score=101, building_score=41),
    )
    rank_calls = []
    monkeypatch.setattr(
        ranking_worker,
        "recalculate_ranks",
        lambda conn=None: rank_calls.append(True) or 135,
    )

    result = ranking_worker.process_dirty_score_batch(conn=_Conn(), limit=1)

    assert result["rank_inputs_changed"] is True
    assert result["rank_rewrites"] == 1
    assert result["ranks_assigned"] == 135
    assert rank_calls == [True]


def test_unranked_player_forces_rank_seed_even_without_score_change(monkeypatch):
    import game.ranking_worker as ranking_worker
    import game.score_events as score_events

    _install_batch(
        monkeypatch,
        ranking_worker,
        score_events,
        before=_before_row(rank_total=None),
        refreshed=_refreshed_scores(),
    )
    rank_calls = []
    monkeypatch.setattr(
        ranking_worker,
        "recalculate_ranks",
        lambda conn=None: rank_calls.append(True) or 135,
    )

    result = ranking_worker.process_dirty_score_batch(conn=_Conn(), limit=1)

    assert result["rank_inputs_changed"] is True
    assert result["rank_rewrites"] == 1
    assert rank_calls == [True]
