"""GC-978 — Global toast / notification UX contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_base_html_global_toast_stack_outside_main_content():
    html = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    main_idx = html.index('id="main-content"')
    stack_idx = html.index('id="gc-toast-stack"')
    assert stack_idx < main_idx
    assert 'class="gc-toast-stack' in html
    assert "gc-flash-container" not in html.split('id="main-content"')[1].split("{% block content %}")[0]


def test_main_js_global_toast_implementation():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function showToast(" in js
    assert "function showNotify(message, category" in js
    assert 'getElementById("gc-toast-stack")' in js
    assert "GC_TOAST_MAX_VISIBLE = 5" in js
    assert "initToastStack" in js
    assert 'getElementById("messages")' not in js
    assert "gc-toast-enter" not in js  # CSS animation, not JS


def test_style_global_toast_stack_fixed():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gc-toast-stack{" in css
    assert "position: fixed" in css.split(".gc-toast-stack{")[1].split("}")[0]
    assert "z-index: var(--gc-z-toast)" in css
    assert ".gc-toast-success" in css
    assert ".gc-toast-error" in css
    assert ".gc-toast-warning" in css
    assert ".gc-toast-info" in css


def test_toast_locales_present():
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = (ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8")
        assert '"toast_title_success"' in data
        assert '"toast_dismiss"' in data
