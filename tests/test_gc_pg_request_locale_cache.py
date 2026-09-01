"""Regression gates for the authenticated request-locale hot path."""

from __future__ import annotations

from types import SimpleNamespace

from flask import Flask, session

from game import i18n


class _FakeConn:
    def __init__(self, locale: str = "en") -> None:
        self.locale = locale
        self.closed = False
        self.sql: list[str] = []
        self.commits = 0

    def execute(self, sql, params=None):  # noqa: ANN001
        text = str(sql)
        self.sql.append(text)
        if text.startswith("SELECT locale FROM users"):
            return SimpleNamespace(fetchone=lambda: {"locale": self.locale})
        if text.startswith("UPDATE users SET locale"):
            self.locale = str(params[0])
            return SimpleNamespace(fetchone=lambda: None)
        raise AssertionError(f"unexpected SQL: {text}")

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.commits += 1


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "gc-test-locale-cache"
    return app


def test_authenticated_request_locale_hits_db_once_then_session_cache(monkeypatch):
    app = _app()
    opens: list[_FakeConn] = []

    def _db():
        conn = _FakeConn("en")
        opens.append(conn)
        return conn

    monkeypatch.setattr(i18n, "db", _db)
    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        assert i18n.get_player_locale(7) == "en"
        assert len(opens) == 1
        assert opens[0].closed is True

        assert i18n.get_player_locale(7) == "en"
        assert i18n.get_player_locale(7) == "en"
        assert len(opens) == 1
        assert int(session[i18n._SESSION_LOCALE_PLAYER_KEY]) == 7
        assert session[i18n._SESSION_LOCALE_KEY] == "en"
        assert float(session[i18n._SESSION_LOCALE_CHECKED_AT_KEY]) > 0


def test_expired_session_locale_revalidates_from_database(monkeypatch):
    app = _app()
    opens: list[_FakeConn] = []
    locales = iter(("en", "fr"))

    def _db():
        conn = _FakeConn(next(locales))
        opens.append(conn)
        return conn

    monkeypatch.setattr(i18n, "db", _db)
    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        assert i18n.get_player_locale(7) == "en"
        assert len(opens) == 1
        session[i18n._SESSION_LOCALE_CHECKED_AT_KEY] = (
            float(session[i18n._SESSION_LOCALE_CHECKED_AT_KEY])
            - i18n._SESSION_LOCALE_TTL_SEC
            - 1.0
        )
        assert i18n.get_player_locale(7) == "fr"
        assert len(opens) == 2
        assert session[i18n._SESSION_LOCALE_KEY] == "fr"


def test_session_locale_is_scoped_to_player(monkeypatch):
    app = _app()
    opens: list[_FakeConn] = []

    def _db():
        conn = _FakeConn("fr")
        opens.append(conn)
        return conn

    monkeypatch.setattr(i18n, "db", _db)
    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        session[i18n._SESSION_LOCALE_PLAYER_KEY] = 99
        session[i18n._SESSION_LOCALE_KEY] = "de"
        session[i18n._SESSION_LOCALE_CHECKED_AT_KEY] = 10**12
        assert i18n.get_player_locale(7) == "fr"
        assert len(opens) == 1
        assert int(session[i18n._SESSION_LOCALE_PLAYER_KEY]) == 7
        assert session[i18n._SESSION_LOCALE_KEY] == "fr"


def test_caller_owned_locale_write_invalidates_cache_until_commit(monkeypatch):
    app = _app()
    conn = _FakeConn("en")

    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        i18n._store_session_player_locale(7, "en")
        assert i18n.set_player_locale(7, "fr", conn=conn) == "fr"
        assert conn.locale == "fr"
        assert conn.commits == 0
        assert i18n._SESSION_LOCALE_KEY not in session
        assert i18n._SESSION_LOCALE_PLAYER_KEY not in session
        assert i18n._SESSION_LOCALE_CHECKED_AT_KEY not in session


def test_owned_locale_write_caches_only_after_commit(monkeypatch):
    app = _app()
    conn = _FakeConn("en")

    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)
    monkeypatch.setattr(i18n, "db", lambda: conn)

    with app.test_request_context("/"):
        assert i18n.set_player_locale(7, "pl") == "pl"
        assert conn.commits == 1
        assert session[i18n._SESSION_LOCALE_KEY] == "pl"
        assert int(session[i18n._SESSION_LOCALE_PLAYER_KEY]) == 7
        assert float(session[i18n._SESSION_LOCALE_CHECKED_AT_KEY]) > 0


def test_explicit_connection_reader_stays_authoritative(monkeypatch):
    app = _app()
    conn = _FakeConn("pl")
    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        i18n._store_session_player_locale(7, "de")
        assert i18n.get_player_locale(7, conn=conn) == "pl"
        assert any(sql.startswith("SELECT locale FROM users") for sql in conn.sql)
