from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/promote-u2-after-dev.yml")


def test_u2_promotion_is_dev_success_gated_and_fast_forward_only():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.state == 'success'" in text
    assert "github.event.context == 'Genesis-Colonies - genesis-colonies'" in text
    assert 'main_sha="$(git rev-parse origin/main)"' in text
    assert 'if [[ "$target_sha" != "$main_sha" ]]' in text
    assert 'merge_base="$(git merge-base "$u2_sha" "$target_sha")"' in text
    assert 'if [[ "$merge_base" != "$u2_sha" ]]' in text
    assert 'git push origin "$target_sha:refs/heads/u2/staging-runtime"' in text
    assert "--force" not in text
    assert "git push -f" not in text
