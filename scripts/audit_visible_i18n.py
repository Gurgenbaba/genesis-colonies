#!/usr/bin/env python3
"""GC-I18N-HARDENING — locale parity + player-facing raw-string audit.

This complements ``scripts/audit_locale_keys.py``:

* exact key-set parity for every supported locale (de is canonical),
* placeholder parity so translations cannot silently drop format arguments,
* heuristic discovery of player-facing raw strings in templates, JS and Python,
* strict changed-line mode for CI without having to bless existing debt.

The full raw-string scan is intentionally available as an inventory/report. CI should
run strict *delta* mode so no new untranslated UI copy can enter while the existing
inventory is cleaned up ticket-by-ticket.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT / "locales"
sys.path.insert(0, str(ROOT))

from game.i18n import SUPPORTED_LOCALES  # noqa: E402

_SCAN_GLOBS = (
    "templates/**/*.html",
    "static/**/*.js",
    "game/**/*.py",
    "app.py",
)

_I18N_IGNORE_MARKERS = ("i18n-ok", "i18n:ignore", "i18n-ignore")

# Jinja translation forms already owned by the locale system.
_RE_JINJA_EXPR = re.compile(r"\{\{.*?\}\}")
_RE_JINJA_STMT = re.compile(r"\{%.*?%\}")
_RE_JINJA_COMMENT = re.compile(r"\{#.*?#\}")
_RE_HTML_COMMENT = re.compile(r"<!--.*?-->")
_RE_TAG = re.compile(r"<[^>]+>")
_RE_VISIBLE_ATTR = re.compile(
    r"\b(aria-label|aria-description|title|placeholder|alt)\s*=\s*([\"'])(.*?)\2",
    re.I,
)
_RE_TEMPLATE_ATTR_SHELL = re.compile(
    r"^(?:aria-label|aria-description|title|placeholder|alt)\s*=\s*[\"']?\s*[\"']?$",
    re.I,
)
_RE_HTML_TEXT = re.compile(r">([^<>]+)<")

# Conservative JS/Python sinks: these are values that are normally visible to players.
_RE_JS_VISIBLE_ASSIGN = re.compile(
    r"(?:\.textContent|\.innerText|\.title|\.placeholder)\s*=\s*([\"'`])([^\n]*?)\1"
)
_RE_JS_VISIBLE_CALL = re.compile(
    r"(?:setAttribute\(\s*[\"'](?:aria-label|aria-description|title|placeholder)[\"']\s*,\s*"
    r"|(?:toast|showToast|notify|alert|confirm)\(\s*)([\"'`])([^\n]*?)\1"
)
_RE_PY_VISIBLE_FIELD = re.compile(
    r"[\"'](?:label|title|subtitle|description|hint|message|empty_text|button_text)[\"']\s*:\s*"
    r"([\"'])(.*?)\1"
)

_RE_PCT_PLACEHOLDER = re.compile(r"%\(([^)]+)\)[#0 +\-]?(?:\d+)?(?:\.\d+)?[diouxXeEfFgGcrs]")
_RE_BRACE_PLACEHOLDER = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)(?:![rsa])?(?::[^{}]+)?\}(?!\})")
_RE_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿА-Яа-яЁёĞğİıŞşÇçĄąĆćĘęŁłŃńÓóŚśŹźŻż]{2,}")
_RE_URLISH = re.compile(r"^(?:https?://|/|\.|#|[A-Za-z0-9_./:-]+\.(?:png|jpg|jpeg|gif|webp|svg|css|js))", re.I)
_RE_CODE_TOKEN = re.compile(r"^[a-z0-9_.:/#@+-]+$", re.I)

# Language-neutral/brand-only literals are not useful findings on their own.
_SAFE_LITERALS = {
    "Genesis Colonies",
    "Discord",
    "GitHub",
    "PayPal",
    "Stripe",
    "API",
    "HTTP",
    "HTTPS",
    "UTC",
    "XP",
    "DNA",
    "PvP",
    "PvE",
    "FAQ",
    "OK",
    "MAX",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def render(self) -> str:
        compact = " ".join(self.text.split())
        if len(compact) > 160:
            compact = compact[:157] + "..."
        return f"{self.path}:{self.line}: {self.kind}: {compact}"


def _load_locale(code: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{code}.json"
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def _placeholder_signature(value: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(sorted(set(_RE_PCT_PLACEHOLDER.findall(value)))),
        tuple(sorted(set(_RE_BRACE_PLACEHOLDER.findall(value)))),
    )


def audit_locale_parity() -> list[str]:
    """Return hard failures for key-set and format-placeholder parity."""
    failures: list[str] = []
    canonical = _load_locale("de")
    canonical_keys = set(canonical)

    for code in sorted(SUPPORTED_LOCALES):
        path = LOCALES_DIR / f"{code}.json"
        if not path.exists():
            failures.append(f"{code}: missing locale file")
            continue
        data = _load_locale(code)
        keys = set(data)
        missing = sorted(canonical_keys - keys)
        extra = sorted(keys - canonical_keys)
        if missing:
            failures.append(f"{code}: missing {len(missing)} keys vs de: {missing[:8]}")
        if extra:
            failures.append(f"{code}: extra {len(extra)} keys vs de: {extra[:8]}")

        for key in sorted(canonical_keys & keys):
            source_sig = _placeholder_signature(canonical[key])
            target_sig = _placeholder_signature(data[key])
            if source_sig != target_sig:
                failures.append(
                    f"{code}:{key}: placeholder mismatch de={source_sig} locale={target_sig}"
                )

    return failures


def _strip_template_syntax(text: str) -> str:
    text = _RE_JINJA_COMMENT.sub(" ", text)
    text = _RE_HTML_COMMENT.sub(" ", text)
    text = _RE_JINJA_EXPR.sub(" ", text)
    text = _RE_JINJA_STMT.sub(" ", text)
    return text


def _looks_player_facing(text: str) -> bool:
    value = " ".join(str(text or "").replace("\\n", " ").split()).strip()
    if not value or value in _SAFE_LITERALS:
        return False
    if any(marker in value for marker in _I18N_IGNORE_MARKERS):
        return False
    if "{{" in value or "{%" in value or "T(" in value or "tr(" in value:
        return False
    # Template syntax stripping can leave an empty attribute shell such as
    # title=" " behind for a fully localized title="{{ T(...) }}" line.
    if _RE_TEMPLATE_ATTR_SHELL.match(value):
        return False
    if _RE_URLISH.match(value):
        return False
    if value.startswith(("data-", "aria-", "--")):
        return False
    words = _RE_WORD.findall(value)
    if not words:
        return False
    if len(words) == 1 and _RE_CODE_TOKEN.match(value) and value == value.lower():
        return False
    # Avoid flagging pure technical identifiers/codes. Human phrases still pass.
    if len(words) == 1 and ("_" in value or "." in value or "/" in value):
        return False
    return True


def _template_findings(path: Path, lines: list[str], selected: set[int] | None) -> list[Finding]:
    out: list[Finding] = []
    rel = path.relative_to(ROOT).as_posix()
    in_script = False
    in_style = False
    for idx, original in enumerate(lines, start=1):
        lower = original.lower()
        if "<script" in lower:
            in_script = True
        if "<style" in lower:
            in_style = True
        if selected is not None and idx not in selected:
            if "</script>" in lower:
                in_script = False
            if "</style>" in lower:
                in_style = False
            continue
        if any(marker in original for marker in _I18N_IGNORE_MARKERS):
            continue
        stripped = _strip_template_syntax(original)

        for attr, _quote, value in _RE_VISIBLE_ATTR.findall(stripped):
            if _looks_player_facing(value):
                out.append(Finding(rel, idx, f"template-{attr.lower()}", value))

        if not in_script and not in_style:
            for match in _RE_HTML_TEXT.finditer(stripped):
                value = _RE_TAG.sub(" ", match.group(1)).strip()
                if _looks_player_facing(value):
                    out.append(Finding(rel, idx, "template-text", value))

        # Also catch literal text on lines that are mostly text (e.g. multiline tags).
        if not in_script and not in_style:
            no_tags = _RE_TAG.sub(" ", stripped).strip()
            if no_tags and "<" not in no_tags and ">" not in no_tags and _looks_player_facing(no_tags):
                if not any(f.line == idx and f.text == no_tags for f in out):
                    out.append(Finding(rel, idx, "template-text", no_tags))

        if "</script>" in lower:
            in_script = False
        if "</style>" in lower:
            in_style = False
    return out


def _js_findings(path: Path, lines: list[str], selected: set[int] | None) -> list[Finding]:
    out: list[Finding] = []
    rel = path.relative_to(ROOT).as_posix()
    for idx, line in enumerate(lines, start=1):
        if selected is not None and idx not in selected:
            continue
        if any(marker in line for marker in _I18N_IGNORE_MARKERS):
            continue
        for regex, kind in (
            (_RE_JS_VISIBLE_ASSIGN, "js-visible-assignment"),
            (_RE_JS_VISIBLE_CALL, "js-visible-call"),
        ):
            for match in regex.finditer(line):
                value = match.group(2)
                if _looks_player_facing(value):
                    out.append(Finding(rel, idx, kind, value))
    return out


def _python_findings(path: Path, lines: list[str], selected: set[int] | None) -> list[Finding]:
    out: list[Finding] = []
    rel = path.relative_to(ROOT).as_posix()
    for idx, line in enumerate(lines, start=1):
        if selected is not None and idx not in selected:
            continue
        if any(marker in line for marker in _I18N_IGNORE_MARKERS):
            continue
        for match in _RE_PY_VISIBLE_FIELD.finditer(line):
            value = match.group(2)
            if _looks_player_facing(value):
                out.append(Finding(rel, idx, "python-visible-field", value))
    return out


def _iter_source_files() -> list[Path]:
    paths: set[Path] = set()
    for pattern in _SCAN_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            paths.add(path)
    return sorted(paths)


def _changed_line_map(base: str) -> dict[str, set[int]]:
    """Map repo-relative paths to added/modified line numbers since ``base``."""
    base = str(base or "").strip()
    if not base or set(base) == {"0"}:
        base = "HEAD^"
    proc = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD", "--", "templates", "static", "game", "app.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        # Push events can provide a before-SHA that is not an ancestor after a force
        # update. Fall back to a direct two-dot diff rather than silently skipping.
        proc = subprocess.run(
            ["git", "diff", "--unified=0", "--no-color", base, "HEAD", "--", "templates", "static", "game", "app.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git diff failed for base {base}")

    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            changed.setdefault(current_path, set())
            continue
        if not line.startswith("@@") or current_path is None:
            continue
        m = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2) or "1")
        if count <= 0:
            continue
        changed[current_path].update(range(start, start + count))
    return changed


def scan_raw_strings(*, diff_base: str | None = None) -> list[Finding]:
    selected_map = _changed_line_map(diff_base) if diff_base else None
    findings: list[Finding] = []
    for path in _iter_source_files():
        rel = path.relative_to(ROOT).as_posix()
        selected = selected_map.get(rel, set()) if selected_map is not None else None
        if selected_map is not None and not selected:
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if path.suffix == ".html":
            findings.extend(_template_findings(path, lines, selected))
        elif path.suffix == ".js":
            findings.extend(_js_findings(path, lines, selected))
        elif path.suffix == ".py":
            findings.extend(_python_findings(path, lines, selected))
    # Stable deterministic order and no duplicate same-line findings.
    unique = {(f.path, f.line, f.kind, f.text): f for f in findings}
    return [unique[k] for k in sorted(unique)]


def _print_failures(title: str, failures: Iterable[str], *, limit: int) -> int:
    items = list(failures)
    if not items:
        print(f"OK — {title}")
        return 0
    print(f"FAIL — {title}: {len(items)} finding(s)")
    for item in items[:limit]:
        print(f"- {item}")
    if len(items) > limit:
        print(f"... and {len(items) - limit} more")
    return len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-base", help="Only raw-scan added/modified lines since this git ref/SHA")
    parser.add_argument("--locales-only", action="store_true", help="Run locale/placeholder parity only")
    parser.add_argument("--raw-only", action="store_true", help="Run visible raw-string scan only")
    parser.add_argument("--report-only", action="store_true", help="Print findings but exit 0")
    parser.add_argument("--max-findings", type=int, default=200, help="Maximum findings printed per section")
    args = parser.parse_args(argv)

    if args.locales_only and args.raw_only:
        parser.error("--locales-only and --raw-only are mutually exclusive")

    failures = 0
    if not args.raw_only:
        failures += _print_failures(
            "all supported locales have exact keys + placeholder parity",
            audit_locale_parity(),
            limit=max(1, args.max_findings),
        )

    if not args.locales_only:
        raw = scan_raw_strings(diff_base=args.diff_base)
        scope = f"changed UI lines since {args.diff_base}" if args.diff_base else "full player-facing source inventory"
        failures += _print_failures(
            f"no raw player-facing strings in {scope}",
            (f.render() for f in raw),
            limit=max(1, args.max_findings),
        )

    if failures and not args.report_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())