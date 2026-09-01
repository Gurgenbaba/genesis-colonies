"""Regression gate: schema readiness probes must never leak a pooled connection."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_app_has_no_direct_schema_ready_db_checkout():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    pattern = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*_schema_ready\(db\(\)\)")
    assert pattern.search(src) is None


def test_schema_ready_short_conn_always_closes():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = src.split("def _schema_ready_with_short_conn(check_fn)", 1)[1].split("\n\ndef ", 1)[0]
    assert "conn = db()" in block
    assert "return bool(check_fn(conn))" in block
    assert "finally:" in block
    assert "conn.close()" in block
