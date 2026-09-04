"""JSON transport contract for gameplay integers.

Python and PostgreSQL can hold integers far beyond JavaScript's IEEE-754 safe
integer range. JSON itself has no integer-width metadata, so emitting those
values as JSON numbers silently rounds them in browsers. Keep normal small
integers numeric for compatibility and emit only JS-unsafe integers as decimal
strings.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask.json.provider import DefaultJSONProvider

JS_SAFE_INTEGER_MAX = 9_007_199_254_740_991


def js_safe_json_value(value: Any) -> Any:
    """Recursively convert only JS-unsafe Python ints to decimal strings."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        if value > JS_SAFE_INTEGER_MAX or value < -JS_SAFE_INTEGER_MAX:
            return str(value)
        return value
    if isinstance(value, Mapping):
        return {key: js_safe_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [js_safe_json_value(item) for item in value]
    if isinstance(value, list):
        return [js_safe_json_value(item) for item in value]
    return value


class GenesisJSONProvider(DefaultJSONProvider):
    """Flask JSON provider with a lossless DB/Python -> browser int boundary."""

    def dumps(self, obj: Any, **kwargs: Any) -> str:
        return super().dumps(js_safe_json_value(obj), **kwargs)
