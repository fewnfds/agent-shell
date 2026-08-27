from __future__ import annotations

import importlib
import inspect
from types import SimpleNamespace

from .support import *
from .support import _build_chat_model
from langchain_core.messages import AIMessageChunk
from agent_shell.model_provider_contracts import _SETTINGS_BY_PROVIDER
from agent_shell.provider_integrations import bundled_provider_integrations
from agent_shell.runtime import agent_builder
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.model_response import ModelResponse, finish_reason_category
from agent_shell.runtime.output_stream import MainAgentMediaBlock, OutputEvent
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile

@pytest.mark.parametrize(
    ("reason", "category"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        ("tool_calls", "tool_calls"),
        ("vendor-specific", "unknown"),
        (None, "unknown"),
    ],
)
def test_finish_reason_categories_keep_unknown_provider_values_explicit(
    reason: str | None, category: str
) -> None:
    assert finish_reason_category(reason) == category


def test_workflow_run_completion_does_not_inherit_an_agent_finish_reason() -> None:
    normalizer = SimpleNamespace(
        usage={},
        finish_reason="length",
        finish_reason_source="response_metadata.finish_reason",
    )
    workflow = RunExecution(
        graph=None,
        input_state={},
        rectifier=None,
        normalizer=normalizer,
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )
    assert workflow.finish_reason == "stop"
    assert workflow.finish_reason_source is None


def test_workflow_execution_closes_v3_stream_and_cancels_children_when_cancelled() -> None:
    async def scenario() -> tuple[bool, bool]:
        class BlockingRun:
            def __init__(self) -> None:
                self.pulling = asyncio.Event()
                self.exited = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                self.exited = True

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.pulling.set()
                await asyncio.Event().wait()
                raise StopAsyncIteration

            async def output(self):
                return None

        class Graph:
            def __init__(self, run: BlockingRun) -> None:
                self.run = run

            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert version == "v3"
                assert config == {"recursion_limit": 1_000_000}
                assert transformers
                return self.run

        output = output_renderer({"lifecycle": "{{message}}"})
        run = BlockingRun()
        children_cancelled = False

        async def cancel_children() -> None:
            nonlocal children_cancelled
            children_cancelled = True

        execution = RunExecution(
            graph=Graph(run),
            input_state={"messages": [{"role": "user", "content": "cancel me"}]},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            cancel_background_children=cancel_children,
        )
        stream = execution.stream_text()
        assert await anext(stream) == "running"
        pending = asyncio.create_task(anext(stream))
        await asyncio.wait_for(run.pulling.wait(), timeout=1)
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        return run.exited, children_cancelled

    assert asyncio.run(scenario()) == (True, True)


def test_workflow_execution_cancel_converges_run_before_stream_cleanup(
    tmp_path,
) -> None:
    async def scenario() -> tuple[str, str, bool]:
        lifecycle = WorkflowLifecycleService(
            SQLiteDatabase(tmp_path / "cancel.sqlite3"),
            store_database=SQLiteFile(tmp_path / "cancel-workflow-store.sqlite3"),
        )
        await lifecycle.start()
        lifecycle_id = await lifecycle.create(
            [{"role": "user", "content": "cancel"}],
            request_id="cancel-request",
            run_id="cancel-run",
            checkpoint_thread_id=None,
            workflow_id="cancel-workflow",
            workflow_name="Cancel Workflow",
        )
        lifecycle.start_run("cancel-run")
        children_cancelled = False

        async def cancel_children() -> None:
            nonlocal children_cancelled
            children_cancelled = True

        execution = RunExecution(
            graph=None,
            input_state={},
            rectifier=None,
            normalizer=SimpleNamespace(usage={}),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            context=WorkflowRuntimeContext.for_run(
                request_id="cancel-request",
                lifecycle_id=lifecycle_id,
                run_id="cancel-run",
                workflow={
                    "id": "cancel-workflow",
                    "name": "Cancel Workflow",
                },
            ),
            lifecycle_service=lifecycle,
            lifecycle_id=lifecycle_id,
            owns_lifecycle=True,
            cancel_background_children=cancel_children,
        )
        try:
            await execution.cancel()
            await execution.cancel()
            run = lifecycle.history.get_run("cancel-run")
            parent = await lifecycle.record(lifecycle_id)
            assert run is not None
            assert parent is not None
            return (
                str(run["status"]),
                str(parent["parent_status"]),
                children_cancelled,
            )
        finally:
            await lifecycle.close()

    assert asyncio.run(scenario()) == ("cancelled", "cancelled", True)


def test_execution_timeout_excludes_time_waiting_for_stream_consumer() -> None:
    async def scenario() -> bool:
        execution = RunExecution(
            graph=EventGraph(
                [message_envelope(AIMessageChunk(content="ready", id="message-1"))]
            ),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(
                OutputProjector(output_renderer())
            ),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            execution_timeout_seconds=0.01,
        )
        stream = execution.stream_text()
        assert await anext(stream) == "ready"
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            return False
        _remaining = [part async for part in stream]
        return True

    assert asyncio.run(scenario()) is True


