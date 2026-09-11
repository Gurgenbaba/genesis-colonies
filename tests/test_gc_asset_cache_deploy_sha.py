from pathlib import Path


def test_asset_version_includes_deploy_sha(monkeypatch):
    import app

    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef1234567890")
    assert app.get_asset_version() == f"{Path('VERSION').read_text(encoding='utf-8').strip()}-abcdef123456"


def test_asset_version_falls_back_to_release_version(monkeypatch):
    import app

    for key in ("RAILWAY_GIT_COMMIT_SHA", "GC_GIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT"):
        monkeypatch.delenv(key, raising=False)
    assert app.get_asset_version() == Path('VERSION').read_text(encoding='utf-8').strip()
