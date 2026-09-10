from pathlib import Path

path = Path(__file__).resolve().parents[1] / "templates/buildings.html"
text = path.read_text(encoding="utf-8")
replacements = {
'''            <button type="button"
                    class="gc-btn gc-bld-evo-btn"
                    data-research-lab-ascend''': '''            <button type="button"
                    class="gc-btn gc-bld-evo-btn" {# i18n-ok: structural attribute #}
                    data-research-lab-ascend''',
'''<div id="gc-research-lab-ascension-confirm-modal"
     class="gc-player-card-modal gc-bld-evo-confirm-modal"
     hidden''': '''<div id="gc-research-lab-ascension-confirm-modal"
     class="gc-player-card-modal gc-bld-evo-confirm-modal" {# i18n-ok: structural attribute #}
     hidden''',
'''  <div class="gc-player-card-dialog gc-bld-evo-confirm-dialog"
       role="dialog"
       aria-modal="true"''': '''  <div class="gc-player-card-dialog gc-bld-evo-confirm-dialog" {# i18n-ok: structural attribute #}
       role="dialog" {# i18n-ok: structural attribute #}
       aria-modal="true"''',
'''      <button type="button"
              class="gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close"
              data-research-lab-ascension-cancel''': '''      <button type="button"
              class="gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close" {# i18n-ok: structural attribute #}
              data-research-lab-ascension-cancel''',
}
for old, new in replacements.items():
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one structural match, got {count}: {old[:60]!r}")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("research lab structural i18n lines marked")
