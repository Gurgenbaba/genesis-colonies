from pathlib import Path
import re

APP = Path("app.py")
ROUTES = (
    "api_world_boss_attack",
    "api_world_boss_auto_attack",
    "api_world_boss_claim",
    "api_world_boss_catch",
    "api_world_boss_companion_mission",
)


def route_span(text: str, func: str) -> tuple[int, int]:
    marker = f"def {func}():"
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"missing route {func}")
    end = text.find("\n@app.route(", start + len(marker))
    if end < 0:
        end = len(text)
    return start, end


def strip_generic_state_builder(block: str, func: str) -> str:
    lines = block.splitlines(keepends=True)
    builder = next(
        (i for i, line in enumerate(lines) if "state, _ = _build_game_state_payload(" in line),
        None,
    )
    if builder is None:
        raise SystemExit(f"{func}: missing generic state builder")

    close = None
    for i in range(builder + 1, len(lines)):
        if lines[i].strip() == ")" and lines[i].startswith("    "):
            close = i
            break
    if close is None:
        raise SystemExit(f"{func}: state builder close not found")

    remove_from = builder
    j = builder - 1
    comments: list[int] = []
    while j >= 0 and (not lines[j].strip() or lines[j].lstrip().startswith("#")):
        if lines[j].lstrip().startswith("#"):
            comments.append(j)
        j -= 1
    if comments and any("GC-PERF-WB" in lines[i] for i in comments):
        remove_from = min(comments)
        while remove_from > 0 and not lines[remove_from - 1].strip():
            remove_from -= 1

    del lines[remove_from : close + 1]
    block = "".join(lines)

    # Multiline response dict member.
    block = re.sub(
        r'^\s*"state"\s*:\s*state\s*,?\s*\n',
        "",
        block,
        flags=re.MULTILINE,
    )
    # Compact return dict (claim) and defensive variants.
    block = block.replace(', "state": state', "")
    block = block.replace('"state": state, ', "")
    block = block.replace('"state": state', "")
    return block


src = APP.read_text(encoding="utf-8")
for func in ROUTES:
    start, end = route_span(src, func)
    patched = strip_generic_state_builder(src[start:end], func)
    src = src[:start] + patched + src[end:]

for func in ROUTES:
    start, end = route_span(src, func)
    block = src[start:end]
    assert "_build_game_state_payload" not in block, func
    assert '"state": state' not in block, func
APP.write_text(src, encoding="utf-8")

# Remove the redundant Galaxy CTA from World Boss cards.
tpl_path = Path("templates/world_boss.html")
tpl = tpl_path.read_text(encoding="utf-8")
token = "world_boss_btn_galaxy"
if tpl.count(token) != 1:
    raise SystemExit(f"expected exactly one Galaxy CTA token, got {tpl.count(token)}")
token_i = tpl.index(token)
start = tpl.rfind("{% if boss.galaxy_href %}", 0, token_i)
end = tpl.find("{% endif %}", token_i)
if start < 0 or end < 0:
    raise SystemExit("Galaxy CTA wrapper not found")
end += len("{% endif %}")
line_start = tpl.rfind("\n", 0, start) + 1
line_end = tpl.find("\n", end)
line_end = end if line_end < 0 else line_end + 1
tpl = tpl[:line_start] + tpl[line_end:]
assert "world_boss_btn_galaxy" not in tpl
assert "boss.galaxy_href" not in tpl
tpl_path.write_text(tpl, encoding="utf-8")

# Flip any existing template regression that expected the now-removed CTA.
changed_tests: list[str] = []
for test_path in Path("tests").glob("test_*.py"):
    text = test_path.read_text(encoding="utf-8")
    original = text
    text = re.sub(
        r'assert\s+"boss\.galaxy_href"\s+in\s+(\w+)',
        r'assert "boss.galaxy_href" not in \1',
        text,
    )
    text = re.sub(
        r'assert\s+"world_boss_btn_galaxy"\s+in\s+(\w+)',
        r'assert "world_boss_btn_galaxy" not in \1',
        text,
    )
    if text != original:
        test_path.write_text(text, encoding="utf-8")
        changed_tests.append(str(test_path))
print("updated Galaxy CTA tests:", changed_tests)

Path("tests/test_gc_perf_wb_hot_012.py").write_text(
    '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _route_block(src: str, func: str) -> str:
    marker = f"def {func}():"
    block = src.split(marker, 1)[1]
    return block.split("\\n@app.route(", 1)[0]


def test_world_boss_mutations_do_not_gate_on_generic_game_state():
    src = _read("app.py")
    for func in (
        "api_world_boss_attack",
        "api_world_boss_auto_attack",
        "api_world_boss_claim",
        "api_world_boss_catch",
        "api_world_boss_companion_mission",
    ):
        block = _route_block(src, func)
        assert "_build_game_state_payload" not in block, func
        assert '\"state\": state' not in block, func


def test_world_boss_frontend_accepts_fastlane_without_generic_state():
    src = _read("static/main.js")
    assert 'if (res && res.state && typeof GC.applyActionState === "function")' in src
    assert "hit_mult: hitMult" in src
    assert "if (hitMult !== 5) hitMult = 1" in src
    assert "/api/world-boss/attack" in src
    assert "/api/world-boss/auto-attack" in src


def test_world_boss_galaxy_cta_is_removed():
    template = _read("templates/world_boss.html")
    assert "world_boss_btn_galaxy" not in template
    assert "boss.galaxy_href" not in template
''',
    encoding="utf-8",
)

version = Path("VERSION")
current = version.read_text(encoding="utf-8").strip()
if current != "0.5.9.162":
    raise SystemExit(f"unexpected VERSION before hotfix: {current}")
version.write_text("0.5.9.163\n", encoding="utf-8")

perf = Path("docs/PERFORMANCE.md")
perf_text = perf.read_text(encoding="utf-8")
if "GC-PERF-WB-HOT-012" not in perf_text:
    perf_text = perf_text.rstrip() + '''

## GC-PERF-WB-HOT-012 — World Boss action fastlane

World Boss mutation responses (`attack`, `auto-attack`, `claim`, `catch`, companion mission) return their authoritative mutation payload immediately and no longer gate the click on a generic `_build_game_state_payload` rebuild. The existing World Boss live poll and normal game-state poll remain the reconciliation owners; no second client state model or gameplay math is introduced. The x5 strike remains one server-authoritative request with `hit_mult=5`. The redundant Galaxy CTA was removed from World Boss cards.
'''
    perf.write_text(perf_text + "\n", encoding="utf-8")
