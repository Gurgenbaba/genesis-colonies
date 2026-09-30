import logging

import game.queue_engine as queue_engine


def test_slow_finish_step_logs_only_above_threshold(monkeypatch, caplog):
    ticks = iter([10.0, 10.300])
    monkeypatch.setattr(queue_engine.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(queue_engine, "get_db_backend", lambda: "sqlite")

    with caplog.at_level(logging.INFO, logger=queue_engine.__name__):
        out = queue_engine._run_finish_step(object(), "derived", lambda: 7)

    assert out == 7
    assert "queue_engine slow-step label=derived duration_ms=300 backend=sqlite" in caplog.text


def test_fast_finish_step_stays_quiet(monkeypatch, caplog):
    ticks = iter([20.0, 20.100])
    monkeypatch.setattr(queue_engine.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(queue_engine, "get_db_backend", lambda: "sqlite")

    with caplog.at_level(logging.INFO, logger=queue_engine.__name__):
        out = queue_engine._run_finish_step(object(), "build:291", lambda: 1)

    assert out == 1
    assert "queue_engine slow-step" not in caplog.text


def test_slow_step_logging_does_not_swallow_exception(monkeypatch, caplog):
    ticks = iter([30.0, 30.500])
    monkeypatch.setattr(queue_engine.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(queue_engine, "get_db_backend", lambda: "sqlite")

    def boom():
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger=queue_engine.__name__):
        try:
            queue_engine._run_finish_step(object(), "research:42", boom)
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("_run_finish_step swallowed the exception")

    assert "queue_engine slow-step label=research:42 duration_ms=500 backend=sqlite" in caplog.text
