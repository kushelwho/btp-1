"""The data structures are frozen at the end of Phase 1.

This pins a fingerprint of every exported schema (fields, types, validation
constraints, enum values). Any change fails here on purpose. To change a
schema after the freeze: get the team's agreement, update architecture.md,
bump SCHEMA_VERSION, note it in checklist.md, then update FROZEN below.
"""

import enum
import hashlib
import json

from pydantic import BaseModel

import tcv.schemas as S

FROZEN = {"1.0": "76caccbf784f63ab2c8978d596f784dd8bb30b70b5b7eccd18102358c4692f56"}


def fingerprint() -> str:
    parts = {}
    for name in sorted(S.__all__):
        obj = getattr(S, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            parts[name] = obj.model_json_schema()
        elif isinstance(obj, type) and issubclass(obj, enum.Enum):
            parts[name] = [m.value for m in obj]
    parts["PASSING"] = sorted(k.value for k in S.PASSING)
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def test_schemas_match_the_frozen_version():
    assert S.SCHEMA_VERSION in FROZEN, f"no frozen fingerprint recorded for SCHEMA_VERSION {S.SCHEMA_VERSION}"
    assert fingerprint() == FROZEN[S.SCHEMA_VERSION], (
        "the data structures changed after the Phase 1 freeze — see this file's docstring")
