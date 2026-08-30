from __future__ import annotations

from langchain_core.messages import AIMessage

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.runtime.response_presentation import PresentationFrame
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile

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
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        parts = [part async for part in execution.stream_text()]
        return parts, execution.usage

    parts, usage = asyncio.run(scenario())

    assert parts == [
        "[R]partial[/R]",
        "[T]answer[/T][C]working[/C]",
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
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    text, _usage = asyncio.run(execution.run())
    assert text == "once"


def test_debug_event_stream_record_failure_does_not_replace_run_result(
    tmp_path,
    monkeypatch,
) -> None:
    class Diagnostics:
        def __init__(self) -> None:
            self.errors: list[dict[str, object]] = []

        def observation_error(self, exc, **kwargs) -> None:
            self.errors.append({"error": exc, **kwargs})

    async def scenario():
        lifecycle = WorkflowLifecycleService(
            SQLiteDatabase(tmp_path / "protocol-event-failure.sqlite3"),
            store_database=SQLiteFile(
                tmp_path / "protocol-event-failure-workflow-store.sqlite3"
            ),
        )
        await lifecycle.start()
        try:
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "debug"}],
                request_id="debug-event-request",
                run_id="debug-event-run",
                checkpoint_thread_id=None,
                workflow_id="debug-event-workflow",
                workflow_name="Debug Event Workflow",
            )

            def fail_record(*_args, **_kwargs) -> None:
                raise OSError("protocol event persistence unavailable")

            monkeypatch.setattr(lifecycle, "append_protocol_event", fail_record)
            diagnostics = Diagnostics()
            projector = OutputProjector(output_renderer({"custom": "{{message}}"}))
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
                                "data": "still-visible",
                            },
                        }
                    ]
                ),
                input_state={"messages": []},
                response_scheduler=response_scheduler(projector),
                event_output_projector=projector,
                origin_resolver=event_origin_resolver(),
                middleware_runtime=noop_middleware_runtime(),
                media_response=noop_media_response(),
                context=WorkflowRuntimeContext.for_run(
                    request_id="debug-event-request",
                    lifecycle_id=lifecycle_id,
                    run_id="debug-event-run",
                    checkpoint_thread_id=None,
                    workflow={
                        "id": "debug-event-workflow",
                        "name": "Debug Event Workflow",
                    },
                ),
                lifecycle_service=lifecycle,
                lifecycle_id=lifecycle_id,
                runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
                workflow_debug_capture_enabled=True,
            )
            parts = [part async for part in execution.stream_text()]
            return (
                parts,
                lifecycle.history.get_run("debug-event-run"),
                diagnostics.errors,
            )
        finally:
            await lifecycle.close()

    parts, run, errors = asyncio.run(scenario())

    assert parts == ["still-visible"]
    assert run is not None
    assert run["status"] == "completed"
    assert run["observation_status"] == "partial"
    assert errors[0]["code"] == "workflow_protocol_event_record_failed"


def test_execution_flushes_lifecycle_output_queued_after_content_finish() -> None:
    def output(event: dict[str, object], origin: dict[str, object]) -> str:
        return ""

    def run_output(event: dict[str, object], origin: dict[str, object]) -> str:
        return "started" if event["phase"] == "start" else "finished"

    payload = ResponseStreamPolicy().model_dump(mode="json")
    payload["queue"]["send_interval_seconds"] = 0.01
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
            middleware_runtime=noop_middleware_runtime(),
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
            middleware_runtime=noop_middleware_runtime(),
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

            def runtime_error(
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
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
        )
        with pytest.raises(AgentRuntimeError) as captured:
            _ = [part async for part in execution.stream_text()]
        return captured.value.code, diagnostics.detail_exception

    code, detail_exception = asyncio.run(scenario())

    assert code == "event_output.execution_failed"
    assert isinstance(detail_exception, KeyError)
