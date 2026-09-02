from scripts.browser_report import evaluate, is_scanner_noise


def _finding(*, action="PJAX /galaxy?view=command_map", failure="net::ERR_ABORTED", resource_type="fetch"):
    return {
        "severity": "HIGH",
        "kind": "request_failed",
        "page": "/galaxy?view=command_map",
        "action": action,
        "problem": "Request failed: /api/fleet/state?planet_id=2",
        "details": {
            "url": "http://127.0.0.1:55179/api/fleet/state?planet_id=2",
            "resource_type": resource_type,
            "failure": failure,
        },
    }


def test_pjax_cancelled_fetch_is_scanner_noise():
    assert is_scanner_noise(_finding()) is True


def test_non_pjax_abort_is_not_ignored():
    assert is_scanner_noise(_finding(action="click fleet tab")) is False


def test_non_fetch_abort_is_not_ignored():
    assert is_scanner_noise(_finding(resource_type="document")) is False


def test_non_abort_request_failure_is_not_ignored():
    assert is_scanner_noise(_finding(failure="net::ERR_CONNECTION_RESET")) is False


def test_gate_passes_when_only_high_is_pjax_cancelled_fetch():
    report = {
        "findings": [_finding()],
        "routes": [{"path": "/galaxy?view=command_map", "status": 200}],
    }
    gate = evaluate(report, "high")
    assert gate["pass"] is True
    assert gate["ignored_scanner_noise"] == 1
    assert gate["blocker_count"] == 0
    assert gate["bad_status_count"] == 0


def test_http_or_real_high_still_blocks():
    real = _finding(failure="net::ERR_CONNECTION_RESET")
    report = {
        "findings": [real],
        "routes": [{"path": "/galaxy?view=command_map", "status": 500}],
    }
    gate = evaluate(report, "high")
    assert gate["pass"] is False
    assert gate["blocker_count"] == 1
    assert gate["bad_status_count"] == 1
