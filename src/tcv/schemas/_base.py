"""Shared base for every boundary type.

Components exchange validated, immutable objects — never dicts. An unknown
field is a bug, not data, so it is rejected rather than silently kept.
"""

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )
