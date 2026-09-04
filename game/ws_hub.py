"""In-process WebSocket push hub.

Single gunicorn worker (Railway: 1 replica, 1 worker, SQLite single-writer) —
no Redis, no cross-process fan-out. Generic pub/sub keyed by an opaque
"topic" string so other stale-state systems (world boss HP, build queues,
shipyard) can register their own topic namespace later without touching hub
internals. Only the galaxy/asteroid path is wired to actually emit today.

Hard rule: never touch the DB from this module, and never call publish()
while the SQLite write mutex (game/db.py _SQLITE_WRITE_MUTEX) is held —
callers must publish only after their write transaction has committed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict

from .json_transport import js_safe_json_value, List, Set, Tuple

logger = logging.getLogger(__name__)

MAX_WS_CONNECTIONS = 2000

_registry_lock = threading.Lock()
_subscribers: Dict[str, Set["WSClient"]] = {}
_connection_count = 0

# Per-thread staging area: request-handling code (e.g. the fleet arrival
# handler) stages events while inside a write transaction; the caller drains
# and publishes them only after commit() has returned, outside the mutex.
_staged = threading.local()


class WSClient:
    __slots__ = ("ws", "player_id", "topics", "connected_at")

    def __init__(self, ws: Any, player_id: int):
        self.ws = ws
        self.player_id = player_id
        self.topics: Set[str] = set()
        self.connected_at = time.time()


def galaxy_topic(galaxy: int, system: int) -> str:
    return f"galaxy:{int(galaxy)}:{int(system)}"


def try_acquire_connection_slot() -> bool:
    """Soft cap on concurrent WS connections (guard under a single worker)."""
    global _connection_count
    with _registry_lock:
        if _connection_count >= MAX_WS_CONNECTIONS:
            return False
        _connection_count += 1
        return True


def release_connection_slot() -> None:
    global _connection_count
    with _registry_lock:
        _connection_count = max(0, _connection_count - 1)


def subscribe(client: "WSClient", topic: str) -> None:
    with _registry_lock:
        _subscribers.setdefault(topic, set()).add(client)
        client.topics.add(topic)


def unsubscribe_all(client: "WSClient") -> None:
    with _registry_lock:
        for topic in list(client.topics):
            bucket = _subscribers.get(topic)
            if bucket is not None:
                bucket.discard(client)
                if not bucket:
                    _subscribers.pop(topic, None)
        client.topics.clear()


def publish(topic: str, payload: Dict[str, Any]) -> int:
    """Fire-and-forget push. Caller must not hold the SQLite write mutex."""
    with _registry_lock:
        targets = list(_subscribers.get(topic, ()))
    if not targets:
        return 0
    msg = json.dumps(js_safe_json_value(payload), separators=(",", ":"))
    sent = 0
    dead: List["WSClient"] = []
    for client in targets:
        try:
            client.ws.send(msg)
            sent += 1
        except Exception:
            dead.append(client)
    for client in dead:
        unsubscribe_all(client)
    return sent


def stage_event(topic: str, payload: Dict[str, Any]) -> None:
    """Queue an event on the current thread, to be drained after commit()."""
    events: List[Tuple[str, Dict[str, Any]]] = getattr(_staged, "events", None)
    if events is None:
        events = []
        _staged.events = events
    events.append((topic, dict(payload)))


def drain_staged_events() -> List[Tuple[str, Dict[str, Any]]]:
    """Pop and return all events staged on the current thread."""
    events: List[Tuple[str, Dict[str, Any]]] = getattr(_staged, "events", None)
    if not events:
        _staged.events = []
        return []
    _staged.events = []
    return events


def publish_staged_events() -> int:
    """Drain this thread's staged events and publish each. Call only after
    commit() has returned (outside any write transaction/mutex)."""
    sent = 0
    for topic, payload in drain_staged_events():
        try:
            sent += publish(topic, payload)
        except Exception:
            logger.exception("ws_hub publish failed for topic=%s", topic)
    return sent
