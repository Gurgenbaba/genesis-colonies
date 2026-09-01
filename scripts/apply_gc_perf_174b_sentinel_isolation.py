from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# A 'safe presentation control' must never be a navigation link. The old selector
# legitimately found <a role=tab href=...> fleet-mode links, and Playwright's
# click wait left real PJAX work alive after the 3s probe timeout.
replace_once(
    "scripts/browser_sentinel.py",
    '            if control.evaluate("(el) => !!el.closest(\'form\')"):\n                continue\n            if control.get_attribute("aria-selected") == "true":\n',
    '            if control.evaluate("(el) => !!el.closest(\'form\')"):\n                continue\n            if control.evaluate("(el) => el.tagName === \'A\' || !!el.getAttribute(\'href\')"):\n                continue\n            if control.get_attribute("aria-selected") == "true":\n',
)
# These remaining controls are in-page tabs. Force avoids false "not stable"
# failures from cosmetic animation without waiting on navigation (there is none).
replace_once(
    "scripts/browser_sentinel.py",
    '            control.click(timeout=3_000)\n',
    '            control.click(timeout=3_000, force=True)\n',
)

# Make the primary PJAX outcome explicit. A timeout sample is useful evidence,
# but must not masquerade as a completed 200 navigation or poison later audits.
replace_once(
    "scripts/browser_sentinel.py",
    '''          let status = null;\n          if (sample && Array.isArray(sample.concurrent_requests)) {\n            const primary = sample.concurrent_requests.find((entry) => entry && entry.server)\n              || sample.concurrent_requests.find((entry) => entry && Number(entry.status) > 0)\n              || null;\n            if (primary) status = Number(primary.status || 0) || null;\n          }\n          return { used_pjax: true, sample, status, href: location.href };\n''',
    '''          let status = null;\n          let primaryError = null;\n          if (sample && Array.isArray(sample.concurrent_requests)) {\n            const primary = sample.concurrent_requests.find((entry) =>\n              entry && Number(entry.offset_ms || 0) === 0 && ["pjax", "galaxy"].includes(String(entry.kind || ""))\n            ) || sample.concurrent_requests.find((entry) => entry && entry.server)\n              || sample.concurrent_requests.find((entry) => entry && Number(entry.status) > 0)\n              || null;\n            if (primary) {\n              status = Number(primary.status || 0) || null;\n              primaryError = primary.error ? String(primary.error) : null;\n            }\n          }\n          return { used_pjax: true, sample, status, primary_error: primaryError, href: location.href };\n''',
)

# Route result records completion explicitly. The runner can continue collecting
# evidence, while failed PJAX requests remain visible as HIGH findings.
replace_once(
    "scripts/browser_sentinel.py",
    '                "navigation_perf": None,\n                "safe_controls": [],\n',
    '                "navigation_perf": None,\n                "navigation_error": None,\n                "safe_controls": [],\n',
)
replace_once(
    "scripts/browser_sentinel.py",
    '''                if nav_result.get("used_pjax"):\n                    result["navigation_mode"] = "pjax"\n                    result["navigation_perf"] = nav_result.get("sample")\n                    result["status"] = nav_result.get("status") or 200\n                else:\n''',
    '''                if nav_result.get("used_pjax"):\n                    result["navigation_mode"] = "pjax"\n                    result["navigation_perf"] = nav_result.get("sample")\n                    result["navigation_error"] = nav_result.get("primary_error")\n                    result["status"] = nav_result.get("status")\n                    if result["navigation_error"]:\n                        _new_finding(\n                            findings,\n                            severity="HIGH",\n                            kind="pjax_navigation_failed",\n                            page_name=spec.name,\n                            route=spec.path,\n                            viewport=viewport_name,\n                            action=action,\n                            problem=f"PJAX primary request failed: {result['navigation_error']}",\n                            screenshot=shot_rel,\n                            dom=dom_rel,\n                            details={"navigation_perf": result["navigation_perf"] or {}},\n                        )\n                else:\n''',
)

# Static regressions pin the separation: navigation links are never UI probes,
# and primary request failures are not silently treated as success.
test = ROOT / "tests/test_gc_perf_174_sentinel_nav_matrix.py"
text = test.read_text(encoding="utf-8")
anchor = '''    assert '"nav_perf_samples": report["navigation_perf"]["sample_count"]' in src\n\n\ndef test_nav_sample_carries_database_backend_identity():\n'''
insert = '''    assert '"nav_perf_samples": report["navigation_perf"]["sample_count"]' in src\n\n\ndef test_sentinel_safe_controls_never_click_navigation_links():\n    src = _read("scripts/browser_sentinel.py")\n    block = src.split("def _probe_safe_controls(page)", 1)[1].split("def _navigate_with_pjax_perf", 1)[0]\n    assert "el.tagName === 'A'" in block\n    assert "el.getAttribute('href')" in block\n    assert "force=True" in block\n\n\ndef test_sentinel_marks_primary_pjax_failures_explicitly():\n    src = _read("scripts/browser_sentinel.py")\n    assert "primaryError" in src\n    assert '"navigation_error": None' in src\n    assert 'kind="pjax_navigation_failed"' in src\n    assert 'result["status"] = nav_result.get("status")' in src\n\n\ndef test_nav_sample_carries_database_backend_identity():\n'''
if text.count(anchor) != 1:
    raise SystemExit("test insertion anchor mismatch")
test.write_text(text.replace(anchor, insert, 1), encoding="utf-8")

print("GC-PERF-174B Sentinel isolation patch staged")
