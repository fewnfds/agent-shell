from __future__ import annotations

import asyncio
import warnings
from copy import deepcopy
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_shell.contracts import (
    FilesystemBlock,
    McpRequirementBlock,
    ResponseStreamSchedulingBlock,
)
from agent_shell.file_manager import FileManagerService
from agent_shell.runtime.agent_builder import AgentBuilder, BuiltAgent
from agent_shell.runtime.context import AgentRuntimeContext, WorkflowRuntimeContext
from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity
from agent_shell.middleware_packages.runtime import MiddlewarePackageRuntime
from agent_shell.command_packages import CommandPackageRuntime
from agent_shell.event_output_packages import (
    EventOutputCallable,
    EventRunOutputCallable,
    EventOutputPackageRuntime,
    EventSegmentEndCallable,
)
from agent_shell.tool_packages import ToolPackageRuntime
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.diagnostics import (
    RuntimeDiagnosticContext,
    RuntimeDiagnostics,
)
from agent_shell.runtime.event_origin import (
    ResolvedEventOrigin,
    RunEventOriginResolver,
    WorkflowNodeSource,
)
from agent_shell.runtime.event_stream import RunEventStream
from agent_shell.runtime.input_messages import client_messages_sha, validate_client_messages
from agent_shell.runtime.media_response import MainAgentMediaResponse
from agent_shell.runtime.output_projection import (
    EventOutputError,
    OutputProjector,
    WorkflowOutputProjector,
)
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.usage import RunUsageAccumulator
from agent_shell.runtime.response_scheduler import (
    LifecycleResponseScheduler,
    PresentationFrame,
    ResponseEventInput,
)
from agent_shell.runtime.response_presentation import (
    ResponseEvent,
    ResponseModelCallBoundary,
)
from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.stream_transformers import RawCustomEventTransformer
from agent_shell.storage.blocks import BlockStore
from agent_shell.runtime.workflow_data import WorkflowDataService
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.validation import validate_workflow_executable
from agent_shell.validation import ValidationReport
from agent_shell.validation.assembly import ResolvedMcpReference, StaticAssembly
from agent_shell.workflow_event_output import WorkflowEventOutputBlock
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import ToolCallTransformer
from langgraph.store.base import BaseStore


def _execution_stream_transformers(graph: Any) -> tuple[Any, ...]:
    """Add Shell projections without duplicating graph-owned transformers."""

    configured = tuple(getattr(graph, "stream_transformers", ()) or ())
    has_tool_calls = any(
        transformer is ToolCallTransformer
        or getattr(transformer, "__name__", "") == "ToolCallTransformer"
        for transformer in configured
    )
    return (
        (RawCustomEventTransformer,)
        if has_tool_calls
        else (RawCustomEventTransformer, ToolCallTransformer)
    )


def _workflow_construction_dependencies() -> tuple[Any, Any, Any]:
    from agent_shell.command import CommandBlock
    from agent_shell.workflow.catalog import CommandNodeConfig
    from agent_shell.workflow.compiler import compile_workflow

    return CommandNodeConfig, CommandBlock, compile_workflow


