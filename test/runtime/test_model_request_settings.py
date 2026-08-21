from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent_shell.runtime.model_request_settings import (
    make_model_request_settings_middleware,
)


@dataclass(frozen=True)
class Request:
    tool_choice: object
    model_settings: dict[str, object] | None

    def override(self, **overrides: Any) -> "Request":
        return replace(self, **overrides)


def test_model_request_settings_preserve_defaults_and_merge_configured_keys() -> None:
    request = Request(
        tool_choice="middleware-default",
        model_settings={"existing": True, "shared": "old"},
    )
    middleware = make_model_request_settings_middleware(
        tool_choice=None,
        model_settings={"shared": "new", "configured": 1},
    )

    result = middleware.wrap_model_call(request, lambda prepared: prepared)

    assert result.tool_choice == "middleware-default"
    assert result.model_settings == {
        "existing": True,
        "shared": "new",
        "configured": 1,
    }

    empty_result = middleware.wrap_model_call(
        Request(tool_choice="middleware-default", model_settings=None),
        lambda prepared: prepared,
    )
    assert empty_result.model_settings == {"shared": "new", "configured": 1}
