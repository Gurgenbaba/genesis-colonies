from pathlib import Path

p = Path(__file__).resolve().parent.parent / "templates" / "admin_panel.html"
t = p.read_text(encoding="utf-8")

replacements = [
    ("admin-cc-tabs", "admin-tabs"),
    ("admin-cc-tab", "admin-tab-btn"),
    ("admin-cc-panel", "admin-panel admin-tab-panel"),
    ("data-panel=", "data-admin-panel="),
    ("admin-cc-toolbar admin-cc-toolbar-wrap", "admin-action-row admin-action-row-wrap"),
    ("admin-cc-toolbar", "admin-action-row"),
    ("admin-cc-panel-title", "admin-panel-title"),
    ("admin-cc-output", "admin-panel-body"),
    ("admin-cc-table-wrap", "admin-panel-body"),
    ("admin-cc-detail", "admin-card admin-detail"),
    ("admin-cc-danger-zone", "admin-danger-zone"),
    ("admin-cc-search-row", "admin-action-row"),
    ("admin-cc-filters", "admin-action-row"),
]
for a, b in replacements:
    t = t.replace(a, b)

if "admin-alert-host" not in t:
    t = t.replace(
        '<nav class="admin-tabs"',
        '    <p id="admin-alert-host" class="admin-alert-host" role="alert" aria-live="polite" hidden></p>\n\n    <nav class="admin-tabs"',
    )

legacy_old = """<section id="admin-tab-settings" class="admin-panel admin-tab-panel" data-admin-panel="settings" role="tabpanel" hidden>

    <!-- ============================================================= -->
    <!-- LEGACY SETTINGS / TOOLS (form POST)                           -->
    <!-- ============================================================= -->"""
legacy_new = """<section id="admin-tab-settings" class="admin-panel admin-tab-panel" data-admin-panel="settings" role="tabpanel" hidden>
    <motion></motion>
    <div class="admin-card admin-legacy-banner">
      <h2 class="admin-panel-title">{{ T("admin_legacy_settings_title") }}</h2>
      <p class="admin-small-hint">{{ T("admin_legacy_settings_hint") }}</p>
    </div>"""
if "admin_legacy_settings_title" not in t and legacy_old in t:
    t = t.replace(legacy_old, legacy_new.replace("<motion></motion>\n    ", ""))

if "admin-migrations-prod-note" not in t:
    t = t.replace(
        '<motion></motion>\n      <motion></motion>\n      <motion></motion>\n      <div class="admin-danger-zone" id="admin-migrations-run-zone"',
        '<p id="admin-migrations-prod-note" class="admin-prod-note" hidden>{{ T("admin_migrations_prod_note") }}</p>\n      <div class="admin-danger-zone" id="admin-migrations-run-zone"',
    )
    t = t.replace(
        '<div class="admin-danger-zone" id="admin-migrations-run-zone"',
        '<p id="admin-migrations-prod-note" class="admin-prod-note" hidden>{{ T("admin_migrations_prod_note") }}</p>\n      <motion></motion>\n      <div class="admin-danger-zone" id="admin-migrations-run-zone"',
        1,
    )

t = t.replace("<motion></motion>", "")
t = t.replace("</motion></motion></div>", "</div>")
t = t.replace("</motion></motion></div>", "</div>")
t = t.replace("</motion></div>", "</motion></div>")
t = t.replace("</motion></div>", "</div>")
t = t.replace(
    "{% block extra_scripts %}\n<script src=\"{{ url_for('static', filename='admin.js') }}\"></script>\n{% endblock %}\n",
    "",
)

p.write_text(t, encoding="utf-8")
print("ok")
