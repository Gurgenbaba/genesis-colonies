"""Optional write-TX context for provenance / diagnostics (GC-PROD-SQLITE-STALL-001B).

Product paths may push a short-lived context around BEGIN IMMEDIATE work.
Harness sitecustomize reads ``current()`` — no-op when unused.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator

_TLS = threading.local()


def push(**kwargs: Any) -> None:
    stack = getattr(_TLS, "stack", None)
    if stack is None:
        stack = []
        _TLS.stack = stack
    stack.append({k: v for k, v in kwargs.items() if v is not None})


def pop() -> None:
    stack = getattr(_TLS, "stack", None)
    if stack:
        stack.pop()


def current() -> Dict[str, Any]:
    stack = getattr(_TLS, "stack", None)
    if not stack:
        return {}
    return dict(stack[-1])


@contextmanager
def tx_context(**kwargs: Any) -> Iterator[None]:
    push(**kwargs)
    try:
        yield
    finally:
        pop()
