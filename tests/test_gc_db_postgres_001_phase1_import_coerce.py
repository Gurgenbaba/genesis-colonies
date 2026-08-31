"""Importer coercion for SQLite text timestamps into Postgres REAL/epoch."""

from __future__ import annotations

from scripts.pg_import_sqlite import _coerce_for_postgres


def test_coerce_datetime_string_to_epoch_float() -> None:
    out = _coerce_for_postgres("2026-07-12 18:09:57", "double precision")
    assert isinstance(out, float)
    assert out > 1_700_000_000


def test_coerce_numeric_string() -> None:
    assert _coerce_for_postgres("42.5", "double precision") == 42.5
    assert _coerce_for_postgres("7", "bigint") == 7


def test_coerce_passthrough_none_and_int() -> None:
    assert _coerce_for_postgres(None, "double precision") is None
    assert _coerce_for_postgres(123, "double precision") == 123
