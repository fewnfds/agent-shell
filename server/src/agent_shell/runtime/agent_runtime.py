from __future__ import annotations

import asyncio
import warnings
from copy import deepcopy
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from agent_shell.contracts import (
    CheckpointerBlock,
    CheckpointDurability,
    FilesystemBlock,
    ResponseStreamSchedulingBlock,
)
from agent_shell.runtime.agent_builder import AgentBuilder, BuiltAgent
from agent_shell.runtime.capabilities import DeepAgentsWorkspace
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.middleware_packages.runtime import MiddlewarePackageRuntime
from agent_shell.command_packages import CommandPackageRuntime
from agent_shell.event_output_packages import (
    EventOutputCallable,
    EventRunOutputCallable,
    EventOutputPackageRuntime,
)
from agent_shell.tool_packages import ToolPackageRuntime
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.diagnostics import (
    RuntimeDiagnosticContext,
    RuntimeDiagnostics,
)
from agent_shell.runtime.model_response import ModelResponse
from agent_shell.runtime.input_messages import client_messages_sha, validate_client_messages
from agent_shell.runtime.limits import (
    GRAPH_RECURSION_LIMIT,
    WORKFLOW_MAX_CONCURRENCY,
)
from agent_shell.runtime.media_response import MainAgentMediaResponse
from agent_shell.runtime.output_projection import (
    EventOutputOriginResolver,
    EventOutputError,
    EventOutputProjectionStream,
    OutputProjector,
    WorkflowOutputProjector,
)
from agent_shell.runtime.output_stream import (
    ModelCallBoundary,
    OutputEvent,
    V3EventNormalizer,
)
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.usage import RunUsageAccumulator
from agent_shell.runtime.protocol_events import serialize_protocol_event
from agent_shell.runtime.response_scheduler import (
    LifecycleResponseScheduler,
    PresentationFrame,
    ResponseEventInput,
)
from agent_shell.runtime.response_presentation import to_response_signal
from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.stream_transformers import RawCustomEventTransformer
from agent_shell.storage.media_outputs import MediaOutputStore
from agent_shell.storage.runtime_policy import RUNTIME_POLICY_DEFAULTS, RuntimePolicyStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.runtime.workflow_run_journal import WorkflowRunJournal
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.validation import validate_workflow_executable
from agent_shell.validation import ValidationReport
from agent_shell.validation.assembly import StaticAssembly
from agent_shell.workflow_event_output import WorkflowEventOutputBlock
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import ToolCallTransformer

EXECUTION_TIMEOUT_SECONDS = 1_200


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointBinding:
    checkpointer: Any
    checkpoint_thread_id: str
    durability: CheckpointDurability


def _workflow_run_config(
    *,
    run_id: str,
    request_id: str,
    workflow_id: str,
    workflow_name: str,
    messages_sha: str,
    recursion_limit: int,
    max_concurrency: int,
    checkpoint_thread_id: str | None,
) -> dict[str, Any]:
    metadata = {
        "request_id": request_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "messages_sha": messages_sha,
    }
    config: dict[str, Any] = {
        "recursion_limit": recursion_limit,
        "max_concurrency": max_concurrency,
        "run_id": UUID(run_id),
        "run_name": f"workflow:{workflow_name}",
        "tags": ["agent-shell", "workflow"],
        "metadata": metadata,
    }
    if checkpoint_thread_id is not None:
        config["configurable"] = {"thread_id": checkpoint_thread_id}
        metadata["thread_id"] = checkpoint_thread_id
    return config


