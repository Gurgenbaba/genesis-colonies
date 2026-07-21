"""
GC-PERF-PG-SCHEMA-001 — SQLite SQL → PostgreSQL dialect rewrite.

Owner: migrate.py (migration scripts) and game.db_pg (runtime SQLite idioms
such as INSERT OR IGNORE / AUTOINCREMENT / PRAGMA no-op).
Does not import live player data (→ GC-PERF-PG-MIGRATE-001).
"""

from __future__ import annotations

import re
from typing import List, Tuple


def split_sql_statements(sql_text: str) -> List[str]:
    """Split SQL on ';' outside quotes/comments (same rules as migrate.py)."""
    s = str(sql_text or "").lstrip("\ufeff")
    out: List[str] = []
    buf: List[str] = []
    in_single = in_double = in_line = in_block = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""
        if not in_single and not in_double and not in_block and not in_line:
            if ch == "-" and nxt == "-":
                in_line = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
        if in_line:
            buf.append(ch)
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block = False
                continue
            i += 1
            continue
        if ch == "'" and not in_double:
            if in_single and nxt == "'":
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            if in_double and nxt == '"':
                buf.append(ch)
                buf.append(nxt)
                i += 2
                continue
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            buf = []
            if stmt:
                out.append(stmt + ";")
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail if tail.endswith(";") else tail + ";")
    return out


def strip_leading_sql_comments(sql: str) -> str:
    """Remove leading -- and /* */ comments so keyword matchers see INSERT/CREATE/…"""
    text = str(sql or "").strip()
    while text:
        if text.startswith("--"):
            nl = text.find("\n")
            if nl < 0:
                return ""
            text = text[nl + 1 :].lstrip()
            continue
        if text.startswith("/*"):
            end = text.find("*/")
            if end < 0:
                return ""
            text = text[end + 2 :].lstrip()
            continue
        break
    return text


def is_pragma_statement(sql: str) -> bool:
    return strip_leading_sql_comments(sql).upper().startswith("PRAGMA")


