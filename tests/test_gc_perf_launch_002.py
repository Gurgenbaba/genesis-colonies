"""GC-PERF-LAUNCH-002 — changelog cache must survive ordinary deploys."""

from __future__ import annotations

import time

from game import player_changelog as changelog


def test_fresh_disk_cache_does_not_refetch_on_new_deploy(monkeypatch):
    now = int(time.time())
    cached = {
        "ok": True,
        "source": "github",
        "generated_at": now,
        "head_sha": "old-head-sha",
        "groups": [{"date": "2026-09-21", "entries": []}],
    }

    monkeypatch.setattr(changelog, "get_deploy_revision", lambda: "new-deploy-sha")
    monkeypatch.setattr(changelog, "_read_disk_cache", lambda: dict(cached))
    monkeypatch.setattr(
        changelog,
        "_fetch_github_history",
        lambda: (_ for _ in ()).throw(AssertionError("fresh cache must not refetch")),
    )
    changelog._MEMORY_CACHE["payload"] = None
    changelog._MEMORY_CACHE["expires_at"] = 0.0

    payload = changelog.get_player_changelog()

    assert payload["head_sha"] == "old-head-sha"
    assert changelog._MEMORY_CACHE["expires_at"] > time.time()


def test_force_refresh_still_bypasses_fresh_cache(monkeypatch):
    monkeypatch.setattr(changelog, "get_deploy_revision", lambda: "new-deploy-sha")
    monkeypatch.setattr(
        changelog,
        "_read_disk_cache",
        lambda: {
            "ok": True,
            "source": "github",
            "generated_at": int(time.time()),
            "head_sha": "old-head-sha",
            "groups": [],
        },
    )
    monkeypatch.setattr(changelog, "_fetch_github_history", lambda: [])
    monkeypatch.setattr(changelog, "_write_disk_cache", lambda payload: None)
    changelog._MEMORY_CACHE["payload"] = None
    changelog._MEMORY_CACHE["expires_at"] = 0.0

    payload = changelog.get_player_changelog(force_refresh=True)

    assert payload["head_sha"] == ""