@dataclass(slots=True)
class RunExecution:
    graph: Any
    input_state: dict[str, Any]
    response_scheduler: LifecycleResponseScheduler | None
    normalizer: V3EventNormalizer
    middleware_runtime: MiddlewarePackageRuntime | None
    media_response: MainAgentMediaResponse
    usage_accumulator: RunUsageAccumulator = field(default_factory=RunUsageAccumulator)
    output_projection_stream: EventOutputProjectionStream | None = None
    origin_resolver: EventOutputOriginResolver | None = None
    event_output_projector: OutputProjector | WorkflowOutputProjector | None = None
    response_consumer: bool = True
    tool_runtime: ToolPackageRuntime | None = None
    middleware_runtimes: tuple[MiddlewarePackageRuntime, ...] = ()
    tool_runtimes: tuple[ToolPackageRuntime, ...] = ()
    command_runtime: CommandPackageRuntime | None = None
    event_output_runtimes: tuple[EventOutputPackageRuntime, ...] = ()
    event_observers: tuple[Callable[[OutputEvent], None], ...] = ()
    context: WorkflowRuntimeContext | None = None
    run_config: dict[str, Any] | None = None
    durability: str | None = None
    lifecycle_service: WorkflowLifecycleService | None = None
    lifecycle_id: str = ""
    owns_lifecycle: bool = False
    runtime_diagnostics: RuntimeDiagnostics | None = None
    request_id: str = ""
    public_model: str = ""
    include_tool_call_transformer: bool = True
    public_output: bool = True
    journal_node_kinds: dict[str, str] | None = None
    journal_agent_names: dict[str, str] | None = None
    journal_agent_profile_ids: dict[str, str] | None = None
    journal_subagent_profile_ids: dict[str, dict[str, str]] | None = None
    workflow_debug_capture_enabled: bool = False
    execution_timeout_seconds: int = EXECUTION_TIMEOUT_SECONDS
    cancel_background_children: Callable[[], Awaitable[None]] | None = None
    final_state: dict[str, Any] | None = None
    _started: bool = False
    _lifecycle_finished: bool = False

    def __post_init__(self) -> None:
        attach_usage = getattr(self.normalizer, "set_usage_accumulator", None)
        if callable(attach_usage):
            attach_usage(self.usage_accumulator)
        if (
            not self.public_output
            or self.context is None
            or self.response_scheduler is None
        ):
            return
        register_origin = getattr(self.response_scheduler, "register_origin", None)
        if callable(register_origin):
            register_origin(
                self.context.run_id,
                str(self.context.workflow.get("id", "")),
            )

    @property
    def usage(self) -> dict[str, int]:
        return self.usage_accumulator.snapshot

    @property
    def finish_reason(self) -> str:
        return "stop"

    @property
    def finish_reason_source(self) -> str | None:
        return None

    def diagnostic_context(self) -> RuntimeDiagnosticContext:
        context = self.context
        if context is None:
            return RuntimeDiagnosticContext(
                request_id=self.request_id,
                subject_kind="workflow",
                subject_name=self.public_model,
            )
        workflow_id = str(context.workflow.get("id", ""))
        workflow_name = str(
            context.workflow.get(
                "name",
                self.public_model,
            )
        )
        return RuntimeDiagnosticContext(
            request_id=context.request_id or self.request_id,
            lifecycle_id=context.lifecycle_id,
            run_id=context.run_id,
            thread_id=context.checkpoint_thread_id,
            parent_workflow_id=workflow_id if self.owns_lifecycle else "",
            parent_workflow_name=workflow_name if self.owns_lifecycle else "",
            subject_kind="workflow",
            subject_id=workflow_id,
            subject_name=workflow_name,
            workflow_node_id=context.workflow_node_id,
            node_invocation_id=context.invocation_id,
        )

    async def cancel(self) -> None:
        """Converge Shell-owned cancellation before graph cleanup completes."""

        cancellation_recorded = True
        if self.lifecycle_service is not None and self.context is not None:
            try:
                cancellation_recorded = self.lifecycle_service.finish_run(
                    self.context.run_id,
                    status="cancelled",
                    error_code="request_cancelled",
                    usage=self.usage,
                )
                if not cancellation_recorded:
                    record = self.lifecycle_service.history.get_run(
                        self.context.run_id
                    )
                    if record is None:
                        raise RuntimeError("the Run registry record is unavailable")
                    cancellation_recorded = record["status"] == "cancelled"
            except Exception as exc:
                cancellation_recorded = True
                try:
                    self.lifecycle_service.mark_run_observation_partial(
                        self.context.run_id
                    )
                except Exception:
                    pass
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.observation_error(
                        exc,
                        code="workflow_run_record_failed",
                        component="observability",
                        context=self.diagnostic_context(),
                    )

        if not cancellation_recorded:
            return

        if (
            self.owns_lifecycle
            and self.lifecycle_service is not None
            and self.lifecycle_id
            and not self._lifecycle_finished
        ):
            self._lifecycle_finished = True
            try:
                await self.lifecycle_service.finish_parent(
                    self.lifecycle_id,
                    "cancelled",
                )
            except Exception as exc:
                if self.context is not None:
                    try:
                        self.lifecycle_service.mark_run_observation_partial(
                            self.context.run_id
                        )
                    except Exception:
                        pass
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.observation_error(
                        exc,
                        code="workflow_lifecycle_record_failed",
                        component="persistence",
                        context=self.diagnostic_context(),
                    )

        if self.cancel_background_children is not None:
            try:
                await self.cancel_background_children()
            except Exception as exc:
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.observation_error(
                        exc,
                        code="background_child_cancellation_failed",
                        component="observability",
                        context=self.diagnostic_context(),
                    )

    async def stream_text(self) -> AsyncIterator[str]:
        if self._started:
            raise RuntimeError("RunExecution can only be consumed once")
        self._started = True
        try:
            async for part in self._stream_text_inner():
                yield part
        finally:
            runtimes = tuple(
                runtime
                for runtime in (self.middleware_runtime, *self.middleware_runtimes)
                if runtime is not None
            )
            for runtime in runtimes:
                await runtime.close()
            tool_runtimes = tuple(
                runtime
                for runtime in (self.tool_runtime, *self.tool_runtimes)
                if runtime is not None
            )
            for runtime in tool_runtimes:
                await runtime.close()
            if self.command_runtime is not None:
                await self.command_runtime.close()
            for runtime in self.event_output_runtimes:
                await runtime.close()

    async def _stream_text_inner(self) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        protocol_event_capture_failed = False

        def observation_error(exc: BaseException, code: str) -> None:
            if self.lifecycle_service is not None and self.context is not None:
                try:
                    self.lifecycle_service.mark_run_observation_partial(
                        self.context.run_id
                    )
                except Exception:
                    pass
            if self.runtime_diagnostics is not None:
                self.runtime_diagnostics.observation_error(
                    exc,
                    code=code,
                    component="observability",
                    context=self.diagnostic_context(),
                )

        def capture_protocol_event(envelope: object) -> None:
            nonlocal protocol_event_capture_failed
            if (
                protocol_event_capture_failed
                or not self.workflow_debug_capture_enabled
                or self.lifecycle_service is None
                or self.context is None
            ):
                return
            try:
                self.lifecycle_service.append_protocol_event(
                    self.context.lifecycle_id,
                    self.context.run_id,
                    serialize_protocol_event(envelope),
                )
            except Exception as exc:
                protocol_event_capture_failed = True
                observation_error(exc, "workflow_protocol_event_record_failed")

        async def cancel_background_children() -> None:
            if self.cancel_background_children is None:
                return
            try:
                await self.cancel_background_children()
            except Exception as exc:
                observation_error(exc, "background_child_cancellation_failed")

        def start_run() -> None:
            if self.lifecycle_service is None or self.context is None:
                return
            try:
                if not self.lifecycle_service.start_run(self.context.run_id):
                    record = self.lifecycle_service.history.get_run(self.context.run_id)
                    if record is None:
                        raise RuntimeError("the Run registry record is unavailable")
            except Exception as exc:
                observation_error(exc, "workflow_run_record_failed")

        def finish_run(status: str, *, error_code: str = "") -> None:
            if self.lifecycle_service is None or self.context is None:
                return
            try:
                if not self.lifecycle_service.finish_run(
                    self.context.run_id,
                    status=status,
                    error_code=error_code,
                    finish_reason=self.finish_reason if status == "completed" else "",
                    usage=self.usage,
                ):
                    record = self.lifecycle_service.history.get_run(self.context.run_id)
                    if record is None:
                        raise RuntimeError("the Run registry record is unavailable")
            except Exception as exc:
                observation_error(exc, "workflow_run_record_failed")

        async def finish_lifecycle(status: str) -> None:
            if (
                not self.owns_lifecycle
                or self.lifecycle_service is None
                or not self.lifecycle_id
                or self._lifecycle_finished
            ):
                return
            self._lifecycle_finished = True
            try:
                await self.lifecycle_service.finish_parent(self.lifecycle_id, status)
            except Exception as exc:
                try:
                    self.lifecycle_service.mark_run_observation_partial(
                        self.context.run_id
                    )
                except Exception:
                    pass
                if self.runtime_diagnostics is not None:
                    self.runtime_diagnostics.observation_error(
                        exc,
                        code="workflow_lifecycle_record_failed",
                        component="persistence",
                        context=self.diagnostic_context(),
                    )

        def record_runtime_error(
            exc: BaseException,
            code: str,
            *,
            detail_exception: BaseException | None = None,
        ) -> None:
            if self.runtime_diagnostics is not None:
                self.runtime_diagnostics.runtime_error(
                    exc,
                    code=code,
                    component="workflow_runtime",
                    context=self.diagnostic_context(),
                    detail_exception=detail_exception,
                )

        def frame_text(frames: list[PresentationFrame]) -> list[str]:
            text = "".join(frame.text for frame in frames if frame.text)
            return [text] if text else []

        def response_origin() -> tuple[str, str]:
            scheduler = self.response_scheduler
            assert scheduler is not None
            if self.context is None:
                return scheduler.origin_run_id, scheduler.origin_workflow_id
            return (
                self.context.run_id,
                str(self.context.workflow.get("id", "")),
            )

        def projection_stream() -> EventOutputProjectionStream:
            stream = self.output_projection_stream
            if stream is None:
                stream = EventOutputProjectionStream()
                self.output_projection_stream = stream
            return stream

        def response_accepting() -> bool:
            scheduler = self.response_scheduler
            if not self.public_output or scheduler is None:
                return False
            origin_run_id, origin_workflow_id = response_origin()
            return scheduler.accepting(origin_run_id, origin_workflow_id)

        def take_response_output() -> list[str]:
            scheduler = self.response_scheduler
            if not self.response_consumer or scheduler is None:
                return []
            return frame_text(scheduler.take_published())

        def project_input(
            event: OutputEvent | ModelCallBoundary,
            *,
            text: str = "",
            segment_end_text: str = "",
        ) -> list[str]:
            if not self.public_output:
                return []
            if isinstance(event, OutputEvent):
                for observer in self.event_observers:
                    observer(event)
            scheduler = self.response_scheduler
            assert scheduler is not None
            origin_run_id, origin_workflow_id = response_origin()
            if not scheduler.accepting(origin_run_id, origin_workflow_id):
                return []
            for projected in projection_stream().project(
                event,
                text=text,
                segment_end_text=segment_end_text,
            ):
                scheduler.publish(
                    ResponseEventInput(
                        lifecycle_id=scheduler.lifecycle_id,
                        origin_run_id=origin_run_id,
                        origin_workflow_id=origin_workflow_id,
                        event=to_response_signal(projected.event),
                        text=projected.text,
                        segment_end_text=projected.segment_end_text,
                    ),
                    now=loop.time(),
                )
            return take_response_output()

        def project_event(event: OutputEvent, *, text: str = "") -> list[str]:
            return project_input(event, text=text)

        def event_origin(
            envelope: Mapping[str, object],
            normalized: tuple[OutputEvent | ModelCallBoundary, ...] = (),
        ) -> Mapping[str, object]:
            resolver = self.origin_resolver
            if resolver is None:
                return {}
            return resolver.resolve(envelope, normalized)

        def render_protocol_event(
            envelope: Mapping[str, object],
            normalized: tuple[OutputEvent | ModelCallBoundary, ...],
        ) -> tuple[str, Mapping[str, object]]:
            origin = event_origin(envelope, normalized)
            projector = self.event_output_projector
            if projector is None:
                return "", origin
            return projector.render(envelope, origin), origin

        def render_run_event(event: OutputEvent) -> str:
            projector = self.event_output_projector
            resolver = self.origin_resolver
            if projector is None:
                return ""
            origin = resolver.resolve({}, (event,)) if resolver is not None else {}
            run_event = {
                "type": "agent_shell.workflow_run",
                "phase": event.phase,
                "status": event.values.get("status", event.message),
                "finish_reason": event.values.get("finish_reason", ""),
                "error_code": event.values.get("error_code", ""),
            }
            return projector.render_run(run_event, origin)

        def raw_atomic_event(
            envelope: Mapping[str, object], origin: Mapping[str, object]
        ) -> OutputEvent:
            params = envelope.get("params")
            data = params.get("data") if isinstance(params, Mapping) else None
            namespace = params.get("namespace") if isinstance(params, Mapping) else ()
            namespace_text = "/".join(str(part) for part in namespace) if isinstance(namespace, (list, tuple)) else str(namespace or "root")
            raw_seq = envelope.get("seq")
            return OutputEvent(
                event_type="custom",
                phase="end",
                sequence=int(raw_seq) if isinstance(raw_seq, int) else 0,
                timestamp=str(params.get("timestamp", "")) if isinstance(params, Mapping) else "",
                namespace=namespace_text or "root",
                source_type=("agent" if origin.get("agent_profile_id") else "non_agent"),
                workflow_node_id=str(origin.get("workflow_node_id") or ""),
                agent_profile_id=str(origin.get("agent_profile_id") or ""),
                subagent_profile_id=str(origin.get("subagent_profile_id") or ""),
                data=data,
                raw_seq=int(raw_seq) if isinstance(raw_seq, int) else 0,
                source_key="raw-protocol",
                cycle_key=namespace_text or "root",
            )

        def project_deadline() -> list[str]:
            if not self.public_output or not self.response_consumer:
                return []
            scheduler = self.response_scheduler
            assert scheduler is not None
            scheduler.advance_published(now=loop.time())
            return take_response_output()

        def failure_output(error_code: str) -> list[str]:
            self.normalizer.abort_main_agent_messages()
            scheduler = self.response_scheduler
            if scheduler is not None and self.public_output:
                projection_stream().discard()
            parts: list[str] = []
            if self.public_output and scheduler is not None:
                if self.response_consumer:
                    parts.extend(frame_text(scheduler.abort()))
                else:
                    origin_run_id, origin_workflow_id = response_origin()
                    scheduler.abort_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
            try:
                error_event = self.normalizer.lifecycle(
                    "error",
                    status="failed",
                    finish_reason="error",
                    error_code=error_code,
                )
                parts.extend(
                    project_event(
                        error_event,
                        text=render_run_event(error_event),
                    )
                )
            except Exception:
                # A broken user lifecycle projector must not replace the safe
                # runtime error that is already crossing the public boundary.
                if scheduler is not None:
                    if self.response_consumer:
                        scheduler.discard()
                    else:
                        origin_run_id, origin_workflow_id = response_origin()
                        scheduler.abort_origin(
                            origin_run_id,
                            origin_workflow_id,
                            now=loop.time(),
                        )
            if self.public_output and scheduler is not None:
                if self.response_consumer:
                    scheduler.discard()
                else:
                    origin_run_id, origin_workflow_id = response_origin()
                    scheduler.finish_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
            return parts

        journal: WorkflowRunJournal | None = None
        start_run()
        try:
            start_event = self.normalizer.lifecycle("start", status="running")
            for rendered in project_event(
                start_event,
                text=render_run_event(start_event),
            ):
                if rendered:
                    yield rendered
            remaining_timeout = float(self.execution_timeout_seconds)
            timeout_scope = asyncio.timeout(None)

            @contextmanager
            def pause_execution_timeout():
                nonlocal remaining_timeout
                deadline = timeout_scope.when()
                if deadline is not None:
                    remaining_timeout = max(0.0, deadline - loop.time())
                timeout_scope.reschedule(None)
                try:
                    yield
                finally:
                    timeout_scope.reschedule(loop.time() + remaining_timeout)

            async with timeout_scope:
                timeout_scope.reschedule(loop.time() + remaining_timeout)
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=(
                            r"The v3 streaming protocol on Pregel is experimental\."
                        ),
                    )
                    config: dict[str, Any] = {
                        "recursion_limit": GRAPH_RECURSION_LIMIT,
                        **(self.run_config or {}),
                    }
                    if self.context is not None and self.lifecycle_service is not None:
                        callbacks = list(config.get("callbacks", ()))
                        journal = WorkflowRunJournal(
                            self.lifecycle_service,
                            self.runtime_diagnostics,
                            self.context,
                            workflow_node_kinds=self.journal_node_kinds or {},
                            agent_names=self.journal_agent_names or {},
                            agent_profile_ids=self.journal_agent_profile_ids or {},
                            subagent_profile_ids=(
                                self.journal_subagent_profile_ids or {}
                            ),
                            debug_capture=self.workflow_debug_capture_enabled,
                        )
                        callbacks.append(journal)
                        config["callbacks"] = callbacks
                    stream_kwargs: dict[str, Any] = {
                        "config": config,
                        "version": "v3",
                        "transformers": (
                            (RawCustomEventTransformer, ToolCallTransformer)
                            if self.include_tool_call_transformer
                            else (RawCustomEventTransformer,)
                        ),
                    }
                    if self.durability is not None:
                        stream_kwargs["durability"] = self.durability
                    if self.context is not None:
                        stream_kwargs["context"] = self.context
                    stream = await self.graph.astream_events(
                        self.input_state,
                        **stream_kwargs,
                    )
                # The v3 run stream owns the graph iterator. Its async context
                # manager aborts in-flight provider/tool work when an OpenAI
                # streaming client disconnects and this generator is cancelled.
                async with stream:
                    envelopes = aiter(stream)
                    next_event_task: asyncio.Task[object] | None = asyncio.create_task(
                        anext(envelopes)
                    )
                    try:
                        while next_event_task is not None:
                            scheduler = (
                                self.response_scheduler
                                if self.public_output and self.response_consumer
                                else None
                            )
                            if scheduler is not None:
                                scheduler.clear_wakeup()
                                for rendered in take_response_output():
                                    with pause_execution_timeout():
                                        yield rendered
                            scheduler_deadline = (
                                scheduler.next_deadline()
                                if scheduler is not None
                                else None
                            )
                            deadline_task: asyncio.Task[None] | None = None
                            wakeup_task: asyncio.Task[None] | None = None
                            waiters: set[asyncio.Task[object] | asyncio.Task[None]] = {
                                next_event_task
                            }
                            if scheduler_deadline is not None:
                                deadline_task = asyncio.create_task(
                                    asyncio.sleep(
                                        max(0.0, scheduler_deadline - loop.time())
                                    )
                                )
                                waiters.add(deadline_task)
                            if scheduler is not None:
                                wakeup_task = asyncio.create_task(
                                    scheduler.wait_for_wakeup()
                                )
                                waiters.add(wakeup_task)
                            done, _pending = await asyncio.wait(
                                waiters,
                                return_when=asyncio.FIRST_COMPLETED,
                            )

                            auxiliary_tasks = tuple(
                                task
                                for task in (deadline_task, wakeup_task)
                                if task is not None
                            )
                            for task in auxiliary_tasks:
                                if not task.done():
                                    task.cancel()
                            if auxiliary_tasks:
                                await asyncio.gather(
                                    *auxiliary_tasks,
                                    return_exceptions=True,
                                )

                            event_ready = next_event_task in done
                            if event_ready:
                                try:
                                    envelope = next_event_task.result()
                                except StopAsyncIteration:
                                    next_event_task = None
                                else:
                                    next_event_task = asyncio.create_task(anext(envelopes))
                                    capture_protocol_event(envelope)
                                    normalized_events = tuple(
                                        self.normalizer.feed(envelope)
                                    )
                                    raw_text = ""
                                    raw_origin: Mapping[str, object] = {}
                                    if self.public_output:
                                        raw_text, raw_origin = render_protocol_event(
                                            envelope,
                                            normalized_events,
                                        )
                                    text_attached = False
                                    for event in normalized_events:
                                        if isinstance(event, ModelCallBoundary):
                                            projected = project_input(event)
                                        elif isinstance(event, MediaContentBlock):
                                            notification = (
                                                await self.media_response.project(event)
                                                if response_accepting()
                                                else None
                                            )
                                            projected = (
                                                project_event(
                                                    self.normalizer.media_notification(
                                                        event, notification
                                                    )
                                                )
                                                if notification is not None
                                                else []
                                            )
                                        else:
                                            event_text = (
                                                raw_text if not text_attached else ""
                                            )
                                            text_attached = text_attached or bool(raw_text)
                                            projected = project_event(
                                                event,
                                                text=event_text,
                                            )
                                        for rendered in projected:
                                            with pause_execution_timeout():
                                                yield rendered
                                    if raw_text and not text_attached:
                                        projected = project_event(
                                            raw_atomic_event(envelope, raw_origin),
                                            text=raw_text,
                                        )
                                        for rendered in projected:
                                            with pause_execution_timeout():
                                                yield rendered

                            if deadline_task is not None and deadline_task in done:
                                for rendered in project_deadline():
                                    with pause_execution_timeout():
                                        yield rendered
                            elif wakeup_task is not None and wakeup_task in done:
                                for rendered in project_deadline():
                                    with pause_execution_timeout():
                                        yield rendered
                    finally:
                        if next_event_task is not None and not next_event_task.done():
                            next_event_task.cancel()
                            await asyncio.gather(
                                next_event_task,
                                return_exceptions=True,
                            )
                    output = await stream.output()
                    self.final_state = dict(output) if isinstance(output, Mapping) else None
                    self.normalizer.close_main_agent_messages()
                    if self.public_output and self.response_scheduler is not None:
                        scheduler = self.response_scheduler
                        origin_run_id, origin_workflow_id = response_origin()
                        for projected in projection_stream().finish():
                            scheduler.publish(
                                ResponseEventInput(
                                    lifecycle_id=scheduler.lifecycle_id,
                                    origin_run_id=origin_run_id,
                                    origin_workflow_id=origin_workflow_id,
                                    event=to_response_signal(projected.event),
                                    text=projected.text,
                                    segment_end_text=projected.segment_end_text,
                                ),
                                now=loop.time(),
                            )
                    for rendered in take_response_output():
                        if rendered:
                            with pause_execution_timeout():
                                yield rendered
            if journal is not None:
                journal.finish_open_spans("completed")
            end_event = self.normalizer.lifecycle(
                "end",
                status="completed",
                finish_reason=self.finish_reason,
            )
            for rendered in project_event(
                end_event,
                text=render_run_event(end_event),
            ):
                if rendered:
                    yield rendered
            if self.public_output and self.response_scheduler is not None:
                scheduler = self.response_scheduler
                origin_run_id, origin_workflow_id = response_origin()
                scheduler.finish_origin(
                    origin_run_id,
                    origin_workflow_id,
                    now=loop.time(),
                )
                if self.response_consumer:
                    final_frames = scheduler.take_published()
                    final_frames.extend(scheduler.finish(now=loop.time()))
                    for rendered in frame_text(final_frames):
                        if rendered:
                            yield rendered
            while (
                self.public_output
                and self.response_consumer
                and self.response_scheduler is not None
                and self.response_scheduler.has_pending_output
            ):
                deadline = self.response_scheduler.next_deadline()
                if deadline is None:
                    break
                delay = max(0.0, deadline - loop.time())
                if delay:
                    await asyncio.sleep(delay)
                for rendered in frame_text(
                    self.response_scheduler.advance(now=loop.time())
                ):
                    if rendered:
                        yield rendered
        except asyncio.CancelledError:
            if journal is not None:
                journal.finish_open_spans(
                    "cancelled", error_code="request_cancelled"
                )
            self.normalizer.abort_main_agent_messages()
            if self.response_scheduler is not None:
                if self.public_output:
                    projection_stream().discard()
                if self.response_consumer:
                    self.response_scheduler.discard()
                elif self.public_output:
                    origin_run_id, origin_workflow_id = response_origin()
                    self.response_scheduler.abort_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
                    self.response_scheduler.finish_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
            await self.cancel()
            raise
        except TimeoutError as exc:
            error = AgentRuntimeError(
                "execution_timeout",
                "The Agent execution exceeded the runtime time limit.",
                status_code=504,
            )
            if journal is not None:
                journal.finish_open_spans("failed", error_code=error.code)
            for rendered in failure_output(error.code):
                yield rendered
            record_runtime_error(error, error.code, detail_exception=exc)
            await cancel_background_children()
            finish_run("failed", error_code=error.code)
            await finish_lifecycle("failed")
            raise error from exc
        except AgentRuntimeError as exc:
            if journal is not None:
                journal.finish_open_spans("failed", error_code=exc.code)
            for rendered in failure_output(exc.code):
                yield rendered
            record_runtime_error(
                exc,
                exc.code,
                detail_exception=(
                    exc.__cause__ if isinstance(exc, EventOutputError) else None
                ),
            )
            await cancel_background_children()
            finish_run("failed", error_code=exc.code)
            await finish_lifecycle("failed")
            raise
        except Exception as exc:
            if isinstance(exc, GraphRecursionError):
                error = AgentRuntimeError(
                    "execution_step_limit",
                    "The Agent exceeded the runtime step limit.",
                    status_code=508,
                )
            else:
                error = AgentRuntimeError(
                    "agent_execution_failed",
                    "The Agent failed during graph execution.",
                    status_code=502,
                )
            if journal is not None:
                journal.finish_open_spans("failed", error_code=error.code)
            for rendered in failure_output(error.code):
                yield rendered
            record_runtime_error(error, error.code, detail_exception=exc)
            await cancel_background_children()
            finish_run("failed", error_code=error.code)
            await finish_lifecycle("failed")
            raise error from exc
        finish_run("completed")
        await finish_lifecycle("completed")

    async def run(self) -> tuple[str, dict[str, int]]:
        parts = [part async for part in self.stream_text()]
        return "".join(parts), self.usage

    async def execute(self) -> None:
        """Run to completion without collecting a public response body."""

        async for _part in self.stream_text():
            pass


