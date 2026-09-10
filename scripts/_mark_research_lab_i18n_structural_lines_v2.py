from pathlib import Path

path = Path(__file__).resolve().parents[1] / "templates/buildings.html"
text = path.read_text(encoding="utf-8")

# Scope the trigger marker strictly to the Research Lab block so the identical
# Mine Ascension button class remains untouched.
block_start = text.index("{% if building_type == 'research_lab'")
block_end = text.index("{% if _evo %}", block_start)
block = text[block_start:block_end]
old = 'class="gc-btn gc-bld-evo-btn"\n                    data-research-lab-ascend'
new = 'class="gc-btn gc-bld-evo-btn" {# i18n-ok: structural attribute #}\n                    data-research-lab-ascend'
if block.count(old) != 1:
    raise SystemExit(f"expected one research trigger structural match, got {block.count(old)}")
block = block.replace(old, new, 1)
text = text[:block_start] + block + text[block_end:]

# Scope modal markers strictly between the Research Lab modal and Stellar Forge.
modal_start = text.index('<div id="gc-research-lab-ascension-confirm-modal"')
modal_end = text.index('<div id="gc-stellar-forge-modal"', modal_start)
modal = text[modal_start:modal_end]
replacements = {
    'class="gc-player-card-modal gc-bld-evo-confirm-modal"\n     hidden':
        'class="gc-player-card-modal gc-bld-evo-confirm-modal" {# i18n-ok: structural attribute #}\n     hidden',
    'class="gc-player-card-dialog gc-bld-evo-confirm-dialog"\n       role="dialog"':
        'class="gc-player-card-dialog gc-bld-evo-confirm-dialog" {# i18n-ok: structural attribute #}\n       role="dialog" {# i18n-ok: structural attribute #}',
    'class="gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close"\n              data-research-lab-ascension-cancel':
        'class="gc-btn gc-btn-ghost gc-btn-xs gc-player-card-close" {# i18n-ok: structural attribute #}\n              data-research-lab-ascension-cancel',
}
for old, new in replacements.items():
    count = modal.count(old)
    if count != 1:
        raise SystemExit(f"expected one research modal structural match, got {count}: {old[:70]!r}")
    modal = modal.replace(old, new, 1)

text = text[:modal_start] + modal + text[modal_end:]
path.write_text(text, encoding="utf-8")
print("research lab structural i18n lines marked (scoped)")
