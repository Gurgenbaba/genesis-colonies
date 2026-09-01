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
        pass


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

        # The before-request path must not checkout PostgreSQL again.
        assert i18n.get_player_locale(7) == "en"
        assert i18n.get_player_locale(7) == "en"
        assert len(opens) == 1
        assert int(session[i18n._SESSION_LOCALE_PLAYER_KEY]) == 7
        assert session[i18n._SESSION_LOCALE_KEY] == "en"


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
        assert i18n.get_player_locale(7) == "fr"
        assert len(opens) == 1
        assert int(session[i18n._SESSION_LOCALE_PLAYER_KEY]) == 7
        assert session[i18n._SESSION_LOCALE_KEY] == "fr"


def test_locale_change_refreshes_request_cache_without_extra_checkout(monkeypatch):
    app = _app()
    conn = _FakeConn("en")

    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)
    monkeypatch.setattr(
        i18n,
        "db",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected pool checkout")),
    )

    with app.test_request_context("/"):
        session[i18n._SESSION_LOCALE_PLAYER_KEY] = 7
        session[i18n._SESSION_LOCALE_KEY] = "en"

        assert i18n.set_player_locale(7, "fr", conn=conn) == "fr"
        assert conn.locale == "fr"
        assert session[i18n._SESSION_LOCALE_KEY] == "fr"
        assert i18n.get_player_locale(7) == "fr"


def test_explicit_connection_reader_stays_authoritative(monkeypatch):
    app = _app()
    conn = _FakeConn("pl")
    monkeypatch.setattr(i18n, "ensure_locale_schema", lambda conn=None: None)

    with app.test_request_context("/"):
        session[i18n._SESSION_LOCALE_PLAYER_KEY] = 7
        session[i18n._SESSION_LOCALE_KEY] = "de"
        assert i18n.get_player_locale(7, conn=conn) == "pl"
        assert any(sql.startswith("SELECT locale FROM users") for sql in conn.sql)
