from pathlib import Path

path = Path("tests/test_ranking.py")
src = path.read_text(encoding="utf-8")

old = '''def _create_player(username: str) -> int:
    uname = f"{username}_{uuid.uuid4().int % 100_000_000:08d}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    return int(user["id"])
'''
new = '''def _create_player(username: str) -> int:
    last_err = ""
    for _ in range(32):
        uname = f"{username}_{uuid.uuid4().int % 100_000_000:08d}"
        ok, err, user = create_user(uname, "test-pass-123")
        if ok and user:
            _close_db()
            return int(user["id"])
        last_err = str(err or "")
        _close_db()
        if last_err != "name_policy_forbidden":
            break
    raise AssertionError(last_err or "create_user_failed")
'''
assert old in src, "_create_player helper anchor missing"
src = src.replace(old, new, 1)

# The earlier narrow workaround is no longer needed once the helper itself is policy-safe.
src = src.replace('        pid = _create_player(f"rankingrow_{i}")\n', '        pid = _create_player(f"join_{i}")\n', 1)

anchor = '''def _seed_scores(player_id: int, building: int, research: int) -> None:
'''
regression = '''def test_create_player_helper_retries_name_policy_collision(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    values = iter((1488, 2468))

    class _FakeUuid:
        def __init__(self, value: int):
            self.int = value

    monkeypatch.setattr(uuid, "uuid4", lambda: _FakeUuid(next(values)))
    pid = _create_player("ranking_helper")
    assert pid > 0


'''
assert anchor in src, "_seed_scores anchor missing"
if "test_create_player_helper_retries_name_policy_collision" not in src:
    src = src.replace(anchor, regression + anchor, 1)

path.write_text(src, encoding="utf-8")
