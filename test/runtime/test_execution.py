from __future__ import annotations

import importlib
import inspect

from .support import *
from .support import _build_chat_model
from langchain_core.messages import AIMessageChunk, ToolMessage
from agent_shell.model_provider_contracts import _SETTINGS_BY_PROVIDER
from agent_shell.provider_integrations import bundled_provider_integrations
from agent_shell.runtime import agent_builder
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity

def test_workflow_run_has_stable_openai_completion_reason() -> None:
    execution = RunExecution(
        graph=None,
        input_state={},
        response_scheduler=None,
        middleware_runtimes=(noop_middleware_runtime(),),
        media_response=noop_media_response(),
    )
    assert execution.finish_reason == "stop"


def test_runtime_diagnostic_context_does_not_invent_workflow_identity() -> None:
    without_identity = RunExecution(
        graph=None,
        input_state={},
        response_scheduler=None,
        middleware_runtimes=(noop_middleware_runtime(),),
        media_response=noop_media_response(),
        request_id="request-1",
        public_model="Public model",
    ).diagnostic_context()
    workflow_identity = WorkflowRunIdentity(
        request_id="request-2",
        lifecycle_id="lifecycle-2",
        run_id="run-2",
        workflow_id="workflow-2",
        workflow_name="Workflow Two",
    )
    with_identity = RunExecution(
        graph=None,
        input_state={},
        response_scheduler=None,
        middleware_runtimes=(noop_middleware_runtime(),),
        media_response=noop_media_response(),
        identity=workflow_identity,
    ).diagnostic_context()

    assert without_identity.subject_kind == ""
    assert without_identity.subject_id == ""
    assert without_identity.subject_name == ""
    assert with_identity.subject_kind == "workflow"
    assert with_identity.subject_id == "workflow-2"
    assert with_identity.subject_name == "Workflow Two"