def test_agent_execution_times_out_and_closes_v3_stream(monkeypatch, tmp_path) -> None:
    async def scenario() -> tuple[bool, dict[str, object], list[dict[str, object]]]:
        class BlockingRun:
            def __init__(self) -> None:
                self.exited = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                self.exited = True

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.Event().wait()
                raise StopAsyncIteration

            async def output(self):
                return None

        class Graph:
            def __init__(self, run: BlockingRun) -> None:
                self.run = run

            async def astream_events(
                self,
                _input,
                *,
                config: dict,
                version: str,
                transformers: tuple = (),
                context=None,
            ):
                assert config["recursion_limit"] == 1_000_000
                assert len(config["callbacks"]) == 1
                config["callbacks"][0].on_tool_start(
                    {"name": "waiting-tool"},
                    "",
                    run_id="waiting-tool-run",
                )
                assert context is not None
                assert version == "v3"
                assert transformers
                return self.run

        output = output_renderer({"lifecycle": "{{message}}"})
        run = BlockingRun()
        lifecycle = WorkflowLifecycleService(
            SQLiteDatabase(tmp_path / "timeout.sqlite3"),
            store_database=SQLiteFile(tmp_path / "timeout-workflow-store.sqlite3"),
        )
        await lifecycle.start()
        try:
            lifecycle_id = await lifecycle.create(
                [{"role": "user", "content": "wait"}],
                request_id="timeout-request",
                run_id="timeout-run",
                checkpoint_thread_id="timeout-thread",
                workflow_id="timeout-workflow",
                workflow_name="Timeout Workflow",
            )
            context = WorkflowRuntimeContext.for_run(
                request_id="timeout-request",
                lifecycle_id=lifecycle_id,
                run_id="timeout-run",
                checkpoint_thread_id="timeout-thread",
                workflow={"id": "timeout-workflow", "name": "Timeout Workflow"},
            )
            execution = RunExecution(
                graph=Graph(run),
                input_state={"messages": [{"role": "user", "content": "wait"}]},
                rectifier=OutputEventRectifier(OutputProjector(output)),
                normalizer=V3EventNormalizer("Main Agent"),
                middleware_runtime=noop_middleware_runtime(),
                media_response=noop_media_response(),
                execution_timeout_seconds=0.01,
                lifecycle_service=lifecycle,
                lifecycle_id=lifecycle_id,
                owns_lifecycle=True,
                context=context,
            )
            stream = execution.stream_text()
            assert await anext(stream) == "running"
            assert await anext(stream) == "failed"
            with pytest.raises(AgentRuntimeError) as captured:
                await anext(stream)
            assert captured.value.code == "execution_timeout"
            record = lifecycle.history.get_run("timeout-run")
            assert record is not None
            return run.exited, record, lifecycle.events(lifecycle_id)
        finally:
            await lifecycle.close()

    closed, record, events = asyncio.run(scenario())
    assert closed is True
    assert record["status"] == "failed"
    assert record["error_code"] == "execution_timeout"
    tool_events = [event for event in events if event["subject_kind"] == "tool"]
    assert [event["phase"] for event in tool_events] == ["started", "failed"]
    assert tool_events[-1]["error_code"] == "execution_timeout"


def test_successful_execution_does_not_add_a_runtime_diagnostic() -> None:
    async def scenario() -> list[str]:
        class EmptyRun:
            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def output(self):
                return {"messages": [], "shared_vars": {"result": "ok"}}

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert version == "v3"
                assert transformers
                return EmptyRun()

        class RecordingDiagnostics:
            def __init__(self) -> None:
                self.codes: list[str] = []

            def observation_error(self, _exc, *, code: str, **_kwargs) -> None:
                self.codes.append(code)

            def runtime_error(self, _exc, *, code: str, **_kwargs) -> None:
                self.codes.append(code)

        diagnostics = RecordingDiagnostics()
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [], "shared_vars": {}},
            rectifier=OutputEventRectifier(OutputProjector(output_renderer())),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
        )

        await execution.run()
        assert execution.final_state == {
            "messages": [],
            "shared_vars": {"result": "ok"},
        }
        return diagnostics.codes

    assert asyncio.run(scenario()) == []


