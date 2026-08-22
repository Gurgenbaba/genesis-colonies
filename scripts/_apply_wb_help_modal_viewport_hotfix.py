from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "templates" / "world_boss.html"
text = path.read_text(encoding="utf-8")

anchor = '{% extends "base.html" %}\n'
block = '''{% block extra_head %}
{{ super() }}
<link rel="stylesheet" href="{{ url_for('static', filename='css/world_boss_help_modal.css') }}?v={{ GC_ASSET_VERSION }}">
{% endblock %}

'''

if "css/world_boss_help_modal.css" not in text:
    if text.count(anchor) != 1:
        raise SystemExit("world_boss.html base-template anchor changed; refusing unsafe patch")
    text = text.replace(anchor, anchor + block, 1)
    path.write_text(text, encoding="utf-8")

rendered = path.read_text(encoding="utf-8")
assert rendered.startswith(anchor + block), "page-specific stylesheet block is not directly after extends"
assert rendered.count("css/world_boss_help_modal.css") == 1
assert 'id="wb-help-modal"' in rendered
assert 'class="gc-player-card-dialog gc-world-boss-help-dialog"' in rendered
assert 'class="gc-player-card-body gc-world-boss-help-body"' in rendered

css = (ROOT / "static" / "css" / "world_boss_help_modal.css").read_text(encoding="utf-8")
for required in (
    ".gc-world-boss-help-modal[hidden]",
    ".gc-world-boss-help-dialog",
    "max-height: calc(100dvh - 32px)",
    "overflow-y: auto",
    "border-radius: 0 !important",
    "@media (max-width: 720px)",
):
    assert required in css, required
