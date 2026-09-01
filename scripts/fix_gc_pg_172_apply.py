from pathlib import Path

path = Path(__file__).resolve().parent / "apply_gc_pg_172_no_legacy_presence.py"
source = path.read_text(encoding="utf-8")
start_marker = '''text = replace_once(\n    text,\n    ''' + "'''    assert \"SAVEPOINT gc_presence_legacy\" in conn.sql\\n"
end_marker = '''    "roster mirror assertions",\n)\n'''
start = source.find(start_marker)
if start < 0:
    raise SystemExit("roster assertion replacement start not found")
end = source.find(end_marker, start)
if end < 0:
    raise SystemExit("roster assertion replacement end not found")
end += len(end_marker)
replacement = '''old_mirror_assertions = (\n    '    assert "SAVEPOINT gc_presence_legacy" in conn.sql\\n'\n    '    assert any("UPDATE players SET last_seen" in sql for sql in conn.sql)\\n'\n)\nnew_mirror_assertions = (\n    '    assert "SAVEPOINT gc_presence_legacy" not in conn.sql\\n'\n    '    assert not any("UPDATE players SET last_seen" in sql for sql in conn.sql)\\n'\n)\nmirror_count = text.count(old_mirror_assertions)\nif mirror_count != 2:\n    raise SystemExit(f"roster mirror assertions: expected 2 matches, found {mirror_count}")\ntext = text.replace(old_mirror_assertions, new_mirror_assertions)\n'''
path.write_text(source[:start] + replacement + source[end:], encoding="utf-8")
print("GC-PG-172 apply codemod fixed")