def test_silent_execution_skips_public_projectors_observers_and_media() -> None:
    async def scenario() -> dict[str, object] | None:
        class OneEnvelopeRun:
            def __init__(self) -> None:
                self._sent = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._sent:
                    raise StopAsyncIteration
                self._sent = True
                return object()

            async def output(self):
                return {"shared_vars": {"result": "ok"}}

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert version == "v3"
                assert transformers
                return OneEnvelopeRun()

        class SilentNormalizer:
            usage: dict[str, int] = {}
            finish_reason = "stop"
            finish_reason_source = None
            last_main_agent_response = None

            def lifecycle(self, phase: str, **_kwargs) -> OutputEvent:
                return OutputEvent(
                    event_type="lifecycle",
                    phase=phase,
                    sequence=1,
                    timestamp="now",
                )

            def feed(self, _envelope):
                return [
                    MainAgentMediaBlock(
                        timestamp="now",
                        namespace="root",
                        agent_name="Agent",
                        node="agent",
                        message_id="message-1",
                        block_index=0,
                        content={"type": "image", "url": "private"},
                    )
                ]

            def close_main_agent_messages(self) -> None:
                return None

            def abort_main_agent_messages(self) -> None:
                return None

            def media_notification(self, *_args):
                raise AssertionError("silent execution must not create media output")

        class ExplodingProjector:
            def enabled(self, _event) -> bool:
                raise AssertionError("silent execution must not inspect output policy")

            def render(self, _event) -> str:
                raise AssertionError("silent execution must not render output")

        class ExplodingMediaResponse:
            async def project(self, _event):
                raise AssertionError("silent execution must not persist response media")

            @property
            def assets(self):
                return []

            def structured_blocks(self, _response):
                return []

        def observe(_event) -> None:
            raise AssertionError("silent execution must not call public observers")

        execution = RunExecution(
            graph=Graph(),
            input_state={"shared_vars": {}},
            rectifier=OutputEventRectifier(ExplodingProjector()),  # type: ignore[arg-type]
            normalizer=SilentNormalizer(),  # type: ignore[arg-type]
            middleware_runtime=noop_middleware_runtime(),
            media_response=ExplodingMediaResponse(),  # type: ignore[arg-type]
            event_observers=(observe,),
            public_output=False,
        )

        await execution.execute()
        return execution.final_state

    assert asyncio.run(scenario()) == {"shared_vars": {"result": "ok"}}

def test_graph_recursion_failure_uses_step_limit_error() -> None:
    async def scenario() -> str:
        from langgraph.errors import GraphRecursionError

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert transformers
                raise GraphRecursionError("private graph state")

        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "loop"}]},
            rectifier=OutputEventRectifier(
                OutputProjector(output_renderer())
            ),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        with pytest.raises(AgentRuntimeError) as captured:
            await anext(execution.stream_text())
        assert "private graph state" not in captured.value.safe_message
        return captured.value.code

    assert asyncio.run(scenario()) == "execution_step_limit"

def test_runtime_boundaries_classify_provider_and_tool_failures() -> None:
    def fail(_request):
        raise RuntimeError("private failure details")

    with pytest.raises(AgentRuntimeError) as tool_error:
        ToolErrorBoundaryMiddleware().wrap_tool_call(None, fail)
    with pytest.raises(AgentRuntimeError) as provider_error:
        ProviderErrorBoundaryMiddleware().wrap_model_call(None, fail)

    assert tool_error.value.code == "tool_execution_failed"
    assert provider_error.value.code == "provider_request_failed"
    assert "private failure details" not in tool_error.value.safe_message
    assert provider_error.value.safe_message == "The model provider request failed."


def test_provider_error_boundary_preserves_status_and_redacts_message() -> None:
    class RateLimitError(RuntimeError):
        status_code = 429

    def fail(_request):
        raise RateLimitError(
            "quota exceeded at C:\\private\\provider.log with Bearer token-value"
        )

    with pytest.raises(AgentRuntimeError) as captured:
        ProviderErrorBoundaryMiddleware().wrap_model_call(None, fail)

    assert captured.value.status_code == 429
    assert captured.value.safe_message == "The model provider request failed."
    assert isinstance(captured.value.__cause__, RateLimitError)

def test_tool_error_boundary_preserves_successful_result() -> None:
    result = ToolMessage(
        content="x" * 1_000_100,
        tool_call_id="call-large",
        name="large",
    )

    returned = ToolErrorBoundaryMiddleware().wrap_tool_call(None, lambda _request: result)

    assert returned is result
    assert returned.content == result.content

def test_unclassified_graph_failure_is_not_mislabeled_as_provider() -> None:
    async def scenario() -> tuple[str, str]:
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

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert transformers
                raise RuntimeError("private middleware or graph details")

        output = output_renderer({"lifecycle": "{{message}}"})
        diagnostics = RecordingDiagnostics()
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "fail"}]},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
        )
        stream = execution.stream_text()
        assert await anext(stream) == "running"
        assert await anext(stream) == "failed"
        with pytest.raises(AgentRuntimeError) as captured:
            await anext(stream)
        assert "private middleware or graph details" not in captured.value.safe_message
        return captured.value.code, str(diagnostics.detail_exception)

    assert asyncio.run(scenario()) == (
        "agent_execution_failed",
        "private middleware or graph details",
    )

def test_classified_graph_failure_emits_matching_lifecycle_error() -> None:
    async def scenario() -> str:
        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert transformers
                raise AgentRuntimeError(
                    "provider_request_failed",
                    "The provider request failed.",
                    status_code=502,
                )

        output = output_renderer({"lifecycle": "{{phase}}:{{error_code}}"})
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "fail"}]},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        stream = execution.stream_text()
        assert await anext(stream) == "start:"
        assert await anext(stream) == "error:provider_request_failed"
        with pytest.raises(AgentRuntimeError) as captured:
            await anext(stream)
        return captured.value.code

    assert asyncio.run(scenario()) == "provider_request_failed"
