#!/usr/bin/env python3
"""Evaluate a Genesis Sentinel raw report for CI gating.

The browser harness intentionally blocks third-party requests. Chromium emits a
bare console error (``Failed to load resource: net::ERR_FAILED``) for those
aborts without exposing the URL on the console message. Same-origin failures
are captured separately as ``request_failed`` / ``http_error`` findings.

A second browser-only noise class occurs during intentional PJAX navigation:
the page lifecycle cancels an in-flight same-origin ``fetch`` and Chromium
reports ``net::ERR_ABORTED``. This is not an HTTP failure and must not turn an
otherwise successful route journey red. The exception below is deliberately
narrow: request_failed + fetch + net::ERR_ABORTED + PJAX action only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
THRESHOLDS = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _is_pjax_navigation_abort(item: dict) -> bool:
    if item.get("kind") != "request_failed":
        return False
    details = item.get("details") or {}
    if not isinstance(details, dict):
        return False
    failure = str(details.get("failure") or "").strip()
    resource_type = str(details.get("resource_type") or "").strip().lower()
    action = str(item.get("action") or "").strip().upper()
    return (
        failure == "net::ERR_ABORTED"
        and resource_type == "fetch"
        and action.startswith("PJAX ")
    )


def is_scanner_noise(item: dict) -> bool:
    bare_blocked_resource = (
        item.get("kind") == "console_error"
        and str(item.get("problem") or "").strip()
        == "Failed to load resource: net::ERR_FAILED"
    )
    return bare_blocked_resource or _is_pjax_navigation_abort(item)


def evaluate(report: dict, fail_on: str) -> dict:
    findings = list(report.get("findings") or [])
    ignored = [item for item in findings if is_scanner_noise(item)]
    effective = [item for item in findings if not is_scanner_noise(item)]
    threshold = THRESHOLDS[fail_on]
    blockers = [
        item
        for item in effective
        if SEVERITY_RANK.get(str(item.get("severity") or ""), 0) >= threshold
    ]

    route_rows = list(report.get("routes") or [])
    bad_status = [
        row
        for row in route_rows
        if row.get("status") is not None and int(row.get("status")) >= 400
    ]

    passed = not blockers and not bad_status
    return {
        "schema_version": 1,
        "tool": "Genesis Sentinel Gate",
        "pass": passed,
        "fail_on": fail_on,
        "raw_summary": dict(Counter(str(x.get("severity") or "UNKNOWN") for x in findings)),
        "effective_summary": dict(Counter(str(x.get("severity") or "UNKNOWN") for x in effective)),
        "ignored_scanner_noise": len(ignored),
        "route_count": len(route_rows),
        "bad_status_count": len(bad_status),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "bad_status": bad_status,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate a Genesis Sentinel report")
    parser.add_argument("report", nargs="?", default="artifacts/browser/report.json")
    parser.add_argument("--fail-on", choices=tuple(THRESHOLDS), default="high")
    parser.add_argument(
        "--output",
        default=None,
        help="Gate JSON path. Defaults to gate.json beside the input report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    if not report_path.is_file():
        print(f"FAIL: Sentinel report missing: {report_path}")
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    gate = evaluate(report, args.fail_on)
    output = Path(args.output) if args.output else report_path.with_name("gate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(
        {
            "pass": gate["pass"],
            "routes": gate["route_count"],
            "raw_summary": gate["raw_summary"],
            "effective_summary": gate["effective_summary"],
            "ignored_scanner_noise": gate["ignored_scanner_noise"],
            "blockers": gate["blocker_count"],
            "bad_status": gate["bad_status_count"],
            "gate": str(output),
        },
        indent=2,
    ))
    return 0 if gate["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
