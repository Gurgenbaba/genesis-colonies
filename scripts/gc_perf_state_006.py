from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "game/ranking.py",
        '''def get_player_score_cached(\n    player_id: int,\n    force_recompute: bool = False,\n    *,\n    read_only: bool = False,\n) -> Dict[str, int]:\n''',
        '''def get_player_score_cached(\n    player_id: int,\n    force_recompute: bool = False,\n    *,\n    read_only: bool = False,\n    conn=None,\n) -> Dict[str, int]:\n''',
        "score cached signature",
    )
    replace_once(
        "game/ranking.py",
        "        out = _to_legacy(refresh_player_score(pid))\n",
        "        out = _to_legacy(refresh_player_score(pid, conn=conn))\n",
        "score recompute connection",
    )
    replace_once(
        "game/ranking.py",
        "    row = get_player_score_row(pid, conn=None)\n",
        "    row = get_player_score_row(pid, conn=conn)\n",
        "score row connection",
    )
    replace_once(
        "game/models.py",
        '''def get_player_rank(player_id: int) -> Tuple[Optional[int], int]:\n    from .ranking import get_player_rank as _ranking_rank\n\n    return _ranking_rank(int(player_id))\n''',
        '''def get_player_rank(player_id: int, conn=None) -> Tuple[Optional[int], int]:\n    from .ranking import get_player_rank as _ranking_rank\n\n    return _ranking_rank(int(player_id), conn=conn)\n''',
        "models rank wrapper connection",
    )
    replace_once(
        "game/live_state.py",
        "        score_raw = get_player_score_cached(uid, read_only=True) or {\n",
        "        score_raw = get_player_score_cached(uid, read_only=True, conn=conn) or {\n",
        "probe score connection",
    )
    replace_once(
        "game/live_state.py",
        "        rank, total_players = get_player_rank(uid)\n",
        "        rank, total_players = get_player_rank(uid, conn=conn)\n",
        "probe rank connection",
    )


if __name__ == "__main__":
    main()
