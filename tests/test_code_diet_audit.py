from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_comment_stripped_sloc_keeps_docstrings_and_inline_code(tmp_path):
    loc = _load(ROOT / "tools" / "loc_report.py", "gc_loc_report_test")
    py = tmp_path / "sample.py"
    py.write_text("# comment\n\nx = 1  # inline\n\"\"\"docstring counts as code\"\"\"\n", encoding="utf-8")
    assert loc._count(py) == (4, 3)
    assert loc._count_sloc(py) == 2


def test_block_comment_sloc_for_js_and_css(tmp_path):
    loc = _load(ROOT / "tools" / "loc_report.py", "gc_loc_report_blocks")
    js = tmp_path / "sample.js"
    js.write_text("/* comment\n * comment\n */\nconst x = 1;\n// only\n", encoding="utf-8")
    css = tmp_path / "sample.css"
    css.write_text("/* one */\n.a { display: block; }\n", encoding="utf-8")
    assert loc._count_sloc(js) == 1
    assert loc._count_sloc(css) == 1


def test_exact_duplicate_python_bodies_are_candidates_not_name_matches(tmp_path, monkeypatch):
    loc = _load(ROOT / "tools" / "loc_report.py", "loc_report")
    sys.modules["loc_report"] = loc
    audit = _load(ROOT / "tools" / "code_diet_audit.py", "gc_code_diet_audit_test")
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    one = tmp_path / "one.py"
    two = tmp_path / "two.py"
    body = """def {name}(value):
    total = value + 1
    total += 2
    total += 3
    total += 4
    total += 5
    total += 6
    return total
"""
    one.write_text(body.format(name="alpha"), encoding="utf-8")
    two.write_text(body.format(name="beta"), encoding="utf-8")
    groups = audit.exact_python_duplicate_functions([one, two], min_lines=8)
    assert len(groups) == 1
    assert groups[0]["copies"] == 2
    assert {site["qualname"] for site in groups[0]["sites"]} == {"alpha", "beta"}


def test_legacy_markers_report_locations(tmp_path, monkeypatch):
    loc = _load(ROOT / "tools" / "loc_report.py", "loc_report_markers")
    sys.modules["loc_report"] = loc
    audit = _load(ROOT / "tools" / "code_diet_audit.py", "gc_code_diet_audit_markers")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    path = tmp_path / "module.py"
    path.write_text("import sqlite3\n# legacy fallback\n", encoding="utf-8")
    hits = audit.marker_hits([path])
    assert hits["sqlite"]["count"] == 1
    assert hits["legacy"]["count"] == 1
    assert hits["fallback"]["count"] == 1
