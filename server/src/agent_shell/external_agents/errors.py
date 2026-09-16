"""Stable failure classification for External Agent runs."""

from __future__ import annotations

from pathlib import Path

from agent_shell.runtime.errors import AgentRuntimeError


def binary_unavailable(message: str, *, path: Path) -> AgentRuntimeError:
    return AgentRuntimeError(
        "external_agent_binary_unavailable",
        message,
        status_code=422,
        source_exception_type="MissingExternalAgentBinary",
        remote_traceback=f"expected binary path: {path}",
    )


def materialization_failed(message: str, *, path: Path) -> AgentRuntimeError:
    return AgentRuntimeError(
        "external_agent_materialization_failed",
        message,
        status_code=500,
        source_exception_type="ExternalAgentMaterializationError",
        remote_traceback=f"failed path: {path}",
    )


def conversation_busy(message: str) -> AgentRuntimeError:
    return AgentRuntimeError(
        "external_agent_conversation_busy",
        message,
        status_code=409,
    )


def conversation_invalid(message: str) -> AgentRuntimeError:
    return AgentRuntimeError(
        "external_agent_conversation_invalid",
        message,
        status_code=422,
    )


def system_prompt_changed(message: str) -> AgentRuntimeError:
    return AgentRuntimeError(
        "external_agent_system_prompt_changed",
        message,
        status_code=409,
    )


__all__ = [
    "binary_unavailable",
    "conversation_busy",
    "conversation_invalid",
    "materialization_failed",
    "system_prompt_changed",
]
