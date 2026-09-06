"""Agent Additional Prompt (AAP) Middleware example.

The middleware initializes one Agent Thread from its current private messages.
Its checkpointed private marker makes later Runs on the same Thread continue the
existing conversation without rebuilding or re-appending the initial prompt.
"""

from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import NotRequired, TypedDict

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.messages.utils import convert_to_messages, convert_to_openai_messages
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from agent_shell.middleware_packages.messages import mutable_request_messages


async def build_agent_additional_prompt_messages(
    state: dict[str, Any],
    runtime: Runtime[Any],
    request_messages: list[dict[str, Any]],
    backend: Any,
) -> list[dict[str, Any]]:
    """Customize the initial private messages for this Agent Thread."""

    del state, runtime, backend
    return mutable_request_messages(request_messages)


class AgentAdditionalPromptMiddleware(AgentMiddleware):
    def __init__(self, *, backend: Any, scope: str, package_id: str) -> None:
        super().__init__()
        self._backend = backend
        self._scope = scope
        self._name = f"AgentAdditionalPromptMiddleware_{package_id}"
        self._state_key = (
            "_agent_shell_aap_" + package_id.replace("-", "_") + "_initialized"
        )
        self.state_schema = TypedDict(
            f"AgentAdditionalPromptState_{package_id.replace('-', '_')}",
            {
                self._state_key: NotRequired[
                    Annotated[bool, PrivateStateAttr]
                ]
            },
        )

    @property
    def name(self) -> str:
        return self._name

    async def abefore_agent(
        self,
        state: dict[str, Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        if state.get(self._state_key):
            return None
        request_messages = mutable_request_messages(
            convert_to_openai_messages(state.get("messages", []))
        )
        messages = await build_agent_additional_prompt_messages(
            state,
            runtime,
            request_messages,
            self._backend,
        )
        return {
            "messages": Overwrite(convert_to_messages(messages)),
            self._state_key: True,
        }


def create_middleware(
    backend: Any,
    scope: str,
    package_id: str,
    **_available: Any,
) -> AgentMiddleware:
    del scope
    return AgentAdditionalPromptMiddleware(
        backend=backend,
        scope="agent",
        package_id=package_id,
    )
