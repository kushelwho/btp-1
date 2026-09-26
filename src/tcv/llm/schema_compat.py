"""Make a Pydantic JSON schema acceptable to structured outputs.

Structured outputs support objects, arrays, enums, $ref/$defs, anyOf, and
string formats, and require ``additionalProperties: false`` on every object.
They do not support numeric or string-length constraints, patterns, or
complex array constraints. Those are stripped here — Pydantic still enforces
them when the response is validated client-side, so no constraint is lost.
"""

from __future__ import annotations

import copy
from typing import Any

_UNSUPPORTED = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern",
    "minItems", "maxItems", "uniqueItems", "prefixItems",
    "default", "title",
})


# Keys whose *children* are user-chosen names (field names, definition names),
# not schema keywords — a field called "title" must survive.
_NAME_MAPS = frozenset({"properties", "$defs", "definitions"})


def _walk(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _NAME_MAPS and isinstance(v, dict):
                out[k] = {name: _walk(sub) for name, sub in v.items()}
            elif k not in _UNSUPPORTED:
                out[k] = _walk(v)
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            props = out.get("properties", {})
            # Every property required: the model must emit each field explicitly;
            # optional fields are expressed as nullable (anyOf with null) instead.
            out["required"] = list(props.keys())
        return out
    if isinstance(node, list):
        return [_walk(v) for v in node]
    return node


def to_structured_output_schema(schema: dict) -> dict:
    return _walk(copy.deepcopy(schema))