def test_workflow_execution_closes_v3_stream_when_cancelled() -> None:
    async def scenario() -> bool:
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
                assert config == {}
                assert transformers
                return self.run

        output = output_renderer({"lifecycle": "{{message}}"})
        run = BlockingRun()
        projector = OutputProjector(output, run_output=run_output_renderer())

        execution = RunExecution(
            graph=Graph(run),
            input_state={"messages": [{"role": "user", "content": "cancel me"}]},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
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
        return run.exited

    assert asyncio.run(scenario()) is True


def test_scheduler_deadline_wakes_while_upstream_iterator_is_quiet() -> None:
    async def scenario() -> tuple[str, bool]:
        class QuietRun:
            def __init__(self) -> None:
                self.pulling = asyncio.Event()
                self.exited = False
                self.sent = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                self.exited = True

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.sent:
                    self.sent = True
                    return message_envelope(
                        AIMessageChunk(content="ready", id="message-1")
                    )
                self.pulling.set()
                await asyncio.Event().wait()
                raise StopAsyncIteration

            async def output(self):
                return None

        class Graph:
            def __init__(self, run: QuietRun) -> None:
                self.run = run

            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                return self.run

        payload = ResponseStreamPolicy().model_dump(mode="json")
        payload["send_interval_seconds"] = 0.1
        run = QuietRun()
        projector = OutputProjector(
            output_renderer(
                {
                    "lifecycle": "{{message}}",
                    "assistant_text": "{{message}}",
                }
            ),
            run_output=run_output_renderer("{{status}}"),
        )
        execution = RunExecution(
            graph=Graph(run),
            input_state={},
            response_scheduler=response_scheduler(
                projector,
                ResponseStreamPolicy.model_validate(payload),
            ),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
            origin_resolver=event_origin_resolver(),
        )
        stream = execution.stream_text()
        assert await anext(stream) == "running"
        notice_task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(run.pulling.wait(), timeout=1)
        notice = await asyncio.wait_for(notice_task, timeout=2)
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        return notice, run.exited

    assert asyncio.run(scenario()) == (
        "ready",
        True,
    )


def test_lifecycle_response_consumer_wakes_for_registered_spawned_run_output() -> None:
    async def scenario() -> str:
        class QuietRun:
            def __init__(self) -> None:
                self.pulling = asyncio.Event()

            async def __aenter__(self):
                return self

            async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
                return None

            def __aiter__(self):
                return self

            async def __anext__(self):
                self.pulling.set()
                await asyncio.Event().wait()
                raise StopAsyncIteration

            async def output(self):
                return None

        class QuietGraph:
            def __init__(self, run: QuietRun) -> None:
                self.run = run

            async def astream_events(self, _input, **_kwargs):
                return self.run

        lifecycle_id = "shared-lifecycle"
        entry_run_id = "entry-run"
        entry_graph_id = "entry-workflow"
        spawned_run_id = "spawned-run"
        spawned_workflow_id = "spawned-workflow"
        output = OutputProjector(output_renderer())
        scheduler = LifecycleResponseScheduler(
            ResponseStreamPolicy.model_validate({
                "idle_timeout_seconds": 0.01,
                "max_batch_kb": 64,
                "send_interval_seconds": 0,
            }),
            lifecycle_id=lifecycle_id,
        )
        quiet_run = QuietRun()
        entry_identity = WorkflowRunIdentity(
            request_id="request",
            lifecycle_id=lifecycle_id,
            run_id=entry_run_id,
            workflow_id=entry_graph_id,
            workflow_name="Entry Workflow",
        )
        spawned_identity = WorkflowRunIdentity(
            request_id="request",
            lifecycle_id=lifecycle_id,
            run_id=spawned_run_id,
            caller_run_id=entry_run_id,
            workflow_id=spawned_workflow_id,
            workflow_name="Spawned Workflow",
        )
        entry = RunExecution(
            graph=QuietGraph(quiet_run),
            input_state={},
            response_scheduler=scheduler,
            event_output_projector=output,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
            identity=entry_identity,
            context=WorkflowRuntimeContext.for_run(identity=entry_identity),
        )
        spawned = RunExecution(
            graph=EventGraph(
                [
                    message_envelope(
                        AIMessageChunk(content="spawned-output", id="spawned-message"),
                        run_id="spawned-model-run",
                        agent_name="Spawned Agent",
                    )
                ]
            ),
            input_state={},
            response_scheduler=scheduler,
            event_output_projector=output,
            response_consumer=False,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
            origin_resolver=event_origin_resolver("Spawned Agent"),
            identity=spawned_identity,
            context=WorkflowRuntimeContext.for_run(identity=spawned_identity),
        )

        stream = entry.stream_text()
        notice_task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(quiet_run.pulling.wait(), timeout=1)
        await spawned.execute()
        notice = await asyncio.wait_for(notice_task, timeout=1)
        await stream.aclose()
        return notice

    assert asyncio.run(scenario()) == "spawned-output"


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

            async def aobservation_error(
                self, _exc, *, code: str, **_kwargs
            ) -> None:
                self.codes.append(code)

            async def aruntime_error(self, _exc, *, code: str, **_kwargs) -> None:
                self.codes.append(code)

        diagnostics = RecordingDiagnostics()
        projector = OutputProjector(output_renderer())
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [], "shared_vars": {}},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
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
                return {
                    "method": "custom",
                    "params": {"namespace": [], "timestamp": 1, "data": {"ok": True}},
                    "seq": 1,
                }

            async def output(self):
                return {"shared_vars": {"result": "ok"}}

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert version == "v3"
                assert transformers
                return OneEnvelopeRun()

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

        execution = RunExecution(
            graph=Graph(),
            input_state={"shared_vars": {}},
            response_scheduler=response_scheduler(ExplodingProjector()),  # type: ignore[arg-type]
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=ExplodingMediaResponse(),  # type: ignore[arg-type]
            origin_resolver=event_origin_resolver(),
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

        projector = OutputProjector(output_renderer())
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "loop"}]},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
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
    async def scenario() -> tuple[str, str, str, tuple[str, str, str]]:
        class RecordingDiagnostics:
            detail_exception: BaseException | None = None
            component = ""
            context = None

            async def aruntime_error(
                self,
                _exc,
                *,
                component: str,
                context,
                detail_exception: BaseException | None = None,
                **_kwargs,
            ) -> None:
                self.detail_exception = detail_exception
                self.component = component
                self.context = context

        class Graph:
            async def astream_events(
                self, _input, *, config: dict, version: str, transformers: tuple = ()
            ):
                assert transformers
                raise RuntimeError("private middleware or graph details")

        output = output_renderer({"lifecycle": "{{message}}"})
        diagnostics = RecordingDiagnostics()
        projector = OutputProjector(output, run_output=run_output_renderer())
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "fail"}]},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
            identity=AgentRunIdentity(
                request_id="request-agent",
                lifecycle_id="lifecycle-agent",
                run_id="run-agent",
                thread_id="thread-agent",
                main_agent_id="agent-1",
                main_agent_name="Agent One",
            ),
        )
        stream = execution.stream_text()
        assert await anext(stream) == "running"
        assert await anext(stream) == "failed"
        with pytest.raises(AgentRuntimeError) as captured:
            await anext(stream)
        assert "private middleware or graph details" not in captured.value.safe_message
        assert diagnostics.context is not None
        return (
            captured.value.code,
            str(diagnostics.detail_exception),
            diagnostics.component,
            (
                diagnostics.context.subject_kind,
                diagnostics.context.subject_id,
                diagnostics.context.subject_name,
            ),
        )

    assert asyncio.run(scenario()) == (
        "agent_execution_failed",
        "private middleware or graph details",
        "graph_runtime",
        ("agent", "agent-1", "Agent One"),
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
        projector = OutputProjector(
            output,
            run_output=run_output_renderer("{{phase}}:{{error_code}}"),
        )
        execution = RunExecution(
            graph=Graph(),
            input_state={"messages": [{"role": "user", "content": "fail"}]},
            response_scheduler=response_scheduler(projector),
            event_output_projector=projector,
            middleware_runtimes=(noop_middleware_runtime(),),
            media_response=noop_media_response(),
        )
        stream = execution.stream_text()
        assert await anext(stream) == "start:"
        assert await anext(stream) == "error:provider_request_failed"
        with pytest.raises(AgentRuntimeError) as captured:
            await anext(stream)
        return captured.value.code

    assert asyncio.run(scenario()) == "provider_request_failed"
