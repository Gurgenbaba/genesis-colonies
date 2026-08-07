"""
Shared provably-fair RNG helpers (HMAC-SHA256 seed commit / reveal).

Used by Case Battles and Space Lottery — single owner for seed hash + seeded Random.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any


def gen_server_seed(*, nbytes: int = 32) -> str:
    return secrets.token_hex(max(16, int(nbytes or 32)))


def hash_seed(server_seed: str) -> str:
    return hashlib.sha256(str(server_seed).encode("utf-8")).hexdigest()


def seeded_rng(server_seed: str, *parts: Any):
    """Deterministic random.Random from HMAC(server_seed, '|'.join(parts))."""
    import random

    msg = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hmac.new(str(server_seed).encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return random.Random(int(digest[:16], 16))


def uniform01(server_seed: str, *parts: Any) -> float:
    """Open unit interval sample in (0, 1) from seeded RNG."""
    rng = seeded_rng(server_seed, *parts)
    # Avoid exact 0/1 for crash formulas.
    u = rng.random()
    if u <= 0.0:
        u = 1e-12
    if u >= 1.0:
        u = 1.0 - 1e-12
    return float(u)