def _find_matching_paren(text: str, open_idx: int) -> int:
    """Index of ')' matching text[open_idx] == '('; -1 if unbalanced."""
    depth = 0
    in_single = in_double = False
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if in_single:
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    i += 2
                    continue
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _args_have_top_level_comma(args: str) -> bool:
    depth = 0
    in_single = in_double = False
    i = 0
    n = len(args)
    while i < n:
        ch = args[i]
        if in_single:
            if ch == "'":
                if i + 1 < n and args[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"':
                if i + 1 < n and args[i + 1] == '"':
                    i += 2
                    continue
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
        i += 1
    return False


def rewrite_sqlite_scalar_minmax(sql: str) -> str:
    """
    SQLite scalar ``MAX(a, b, …)`` / ``MIN(a, b, …)`` → Postgres ``GREATEST`` / ``LEAST``.

    Leaves single-arg aggregates alone (``MAX(score)``, ``MIN(created_at)``).
    """
    text = str(sql or "")
    if not text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    upper = text.upper()
    while i < n:
        # Match MAX( or MIN( as whole words
        matched = None
        if upper.startswith("MAX", i) and (i == 0 or not (upper[i - 1].isalnum() or upper[i - 1] == "_")):
            j = i + 3
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == "(":
                matched = ("MAX", "GREATEST", j)
        elif upper.startswith("MIN", i) and (i == 0 or not (upper[i - 1].isalnum() or upper[i - 1] == "_")):
            j = i + 3
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == "(":
                matched = ("MIN", "LEAST", j)
        if matched is None:
            out.append(text[i])
            i += 1
            continue
        _old, replacement, open_idx = matched
        close_idx = _find_matching_paren(text, open_idx)
        if close_idx < 0:
            out.append(text[i])
            i += 1
            continue
        args = text[open_idx + 1 : close_idx]
        if _args_have_top_level_comma(args):
            args_rw = rewrite_sqlite_scalar_minmax(args)
            out.append(replacement)
            out.append("(")
            out.append(args_rw)
            out.append(")")
            i = close_idx + 1
        else:
            # Aggregate / single-arg — keep name, continue scanning inside args
            out.append(text[i : open_idx + 1])
            i = open_idx + 1
    return "".join(out)


def has_sqlite_scalar_minmax(sql: str) -> bool:
    """True when SQL contains multi-arg SQLite MAX/MIN that Postgres rejects."""
    rewritten = rewrite_sqlite_scalar_minmax(sql)
    return rewritten != str(sql or "")


def rewrite_sqlite_statement(stmt: str) -> str:
    """Rewrite one SQLite statement for PostgreSQL. Empty string = skip (e.g. PRAGMA)."""
    text = str(stmt or "").strip()
    if not text:
        return ""
    if is_pragma_statement(text):
        return ""

    # Keep leading comments in output optional — operate on body for transforms
    body = strip_leading_sql_comments(text)
    if not body:
        return ""

    # SQLite scalar MAX(a,b)/MIN(a,b) → GREATEST/LEAST (before other transforms)
    body = rewrite_sqlite_scalar_minmax(body)

    body = re.sub(
        r"\bBEGIN\s+(IMMEDIATE|EXCLUSIVE|DEFERRED)\b",
        "BEGIN",
        body,
        flags=re.IGNORECASE,
    )

    # INSERT OR IGNORE / REPLACE — match anywhere after comments (not only ^)
    if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", body, re.IGNORECASE):
        body = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            body,
            count=1,
            flags=re.IGNORECASE,
        )
        body = _append_on_conflict_do_nothing(body)
    elif re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", body, re.IGNORECASE):
        body = re.sub(
            r"\bINSERT\s+OR\s+REPLACE\s+INTO\b",
            "INSERT INTO",
            body,
            count=1,
            flags=re.IGNORECASE,
        )
        body = _append_on_conflict_do_nothing(body)
    elif re.match(r"REPLACE\s+INTO\b", body, re.IGNORECASE):
        body = re.sub(r"^REPLACE\s+INTO\b", "INSERT INTO", body, count=1, flags=re.IGNORECASE)
        body = _append_on_conflict_do_nothing(body)

    body = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"\bAUTOINCREMENT\b", "", body, flags=re.IGNORECASE)

    # SQLite INTEGER is i64; dna_seed stores full 63-bit seeds → Postgres BIGINT
    body = re.sub(r"\bdna_seed\s+INTEGER\b", "dna_seed BIGINT", body, flags=re.IGNORECASE)

    body = re.sub(r"\bREAL\b", "DOUBLE PRECISION", body, flags=re.IGNORECASE)
    body = re.sub(r"\bBLOB\b", "BYTEA", body, flags=re.IGNORECASE)

    body = re.sub(
        r"datetime\s*\(\s*'now'\s*\)",
        "NOW()",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(
        r"strftime\s*\(\s*'%s'\s*,\s*'now'\s*\)",
        "EXTRACT(EPOCH FROM NOW())",
        body,
        flags=re.IGNORECASE,
    )
    # CAST(strftime('%s','now') AS INTEGER) after above becomes CAST(EXTRACT… AS INTEGER) — OK
    # Also handle spaced variant already covered by \s*

    # ALTER TABLE … ADD COLUMN x → ADD COLUMN IF NOT EXISTS
    body = re.sub(
        r"\bALTER\s+TABLE\s+(\S+)\s+ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)",
        r"ALTER TABLE \1 ADD COLUMN IF NOT EXISTS ",
        body,
        flags=re.IGNORECASE,
    )

    # SQLite CHECK rebuilds use PRAGMA foreign_keys=OFF + DROP TABLE.
    # Postgres: CASCADE so dependent FKs do not block the drop (re-added below when needed).
    body = re.sub(
        r"\bDROP\s+TABLE\s+(IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(CASCADE)?\s*;",
        r"DROP TABLE IF EXISTS \2 CASCADE;",
        body,
        flags=re.IGNORECASE,
    )

    # Collapse only horizontal whitespace runs (keep newlines for VALUES lists)
    body = re.sub(r"[ \t]{2,}", " ", body).strip()
    if body and not body.endswith(";"):
        body += ";"
    return body


def rewrite_migration_script(sql_text: str) -> Tuple[str, List[str]]:
    """Rewrite a full migration file. Returns (rewritten_sql, human notes)."""
    notes: List[str] = []
    parts: List[str] = []
    raw = str(sql_text or "")
    # Leftover *_new tables from a failed SQLite CHECK rebuild mid-flight
    if re.search(r"fleet_movements_new", raw, re.IGNORECASE) or re.search(
        r"fleet_presets_new", raw, re.IGNORECASE
    ):
        parts.append("DROP TABLE IF EXISTS fleet_movements_new CASCADE;")
        parts.append("DROP TABLE IF EXISTS fleet_presets_new CASCADE;")
        notes.append("drop leftover *_new tables before CHECK rebuild")

    for stmt in split_sql_statements(raw):
        if is_pragma_statement(stmt):
            notes.append(f"skip PRAGMA: {stmt[:72]}")
            continue
        upper = strip_leading_sql_comments(stmt).upper()
        if "INSERT OR IGNORE" in upper:
            notes.append("INSERT OR IGNORE -> ON CONFLICT DO NOTHING")
        if "INSERT OR REPLACE" in upper or upper.startswith("REPLACE INTO"):
            notes.append("REPLACE/OR REPLACE -> INSERT ... ON CONFLICT DO NOTHING")
        if re.search(r"\bDROP\s+TABLE\b", upper):
            notes.append("DROP TABLE -> DROP TABLE IF EXISTS ... CASCADE")
        rewritten = rewrite_sqlite_statement(stmt)
        if rewritten:
            if "INSERT OR IGNORE" in rewritten.upper() or "INSERT OR REPLACE" in rewritten.upper():
                raise RuntimeError(
                    f"pg-rewrite left SQLite INSERT OR * intact: {rewritten[:120]}"
                )
            parts.append(rewritten)

    # After SQLite fleet_presets CHECK rebuild, CASCADE drops movements→presets FK.
    if (
        re.search(r"fleet_presets_new", raw, re.IGNORECASE)
        and re.search(r"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?fleet_presets\b", raw, re.IGNORECASE)
    ):
        parts.append(
            "ALTER TABLE fleet_movements "
            "ADD CONSTRAINT fleet_movements_preset_id_fkey "
            "FOREIGN KEY (preset_id) REFERENCES fleet_presets(id) ON DELETE SET NULL;"
        )
        notes.append("re-add fleet_movements.preset_id FK after presets rebuild")

    joined = "\n".join(parts)
    if parts:
        joined += "\n"
    return joined, notes


def _append_on_conflict_do_nothing(stmt: str) -> str:
    if "ON CONFLICT" in stmt.upper():
        return stmt
    body = stmt.rstrip().rstrip(";")
    return body + " ON CONFLICT DO NOTHING;"


def is_idempotent_postgres_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "already exists" in msg:
        return True
    if "duplicate column" in msg:
        return True
    if "duplicate key" in msg:
        return True
    if "duplicate object" in msg:
        return True
    try:
        from psycopg.errors import DuplicateTable, DuplicateObject, DuplicateColumn

        if isinstance(exc, (DuplicateTable, DuplicateObject, DuplicateColumn)):
            return True
    except Exception:
        pass
    return False
