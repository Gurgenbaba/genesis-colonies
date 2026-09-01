from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tests" / "test_gc_pg_170_admin_legacy_presence.py"
text = path.read_text(encoding="utf-8")
old = '''    block = _block(text, "def list_bot_roster", "def bootstrap_faction_bots")\n'''
new = '''    block = text[text.index("def list_bot_roster") :]\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one pirate roster test marker, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("GC-PG-170 generated regression test fixed")
