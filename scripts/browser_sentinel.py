#!/usr/bin/env python3
"""Genesis Sentinel V1 — browser journey, runtime error capture and UI geometry audit.

Sandbox mode is the CI/default mode. It creates a disposable DB and Flask
subprocess. Live mode is read-only and requires explicit environment variables.

Examples:
  python scripts/browser_sentinel.py --mode sandbox
  GC_SENTINEL_BASE_URL=https://example.invalid \
  GC_SENTINEL_USERNAME=qa GC_SENTINEL_PASSWORD=... \
  python scripts/browser_sentinel.py --mode live --fail-on high
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.browser_test_support import (  # noqa: E402
    login_with_ui,
    safe_name,
    start_sandbox,
)

VIEWPORTS = (
    ("desktop", {"width": 1440, "height": 900}),
    ("mobile", {"width": 390, "height": 844}),
)

CORE_ROUTES = (
    ("overview", "/overview"),
    ("buildings", "/buildings"),
    ("research", "/research"),
    ("shipyard", "/shipyard"),
    ("defense", "/defense"),
    ("fleet", "/fleet"),
    ("logistics", "/logistics"),
    ("galaxy", "/galaxy?view=command_map"),
    ("planet-evolution", "/planet-evolution"),
    ("ranking", "/ranking"),
    ("alliance", "/alliance"),
    ("world-boss", "/world-boss"),
    ("trader-hub", "/trader-hub"),
    ("inventory", "/inventory"),
    ("auction-house", "/auction-house"),
    ("galactic-politics", "/galactic-politics"),
    ("shop", "/shop"),
    ("messages", "/messages"),
)

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
FAIL_RANK = {"none": 99, "critical": 4, "high": 3, "medium": 2, "low": 1}

UI_AUDIT_JS = r"""
() => {
  const findings = [];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const tol = 4;

  const desc = (el) => {
    if (!el) return "";
    let out = el.tagName ? el.tagName.toLowerCase() : "node";
    if (el.id) out += "#" + el.id;
    if (el.classList && el.classList.length) {
      out += "." + Array.from(el.classList).slice(0, 3).join(".");
    }
    return out;
  };
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return {
      left: Math.round(r.left * 10) / 10,
      top: Math.round(r.top * 10) / 10,
      right: Math.round(r.right * 10) / 10,
      bottom: Math.round(r.bottom * 10) / 10,
      width: Math.round(r.width * 10) / 10,
      height: Math.round(r.height * 10) / 10,
    };
  };
  const styleVisible = (el) => {
    if (!el || el.hidden || el.getAttribute("aria-hidden") === "true") return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity || "1") <= 0.01) return false;
    return true;
  };
  const visible = (el) => {
    if (!styleVisible(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0.5 && r.height > 0.5;
  };
  const hasHorizontalScrollAncestor = (el) => {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const s = getComputedStyle(p);
      const allows = ["auto", "scroll"].includes(s.overflowX);
      if (allows && p.scrollWidth > p.clientWidth + 2) return true;
      p = p.parentElement;
    }
    return false;
  };
  const sameOrigin = (src) => {
    try { return new URL(src, location.href).origin === location.origin; }
    catch (_) { return false; }
  };

  const doc = document.documentElement;
  const body = document.body;
  const overflowBy = Math.max(doc.scrollWidth, body ? body.scrollWidth : 0) - vw;
  if (overflowBy > tol) {
    findings.push({
      kind: "horizontal_page_overflow",
      severity: "MEDIUM",
      problem: `Document is ${Math.round(overflowBy)}px wider than viewport`,
      geometry: { viewportWidth: vw, documentWidth: Math.max(doc.scrollWidth, body ? body.scrollWidth : 0), overflow: Math.round(overflowBy) },
    });
  }

  for (const img of Array.from(document.images)) {
    const src = img.currentSrc || img.src || "";
    if (!src || !sameOrigin(src)) continue;
    if (img.complete && img.naturalWidth === 0 && visible(img)) {
      findings.push({
        kind: "broken_image",
        severity: "HIGH",
        problem: `Visible same-origin image failed to load: ${src}`,
        element: desc(img),
        geometry: rect(img),
      });
    }
  }

  const interactiveSelector = [
    "button", "a[href]", "input", "select", "textarea",
    "[role='button']", "[role='tab']", "[tabindex]"
  ].join(",");
  const allInteractive = Array.from(document.querySelectorAll(interactiveSelector));
  const interactive = [];
  for (const el of allInteractive) {
    if (!styleVisible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0.5 || r.height <= 0.5) {
      if (el.offsetParent !== null) {
        findings.push({
          kind: "zero_size_control",
          severity: "MEDIUM",
          problem: "Interactive element is rendered with ~0px size",
          element: desc(el),
          geometry: rect(el),
        });
      }
      continue;
    }
    if (!visible(el)) continue;
    interactive.push(el);

    const isFarOutside = r.right < -tol || r.left > vw + tol || r.bottom < -tol || r.top > vh + tol;
    const crossesX = r.left < -tol || r.right > vw + tol;
    if (!isFarOutside && crossesX && !hasHorizontalScrollAncestor(el)) {
      findings.push({
        kind: "control_outside_viewport",
        severity: "LOW",
        problem: "Interactive element crosses horizontal viewport boundary",
        element: desc(el),
        geometry: rect(el),
      });
    }

    const s = getComputedStyle(el);
    const clippedX = el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 4;
    const clippedY = el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 4;
    const intentionallyEllipsized = s.textOverflow === "ellipsis";
    if ((clippedX || clippedY) && !intentionallyEllipsized && ["hidden", "clip"].includes(s.overflowX || s.overflow)) {
      findings.push({
        kind: "clipped_control_content",
        severity: "MEDIUM",
        problem: "Interactive element content is clipped",
        element: desc(el),
        geometry: { ...rect(el), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight },
      });
    }
  }

  // Detect strong unexpected intersections between interactive controls.
  // Fixed/sticky controls are excluded because intentional shell overlays exist.
  const overlapCandidates = interactive.slice(0, 160);
  let overlapCount = 0;
  for (let i = 0; i < overlapCandidates.length && overlapCount < 15; i++) {
    const a = overlapCandidates[i];
    const as = getComputedStyle(a);
    if (["fixed", "sticky"].includes(as.position)) continue;
    const ar = a.getBoundingClientRect();
    for (let j = i + 1; j < overlapCandidates.length && overlapCount < 15; j++) {
      const b = overlapCandidates[j];
      if (a.contains(b) || b.contains(a)) continue;
      const bs = getComputedStyle(b);
      if (["fixed", "sticky"].includes(bs.position)) continue;
      const br = b.getBoundingClientRect();
      const iw = Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.left, br.left));
      const ih = Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top));
      if (iw <= 0 || ih <= 0) continue;
      const intersection = iw * ih;
      const smaller = Math.max(1, Math.min(ar.width * ar.height, br.width * br.height));
      if (intersection / smaller < 0.35) continue;
      findings.push({
        kind: "control_overlap",
        severity: "MEDIUM",
        problem: "Two interactive controls overlap substantially",
        element: `${desc(a)} <> ${desc(b)}`,
        geometry: {
          first: rect(a),
          second: rect(b),
          overlapWidth: Math.round(iw * 10) / 10,
          overlapHeight: Math.round(ih * 10) / 10,
          overlapRatio: Math.round((intersection / smaller) * 1000) / 1000,
        },
      });
      overlapCount += 1;
    }
  }

  const dialogs = Array.from(document.querySelectorAll("[role='dialog'], dialog, .modal, .gc-modal, .dialog")).filter(visible);
  for (const el of dialogs) {
    const r = el.getBoundingClientRect();
    if (r.left < -8 || r.top < -8 || r.right > vw + 8 || r.bottom > vh + 8) {
      findings.push({
        kind: "dialog_outside_viewport",
        severity: "HIGH",
        problem: "Visible dialog extends outside the viewport",
        element: desc(el),
        geometry: rect(el),
      });
    }
  }

  return findings;
}
"""


@dataclass(frozen=True)
class RouteSpec:
    name: str
    path: str


def _same_origin(url: str, base_url: str) -> bool:
    try:
        a = urlsplit(url)
        b = urlsplit(base_url)
        return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)
    except Exception:
        return False


def _new_finding(
    findings: list[dict],
    *,
    severity: str,
    kind: str,
    page_name: str,
    route: str,
    viewport: str,
    action: str,
    problem: str,
    geometry: dict | None = None,
    element: str | None = None,
    screenshot: str | None = None,
    dom: str | None = None,
    details: dict | None = None,
) -> dict:
    raw = f"{viewport}|{page_name}|{kind}|{action}|{problem}|{len(findings)}"
    finding_id = "GC-SENTINEL-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()
    item = {
        "id": finding_id,
        "severity": severity,
        "kind": kind,
        "page": route,
        "page_name": page_name,
        "viewport": viewport,
        "action": action,
        "problem": problem,
        "geometry": geometry or {},
        "element": element,
        "screenshot": screenshot,
        "dom": dom,
        "details": details or {},
    }
    findings.append(item)
    return item


def _install_third_party_guard(context, base_url: str) -> None:
    def route_handler(route, request) -> None:
        url = request.url
        if url.startswith(("data:", "blob:", "about:")) or _same_origin(url, base_url):
            route.continue_()
        else:
            route.abort()

    context.route("**/*", route_handler)


def _attach_runtime_capture(page, base_url: str, current: dict, events: list[dict]) -> None:
    def add(kind: str, severity: str, **payload) -> None:
        events.append(
            {
                "kind": kind,
                "severity": severity,
                "page_name": current.get("page_name", ""),
                "route": current.get("route", ""),
                "viewport": current.get("viewport", ""),
                "timestamp": time.time(),
                **payload,
            }
        )

    def on_console(message) -> None:
        if message.type == "error":
            add("console_error", "HIGH", problem=message.text)

    def on_page_error(error) -> None:
        add("page_exception", "HIGH", problem=str(error))

    def on_response(response) -> None:
        if not _same_origin(response.url, base_url):
            return
        if response.status >= 400:
            severity = "CRITICAL" if response.status >= 500 and response.request.resource_type == "document" else "HIGH"
            add(
                "http_error",
                severity,
                problem=f"HTTP {response.status} for {response.url}",
                details={"status": response.status, "url": response.url, "resource_type": response.request.resource_type},
            )

    def on_request_failed(request) -> None:
        if not _same_origin(request.url, base_url):
            return
        failure = getattr(request, "failure", None)
        add(
            "request_failed",
            "HIGH",
            problem=f"Request failed: {request.url}",
            details={"url": request.url, "resource_type": request.resource_type, "failure": failure},
        )

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)


def _probe_safe_controls(page) -> list[dict]:
    """Click only presentation controls that are very unlikely to mutate game state."""
    results: list[dict] = []
    selector = "[role='tab'], button[data-tab], button[data-tab-target], .tabs button, .tab-button"
    locator = page.locator(selector)
    count = min(locator.count(), 8)
    for index in range(count):
        control = locator.nth(index)
        try:
            if not control.is_visible() or not control.is_enabled():
                continue
            if control.evaluate("(el) => !!el.closest('form')"):
                continue
            if control.get_attribute("aria-selected") == "true":
                continue
            label = (control.inner_text(timeout=1_000) or control.get_attribute("aria-label") or f"control-{index}").strip()
            controls_id = control.get_attribute("aria-controls")
            before = None
            if controls_id:
                target = page.locator(f"#{controls_id}")
                if target.count():
                    before = target.evaluate(
                        "(el) => ({hidden: !!el.hidden, ariaHidden: el.getAttribute('aria-hidden'), className: el.className})"
                    )
            control.click(timeout=3_000)
            page.wait_for_timeout(150)
            after = None
            if controls_id:
                target = page.locator(f"#{controls_id}")
                if target.count():
                    after = target.evaluate(
                        "(el) => ({hidden: !!el.hidden, ariaHidden: el.getAttribute('aria-hidden'), className: el.className})"
                    )
            results.append(
                {
                    "label": label[:120],
                    "aria_controls": controls_id,
                    "target_changed": None if before is None or after is None else before != after,
                    "ok": True,
                }
            )
        except Exception as exc:
            results.append({"label": f"control-{index}", "ok": False, "error": str(exc)[:500]})
    return results


def _write_html_report(report: dict, path: Path) -> None:
    counts = Counter(item["severity"] for item in report["findings"])
    rows = []
    for item in report["findings"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['severity'])}</td>"
            f"<td>{html.escape(item['kind'])}</td>"
            f"<td>{html.escape(item['viewport'])}</td>"
            f"<td>{html.escape(item['page_name'])}</td>"
            f"<td>{html.escape(item['problem'])}</td>"
            f"<td>{html.escape(item.get('element') or '')}</td>"
            "</tr>"
        )
    summary = " · ".join(f"{key}: {counts.get(key, 0)}" for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW"))
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Genesis Sentinel Report</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:24px;background:#0b111a;color:#e6edf3}}
h1{{margin-bottom:4px}} .meta{{color:#9fb1c5;margin-bottom:18px}}
.pass{{color:#7ee787}} .fail{{color:#ff7b72}}
table{{border-collapse:collapse;width:100%;background:#111923}}
th,td{{border:1px solid #263442;padding:8px;vertical-align:top;text-align:left}}
th{{background:#162230;position:sticky;top:0}}
code{{color:#c9d1d9}}
</style>
</head>
<body>
<h1>Genesis Sentinel V1</h1>
<p class="meta">Mode: {html.escape(report['mode'])} · Started: {html.escape(report['started_at'])} · {html.escape(summary)}</p>
<h2 class="{'pass' if report['pass'] else 'fail'}">{'PASS' if report['pass'] else 'FAIL'}</h2>
<p>Gate: fail on <code>{html.escape(report['fail_on'])}</code> or worse. Findings: {len(report['findings'])}.</p>
<table>
<thead><tr><th>Severity</th><th>Kind</th><th>Viewport</th><th>Page</th><th>Problem</th><th>Element</th></tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan="6">No findings.</td></tr>'}</tbody>
</table>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def _selected_routes(names: list[str] | None) -> list[RouteSpec]:
    specs = [RouteSpec(name, path) for name, path in CORE_ROUTES]
    if not names:
        return specs
    wanted = set(names)
    known = {spec.name for spec in specs}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(f"Unknown Sentinel route name(s): {', '.join(unknown)}")
    return [spec for spec in specs if spec.name in wanted]


def _run_viewport(
    browser,
    *,
    viewport_name: str,
    viewport: dict,
    base_url: str,
    username: str,
    password: str,
    artifact_root: Path,
    routes: list[RouteSpec],
    findings: list[dict],
    route_results: list[dict],
) -> None:
    context = browser.new_context(viewport=viewport, ignore_https_errors=False)
    _install_third_party_guard(context, base_url)
    trace_dir = artifact_root / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(30_000)
    current = {"page_name": "login", "route": "/login", "viewport": viewport_name}
    events: list[dict] = []
    _attach_runtime_capture(page, base_url, current, events)

    try:
        login_with_ui(page, base_url, username, password)
        # Ignore login-page runtime noise when evaluating game routes.
        events.clear()

        for spec in routes:
            current.update(page_name=spec.name, route=spec.path, viewport=viewport_name)
            event_start = len(events)
            shot_rel = f"screenshots/{viewport_name}-{safe_name(spec.name)}.png"
            dom_rel = f"dom/{viewport_name}-{safe_name(spec.name)}.html"
            shot_path = artifact_root / shot_rel
            dom_path = artifact_root / dom_rel
            shot_path.parent.mkdir(parents=True, exist_ok=True)
            dom_path.parent.mkdir(parents=True, exist_ok=True)

            result = {
                "name": spec.name,
                "route": spec.path,
                "viewport": viewport_name,
                "final_url": None,
                "status": None,
                "safe_controls": [],
                "screenshot": shot_rel,
                "dom": dom_rel,
            }
            action = f"GET {spec.path}"
            try:
                response = page.goto(f"{base_url.rstrip('/')}{spec.path}", wait_until="domcontentloaded", timeout=60_000)
                result["status"] = response.status if response else None
                page.wait_for_selector("body", state="attached", timeout=10_000)
                page.wait_for_timeout(650)
                result["final_url"] = page.url

                if "/login" in urlsplit(page.url).path:
                    _new_finding(
                        findings,
                        severity="CRITICAL",
                        kind="auth_regression",
                        page_name=spec.name,
                        route=spec.path,
                        viewport=viewport_name,
                        action=action,
                        problem="Journey was redirected back to login",
                        screenshot=shot_rel,
                        dom=dom_rel,
                    )

                expected_path = urlsplit(spec.path).path
                final_path = urlsplit(page.url).path
                if final_path != expected_path:
                    _new_finding(
                        findings,
                        severity="MEDIUM",
                        kind="navigation_target_mismatch",
                        page_name=spec.name,
                        route=spec.path,
                        viewport=viewport_name,
                        action=action,
                        problem=f"Expected {expected_path}, landed on {final_path}",
                        screenshot=shot_rel,
                        dom=dom_rel,
                        details={"final_url": page.url},
                    )

                ui_findings = page.evaluate(UI_AUDIT_JS)
                for issue in ui_findings:
                    _new_finding(
                        findings,
                        severity=issue.get("severity", "MEDIUM"),
                        kind=issue.get("kind", "ui_issue"),
                        page_name=spec.name,
                        route=spec.path,
                        viewport=viewport_name,
                        action=action,
                        problem=issue.get("problem", "UI audit finding"),
                        geometry=issue.get("geometry") or {},
                        element=issue.get("element"),
                        screenshot=shot_rel,
                        dom=dom_rel,
                    )

                result["safe_controls"] = _probe_safe_controls(page)
                for control in result["safe_controls"]:
                    if not control.get("ok"):
                        _new_finding(
                            findings,
                            severity="MEDIUM",
                            kind="safe_control_click_failed",
                            page_name=spec.name,
                            route=spec.path,
                            viewport=viewport_name,
                            action="Click safe presentation control",
                            problem=control.get("error", "Safe control click failed"),
                            screenshot=shot_rel,
                            dom=dom_rel,
                        )

            except Exception as exc:
                _new_finding(
                    findings,
                    severity="CRITICAL",
                    kind="journey_exception",
                    page_name=spec.name,
                    route=spec.path,
                    viewport=viewport_name,
                    action=action,
                    problem=str(exc)[:1000],
                    screenshot=shot_rel,
                    dom=dom_rel,
                )
            finally:
                try:
                    dom_path.write_text(page.content(), encoding="utf-8")
                except Exception as exc:
                    _new_finding(
                        findings,
                        severity="MEDIUM",
                        kind="dom_capture_failed",
                        page_name=spec.name,
                        route=spec.path,
                        viewport=viewport_name,
                        action="Capture DOM",
                        problem=str(exc)[:500],
                    )
                try:
                    page.screenshot(path=str(shot_path), full_page=True, animations="disabled", timeout=30_000)
                except Exception as exc:
                    _new_finding(
                        findings,
                        severity="MEDIUM",
                        kind="screenshot_failed",
                        page_name=spec.name,
                        route=spec.path,
                        viewport=viewport_name,
                        action="Capture screenshot",
                        problem=str(exc)[:500],
                        dom=dom_rel,
                    )

            for event in events[event_start:]:
                _new_finding(
                    findings,
                    severity=event["severity"],
                    kind=event["kind"],
                    page_name=spec.name,
                    route=spec.path,
                    viewport=viewport_name,
                    action=action,
                    problem=event["problem"],
                    screenshot=shot_rel,
                    dom=dom_rel,
                    details=event.get("details") or {},
                )
            route_results.append(result)
    finally:
        try:
            context.tracing.stop(path=str(trace_dir / f"{viewport_name}.zip"))
        finally:
            context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genesis Sentinel browser QA")
    parser.add_argument("--mode", choices=("sandbox", "live"), default="sandbox")
    parser.add_argument("--artifacts", default="artifacts/browser")
    parser.add_argument("--fail-on", choices=("none", "critical", "high", "medium", "low"), default="high")
    parser.add_argument("--route", action="append", help="Run only a named core route (repeatable)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_root = (ROOT / args.artifacts).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    runtime = None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: install dev requirements and run `python -m playwright install chromium`")
        return 2

    try:
        routes = _selected_routes(args.route)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.mode == "sandbox":
        try:
            runtime = start_sandbox(artifact_root)
        except Exception as exc:
            print(f"FAIL: could not start Sentinel sandbox: {exc}")
            return 2
        base_url = runtime.base_url
        username = runtime.username
        password = runtime.password
    else:
        base_url = os.environ.get("GC_SENTINEL_BASE_URL", "").strip().rstrip("/")
        username = os.environ.get("GC_SENTINEL_USERNAME", "").strip()
        password = os.environ.get("GC_SENTINEL_PASSWORD", "")
        if not base_url or not username or not password:
            print("FAIL: live mode requires GC_SENTINEL_BASE_URL, GC_SENTINEL_USERNAME and GC_SENTINEL_PASSWORD")
            return 2

    findings: list[dict] = []
    route_results: list[dict] = []
    infrastructure_error: str | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport_name, viewport in VIEWPORTS:
                    _run_viewport(
                        browser,
                        viewport_name=viewport_name,
                        viewport=viewport,
                        base_url=base_url,
                        username=username,
                        password=password,
                        artifact_root=artifact_root,
                        routes=routes,
                        findings=findings,
                        route_results=route_results,
                    )
            finally:
                browser.close()
    except Exception as exc:
        infrastructure_error = str(exc)
        _new_finding(
            findings,
            severity="CRITICAL",
            kind="sentinel_infrastructure_error",
            page_name="sentinel",
            route="",
            viewport="",
            action="Run browser harness",
            problem=infrastructure_error[:1500],
        )
    finally:
        if runtime is not None:
            runtime.stop()

    threshold = FAIL_RANK[args.fail_on]
    gate_findings = [item for item in findings if SEVERITY_RANK.get(item["severity"], 0) >= threshold]
    report = {
        "schema_version": 1,
        "tool": "Genesis Sentinel",
        "mode": args.mode,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url if args.mode == "live" else "sandbox://127.0.0.1",
        "fail_on": args.fail_on,
        "pass": not gate_findings and infrastructure_error is None,
        "summary": dict(Counter(item["severity"] for item in findings)),
        "route_count": len(route_results),
        "findings": findings,
        "routes": route_results,
    }

    report_path = artifact_root / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_html_report(report, artifact_root / "report.html")

    finding_dir = artifact_root / "findings"
    finding_dir.mkdir(parents=True, exist_ok=True)
    for item in findings:
        (finding_dir / f"{item['id']}.json").write_text(
            json.dumps(item, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(json.dumps(
        {
            "pass": report["pass"],
            "mode": report["mode"],
            "routes": report["route_count"],
            "summary": report["summary"],
            "gate_findings": len(gate_findings),
            "report": str(report_path.relative_to(ROOT)),
        },
        indent=2,
    ))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
