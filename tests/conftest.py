"""
Pytest hooks for Genesis Colonies.

GC-PERF-PG-PARITY-001: load isolated Postgres fixtures from pg_fixtures.py
so session-scoped dependencies resolve correctly.
"""

pytest_plugins = ["pg_fixtures"]
