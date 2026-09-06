from __future__ import annotations

from langchain_core.messages import AIMessage

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.runtime.response_presentation import PresentationFrame
from support import runtime_workflow_document

from .support import *


def test_execution_yields_each_completed_semantic_event_once() -> None:
    async def scenario() -> tuple[list[str], dict[str, int]]:
        output = output_renderer({
            "assistant_text": "[T]{{message}}[/T]",
            "reasoning": "[R]{{message}}[/R]",
            "custom": "[C]{{message}}[/C]",
        })
        events = [
            message_envelope(
                {"event": "message-start", "role": "ai", "id": "message-1"}
            ),
            message_envelope(
                {
                    "event": "content-block-start",
                    "index": 0,
                    "content": {"type": "reasoning", "reasoning": ""},
                }
            ),
            message_envelope(
                {
                    "event": "content-block-delta",
                    "index": 0,
                    "delta": {
                        "type": "reasoning-delta",
                        "reasoning": "partial",
                    },
                }
            ),
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 0,
                    "content": {"type": "reasoning", "reasoning": "thought"},
                }
            ),
            {
                "method": "custom",
                "params": {"namespace": [], "timestamp": 2, "data": "working"},
            },
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 1,
                    "content": {"type": "text", "text": "answer"},
                }
            ),
            message_envelope(
                {
                    "event": "message-finish",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 4,
                        "total_tokens": 6,
                    },
                }
            ),
        ]
        projector = OutputProjector(output)
        execution = RunExecution(
            graph=EventGraph(events),
            input_state={"messages": []},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            origin_resolver=event_origin_resolver(),
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
        )
        parts = [part async for part in execution.stream_text()]
        return parts, execution.usage

    parts, usage = asyncio.run(scenario())

    assert parts == [
        "[R]partial[/R]",
        "[C]working[/C][T]answer[/T]",
    ]
    assert usage == {"input_tokens": 2, "output_tokens": 4, "total_tokens": 6}


def test_execution_does_not_repeat_whole_ai_message_after_streamed_deltas() -> None:
    run_id = "model-duplicate-shape"
    events = [
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"},
            run_id=run_id,
        ),
        message_envelope({
            "event": "content-block-start",
            "index": 0,
            "content": {"type": "text", "text": ""},
        }, run_id=run_id),
        message_envelope({
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "once"},
        }, run_id=run_id),
        message_envelope({
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "once"},
        }, run_id=run_id),
        message_envelope(
            {"event": "message-finish", "usage": {}},
            run_id=run_id,
        ),
        message_envelope(AIMessage(content="once"), run_id=run_id),
    ]
    projector = OutputProjector(output_renderer())
    execution = RunExecution(
        graph=EventGraph(events),
        input_state={"messages": []},
        response_scheduler=response_scheduler(projector),
        event_output_projector=projector,
        origin_resolver=event_origin_resolver(),
        middleware_runtimes=(noop_middleware_runtime(),),
        media_response=noop_media_response(),
    )

    text, _usage = asyncio.run(execution.run())
    assert text == "once"


def test_execution_flushes_lifecycle_output_queued_after_content_finish() -> None:
    def output(event: dict[str, object], origin: dict[str, object]) -> str:
        return ""

    def run_output(event: dict[str, object], origin: dict[str, object]) -> str:
        return "started" if event["phase"] == "start" else "finished"

    payload = ResponseStreamPolicy().model_dump(mode="json")
    payload["send_interval_seconds"] = 0.01
    projector = OutputProjector(output, run_output=run_output)
    scheduler = response_scheduler(
        projector,
        ResponseStreamPolicy.model_validate(payload),
    )

    async def scenario() -> list[str]:
        execution = RunExecution(
            graph=EventGraph([]),
            input_state={"messages": []},
            response_scheduler=scheduler,
            event_output_projector=projector,
            origin_resolver=event_origin_resolver(),
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
        )
        return [part async for part in execution.stream_text()]

    assert asyncio.run(scenario()) == ["started", "finished"]


def test_non_string_lifecycle_output_stays_behind_the_runtime_error_boundary() -> None:
    async def scenario() -> None:
        projector = OutputProjector(lambda event, origin: event)
        execution = RunExecution(
            graph=EventGraph(
                [
                    {
                        "type": "event",
                        "seq": 1,
                        "method": "custom",
                        "params": {
                            "namespace": [],
                            "timestamp": 1,
                            "data": "custom",
                        },
                    }
                ]
            ),
            input_state={"messages": []},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            origin_resolver=event_origin_resolver(),
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
        )
        with pytest.raises(AgentRuntimeError) as captured:
            _ = [part async for part in execution.stream_text()]
        assert captured.value.code == "event_output.execution_failed"

    asyncio.run(scenario())


def test_unguarded_event_field_failure_keeps_the_original_diagnostic() -> None:
    async def scenario() -> tuple[str, BaseException | None]:
        class RecordingDiagnostics:
            detail_exception: BaseException | None = None

            async def aruntime_error(
                self,
                _exc,
                *,
                detail_exception: BaseException | None = None,
                **_kwargs,
            ) -> None:
                self.detail_exception = detail_exception

        def output(event: dict[str, object], origin: dict[str, object]) -> str:
            return str(event["tool_name"])

        diagnostics = RecordingDiagnostics()
        projector = OutputProjector(output)
        execution = RunExecution(
            graph=EventGraph(
                [
                    {
                        "type": "event",
                        "seq": 1,
                        "method": "custom",
                        "params": {
                            "namespace": [],
                            "timestamp": 1,
                            "data": "custom",
                        },
                    }
                ]
            ),
            input_state={"messages": []},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            origin_resolver=event_origin_resolver(),
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
        )
        with pytest.raises(AgentRuntimeError) as captured:
            _ = [part async for part in execution.stream_text()]
        return captured.value.code, diagnostics.detail_exception

    code, detail_exception = asyncio.run(scenario())

    assert code == "event_output.execution_failed"
    assert isinstance(detail_exception, KeyError)