class AgentRuntime:
    def __init__(
        self,
        builder: AgentBuilder,
        media_outputs: MediaOutputStore,
        *,
        blocks: BlockStore | None = None,
        python_packages_dir: Path | None = None,
        runtime_dir: Path | None = None,
        workflow_checkpoints: WorkflowCheckpointService | None = None,
        workflow_lifecycle: WorkflowLifecycleService,
        runtime_diagnostics: RuntimeDiagnostics | None = None,
        runtime_policy: RuntimePolicyStore | None = None,
    ) -> None:
        self._builder = builder
        self._media_outputs = media_outputs
        self._blocks = blocks
        self._python_packages_dir = python_packages_dir
        self._runtime_dir = runtime_dir
        self._workflow_checkpoints = workflow_checkpoints
        self._workflow_lifecycle = workflow_lifecycle
        self._runtime_diagnostics = runtime_diagnostics
        self._runtime_policy = runtime_policy

    def _input_policy(self):
        return (
            self._runtime_policy.snapshot()
            if self._runtime_policy is not None
            else RUNTIME_POLICY_DEFAULTS
        )

    async def _finish_parent_lifecycle(
        self,
        lifecycle_id: str,
        status: str,
        *,
        context: RuntimeDiagnosticContext,
    ) -> None:
        try:
            await self._workflow_lifecycle.finish_parent(lifecycle_id, status)
        except Exception as exc:
            try:
                self._workflow_lifecycle.mark_run_observation_partial(context.run_id)
            except Exception:
                pass
            if self._runtime_diagnostics is not None:
                self._runtime_diagnostics.observation_error(
                    exc,
                    code="workflow_lifecycle_record_failed",
                    component="persistence",
                    context=context,
                )

    def _register_run_observation(
        self,
        record: dict[str, object],
        *,
        context: RuntimeDiagnosticContext,
    ) -> None:
        try:
            self._workflow_lifecycle.register_run(record)
        except Exception as exc:
            if self._runtime_diagnostics is not None:
                self._runtime_diagnostics.observation_error(
                    exc,
                    code="workflow_run_record_failed",
                    component="observability",
                    context=context,
                )

    def _finish_run_observation(
        self,
        run_id: str,
        *,
        status: str,
        error_code: str,
        context: RuntimeDiagnosticContext,
    ) -> None:
        try:
            if not self._workflow_lifecycle.finish_run(
                run_id,
                status=status,
                error_code=error_code,
            ) and self._workflow_lifecycle.history.get_run(run_id) is None:
                raise RuntimeError("the Run registry record is unavailable")
        except Exception as exc:
            try:
                self._workflow_lifecycle.mark_run_observation_partial(run_id)
            except Exception:
                pass
            if self._runtime_diagnostics is not None:
                self._runtime_diagnostics.observation_error(
                    exc,
                    code="workflow_run_record_failed",
                    component="observability",
                    context=context,
                )

    async def build_agent(
        self,
        main_agent_id: str,
        raw_messages: object,
        *,
        model_response_observer: Callable[[ModelResponse], None] | None = None,
        request_id: str = "",
        workflow_node_id: str | None = None,
        workspace: DeepAgentsWorkspace | None = None,
    ) -> BuiltAgent:
        try:
            return await self._builder.build(
                main_agent_id,
                raw_messages,
                model_response_observer=model_response_observer,
                request_id=request_id,
                workflow_node_id=workflow_node_id,
                workspace=workspace,
            )
        except Exception:
            await self._builder.close_failed_build()
            raise

    async def build_resolved_agent(
        self,
        assembly: StaticAssembly,
        raw_messages: object,
        **kwargs: Any,
    ) -> BuiltAgent:
        try:
            return await self._builder.build_resolved(assembly, raw_messages, **kwargs)
        except Exception:
            await self._builder.close_failed_build()
            raise

    async def _resolved_mapped_directory_paths_by_filesystem(
        self,
        lifecycle_id: str,
        assembly: StaticAssembly,
    ) -> dict[str, dict[str, Path]]:
        stored_filesystems: dict[str, dict[str, Any]] = {}
        for blocks in (
            assembly.blocks,
            *(node.blocks for node in assembly.subagent_nodes.values()),
        ):
            stored = blocks.get("filesystem")
            if stored is None:
                continue
            filesystem_id = str(stored.get("id", ""))
            if not filesystem_id:
                raise AgentRuntimeError(
                    "filesystem_identity_missing",
                    "The selected Filesystem has no stable identity.",
                    status_code=422,
                )
            stored_filesystems[filesystem_id] = stored

        resolved: dict[str, dict[str, Path]] = {}
        for filesystem_id, stored in stored_filesystems.items():
            filesystem = FilesystemBlock.model_validate(
                {key: value for key, value in stored.items() if key != "id"}
            )
            try:
                resolved[filesystem_id] = (
                    await self._workflow_lifecycle.resolve_mapped_directories(
                        lifecycle_id,
                        filesystem_id,
                        filesystem,
                    )
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise AgentRuntimeError(
                    "filesystem_mapping_unavailable",
                    "The selected Filesystem mapping could not be resolved.",
                    status_code=422,
                ) from exc
        return resolved

    def _execution(
        self,
        built: BuiltAgent | None,
        *,
        graph: Any | None = None,
        input_state: dict[str, Any] | None = None,
        workflow_node_id: str = "",
        event_observer: Callable[[OutputEvent], None] | None = None,
        model_response_observer: Callable[[ModelResponse], None] | None = None,
        request_id: str = "",
        public_model: str = "",
        workflow_built: tuple[tuple[str, BuiltAgent], ...] = (),
        agent_event_outputs: Mapping[str, EventOutputCallable] | None = None,
        workflow_event_output: EventOutputCallable | None = None,
        agent_run_outputs: Mapping[str, EventRunOutputCallable | None] | None = None,
        workflow_run_output: EventRunOutputCallable | None = None,
        event_output_runtimes: tuple[EventOutputPackageRuntime, ...] = (),
        command_runtime: CommandPackageRuntime | None = None,
        context: WorkflowRuntimeContext | None = None,
        run_config: dict[str, Any] | None = None,
        durability: str | None = None,
        owns_lifecycle: bool = False,
        include_tool_call_transformer: bool = True,
        public_output: bool = True,
        execution_timeout_seconds: int = EXECUTION_TIMEOUT_SECONDS,
        cancel_background_children: Callable[[], Awaitable[None]] | None = None,
        response_stream_policy: ResponseStreamPolicy | None = None,
        response_scheduler: LifecycleResponseScheduler | None = None,
        response_consumer: bool = True,
        workflow_debug_capture_enabled: bool | None = None,
    ) -> RunExecution:
        if built is None:
            if graph is None or input_state is None:
                raise ValueError(
                    "a Workflow execution requires a graph and input state"
                )
            effective_graph = graph
            effective_input_state = input_state
        else:
            effective_graph = graph if graph is not None else built.graph
            effective_input_state = (
                input_state if input_state is not None else built.input_state
            )
        observers = []
        if event_observer is not None:
            observers.append(event_observer)
        workflow_agents = workflow_built or (
            ((workflow_node_id, built),) if built is not None else ()
        )
        from agent_shell.workflow.events import WorkflowEventSourceV1

        workflow_sources = {
            node_id: WorkflowEventSourceV1(
                source_type="agent",
                workflow_node_id=node_id,
                agent_profile_id=agent.agent_id,
            )
            for node_id, agent in workflow_agents
        }
        if public_output:
            projector = WorkflowOutputProjector(
                agent_event_outputs or {},
                workflow_output=workflow_event_output,
                run_outputs_by_node=agent_run_outputs,
                workflow_run_output=workflow_run_output,
            )
        else:
            projector = OutputProjector(None)
        journal_node_kinds: dict[str, str] = {}
        if context is not None:
            graph_document = context.workflow.get("graph")
            definition = (
                graph_document.get("definition")
                if isinstance(graph_document, Mapping)
                else None
            )
            nodes = definition.get("nodes", ()) if isinstance(definition, Mapping) else ()
            journal_node_kinds = {
                str(node.get("id", "")): str(node.get("type", ""))
                for node in nodes
                if isinstance(node, Mapping)
            }
        for node_id, node_type in journal_node_kinds.items():
            if node_type == "command":
                workflow_sources[node_id] = WorkflowEventSourceV1(
                    source_type="script",
                    workflow_node_id=node_id,
                )
        debug_capture = (
            self._input_policy().workflow_debug_capture_enabled
            if workflow_debug_capture_enabled is None
            else workflow_debug_capture_enabled
        )
        scheduler_policy = (
            response_stream_policy.model_copy(deep=True)
            if response_stream_policy is not None
            else ResponseStreamPolicy()
        )
        lifecycle_identity = context.lifecycle_id if context is not None else ""
        run_identity = context.run_id if context is not None else ""
        workflow_identity = (
            str(context.workflow.get("id", "")) if context is not None else ""
        )
        output_projection_stream = EventOutputProjectionStream()
        usage_accumulator = RunUsageAccumulator()
        origin_resolver = EventOutputOriginResolver(
            context,
            workflow_sources=workflow_sources,
            main_agent_names=tuple(agent.agent_name for _, agent in workflow_agents),
            workflow_subagent_profile_ids={
                node_id: agent.subagent_profile_ids
                for node_id, agent in workflow_agents
            },
            subagent_profile_ids=(built.subagent_profile_ids if built is not None else {}),
        )
        effective_response_scheduler = response_scheduler
        if effective_response_scheduler is None:
            effective_response_scheduler = LifecycleResponseScheduler(
                scheduler_policy,
                lifecycle_id=lifecycle_identity,
                origin_run_id=run_identity,
                origin_workflow_id=workflow_identity,
            )
        return RunExecution(
            graph=effective_graph,
            input_state=effective_input_state,
            middleware_runtime=(built.middleware_runtime if built is not None else None),
            tool_runtime=(built.tool_runtime if built is not None else None),
            media_response=MainAgentMediaResponse(self._media_outputs, request_id),
            response_scheduler=effective_response_scheduler,
            usage_accumulator=usage_accumulator,
            output_projection_stream=output_projection_stream,
            origin_resolver=origin_resolver,
            event_output_projector=projector,
            response_consumer=response_consumer,
            normalizer=V3EventNormalizer(
                built.agent_name if built is not None else "",
                model_response_observers=(model_response_observer,)
                if model_response_observer is not None
                else (),
                workflow_mode=True,
                workflow_sources=workflow_sources,
                subagent_profile_ids=(
                    built.subagent_profile_ids if built is not None else {}
                ),
                main_agent_names=tuple(agent.agent_name for _, agent in workflow_agents),
                workflow_subagent_profile_ids={
                    node_id: agent.subagent_profile_ids
                    for node_id, agent in workflow_agents
                },
                workflow_agent_names={
                    node_id: agent.agent_name
                    for node_id, agent in workflow_agents
                },
                usage_accumulator=usage_accumulator,
            ),
            event_observers=tuple(observers),
            middleware_runtimes=tuple(
                agent.middleware_runtime
                for _, agent in workflow_agents[1:]
            ),
            tool_runtimes=tuple(
                agent.tool_runtime
                for _, agent in workflow_agents[1:]
            ),
            command_runtime=command_runtime,
            event_output_runtimes=event_output_runtimes,
            context=context,
            run_config=run_config,
            durability=durability,
            lifecycle_service=self._workflow_lifecycle,
            lifecycle_id=context.lifecycle_id if context is not None else "",
            owns_lifecycle=owns_lifecycle,
            runtime_diagnostics=self._runtime_diagnostics,
            request_id=request_id,
            public_model=public_model,
            include_tool_call_transformer=include_tool_call_transformer,
            public_output=public_output,
            journal_node_kinds=journal_node_kinds,
            journal_agent_names={
                node_id: agent.agent_name for node_id, agent in workflow_agents
            },
            journal_agent_profile_ids={
                node_id: agent.agent_id for node_id, agent in workflow_agents
            },
            journal_subagent_profile_ids={
                node_id: dict(agent.subagent_profile_ids)
                for node_id, agent in workflow_agents
            },
            workflow_debug_capture_enabled=debug_capture,
            execution_timeout_seconds=execution_timeout_seconds,
            cancel_background_children=cancel_background_children,
        )

    async def start_workflow(
        self,
        document: WorkflowGraphDocumentV1,
        raw_messages: object,
        *,
        workflow_snapshot: Mapping[str, Any] | None = None,
        model_response_observer: Callable[[ModelResponse], None] | None = None,
        event_observer: Callable[[OutputEvent], None] | None = None,
        request_id: str = "",
        public_model: str = "",
        lifecycle_id: str | None = None,
        run_id: str | None = None,
        checkpoint_thread_id: str | None = None,
        parent_run_id: str = "",
        background_task_id: str = "",
        launcher_id: str = "",
        run_depth: int = 0,
        initial_shared_vars: Mapping[str, Any] | None = None,
        initial_workflow_task: Mapping[str, Any] | None = None,
        background_runtime: Any | None = None,
        public_output: bool = True,
        response_scheduler: LifecycleResponseScheduler | None = None,
        response_consumer: bool = True,
    ) -> RunExecution:
        from agent_shell.workflow.catalog import (
            AgentNodeConfig,
            CommandNodeConfig,
        )
        from agent_shell.workflow.compiler import compile_workflow

        agent_nodes = [
            node for node in document.definition.nodes if node.type == "agent"
        ]
        command_nodes = [
            node
            for node in document.definition.nodes
            if node.type == "command"
        ]
        runtime_policy = self._input_policy()
        messages = validate_client_messages(raw_messages, runtime_policy)
        messages_sha = client_messages_sha(messages)
        assemblies: dict[str, StaticAssembly] = {}

        def validate_main_agent(main_agent_id: str) -> ValidationReport:
            if main_agent_id in assemblies:
                return ValidationReport(stage="workflow_publish")
            try:
                assemblies[main_agent_id] = self._builder.resolve(main_agent_id)
            except AgentRuntimeError as exc:
                if exc.validation_report is not None:
                    return exc.validation_report
                raise
            return ValidationReport(stage="workflow_publish")

        from agent_shell.command import CommandBlock

        command_blocks: dict[str, tuple[str, CommandBlock]] = {}
        for command_node in command_nodes:
            command_id = str(
                CommandNodeConfig.model_validate(
                    command_node.config
                ).command_id
            )
            stored_command = (
                self._blocks.get_block_internal("command", command_id)
                if self._blocks is not None
                else None
            )
            if stored_command is None:
                continue
            try:
                command_blocks[command_node.id] = (
                    command_id,
                    CommandBlock.model_validate(
                        {key: value for key, value in stored_command.items() if key != "id"}
                    ),
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "workflow.command_invalid",
                    "The selected Command Node configuration is invalid.",
                    status_code=422,
                ) from exc

        resolved_command_nodes: dict[str, Any] = {
            node_id: block for node_id, (_command_id, block) in command_blocks.items()
        }
        executable = validate_workflow_executable(
            document,
            validate_main_agent=validate_main_agent,
            commands=resolved_command_nodes,
            workflow_role=(workflow_snapshot or {}).get("workflow_role"),
        )
        if not executable.valid:
            issue = executable.issues[0]
            raise AgentRuntimeError(
                issue.code,
                issue.message,
                status_code=422,
                validation_report=executable,
            )
        workflow_context = {
            **dict(workflow_snapshot or {}),
            "graph": document.model_dump(mode="json"),
        }
        workflow_checkpoints = self._workflow_checkpoints
        runtime_diagnostics = getattr(self, "_runtime_diagnostics", None)
        workflow_identity = dict(workflow_snapshot or {})
        resolved_run_id = run_id or str(uuid4())
        workflow_id = str(workflow_identity.get("id", ""))
        workflow_name = str(
            workflow_identity.get("name", public_model or "workflow")
        )
        checkpointer_id = workflow_identity.get("checkpointer_id")
        checkpointer_component: CheckpointerBlock | None = None
        if checkpointer_id is not None:
            stored_checkpointer = (
                self._blocks.get_block_internal("checkpointer", str(checkpointer_id))
                if self._blocks is not None
                else None
            )
            if stored_checkpointer is None:
                raise AgentRuntimeError(
                    "workflow_checkpointer_not_found",
                    "The selected Checkpointer component does not exist.",
                    status_code=422,
                )
            try:
                checkpointer_component = CheckpointerBlock.model_validate(
                    {
                        key: value
                        for key, value in stored_checkpointer.items()
                        if key != "id"
                    }
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "workflow_checkpointer_invalid",
                    "The selected Checkpointer configuration is invalid.",
                    status_code=422,
                ) from exc
            checkpoint_thread_id = checkpoint_thread_id or str(uuid4())
        elif checkpoint_thread_id is not None:
            raise AgentRuntimeError(
                "workflow_checkpoint_thread_unexpected",
                "A checkpoint thread cannot be supplied when the Workflow has no Checkpointer.",
                status_code=422,
            )
        response_stream_policy = ResponseStreamPolicy()
        scheduling_id = workflow_identity.get("response_stream_scheduling_id")
        if scheduling_id is not None:
            stored_scheduling = (
                self._blocks.get_block_internal(
                    "response-stream-scheduling",
                    str(scheduling_id),
                )
                if self._blocks is not None
                else None
            )
            if stored_scheduling is None:
                raise AgentRuntimeError(
                    "workflow_response_stream_scheduling_not_found",
                    "The selected Response Stream Scheduling component does not exist.",
                    status_code=422,
                )
            try:
                scheduling = ResponseStreamSchedulingBlock.model_validate(
                    {
                        key: value
                        for key, value in stored_scheduling.items()
                        if key != "id"
                    }
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "workflow_response_stream_scheduling_invalid",
                    "The selected Response Stream Scheduling configuration is invalid.",
                    status_code=422,
                ) from exc
            response_stream_policy = ResponseStreamPolicy(
                queue=scheduling.queue.model_copy(deep=True)
            )
        owns_lifecycle = lifecycle_id is None
        if owns_lifecycle:
            resolved_lifecycle_id = await self._workflow_lifecycle.create(
                messages,
                request_id=request_id,
                run_id=resolved_run_id,
                checkpoint_thread_id=checkpoint_thread_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
            )
        else:
            if await self._workflow_lifecycle.input_record(lifecycle_id) is None:
                raise AgentRuntimeError(
                    "workflow_lifecycle_not_found",
                    "The Workflow lifecycle input does not exist.",
                    status_code=409,
                )
            resolved_lifecycle_id = lifecycle_id
        assembly_diagnostic_context = RuntimeDiagnosticContext(
            request_id=request_id,
            lifecycle_id=resolved_lifecycle_id,
            run_id=resolved_run_id,
            thread_id=checkpoint_thread_id,
            parent_workflow_id=(
                workflow_id if owns_lifecycle else ""
            ),
            parent_workflow_name=(
                workflow_name if owns_lifecycle else ""
            ),
            subject_kind="workflow",
            subject_id=workflow_id,
            subject_name=workflow_name,
        )
        self._register_run_observation(
            {
                "run_id": resolved_run_id,
                "lifecycle_id": resolved_lifecycle_id,
                "request_id": request_id,
                "checkpoint_thread_id": checkpoint_thread_id,
                "run_kind": "workflow",
                "target_id": workflow_id,
                "target_name": workflow_name,
                "parent_run_id": parent_run_id,
                "launcher_id": launcher_id,
                "background_task_id": background_task_id,
                "run_depth": run_depth,
            },
            context=assembly_diagnostic_context,
        )
        built_agents: list[tuple[str, BuiltAgent]] = []
        workflow_initial_files: dict[str, Any] = {}
        agent_event_output_runtime: EventOutputPackageRuntime | None = None
        workflow_event_output_runtime: EventOutputPackageRuntime | None = None
        agent_event_outputs: dict[str, EventOutputCallable] = {}
        agent_run_outputs: dict[str, EventRunOutputCallable | None] = {}
        workflow_event_output: EventOutputCallable | None = None
        workflow_run_output: EventRunOutputCallable | None = None
        command_runtime: CommandPackageRuntime | None = None
        commands: dict[str, Any] = {}
        workspace = None
        checkpoint_binding: WorkflowCheckpointBinding | None = None

        async def close_workflow_package_runtimes() -> None:
            if command_runtime is not None:
                await command_runtime.close()
            if agent_event_output_runtime is not None:
                await agent_event_output_runtime.close()
            if workflow_event_output_runtime is not None:
                await workflow_event_output_runtime.close()

        try:
            if checkpointer_component is not None:
                if workflow_checkpoints is None:
                    raise AgentRuntimeError(
                        "workflow_checkpointer_unavailable",
                        "The Workflow Checkpointer service is unavailable.",
                        status_code=500,
                    )
                try:
                    checkpointer = await workflow_checkpoints.require_checkpointer()
                except Exception as exc:
                    raise AgentRuntimeError(
                        "workflow_checkpointer_unavailable",
                        "The Workflow Checkpointer could not be initialized.",
                        status_code=500,
                    ) from exc
                assert checkpoint_thread_id is not None
                checkpoint_binding = WorkflowCheckpointBinding(
                    checkpointer=checkpointer,
                    checkpoint_thread_id=checkpoint_thread_id,
                    durability=checkpointer_component.durability,
                )
            resolved_agents: list[tuple[Any, StaticAssembly]] = []
            for agent_node in agent_nodes:
                main_agent_id = str(
                    AgentNodeConfig.model_validate(agent_node.config).main_agent_id
                )
                resolved_agents.append(
                    (
                        agent_node,
                        assemblies[main_agent_id],
                    )
                )
            context = WorkflowRuntimeContext.for_run(
                request_id=request_id,
                lifecycle_id=resolved_lifecycle_id,
                run_id=resolved_run_id,
                checkpoint_thread_id=checkpoint_thread_id,
                parent_run_id=parent_run_id,
                background_task_id=background_task_id,
                launcher_id=launcher_id,
                run_depth=run_depth,
                workflow=workflow_context,
                background_runtime=background_runtime,
            )

            output_id = (workflow_snapshot or {}).get("workflow_event_output_id")
            if (
                command_blocks
                or (public_output and (resolved_agents or output_id is not None))
            ):
                if self._python_packages_dir is None or self._runtime_dir is None:
                    raise AgentRuntimeError(
                        "workflow.python_package_runtime_unavailable",
                        "The Python package runtime is not configured.",
                        status_code=500,
                    )
            if public_output and resolved_agents:
                assert self._python_packages_dir is not None
                assert self._runtime_dir is not None
                agent_event_output_runtime = EventOutputPackageRuntime(
                    "agent",
                    request_id=request_id,
                    packages_dir=self._python_packages_dir,
                    runtime_root=self._runtime_dir,
                )
            if command_blocks:
                command_runtime = CommandPackageRuntime(
                    request_id=request_id,
                    packages_dir=self._python_packages_dir,
                    runtime_root=self._runtime_dir,
                )
                commands = {
                    node_id: command_runtime.command_for(
                        node_id,
                        command_id,
                        block.model_dump(mode="python")["python_package"],
                    )
                    for node_id, (command_id, block) in command_blocks.items()
                }
            if public_output and output_id is not None:
                stored_output = (
                    self._blocks.get_block_internal(
                        "workflow-event-output", str(output_id)
                    )
                    if self._blocks is not None
                    else None
                )
                if stored_output is None:
                    raise AgentRuntimeError(
                        "workflow_event_output_not_found",
                        "The selected event output component does not exist.",
                        status_code=422,
                    )
                try:
                    output_block = WorkflowEventOutputBlock.model_validate(
                        {
                            key: value
                            for key, value in stored_output.items()
                            if key != "id"
                        }
                    )
                except Exception as exc:
                    raise AgentRuntimeError(
                        "workflow.event_output_invalid",
                        "The selected Workflow event output configuration is invalid.",
                        status_code=422,
                    ) from exc
                assert self._python_packages_dir is not None
                assert self._runtime_dir is not None
                workflow_event_output_runtime = EventOutputPackageRuntime(
                    "workflow",
                    request_id=request_id,
                    packages_dir=self._python_packages_dir,
                    runtime_root=self._runtime_dir,
                )
                workflow_event_output = workflow_event_output_runtime.output_for(
                    str(workflow_identity.get("id", "")) or "workflow",
                    str(output_id),
                    output_block.python_package.model_dump(mode="json"),
                )
                workflow_run_output = workflow_event_output_runtime.run_output_for(
                    str(workflow_identity.get("id", "")) or "workflow",
                    str(output_id),
                    output_block.python_package.model_dump(mode="json"),
                )

            for agent_node, assembly in resolved_agents:
                mapped_directory_paths_by_filesystem = (
                    await self._resolved_mapped_directory_paths_by_filesystem(
                        resolved_lifecycle_id,
                        assembly,
                    )
                )
                built = await self.build_resolved_agent(
                    assembly,
                    messages,
                    model_response_observer=model_response_observer,
                    request_id=request_id,
                    workflow_node_id=agent_node.id,
                    workspace=workspace,
                    mapped_directory_paths_by_filesystem=(
                        mapped_directory_paths_by_filesystem
                    ),
                    workflow_debug_capture_enabled=(
                        runtime_policy.workflow_debug_capture_enabled
                    ),
                )
                built_agents.append((agent_node.id, built))
                if agent_event_output_runtime is not None:
                    agent_event_outputs[agent_node.id] = (
                        agent_event_output_runtime.output_for(
                            agent_node.id,
                            built.event_output_id,
                            built.event_output_reference,
                        )
                    )
                    agent_run_outputs[agent_node.id] = (
                        agent_event_output_runtime.run_output_for(
                            agent_node.id,
                            built.event_output_id,
                            built.event_output_reference,
                        )
                    )
                if workspace is None:
                    workspace = built.workspace
                for path, value in built.input_state.get("files", {}).items():
                    previous = workflow_initial_files.get(path)
                    if previous is not None and previous != value:
                        raise AgentRuntimeError(
                            "filesystem_virtual_source_conflict",
                            f"Workflow Agent virtual sources conflict at {path!r}.",
                            status_code=422,
                        )
                    workflow_initial_files[path] = value
            graph = compile_workflow(
                document,
                node_agents=dict(built_agents),
                commands=commands,
                workflow_role=(workflow_snapshot or {}).get("workflow_role"),
                checkpointer=(
                    checkpoint_binding.checkpointer
                    if checkpoint_binding is not None
                    else None
                ),
                store=self._workflow_lifecycle.store,
            )
        except asyncio.CancelledError:
            for _, agent in built_agents:
                await agent.tool_runtime.close()
                await agent.middleware_runtime.close()
            await close_workflow_package_runtimes()
            self._finish_run_observation(
                resolved_run_id,
                status="cancelled",
                error_code="request_cancelled",
                context=assembly_diagnostic_context,
            )
            if owns_lifecycle:
                await self._finish_parent_lifecycle(
                    resolved_lifecycle_id,
                    "cancelled",
                    context=assembly_diagnostic_context,
                )
            raise
        except Exception as exc:
            for _, agent in built_agents:
                await agent.tool_runtime.close()
                await agent.middleware_runtime.close()
            await close_workflow_package_runtimes()
            error_code = (
                exc.code
                if isinstance(exc, AgentRuntimeError)
                else "workflow_assembly_failed"
            )
            if runtime_diagnostics is not None:
                runtime_diagnostics.runtime_error(
                    exc,
                    code=error_code,
                    component="workflow_runtime",
                    context=assembly_diagnostic_context,
                )
            self._finish_run_observation(
                resolved_run_id,
                status="failed",
                error_code=error_code,
                context=assembly_diagnostic_context,
            )
            if owns_lifecycle:
                await self._finish_parent_lifecycle(
                    resolved_lifecycle_id,
                    "failed",
                    context=assembly_diagnostic_context,
                )
            raise
        first_node_id = built_agents[0][0] if built_agents else ""
        built = built_agents[0][1] if built_agents else None
        input_state: dict[str, Any] = {
            "shared_vars": deepcopy(dict(initial_shared_vars or {})),
            "agent_invocations": {},
            "background_tasks": {},
        }
        if initial_workflow_task is not None:
            input_state["workflow_task"] = deepcopy(dict(initial_workflow_task))
        if workflow_initial_files:
            input_state["files"] = workflow_initial_files

        async def cancel_background_children() -> None:
            if background_runtime is not None:
                await background_runtime.cancel_children_on_parent_termination(
                    resolved_lifecycle_id,
                    resolved_run_id,
                )

        return self._execution(
            built,
            graph=graph,
            input_state=input_state,
            workflow_node_id=first_node_id,
            workflow_built=tuple(built_agents),
            event_observer=event_observer,
            model_response_observer=model_response_observer,
            request_id=request_id,
            public_model=public_model,
            agent_event_outputs=agent_event_outputs,
            workflow_event_output=workflow_event_output,
            agent_run_outputs=agent_run_outputs,
            workflow_run_output=workflow_run_output,
            event_output_runtimes=tuple(
                runtime
                for runtime in (
                    agent_event_output_runtime,
                    workflow_event_output_runtime,
                )
                if runtime is not None
            ),
            context=context,
            run_config=_workflow_run_config(
                run_id=resolved_run_id,
                request_id=request_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                messages_sha=messages_sha,
                recursion_limit=int(
                    (workflow_snapshot or {}).get(
                        "recursion_limit", GRAPH_RECURSION_LIMIT
                    )
                ),
                max_concurrency=int(
                    (workflow_snapshot or {}).get(
                        "max_concurrency", WORKFLOW_MAX_CONCURRENCY
                    )
                ),
                checkpoint_thread_id=checkpoint_thread_id,
            ),
            execution_timeout_seconds=int(
                (workflow_snapshot or {}).get(
                    "execution_timeout_seconds",
                    EXECUTION_TIMEOUT_SECONDS,
                )
            ),
            cancel_background_children=(
                cancel_background_children if background_runtime is not None else None
            ),
            durability=(
                checkpoint_binding.durability
                if checkpoint_binding is not None
                else None
            ),
            owns_lifecycle=owns_lifecycle,
            public_output=public_output,
            command_runtime=command_runtime,
            response_stream_policy=response_stream_policy,
            response_scheduler=response_scheduler,
            response_consumer=response_consumer,
            workflow_debug_capture_enabled=(
                runtime_policy.workflow_debug_capture_enabled
            ),
        )
