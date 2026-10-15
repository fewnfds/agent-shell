from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import PIIMiddleware


def materialize_pii_middleware(block: Mapping[str, Any]) -> tuple[PIIMiddleware, ...]:
    """Create fresh official middleware instances from validated component rules."""
    return tuple(PIIMiddleware(**rule) for rule in block["rules"])
