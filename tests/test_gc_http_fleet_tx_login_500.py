import inspect

from game import logic


def test_ssr_live_state_never_finishes_fleet_on_page_transaction():
    source = inspect.getsource(logic.refresh_player_live_state)

    assert "finish_due_work(" in source
    assert "include_fleet=False" in source
    assert "finish_player_due_work(" not in source


def test_poll_queue_safety_net_keeps_fleet_on_dedicated_short_tx():
    source = inspect.getsource(logic.read_player_live_state_for_poll)

    assert "process_player_due_fleets_now" in source
    assert "finish_due_work(" in source
    assert "include_fleet=False" in source
    assert "finish_player_due_work(" not in source
