from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langgraph.runtime import Runtime

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.task_dispatcher import (
    TaskDispatcherCallable,
    TaskDispatcherError,
    TaskDispatcherResult,
    run_task_dispatcher,
)


def _run(dispatch: TaskDispatcherCallable) -> TaskDispatcherResult:
    return asyncio.run(
        run_task_dispatcher(
            dispatch,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=Runtime(context=WorkflowRuntimeContext()),
            allowed_dispatch_keys={"city"},
        )
    )


def _result(*, payload: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    return {
        "tasks": [
            {
                "task_id": "city:1",
                "dispatch_key": "city",
                "payload": payload,
            }
        ],
        "update": update,
    }


def test_dispatcher_accepts_every_declared_workflow_state_channel() -> None:
    async def dispatch(state, runtime):
        return _result(
            payload={},
            update={
                "shared_vars": {"planned": True},
                "agent_invocations": {},
                "files": {},
            },
        )

    result = _run(dispatch)

    assert result.update == {
        "shared_vars": {"planned": True},
        "agent_invocations": {},
        "files": {},
    }


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"value": float("nan")}, id="nan"),
        pytest.param({"value": float("inf")}, id="positive-infinity"),
        pytest.param({"value": float("-inf")}, id="negative-infinity"),
    ],
)
def test_dispatcher_rejects_non_finite_payload_numbers(
    payload: dict[str, Any],
) -> None:
    async def dispatch(state, runtime):
        return _result(payload=payload, update={})

    with pytest.raises(TaskDispatcherError):
        _run(dispatch)


@pytest.mark.parametrize(
    "update",
    [
        pytest.param({"shared_vars": [1]}, id="shared-vars-shape"),
        pytest.param(
            {"shared_vars": {"value": object()}},
            id="shared-vars-python-object",
        ),
        pytest.param(
            {"agent_invocations": {"invalid": {}}},
            id="agent-invocation-shape",
        ),
    ],
)
def test_dispatcher_rejects_invalid_declared_channel_values(
    update: dict[str, Any],
) -> None:
    async def dispatch(state, runtime):
        return _result(payload={}, update=update)

    with pytest.raises(TaskDispatcherError):
        _run(dispatch)