def _workflow_run_config(
    *,
    request_id: str,
    workflow_id: str,
    workflow_name: str,
    messages_sha: str,
    base_config: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = {
        "request_id": request_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "messages_sha": messages_sha,
    }
    config: dict[str, Any] = {
        **base_config,
        "run_name": f"workflow:{workflow_name}",
        "tags": ["agent-shell", "workflow"],
        "metadata": metadata,
    }
    return config


@dataclass(slots=True)
class RunExecution:
    graph: Any
    input_state: dict[str, Any]
    response_scheduler: LifecycleResponseScheduler | None
    media_response: MainAgentMediaResponse
    usage_accumulator: RunUsageAccumulator = field(default_factory=RunUsageAccumulator)
    event_stream: RunEventStream = field(init=False)
    origin_resolver: RunEventOriginResolver | None = None
    event_output_projector: OutputProjector | WorkflowOutputProjector | None = None
    response_consumer: bool = True
    middleware_runtimes: tuple[MiddlewarePackageRuntime, ...] = ()
    tool_runtimes: tuple[ToolPackageRuntime, ...] = ()
    command_runtime: CommandPackageRuntime | None = None
    event_output_runtimes: tuple[EventOutputPackageRuntime, ...] = ()
    identity: AgentRunIdentity | WorkflowRunIdentity | None = None
    context: AgentRuntimeContext | WorkflowRuntimeContext | None = None
    run_config: dict[str, Any] | None = None
    runtime_diagnostics: RuntimeDiagnostics | None = None
    request_id: str = ""
    public_model: str = ""
    public_output: bool = True
    cancel_run: Callable[[], Awaitable[None]] | None = None
    final_state: dict[str, Any] | None = None
    _started: bool = False
    _resources_closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.event_stream = RunEventStream(self.usage_accumulator)
        if (
            not self.public_output
            or self.identity is None
            or self.response_scheduler is None
        ):
            return
        register_origin = getattr(self.response_scheduler, "register_origin", None)
        if callable(register_origin):
            register_origin(
                self.identity.run_id,
                self.identity.subject_id,
            )

    @property
    def usage(self) -> dict[str, int]:
        return self.usage_accumulator.snapshot

    @property
    def finish_reason(self) -> str:
        return "stop"

    def diagnostic_context(self) -> RuntimeDiagnosticContext:
        identity = self.identity
        if identity is None:
            return RuntimeDiagnosticContext(
                request_id=self.request_id,
                subject_kind="workflow",
                subject_name=self.public_model,
            )
        return RuntimeDiagnosticContext(
            request_id=identity.request_id or self.request_id,
            lifecycle_id=identity.lifecycle_id,
            run_id=identity.run_id,
            thread_id=identity.thread_id,
            subject_kind=identity.graph_kind,
            subject_id=identity.subject_id,
            subject_name=identity.subject_name,
        )
    async def cancel(self) -> None:
        """Cancel this official Run when local stream consumption is interrupted."""

        if self.cancel_run is not None:
            try:
                await self.cancel_run()
            except Exception as exc:
                if self.runtime_diagnostics is not None:
                    await self.runtime_diagnostics.aobservation_error(
                        exc,
                        code="official_run_cancellation_failed",
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
            await self.close_resources()

    async def close_resources(self) -> None:
        """Release execution-only package resources exactly once."""

        if self._resources_closed:
            return
        self._resources_closed = True
        for runtime in self.middleware_runtimes:
            await runtime.close()
        for runtime in self.tool_runtimes:
            await runtime.close()
        if self.command_runtime is not None:
            await self.command_runtime.close()
        for runtime in self.event_output_runtimes:
            await runtime.close()

    async def _stream_text_inner(self) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()

        async def observation_error(
            exc: BaseException,
            code: str,
        ) -> None:
            if self.runtime_diagnostics is not None:
                await self.runtime_diagnostics.aobservation_error(
                    exc,
                    code=code,
                    component="observability",
                    context=self.diagnostic_context(),
                )

        async def cancel_official_run() -> None:
            if self.cancel_run is None:
                return
            try:
                await self.cancel_run()
            except Exception as exc:
                await observation_error(exc, "official_run_cancellation_failed")

        async def record_runtime_error(
            exc: BaseException,
            code: str,
            *,
            detail_exception: BaseException | None = None,
        ) -> None:
            if self.runtime_diagnostics is not None:
                await self.runtime_diagnostics.aruntime_error(
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
            if self.identity is None:
                return scheduler.origin_run_id, scheduler.origin_workflow_id
            return (
                self.identity.run_id,
                self.identity.subject_id,
            )

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
            event: ResponseEvent | ResponseModelCallBoundary,
            *,
            text: str = "",
            segment_end_text: str = "",
        ) -> list[str]:
            if not self.public_output:
                return []
            scheduler = self.response_scheduler
            assert scheduler is not None
            origin_run_id, origin_workflow_id = response_origin()
            if not scheduler.accepting(origin_run_id, origin_workflow_id):
                return []
            scheduler.publish(
                ResponseEventInput(
                    lifecycle_id=scheduler.lifecycle_id,
                    origin_run_id=origin_run_id,
                    origin_workflow_id=origin_workflow_id,
                    event=event,
                    text=text,
                    segment_end_text=segment_end_text,
                ),
                now=loop.time(),
            )
            return take_response_output()

        def project_run_event(
            phase: str,
            *,
            status: str,
            finish_reason: str = "",
            error_code: str = "",
        ) -> list[str]:
            if not self.public_output:
                return []
            scheduler = self.response_scheduler
            assert scheduler is not None
            origin_run_id, origin_workflow_id = response_origin()
            if not scheduler.accepting(origin_run_id, origin_workflow_id):
                return []
            run_event: dict[str, object] = {
                "type": "agent_shell.workflow_run",
                "phase": phase,
                "status": status,
                "finish_reason": finish_reason,
                "error_code": error_code,
            }
            projector = self.event_output_projector
            resolver = self.origin_resolver
            origin = resolver.run_origin() if resolver is not None else {}
            text = (
                projector.render_run(run_event, origin)
                if projector is not None
                else ""
            )
            scheduler.publish(
                ResponseEventInput(
                    lifecycle_id=scheduler.lifecycle_id,
                    origin_run_id=origin_run_id,
                    origin_workflow_id=origin_workflow_id,
                    event=ResponseEvent(
                        kind="lifecycle",
                        phase=phase,
                        namespace="root",
                        source_type="non_agent",
                        data=run_event,
                    ),
                    text=text,
                ),
                now=loop.time(),
            )
            return take_response_output()

        def event_origin(
            envelope: Mapping[str, object],
        ):
            resolver = self.origin_resolver
            if resolver is None:
                raise RuntimeError("Run event origin resolver is unavailable")
            return resolver.resolve(envelope)

        def render_protocol_event(
            envelope: Mapping[str, object],
            origin,
        ) -> str:
            projector = self.event_output_projector
            if projector is None:
                return ""
            return projector.render(envelope, origin.output)

        def render_protocol_segment_end(
            envelope: Mapping[str, object],
            origin,
        ) -> str:
            projector = self.event_output_projector
            if projector is None:
                return ""
            return projector.render_segment_end(envelope, origin.output)

        def project_deadline() -> list[str]:
            if not self.public_output or not self.response_consumer:
                return []
            scheduler = self.response_scheduler
            assert scheduler is not None
            scheduler.advance_published(now=loop.time())
            return take_response_output()

        def failure_output(error_code: str) -> list[str]:
            self.event_stream.close()
            if self.origin_resolver is not None:
                self.origin_resolver.close()
            scheduler = self.response_scheduler
            parts: list[str] = []
            if self.public_output and scheduler is not None:
                if self.response_consumer:
                    parts.extend(frame_text(scheduler.abort()))
            try:
                parts.extend(project_run_event(
                    "error",
                    status="failed",
                    finish_reason="error",
                    error_code=error_code,
                ))
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
                    scheduler.abort_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
            return parts

        try:
            for rendered in project_run_event("start", status="running"):
                if rendered:
                    yield rendered
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=(r"The v3 streaming protocol on Pregel is experimental\."),
                )
                config: dict[str, Any] = dict(self.run_config or {})
                stream_kwargs: dict[str, Any] = {
                    "config": config,
                    "version": "v3",
                    "transformers": _execution_stream_transformers(self.graph),
                }
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
                                    origin = event_origin(envelope)
                                    (
                                        stream_events,
                                        publish_raw_output,
                                    ) = self.event_stream.consume(envelope, origin)
                                    raw_text = ""
                                    if self.public_output:
                                        raw_text = render_protocol_event(
                                            envelope,
                                            origin,
                                        )
                                        if not publish_raw_output:
                                            raw_text = ""
                                    text_attached = False
                                    for event in stream_events:
                                        if isinstance(event, ResponseModelCallBoundary):
                                            projected = project_input(event)
                                        elif isinstance(event, MediaContentBlock):
                                            notification = (
                                                await self.media_response.project(event)
                                                if response_accepting()
                                                else None
                                            )
                                            projected = (
                                                project_input(
                                                    self.event_stream.media_notification(
                                                        origin,
                                                        event,
                                                    ),
                                                    text=notification,
                                                )
                                                if notification is not None
                                                else []
                                            )
                                        else:
                                            event_text = (
                                                raw_text if not text_attached else ""
                                            )
                                            text_attached = text_attached or bool(raw_text)
                                            segment_end_text = (
                                                render_protocol_segment_end(
                                                    envelope,
                                                    origin,
                                                )
                                                if event.kind == "content"
                                                and event.phase == "start"
                                                else ""
                                            )
                                            projected = project_input(
                                                event,
                                                text=event_text,
                                                segment_end_text=segment_end_text,
                                            )
                                        for rendered in projected:
                                            yield rendered
                                    if raw_text and not text_attached:
                                        params = envelope.get("params")
                                        data = (
                                            params.get("data")
                                            if isinstance(params, Mapping)
                                            else None
                                        )
                                        projected = project_input(
                                            self.event_stream.atomic(origin, data),
                                            text=raw_text,
                                        )
                                        for rendered in projected:
                                            yield rendered

                            if deadline_task is not None and deadline_task in done:
                                for rendered in project_deadline():
                                    yield rendered
                            elif wakeup_task is not None and wakeup_task in done:
                                for rendered in project_deadline():
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
                    self.event_stream.close()
                    if self.origin_resolver is not None:
                        self.origin_resolver.close()
                    for rendered in take_response_output():
                        if rendered:
                            yield rendered
            for rendered in project_run_event(
                "end",
                status="completed",
                finish_reason=self.finish_reason,
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
            self.event_stream.close()
            if self.origin_resolver is not None:
                self.origin_resolver.close()
            if self.response_scheduler is not None:
                if self.response_consumer:
                    self.response_scheduler.discard()
                elif self.public_output:
                    origin_run_id, origin_workflow_id = response_origin()
                    self.response_scheduler.abort_origin(
                        origin_run_id,
                        origin_workflow_id,
                        now=loop.time(),
                    )
            await self.cancel()
            raise
        except AgentRuntimeError as exc:
            for rendered in failure_output(exc.code):
                yield rendered
            await record_runtime_error(
                exc,
                exc.code,
                detail_exception=(
                    exc.__cause__ if isinstance(exc, EventOutputError) else None
                ),
            )
            await cancel_official_run()
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
            for rendered in failure_output(error.code):
                yield rendered
            await record_runtime_error(error, error.code, detail_exception=exc)
            await cancel_official_run()
            raise error from exc

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
        files: FileManagerService,
        *,
        blocks: BlockStore | None = None,
        python_packages_dir: Path | None = None,
        runtime_dir: Path | None = None,
        workflow_data: WorkflowDataService,
        runtime_diagnostics: RuntimeDiagnostics | None = None,
        run_config: Mapping[str, Any] | None = None,
        graph_store: BaseStore,
    ) -> None:
        self._builder = builder
        self._files = files
        self._blocks = blocks
        self._python_packages_dir = python_packages_dir
        self._runtime_dir = runtime_dir
        self._workflow_data = workflow_data
        self._runtime_diagnostics = runtime_diagnostics
        self._run_config = dict(run_config or {})
        self._graph_store = graph_store

    def build_workflow_structure(
        self,
        document: WorkflowGraphDocumentV1,
        *,
        workflow_snapshot: Mapping[str, Any],
        server_context: WorkflowRuntimeContext,
    ) -> Any:
        """Compile topology and schemas without opening execution resources."""

        from agent_shell.command import CommandBlock
        from agent_shell.workflow.catalog import CommandNodeConfig
        from agent_shell.workflow.compiler import compile_workflow

        async def unavailable_command(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(
                "structural Workflow graphs cannot execute Command nodes"
            )

        structural_commands: dict[str, Any] = {}
        validation_commands: dict[str, CommandBlock] = {}
        for node in document.definition.nodes:
            if node.type != "command":
                continue
            command_id = str(
                CommandNodeConfig.model_validate(node.config).command_id
            )
            stored = (
                self._blocks.get_block_internal("command", command_id)
                if self._blocks is not None
                else None
            )
            if stored is None:
                continue
            try:
                validation_commands[node.id] = CommandBlock.model_validate(
                    {key: value for key, value in stored.items() if key != "id"}
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "workflow.command_invalid",
                    "The selected Command Node configuration is invalid.",
                    status_code=422,
                ) from exc
            structural_commands[node.id] = unavailable_command

        executable = validate_workflow_executable(
            document,
            commands=validation_commands,
        )
        if not executable.valid:
            issue = executable.issues[0]
            raise AgentRuntimeError(
                issue.code,
                issue.message,
                status_code=422,
                validation_report=executable,
            )
        return compile_workflow(
            document,
            commands=structural_commands,
            store=self._graph_store,
            runtime_context=server_context,
        )

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

    def resolve_main_agent(self, main_agent_id: str) -> StaticAssembly:
        """Resolve one Main Agent without opening execution-only resources."""

        return self._builder.resolve(main_agent_id)

    async def build_main_agent_graph(
        self,
        main_agent_id: str,
        *,
        lifecycle_id: str,
        request_id: str = "",
    ) -> BuiltAgent:
        """Build a Main Agent as an Agent Server root graph."""

        assembly = await self._builder.aresolve(main_agent_id)
        mapped_directories = await self._resolved_mapped_directory_paths_by_filesystem(
            lifecycle_id,
            assembly,
        )
        mcp_runtime = await self._builder.discover_mcp(
            tuple(
                [*assembly.mcp_references]
                + [
                    reference
                    for subagent in assembly.subagent_nodes.values()
                    for reference in subagent.mcp_references
                ]
            )
        )
        self._builder.bind_mcp_runtime(mcp_runtime)
        return await self.build_resolved_agent(
            assembly,
            [],
            request_id=request_id,
            mapped_directory_paths_by_filesystem=mapped_directories,
            context_schema=AgentRuntimeContext,
        )

    def _resolved_command_mcp_references(
        self,
        command_id: str,
        command: Any,
    ) -> tuple[ResolvedMcpReference, ...]:
        references: list[ResolvedMcpReference] = []
        for reference in command.mcp_refs:
            requirement_id = str(reference.requirement_id)
            requirement = (
                self._blocks.get_block_internal("mcp-requirement", requirement_id)
                if self._blocks is not None
                else None
            )
            if requirement is None:
                raise AgentRuntimeError(
                    "configuration.reference_not_found",
                    "A Command references an MCP requirement that does not exist.",
                    status_code=422,
                )
            try:
                McpRequirementBlock.model_validate(
                    {key: value for key, value in requirement.items() if key != "id"}
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "assembly.referenced_block_invalid",
                    "A Command references an invalid MCP requirement.",
                    status_code=422,
                ) from exc
            references.append(
                ResolvedMcpReference(
                    reference=reference.model_dump(mode="json"),
                    requirement=requirement,
                )
            )
        return tuple(references)

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
                    await self._workflow_data.resolve_mapped_directories(
                        self._graph_store,
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

    def _workflow_execution(
        self,
        *,
        graph: Any,
        input_state: dict[str, Any],
        identity: WorkflowRunIdentity,
        context: WorkflowRuntimeContext,
        workflow_node_kinds: Mapping[str, str],
        request_id: str = "",
        public_model: str = "",
        workflow_event_output: EventOutputCallable | None = None,
        workflow_event_segment_end: EventSegmentEndCallable | None = None,
        workflow_run_output: EventRunOutputCallable | None = None,
        event_output_runtimes: tuple[EventOutputPackageRuntime, ...] = (),
        command_runtime: CommandPackageRuntime | None = None,
        run_config: dict[str, Any] | None = None,
        public_output: bool = True,
        response_stream_policy: ResponseStreamPolicy | None = None,
        response_scheduler: LifecycleResponseScheduler | None = None,
        response_consumer: bool = True,
    ) -> RunExecution:
        workflow_sources: dict[str, WorkflowNodeSource] = {}
        if public_output:
            projector = WorkflowOutputProjector(
                {},
                workflow_output=workflow_event_output,
                workflow_segment_end=workflow_event_segment_end,
                workflow_run_output=workflow_run_output,
            )
        else:
            projector = OutputProjector(None)
        node_kinds = dict(workflow_node_kinds)
        for node_id, node_type in node_kinds.items():
            if node_type == "command":
                workflow_sources[node_id] = WorkflowNodeSource(
                    source_type="script",
                    workflow_node_id=node_id,
                )
        scheduler_policy = (
            response_stream_policy.model_copy(deep=True)
            if response_stream_policy is not None
            else ResponseStreamPolicy()
        )
        lifecycle_identity = identity.lifecycle_id
        run_identity = identity.run_id
        workflow_identity = identity.workflow_id
        usage_accumulator = RunUsageAccumulator()
        origin_resolver = RunEventOriginResolver(
            identity,
            workflow_sources=workflow_sources,
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
            graph=graph,
            input_state=input_state,
            media_response=MainAgentMediaResponse(
                self._files,
                request_id,
            ),
            response_scheduler=effective_response_scheduler,
            usage_accumulator=usage_accumulator,
            origin_resolver=origin_resolver,
            event_output_projector=projector,
            response_consumer=response_consumer,
            command_runtime=command_runtime,
            event_output_runtimes=event_output_runtimes,
            identity=identity,
            context=context,
            run_config=run_config,
            runtime_diagnostics=self._runtime_diagnostics,
            request_id=request_id,
            public_model=public_model,
            public_output=public_output,
        )

    async def start_main_agent(
        self,
        main_agent_id: str,
        raw_messages: object,
        *,
        request_id: str,
        lifecycle_id: str,
        run_id: str,
        thread_id: str,
        assistant_id: str,
        public_model: str,
        caller_run_id: str = "",
        operation_id: str = "",
        public_output: bool = True,
        response_scheduler: LifecycleResponseScheduler | None = None,
        response_consumer: bool = True,
    ) -> RunExecution:
        """Materialize one Main Agent root Run around Server-owned execution."""

        messages = validate_client_messages(raw_messages)
        built: BuiltAgent | None = None
        output_runtime: EventOutputPackageRuntime | None = None
        try:
            built = await self.build_main_agent_graph(
                main_agent_id,
                lifecycle_id=lifecycle_id,
                request_id=request_id,
            )
            output_runtime = EventOutputPackageRuntime(
                "agent",
                request_id=request_id,
                packages_dir=self._python_packages_dir,
                runtime_root=self._runtime_dir,
            )

            def materialize_output() -> tuple[Any, Any]:
                assert built is not None
                assert output_runtime is not None
                return (
                    output_runtime.output_for(
                        built.agent_id,
                        built.event_output_id,
                        built.event_output_reference,
                    ),
                    output_runtime.segment_end_for(
                        built.agent_id,
                        built.event_output_id,
                        built.event_output_reference,
                    ),
                )

            output, segment_end = await asyncio.to_thread(materialize_output)
        except BaseException:
            if built is not None:
                if built.tool_runtime is not None:
                    await built.tool_runtime.close()
                await built.middleware_runtime.close()
            if output_runtime is not None:
                await output_runtime.close()
            raise

        identity = AgentRunIdentity(
            request_id=request_id,
            lifecycle_id=lifecycle_id,
            run_id=run_id,
            main_agent_id=built.agent_id,
            main_agent_name=built.agent_name,
            thread_id=thread_id,
            assistant_id=assistant_id,
            caller_run_id=caller_run_id,
            operation_id=operation_id,
        )
        scheduler = response_scheduler or LifecycleResponseScheduler(
            ResponseStreamPolicy(),
            lifecycle_id=lifecycle_id,
            origin_run_id=run_id,
            origin_workflow_id=built.agent_id,
        )
        return RunExecution(
            graph=built.graph,
            input_state={"messages": messages},
            media_response=MainAgentMediaResponse(self._files, request_id),
            response_scheduler=scheduler,
            origin_resolver=RunEventOriginResolver(
                identity,
                main_agent_names=(built.agent_name,),
                root_agent_profile_id=built.agent_id,
                root_subagent_profile_ids=built.subagent_profile_ids,
            ),
            event_output_projector=OutputProjector(
                output,
                segment_end=segment_end,
            ),
            response_consumer=response_consumer,
            middleware_runtimes=(built.middleware_runtime,),
            tool_runtimes=(
                (built.tool_runtime,) if built.tool_runtime is not None else ()
            ),
            event_output_runtimes=(output_runtime,),
            identity=identity,
            context=AgentRuntimeContext.for_run(identity),
            run_config={
                **self._run_config,
                "run_name": f"agent:{built.agent_name}",
                "tags": ["agent-shell", "agent"],
                "metadata": {
                    "request_id": request_id,
                    "main_agent_id": built.agent_id,
                    "main_agent_name": built.agent_name,
                    "messages_sha": client_messages_sha(messages),
                },
            },
            runtime_diagnostics=self._runtime_diagnostics,
            request_id=request_id,
            public_model=public_model,
            public_output=public_output,
        )

    async def start_workflow(
        self,
        document: WorkflowGraphDocumentV1,
        raw_messages: object,
        *,
        workflow_snapshot: Mapping[str, Any] | None = None,
        request_id: str = "",
        public_model: str = "",
        lifecycle_id: str | None = None,
        run_id: str | None = None,
        thread_id: str = "",
        assistant_id: str = "",
        caller_run_id: str = "",
        operation_id: str = "",
        initial_shared_vars: Mapping[str, Any] | None = None,
        agent_run_runtime: Any | None = None,
        workflow_run_runtime: Any | None = None,
        public_output: bool = True,
        response_scheduler: LifecycleResponseScheduler | None = None,
        response_consumer: bool = True,
        server_context: WorkflowRuntimeContext | None = None,
    ) -> RunExecution:
        (
            CommandNodeConfig,
            CommandBlock,
            compile_workflow,
        ) = await asyncio.to_thread(_workflow_construction_dependencies)

        command_nodes = [
            node for node in document.definition.nodes if node.type == "command"
        ]
        server_managed = server_context is not None
        messages = (
            [] if server_managed else validate_client_messages(raw_messages)
        )
        messages_sha = client_messages_sha(messages)

        command_blocks: dict[str, tuple[str, CommandBlock]] = {}
        for command_node in command_nodes:
            command_id = str(
                CommandNodeConfig.model_validate(command_node.config).command_id
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
                        {
                            key: value
                            for key, value in stored_command.items()
                            if key != "id"
                        }
                    ),
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "workflow.command_invalid",
                    "The selected Command Node configuration is invalid.",
                    status_code=422,
                ) from exc

        executable = validate_workflow_executable(
            document,
            commands={
                node_id: block
                for node_id, (_command_id, block) in command_blocks.items()
            },
        )
        if not executable.valid:
            issue = executable.issues[0]
            raise AgentRuntimeError(
                issue.code,
                issue.message,
                status_code=422,
                validation_report=executable,
            )

        runtime_diagnostics = getattr(self, "_runtime_diagnostics", None)
        workflow_identity = dict(workflow_snapshot or {})
        resolved_run_id = run_id or ("" if server_managed else str(uuid4()))
        workflow_id = str(workflow_identity.get("id", ""))
        workflow_name = str(
            workflow_identity.get("name", public_model or "workflow")
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

        if server_context is not None:
            resolved_lifecycle_id = server_context.lifecycle_id
            if (
                server_context.workflow_id
                and server_context.workflow_id != workflow_id
            ):
                raise AgentRuntimeError(
                    "workflow.identity_mismatch",
                    "The Server Run context does not match the selected Workflow.",
                    status_code=409,
                )
        else:
            resolved_lifecycle_id = lifecycle_id or str(uuid4())

        identity = WorkflowRunIdentity(
            request_id=request_id,
            lifecycle_id=resolved_lifecycle_id,
            run_id=resolved_run_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            thread_id=thread_id,
            assistant_id=assistant_id,
            caller_run_id=caller_run_id,
            operation_id=operation_id,
        )
        diagnostic_context = RuntimeDiagnosticContext(
            request_id=request_id,
            lifecycle_id=resolved_lifecycle_id,
            run_id=resolved_run_id,
            thread_id=thread_id,
            subject_kind="workflow",
            subject_id=workflow_id,
            subject_name=workflow_name,
        )

        command_runtime: CommandPackageRuntime | None = None
        workflow_event_output_runtime: EventOutputPackageRuntime | None = None
        workflow_event_output: EventOutputCallable | None = None
        workflow_event_segment_end: EventSegmentEndCallable | None = None
        workflow_run_output: EventRunOutputCallable | None = None
        commands: dict[str, Any] = {}

        async def close_package_runtimes() -> None:
            if command_runtime is not None:
                await command_runtime.close()
            if workflow_event_output_runtime is not None:
                await workflow_event_output_runtime.close()

        try:
            command_mcp_references = {
                node_id: self._resolved_command_mcp_references(command_id, block)
                for node_id, (command_id, block) in command_blocks.items()
            }
            all_mcp_references = tuple(
                reference
                for references in command_mcp_references.values()
                for reference in references
            )
            mcp_runtime = await self._builder.discover_mcp(all_mcp_references)
            self._builder.bind_mcp_runtime(mcp_runtime)
            mcp_commands_by_node = (
                {
                    node_id: mcp_runtime.commands_for(references)
                    for node_id, references in command_mcp_references.items()
                    if references
                }
                if mcp_runtime is not None
                else {}
            )
            context = (
                server_context.with_runtime_bindings(
                    agent_run_runtime=agent_run_runtime,
                    workflow_run_runtime=workflow_run_runtime,
                    mcp_commands_by_node=mcp_commands_by_node,
                )
                if server_context is not None
                else WorkflowRuntimeContext.for_run(
                    identity=identity,
                    agent_run_runtime=agent_run_runtime,
                    workflow_run_runtime=workflow_run_runtime,
                    mcp_commands_by_node=mcp_commands_by_node,
                )
            )

            output_id = workflow_identity.get("workflow_event_output_id")
            if command_blocks or (public_output and output_id is not None):
                if self._python_packages_dir is None or self._runtime_dir is None:
                    raise AgentRuntimeError(
                        "workflow.python_package_runtime_unavailable",
                        "The Python package runtime is not configured.",
                        status_code=500,
                    )

            if command_blocks:
                assert self._python_packages_dir is not None
                assert self._runtime_dir is not None
                command_runtime = CommandPackageRuntime(
                    request_id=request_id,
                    packages_dir=self._python_packages_dir,
                    runtime_root=self._runtime_dir,
                )

                def materialize_commands() -> dict[str, Any]:
                    assert command_runtime is not None
                    return {
                        node_id: command_runtime.command_for(
                            node_id,
                            command_id,
                            block.model_dump(mode="python")["python_package"],
                        )
                        for node_id, (command_id, block) in command_blocks.items()
                    }

                commands = await asyncio.to_thread(materialize_commands)

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
                        "The selected Workflow event output component does not exist.",
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

                def materialize_workflow_event_output() -> tuple[Any, Any, Any]:
                    assert workflow_event_output_runtime is not None
                    binding_id = workflow_id or "workflow"
                    reference = output_block.python_package.model_dump(mode="json")
                    return (
                        workflow_event_output_runtime.output_for(
                            binding_id,
                            str(output_id),
                            reference,
                        ),
                        workflow_event_output_runtime.segment_end_for(
                            binding_id,
                            str(output_id),
                            reference,
                        ),
                        workflow_event_output_runtime.workflow_run_output_for(
                            binding_id,
                            str(output_id),
                            reference,
                        ),
                    )

                (
                    workflow_event_output,
                    workflow_event_segment_end,
                    workflow_run_output,
                ) = await asyncio.to_thread(materialize_workflow_event_output)

            graph = await asyncio.to_thread(
                compile_workflow,
                document,
                commands=commands,
                store=self._graph_store,
                runtime_context=(context if server_managed else None),
            )
        except asyncio.CancelledError:
            await close_package_runtimes()
            raise
        except Exception as exc:
            await close_package_runtimes()
            error_code = (
                exc.code
                if isinstance(exc, AgentRuntimeError)
                else "workflow_assembly_failed"
            )
            if runtime_diagnostics is not None:
                await runtime_diagnostics.aruntime_error(
                    exc,
                    code=error_code,
                    component="workflow_runtime",
                    context=diagnostic_context,
                )
            raise

        return self._workflow_execution(
            graph=graph,
            input_state={
                "shared_vars": deepcopy(dict(initial_shared_vars or {})),
            },
            request_id=request_id,
            public_model=public_model,
            workflow_event_output=workflow_event_output,
            workflow_event_segment_end=workflow_event_segment_end,
            workflow_run_output=workflow_run_output,
            event_output_runtimes=(
                (workflow_event_output_runtime,)
                if workflow_event_output_runtime is not None
                else ()
            ),
            identity=identity,
            context=context,
            workflow_node_kinds={
                node.id: node.type
                for node in document.definition.nodes
                if node.type == "command"
            },
            run_config=_workflow_run_config(
                request_id=request_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                messages_sha=messages_sha,
                base_config=getattr(self, "_run_config", {}),
            ),
            public_output=public_output,
            command_runtime=command_runtime,
            response_stream_policy=response_stream_policy,
            response_scheduler=response_scheduler,
            response_consumer=response_consumer,
        )
