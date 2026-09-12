from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.store.base import BaseStore
from langgraph_sdk import get_client

from agent_shell.file_manager import FileManagerService
from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.python_packages.validation import PythonPackageValidationService
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.provider_secrets import ProviderSecretResolver
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_assistants import main_agent_assistant_id
from agent_shell.runtime.agent_run_calls import AgentRunHandle, AgentRunSnapshot
from agent_shell.runtime.agent_runtime import AgentRuntime, RunExecution
from agent_shell.runtime.detached_tasks import DetachedTaskManager
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.errors import (
    AgentRuntimeError,
    decode_server_run_error,
    describe_exception,
)
from agent_shell.runtime.input_messages import client_messages_sha, validate_client_messages
from agent_shell.runtime.langgraph_lifecycle import LangGraphLifecycleService
from agent_shell.runtime.lifecycle_configuration import (
    LIFECYCLE_CONFIGURATION_SCHEMA_VERSION,
    LifecycleConfigurationSnapshot,
)
from agent_shell.runtime.response_scheduler import LifecycleResponseScheduler
from agent_shell.runtime.run_calls import (
    ACTIVE_RUN_STATUSES,
    GraphRunCallRelation,
    RunCaller,
    RunStatus,
    official_status,
    relation_key,
    save_lifecycle_run_relation,
    search_lifecycle_run_relations,
    select_run_relations,
)
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_CONFIGURATION_KEY,
    LIFECYCLE_INPUT_KEY,
    LIFECYCLE_RECORD_KEY,
    LIFECYCLE_START_ERROR_KEY,
    LifecycleRecord,
    lifecycle_configuration_namespace,
    lifecycle_input_namespace,
    lifecycle_record_namespace,
)
from agent_shell.runtime.workflow_data import WorkflowDataService
from agent_shell.runtime.workflow_run_calls import (
    WorkflowRunHandle,
    WorkflowRunSnapshot,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import McpResourceSnapshot, McpResourceStore
from agent_shell.storage.model_connections import ModelResourceSnapshot, ModelResourceStore
from agent_shell.storage.workflow_lifecycle_settings import (
    WorkflowLifecycleSettingsStore,
)
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.workflow import WorkflowGraphDocumentV1


LANGGRAPH_WORKFLOW_GRAPH_ID = "agent-shell-workflow"
LANGGRAPH_AGENT_GRAPH_ID = "agent-shell-agent"


async def _ensure_assistant(
    assistants: Any,
    graph_id: str,
    *,
    name: str,
    **create_kwargs: Any,
) -> Mapping[str, Any]:
    """Create a stable Assistant and keep its user-facing name current."""

    assistant = await assistants.create(
        graph_id,
        **create_kwargs,
        if_exists="do_nothing",
        name=name,
    )
    if assistant.get("name") == name:
        return assistant
    return await assistants.update(
        str(assistant["assistant_id"]),
        name=name,
    )


def _root_terminal_status(event: Mapping[str, object]) -> str:
    """Return the entry Run's own terminal status, or "" for any other event.

    Official ``lifecycle`` events for the Run's nested graphs and node
    invocations share the same root stream; their identity is carried in
    ``data.namespace``. Only an event without a nested namespace describes the
    root Run, so a nested interruption never ends the request subscription.
    """

    if event.get("method") != "lifecycle":
        return ""
    params = event.get("params")
    if not isinstance(params, Mapping) or params.get("namespace") not in (None, []):
        return ""
    data = params.get("data")
    if not isinstance(data, Mapping) or data.get("namespace") not in (None, []):
        return ""
    status = str(data.get("event") or "")
    return status if status in {
        "completed",
        "failed",
        "error",
        "interrupted",
        "cancelled",
        "timeout",
        "timed_out",
    } else ""


def _root_run_error(event: Mapping[str, object]) -> AgentRuntimeError:
    params = event.get("params")
    data = params.get("data") if isinstance(params, Mapping) else None
    raw_error = data.get("error") if isinstance(data, Mapping) else None
    decoded = decode_server_run_error(raw_error)
    if decoded is not None:
        return decoded
    if isinstance(raw_error, str) and raw_error:
        message = raw_error
    elif raw_error is not None:
        message = f"{type(raw_error).__name__}: {raw_error!r}"
    else:
        message = "The official Run failed without an error detail."
    return AgentRuntimeError(
        "official_run_failed",
        message,
        status_code=502,
        decoded_from_server=True,
    )


def _project_root_run_error(
    event: Mapping[str, object],
    error: AgentRuntimeError,
) -> Mapping[str, object]:
    params = event.get("params")
    if not isinstance(params, Mapping):
        return event
    data = params.get("data")
    if not isinstance(data, Mapping):
        return event
    projected_data = dict(data)
    projected_data["error"] = error.message
    projected_data["error_code"] = error.code
    if error.source_exception_type:
        projected_data["exception_type"] = error.source_exception_type
    return {
        **event,
        "params": {
            **params,
            "data": projected_data,
        },
    }


class _OfficialRunEventStream:
    """Expose one official Protocol v2 stream to the existing projector."""

    def __init__(
        self,
        events: AsyncIterator[Mapping[str, object]],
        coordinator: LifecycleRunCoordinator,
        thread_id: str,
    ) -> None:
        self._events = events
        self._coordinator = coordinator
        self._thread_id = thread_id
        self.terminal_status = ""

    async def __aenter__(self) -> _OfficialRunEventStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._coordinator.close_official_session(self._thread_id)

    def __aiter__(self) -> AsyncIterator[Mapping[str, object]]:
        return self._until_terminal()

    async def _until_terminal(self) -> AsyncIterator[Mapping[str, object]]:
        async for event in self._events:
            status = _root_terminal_status(event)
            if status:
                # Fix the Run's own terminal state before the projector sees it
                # so the response layer can name how the Run actually ended.
                self.terminal_status = status
            error = (
                _root_run_error(event)
                if status in {"failed", "error"}
                else None
            )
            yield (
                _project_root_run_error(event, error)
                if error is not None
                else event
            )
            if status:
                if error is not None:
                    raise error
                if status in {"timeout", "timed_out"}:
                    raise TimeoutError("The official Workflow Run timed out.")
                # `interrupted` and `cancelled` are ordinary official terminal
                # states: they end this subscription like `completed`. Raising
                # `CancelledError` here would be read as a cancellation of the
                # local consumer, and the response would never be sealed.
                return

    async def output(self) -> object:
        return await self._coordinator.official_output(self._thread_id)


class _OfficialRunEventGraph:
    """Keep RunExecution's projector while Agent Server owns Graph execution."""

    def __init__(self, stream: _OfficialRunEventStream) -> None:
        self._stream = stream

    @property
    def terminal_status(self) -> str:
        return self._stream.terminal_status

    async def astream_events(self, *_args: object, **_kwargs: object) -> object:
        return self._stream


@dataclass(slots=True)
class _RunBinding:
    workflow: Mapping[str, Any]
    document: WorkflowGraphDocumentV1
    request_id: str
    lifecycle_id: str
    public_model: str
    caller_run_id: str = ""
    operation_id: str = ""
    thread_id: str = ""
    assistant_id: str = ""
    run_id: str = ""
    initial_shared_vars: Mapping[str, Any] = field(default_factory=dict)
    response_consumer: bool = False
    run_id_ready: asyncio.Future[str] | None = None
    execution_ready: asyncio.Future[RunExecution] | None = None
    protocol_stream: _OfficialRunEventStream | None = None

    @property
    def key(self) -> str:
        return relation_key(self.caller_run_id, self.operation_id)


@dataclass(slots=True)
class _OfficialSession:
    client: Any
    stream: Any


@dataclass(slots=True)
class _AgentRunBinding:
    main_agent: Mapping[str, Any]
    messages: list[dict[str, Any]]
    request_id: str
    lifecycle_id: str
    public_model: str
    caller_run_id: str = ""
    operation_id: str = ""
    thread_id: str = ""
    assistant_id: str = ""
    run_id: str = ""
    response_consumer: bool = False
    run_id_ready: asyncio.Future[str] | None = None
    execution_ready: asyncio.Future[RunExecution] | None = None
    protocol_stream: _OfficialRunEventStream | None = None

    @property
    def key(self) -> str:
        return relation_key(self.caller_run_id, self.operation_id)


@dataclass(frozen=True, slots=True)
class RequestRuntimeSnapshot:
    """Immutable configuration catalog and runtime materialization inputs."""

    _workflows: WorkflowStore
    _agents: AgentConfigStore
    _runtime_factory: Callable[[BaseStore | None], AgentRuntime]
    _response_stream_policy: ResponseStreamPolicy
    _configuration: dict[str, Any] = field(default_factory=dict)
    _run_config: dict[str, Any] = field(default_factory=dict)

    def workflow_by_name(self, name: str) -> dict[str, Any] | None:
        return self._workflows.get_item_by_name(name)

    def main_agent_by_name(self, name: str) -> dict[str, Any] | None:
        return self._agents.get_item_by_name("main_agents", name)

    def main_agent_by_id(self, main_agent_id: str) -> dict[str, Any] | None:
        return self._agents.get_item("main_agents", main_agent_id)

    def workflow_by_id(self, workflow_id: str) -> dict[str, Any] | None:
        return self._workflows.get_item(workflow_id)

    def workflow_document(self, workflow_id: str) -> WorkflowGraphDocumentV1 | None:
        return self._workflows.get_graph(workflow_id)

    async def new_runtime(self, *, store: BaseStore) -> AgentRuntime:
        return await asyncio.to_thread(self._runtime_factory, store)

    def response_stream_policy(self) -> ResponseStreamPolicy:
        return self._response_stream_policy.model_copy(deep=True)

    def run_config(self) -> dict[str, Any]:
        return deepcopy(self._run_config)

    def lifecycle_configuration(
        self,
        *,
        graph_kind: str,
        resource_id: str,
    ) -> LifecycleConfigurationSnapshot:
        return LifecycleConfigurationSnapshot.model_validate(
            {
                **deepcopy(self._configuration),
                "entry_graph": {
                    "graph_kind": graph_kind,
                    "resource_id": resource_id,
                },
            }
        )


@dataclass(slots=True)
class LifecycleRunCoordinator:
    """Coordinate one request Lifecycle while Agent Server owns every Run."""

    _owner: RequestSnapshotRuntime
    _snapshot: RequestRuntimeSnapshot
    _detached_tasks: DetachedTaskManager
    _response_scheduler: LifecycleResponseScheduler | None = field(
        default=None,
        init=False,
    )
    _lifecycle_id: str = field(default="", init=False)
    _lifecycle_created_at: datetime | None = field(default=None, init=False)
    _bindings: dict[str, _RunBinding] = field(default_factory=dict, init=False)
    _agent_bindings: dict[str, _AgentRunBinding] = field(
        default_factory=dict,
        init=False,
    )
    _sessions: dict[str, _OfficialSession] = field(default_factory=dict, init=False)
    _relations: dict[str, GraphRunCallRelation] = field(
        default_factory=dict,
        init=False,
    )
    _detached_run_ids: set[str] = field(default_factory=set, init=False)
    _disconnected: bool = field(default=False, init=False)
    _response_terminated: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
    )

    @property
    def lifecycle_id(self) -> str:
        return self._lifecycle_id

    @property
    def response_terminated(self) -> asyncio.Event:
        """Signal the in-flight request-entry response to stop streaming."""

        return self._response_terminated

    def response_terminated_flag(self) -> bool:
        """Report whether an explicit Lifecycle cancel already stopped the response."""

        return self._response_terminated.is_set()

    def _begin_lifecycle(self, lifecycle_id: str) -> None:
        if self._lifecycle_id or self._response_scheduler is not None:
            raise RuntimeError("the request Lifecycle has already started")
        self._lifecycle_id = lifecycle_id
        self._lifecycle_created_at = datetime.now(timezone.utc)
        self._response_scheduler = LifecycleResponseScheduler(
            self._snapshot.response_stream_policy(),
            lifecycle_id=lifecycle_id,
        )

    def _lifecycle_record(
        self,
        *,
        graph_kind: str,
        resource_id: str,
        resource_name: str,
        request_id: str,
    ) -> LifecycleRecord:
        if self._lifecycle_created_at is None:
            raise RuntimeError("the request Lifecycle has not started")
        return LifecycleRecord.model_validate(
            {
                "lifecycle_id": self._lifecycle_id,
                "request_id": request_id,
                "created_at": self._lifecycle_created_at,
                "entry_subject": {
                    "graph_kind": graph_kind,
                    "id": resource_id,
                    "name": resource_name,
                },
            }
        )

    async def _persist_lifecycle_record(
        self,
        record: LifecycleRecord,
    ) -> None:
        async with self._owner.new_agent_server_client() as client:
            namespace = lifecycle_record_namespace(self._lifecycle_id)
            existing = await client.store.get_item(namespace, LIFECYCLE_RECORD_KEY)
            if existing is not None:
                raise RuntimeError("the Lifecycle record already exists")
            await client.store.put_item(
                namespace,
                LIFECYCLE_RECORD_KEY,
                record.as_store_value(),
                index=False,
            )

    async def _persist_configuration(
        self,
        *,
        graph_kind: str,
        resource_id: str,
    ) -> None:
        value = self._snapshot.lifecycle_configuration(
            graph_kind=graph_kind,
            resource_id=resource_id,
        ).as_store_value()
        async with self._owner.new_agent_server_client() as client:
            namespace = lifecycle_configuration_namespace(self._lifecycle_id)
            existing = await client.store.get_item(
                namespace,
                LIFECYCLE_CONFIGURATION_KEY,
            )
            if existing is not None:
                raise RuntimeError("the Lifecycle configuration snapshot already exists")
            await client.store.put_item(
                namespace,
                LIFECYCLE_CONFIGURATION_KEY,
                value,
                index=False,
            )

    async def _record_entry_start_failure(
        self,
        exc: Exception,
        *,
        graph_kind: str,
        subject_id: str,
        subject_name: str,
        request_id: str,
        thread_id: str,
        lifecycle_record: LifecycleRecord,
    ) -> None:
        detail = describe_exception(exc)
        context = RuntimeDiagnosticContext(
            request_id=request_id,
            lifecycle_id=self._lifecycle_id,
            thread_id=thread_id,
            subject_kind=graph_kind,
            subject_id=subject_id,
            subject_name=subject_name,
        )
        marker = {
            "status": "error",
            "code": "run_start_failed",
            "message": detail,
            "exception_type": (
                exc.source_exception_type
                if isinstance(exc, AgentRuntimeError) and exc.source_exception_type
                else type(exc).__name__
            ),
            "occurred_at": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "request_id": request_id,
            "graph_kind": graph_kind,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "thread_id": thread_id,
        }
        try:
            async with self._owner.new_agent_server_client() as client:
                record_item = await client.store.get_item(
                    lifecycle_record_namespace(self._lifecycle_id),
                    LIFECYCLE_RECORD_KEY,
                )
                if record_item is not None:
                    stored_record = LifecycleRecord.model_validate(
                        record_item.get("value")
                        if isinstance(record_item, Mapping)
                        else None
                    )
                    if stored_record != lifecycle_record:
                        raise RuntimeError("the persisted Lifecycle record changed")
                    await client.store.put_item(
                        lifecycle_input_namespace(self._lifecycle_id),
                        LIFECYCLE_START_ERROR_KEY,
                        marker,
                        index=False,
                    )
        except Exception as marker_error:
            with suppress(Exception):
                await self._owner.runtime_diagnostics.aobservation_error(
                    marker_error,
                    code="lifecycle_start_error_persistence_failed",
                    component="observability",
                    context=context,
                )
        with suppress(Exception):
            await self._owner.runtime_diagnostics.aruntime_error(
                AgentRuntimeError("run_start_failed", detail),
                code="run_start_failed",
                component="graph_runtime",
                context=context,
                detail_exception=exc,
            )

    async def start_workflow(
        self,
        workflow: Mapping[str, Any],
        raw_messages: object,
        **kwargs: Any,
    ) -> RunExecution:
        request_id = str(kwargs.pop("request_id", ""))
        public_model = str(kwargs.pop("public_model", workflow["name"]))
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"unexpected request Run arguments: {unexpected}")
        messages = validate_client_messages(raw_messages)
        lifecycle_id = str(uuid4())
        self._begin_lifecycle(lifecycle_id)
        binding = self._new_binding(
            workflow,
            request_id=request_id,
            lifecycle_id=lifecycle_id,
            public_model=public_model,
            response_consumer=True,
        )
        self._bindings[binding.key] = binding
        self._owner.register_active_lifecycle(self)
        lifecycle_record = self._lifecycle_record(
            graph_kind="workflow",
            resource_id=str(workflow["id"]),
            resource_name=str(workflow["name"]),
            request_id=request_id,
        )
        try:
            await self._persist_lifecycle_record(lifecycle_record)
            await self._persist_configuration(
                graph_kind="workflow",
                resource_id=str(workflow["id"]),
            )
            client, thread_stream = await self._open_run_session(binding)
            await client.store.put_item(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
                {
                    "messages": deepcopy(messages),
                    "messages_sha": client_messages_sha(messages),
                    "metadata": {
                        "lifecycle_id": lifecycle_id,
                        "request_id": request_id,
                        "workflow_id": str(workflow["id"]),
                        "workflow_name": str(workflow["name"]),
                    },
                },
                index=False,
            )
            result = await self._start_bound_run(binding, thread_stream)
            self._bind_official_run_id(binding, result)
            await self._record_relation(
                client,
                self._workflow_relation(binding),
            )
            assert binding.execution_ready is not None
            return await binding.execution_ready
        except BaseException as exc:
            self._cancel_binding_futures(binding)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            if isinstance(exc, Exception):
                with suppress(Exception):
                    await self._record_entry_start_failure(
                        exc,
                        graph_kind="workflow",
                        subject_id=str(workflow["id"]),
                        subject_name=str(workflow["name"]),
                        request_id=request_id,
                        thread_id=binding.thread_id,
                        lifecycle_record=lifecycle_record,
                    )
            self._release_if_finished()
            raise

    async def start_agent(
        self,
        main_agent: Mapping[str, Any],
        raw_messages: object,
        **kwargs: Any,
    ) -> RunExecution:
        """Start one request-entry Main Agent as an official root Run."""

        request_id = str(kwargs.pop("request_id", ""))
        public_model = str(kwargs.pop("public_model", main_agent["name"]))
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"unexpected request Run arguments: {unexpected}")
        messages = validate_client_messages(raw_messages)
        lifecycle_id = str(uuid4())
        self._begin_lifecycle(lifecycle_id)
        loop = asyncio.get_running_loop()
        binding = _AgentRunBinding(
            main_agent=main_agent,
            messages=messages,
            request_id=request_id,
            lifecycle_id=lifecycle_id,
            public_model=public_model,
            response_consumer=True,
            run_id_ready=loop.create_future(),
            execution_ready=loop.create_future(),
        )
        self._agent_bindings[binding.key] = binding
        self._owner.register_active_lifecycle(self)
        lifecycle_record = self._lifecycle_record(
            graph_kind="agent",
            resource_id=str(main_agent["id"]),
            resource_name=str(main_agent["name"]),
            request_id=request_id,
        )
        client: Any | None = None
        try:
            await self._persist_lifecycle_record(lifecycle_record)
            await self._persist_configuration(
                graph_kind="agent",
                resource_id=str(main_agent["id"]),
            )
            client, thread_stream = await self._open_agent_run_session(binding)
            await client.store.put_item(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
                {
                    "messages": deepcopy(messages),
                    "messages_sha": client_messages_sha(messages),
                    "metadata": {
                        "lifecycle_id": lifecycle_id,
                        "request_id": request_id,
                        "graph_kind": "agent",
                        "main_agent_id": str(main_agent["id"]),
                        "main_agent_name": str(main_agent["name"]),
                    },
                },
                index=False,
            )
            result = await self._start_bound_agent_run(binding, thread_stream)
            run_id = self._run_id_from_result(result, graph_kind="Main Agent")
            self._bind_agent_run_id(binding, run_id)
            await self._record_relation(
                client,
                self._agent_relation(binding),
            )
            assert binding.execution_ready is not None
            return await binding.execution_ready
        except BaseException as exc:
            self._cancel_agent_binding_futures(binding)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            if client is not None and binding.thread_id not in self._sessions:
                with suppress(Exception):
                    await client.aclose()
            if isinstance(exc, Exception):
                with suppress(Exception):
                    await self._record_entry_start_failure(
                        exc,
                        graph_kind="agent",
                        subject_id=str(main_agent["id"]),
                        subject_name=str(main_agent["name"]),
                        request_id=request_id,
                        thread_id=binding.thread_id,
                        lifecycle_record=lifecycle_record,
                    )
            self._release_if_finished()
            raise

    async def build_server_agent_graph(
        self,
        *,
        main_agent_id: str,
        store: BaseStore,
        context: Any,
        snapshot: RequestRuntimeSnapshot,
    ) -> Any:
        key = relation_key(context.caller_run_id, context.operation_id)
        binding = self._agent_bindings.get(key)
        if binding is None:
            raise RuntimeError("the official Main Agent Run binding is unavailable")
        if (
            main_agent_id != str(binding.main_agent["id"])
            or context.lifecycle_id != binding.lifecycle_id
        ):
            raise RuntimeError("the official Main Agent Run does not match its binding")
        assert binding.run_id_ready is not None
        assert binding.execution_ready is not None
        try:
            run_id = await binding.run_id_ready
            if snapshot.main_agent_by_id(main_agent_id) is None:
                raise AgentRuntimeError(
                    "lifecycle_graph_not_in_snapshot",
                    f"Main Agent {main_agent_id} is not in the Lifecycle snapshot.",
                    status_code=422,
                )
            runtime = await snapshot.new_runtime(store=store)
            execution = await runtime.start_main_agent(
                main_agent_id,
                binding.messages,
                request_id=binding.request_id,
                lifecycle_id=binding.lifecycle_id,
                run_id=run_id,
                thread_id=binding.thread_id,
                assistant_id=binding.assistant_id,
                public_model=binding.public_model,
                caller_run_id=binding.caller_run_id,
                operation_id=binding.operation_id,
                public_output=True,
                response_scheduler=self._response_scheduler,
                response_consumer=binding.response_consumer,
            )
            protocol_stream = binding.protocol_stream
            if protocol_stream is None:
                raise RuntimeError("the official Main Agent event stream is unavailable")
            graph = execution.graph
            execution.graph = _OfficialRunEventGraph(protocol_stream)
            execution.cancel_run = lambda: self.cancel_official_run(
                binding.thread_id,
                run_id,
            )
            execution.response_terminated = self.response_terminated_flag
            if binding.response_consumer:
                self._response_scheduler = execution.response_scheduler
            if not binding.execution_ready.done():
                binding.execution_ready.set_result(execution)
            return graph
        except BaseException as exc:
            if not binding.execution_ready.done():
                binding.execution_ready.set_exception(exc)
            raise

    async def build_server_graph(
        self,
        *,
        workflow_id: str,
        store: BaseStore,
        context: Any,
        snapshot: RequestRuntimeSnapshot,
    ) -> Any:
        key = relation_key(context.caller_run_id, context.operation_id)
        binding = self._bindings.get(key)
        if binding is None:
            raise RuntimeError("the official Workflow Run binding is unavailable")
        if (
            workflow_id != str(binding.workflow["id"])
            or context.lifecycle_id != binding.lifecycle_id
        ):
            raise RuntimeError("the official Workflow Run does not match its binding")
        assert binding.run_id_ready is not None
        assert binding.execution_ready is not None
        try:
            run_id = await binding.run_id_ready
            input_item = await store.aget(
                lifecycle_input_namespace(binding.lifecycle_id),
                LIFECYCLE_INPUT_KEY,
            )
            messages = (
                input_item.value.get("messages")
                if input_item is not None and isinstance(input_item.value, Mapping)
                else None
            )
            if not isinstance(messages, list):
                raise RuntimeError("the Workflow Lifecycle input is unavailable")
            workflow = snapshot.workflow_by_id(workflow_id)
            document = snapshot.workflow_document(workflow_id)
            if workflow is None or document is None:
                raise AgentRuntimeError(
                    "lifecycle_graph_not_in_snapshot",
                    f"Workflow {workflow_id} is not in the Lifecycle snapshot.",
                    status_code=422,
                )
            runtime = await snapshot.new_runtime(store=store)
            execution = await runtime.start_workflow(
                document,
                messages,
                workflow_snapshot=workflow,
                request_id=binding.request_id,
                public_model=binding.public_model,
                lifecycle_id=binding.lifecycle_id,
                run_id=run_id,
                thread_id=binding.thread_id,
                assistant_id=binding.assistant_id,
                caller_run_id=binding.caller_run_id,
                operation_id=binding.operation_id,
                initial_shared_vars=binding.initial_shared_vars,
                agent_run_runtime=self,
                workflow_run_runtime=self,
                public_output=True,
                response_scheduler=self._response_scheduler,
                response_consumer=binding.response_consumer,
                server_context=context,
            )
            protocol_stream = binding.protocol_stream
            if protocol_stream is None:
                raise RuntimeError("the official Workflow event stream is unavailable")
            graph = execution.graph
            execution.graph = _OfficialRunEventGraph(protocol_stream)
            execution.cancel_run = lambda: self.cancel_official_run(
                binding.thread_id,
                run_id,
            )
            execution.response_terminated = self.response_terminated_flag
            if binding.response_consumer:
                self._response_scheduler = execution.response_scheduler
            if not binding.execution_ready.done():
                binding.execution_ready.set_result(execution)
            return graph
        except BaseException as exc:
            if not binding.execution_ready.done():
                binding.execution_ready.set_exception(exc)
            raise

    async def start_workflow_run(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        caller: RunCaller,
        shared_vars: Mapping[str, Any],
    ) -> WorkflowRunHandle:
        normalized_operation_id = operation_id.strip()
        if not normalized_operation_id:
            raise AgentRuntimeError(
                "workflow_run_operation_id_invalid",
                "Workflow Run operation_id must not be empty.",
                status_code=422,
            )
        if caller.lifecycle_id != self._lifecycle_id:
            raise AgentRuntimeError(
                "workflow_lifecycle_mismatch",
                "The Workflow Run caller belongs to another Lifecycle.",
                status_code=409,
            )
        target = self._snapshot.workflow_by_id(target_workflow_id)
        document = self._snapshot.workflow_document(target_workflow_id)
        if target is None or not target["enabled"] or document is None:
            raise AgentRuntimeError(
                "lifecycle_graph_not_in_snapshot",
                f"Workflow {target_workflow_id} is not in the Lifecycle snapshot.",
                status_code=422,
            )
        existing = await self._relation_for_operation(
            caller,
            normalized_operation_id,
        )
        if existing is not None:
            if existing.resource_id != target_workflow_id:
                raise AgentRuntimeError(
                    "workflow_run_operation_conflict",
                    "The operation_id is already bound to another Workflow.",
                    status_code=409,
                )
            async with self._owner.new_agent_server_client() as client:
                run = await client.runs.get(existing.thread_id, existing.run_id)
            return self._handle(existing, run)

        binding = self._new_binding(
            target,
            request_id=caller.request_id,
            lifecycle_id=caller.lifecycle_id,
            public_model=str(target["name"]),
            caller_run_id=caller.run_id,
            operation_id=normalized_operation_id,
            initial_shared_vars=deepcopy(dict(shared_vars)),
        )
        if binding.key in self._bindings:
            raise AgentRuntimeError(
                "workflow_run_operation_conflict",
                "The operation_id is already being started.",
                status_code=409,
            )
        self._bindings[binding.key] = binding
        try:
            client, thread_stream = await self._open_run_session(binding)
            result = await self._start_bound_run(binding, thread_stream)
            self._bind_official_run_id(binding, result)
            relation = self._workflow_relation(binding)
            await self._record_relation(client, relation)
            assert binding.execution_ready is not None
            execution = await binding.execution_ready
            self._detached_tasks.create(
                self._consume_spawned(execution),
                name=f"workflow-run-stream:{binding.run_id}",
            )
            run = await client.runs.get(binding.thread_id, binding.run_id)
            return self._handle(relation, run)
        except BaseException:
            self._bindings.pop(binding.key, None)
            self._cancel_binding_futures(binding)
            if binding.thread_id and binding.run_id:
                with suppress(Exception):
                    await self.cancel_official_run(binding.thread_id, binding.run_id)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            raise

    async def start_agent_run(
        self,
        main_agent_id: str,
        input: object,
        *,
        operation_id: str,
        caller: RunCaller,
        thread_id: str | None = None,
    ) -> AgentRunHandle:
        normalized_operation_id = operation_id.strip()
        if not normalized_operation_id:
            raise AgentRuntimeError(
                "agent_run_operation_id_invalid",
                "Agent Run operation_id must not be empty.",
                status_code=422,
            )
        self._validate_run_caller(caller)
        target = self._snapshot.main_agent_by_id(main_agent_id)
        if target is None:
            raise AgentRuntimeError(
                "lifecycle_graph_not_in_snapshot",
                f"Main Agent {main_agent_id} is not in the Lifecycle snapshot.",
                status_code=422,
            )
        messages = validate_client_messages(input)
        requested_thread_id = None
        if thread_id is not None:
            requested_thread_id = thread_id.strip()
            if not requested_thread_id:
                raise AgentRuntimeError(
                    "agent_run_thread_id_invalid",
                    "Agent Run thread_id must not be empty when provided.",
                    status_code=422,
                )

        existing = await self._relation_for_operation(
            caller,
            normalized_operation_id,
            graph_kind="agent",
        )
        if existing is not None:
            if (
                existing.resource_id != main_agent_id
                or (
                    requested_thread_id is not None
                    and existing.thread_id != requested_thread_id
                )
            ):
                raise AgentRuntimeError(
                    "agent_run_operation_conflict",
                    "The operation_id is already bound to another Agent Run.",
                    status_code=409,
                )
            async with self._owner.new_agent_server_client() as client:
                run = await client.runs.get(existing.thread_id, existing.run_id)
            return self._agent_handle(existing, run)

        key = relation_key(caller.run_id, normalized_operation_id)
        pending = self._agent_bindings.get(key)
        if pending is not None:
            if (
                str(pending.main_agent["id"]) != main_agent_id
                or (
                    requested_thread_id is not None
                    and pending.thread_id
                    and pending.thread_id != requested_thread_id
                )
            ):
                raise AgentRuntimeError(
                    "agent_run_operation_conflict",
                    "The operation_id is already bound to another Agent Run.",
                    status_code=409,
                )
            assert pending.run_id_ready is not None
            await pending.run_id_ready
            relation = self._agent_relation(pending)
            async with self._owner.new_agent_server_client() as client:
                run = await client.runs.get(relation.thread_id, relation.run_id)
            return self._agent_handle(relation, run)

        loop = asyncio.get_running_loop()
        binding = _AgentRunBinding(
            main_agent=target,
            messages=messages,
            request_id=caller.request_id,
            lifecycle_id=caller.lifecycle_id,
            public_model=str(target["name"]),
            caller_run_id=caller.run_id,
            operation_id=normalized_operation_id,
            run_id_ready=loop.create_future(),
            execution_ready=loop.create_future(),
        )
        self._agent_bindings[key] = binding
        client: Any | None = None
        try:
            client, thread_stream = await self._open_agent_run_session(
                binding,
                existing_thread_id=requested_thread_id,
            )
            result = await self._start_bound_agent_run(binding, thread_stream)
            run_id = self._run_id_from_result(result, graph_kind="Main Agent")
            self._bind_agent_run_id(binding, run_id)
            relation = self._agent_relation(binding)
            await self._record_relation(client, relation)
            assert binding.execution_ready is not None
            execution = await binding.execution_ready
            self._detached_tasks.create(
                self._consume_spawned(execution),
                name=f"agent-run-stream:{binding.run_id}",
            )
            run = await client.runs.get(binding.thread_id, binding.run_id)
            return self._agent_handle(relation, run)
        except BaseException:
            self._agent_bindings.pop(key, None)
            self._cancel_agent_binding_futures(binding)
            if binding.thread_id and binding.run_id:
                with suppress(Exception):
                    await self.cancel_official_run(binding.thread_id, binding.run_id)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            if client is not None and binding.thread_id not in self._sessions:
                with suppress(Exception):
                    await client.aclose()
            raise

    async def check_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot:
        relation = await self._agent_relation_for_identity(caller, thread_id, run_id)
        if relation is None:
            return AgentRunSnapshot(
                thread_id=thread_id,
                run_id=run_id,
                status="not_found",
            )
        async with self._owner.new_agent_server_client() as client:
            run = await client.runs.get(thread_id, run_id)
            return await self._agent_run_snapshot(client, relation, run)

    async def join_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot:
        relation = await self._agent_relation_for_identity(caller, thread_id, run_id)
        if relation is None:
            return AgentRunSnapshot(
                thread_id=thread_id,
                run_id=run_id,
                status="not_found",
            )
        async with self._owner.new_agent_server_client() as client:
            output = await client.runs.join(thread_id, run_id)
            run = await client.runs.get(thread_id, run_id)
        return self._agent_snapshot_value(
            relation,
            official_status(run),
            output=output if isinstance(output, dict) else {},
        )

    async def cancel_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot:
        relation = await self._agent_relation_for_identity(caller, thread_id, run_id)
        if relation is None:
            return AgentRunSnapshot(
                thread_id=thread_id,
                run_id=run_id,
                status="not_found",
            )
        async with self._owner.new_agent_server_client() as client:
            run = await client.runs.get(thread_id, run_id)
            if official_status(run) in ACTIVE_RUN_STATUSES:
                await client.runs.cancel(thread_id, run_id, wait=True)
                run = await client.runs.get(thread_id, run_id)
        return self._agent_snapshot_value(relation, official_status(run))

    async def check_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._lifecycle_relations(caller)
        by_run = {relation.run_id: relation for relation in relations}
        snapshots: list[WorkflowRunSnapshot] = []
        async with self._owner.new_agent_server_client() as client:
            for run_id in run_ids:
                relation = by_run.get(run_id)
                if relation is None:
                    snapshots.append(WorkflowRunSnapshot(run_id=run_id, status="not_found"))
                    continue
                run = await client.runs.get(relation.thread_id, relation.run_id)
                snapshots.append(await self._run_snapshot(client, relation, run))
        return snapshots

    async def list_workflow_runs(
        self,
        *,
        caller: RunCaller,
        statuses: frozenset[RunStatus] | None = None,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._lifecycle_relations(caller)
        snapshots: list[WorkflowRunSnapshot] = []
        async with self._owner.new_agent_server_client() as client:
            for relation in relations:
                run = await client.runs.get(relation.thread_id, relation.run_id)
                status = official_status(run)
                if statuses is None or status in statuses:
                    snapshots.append(self._snapshot_value(relation, status))
        return snapshots

    async def join_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._selected_relations(caller, run_ids)
        by_run = {relation.run_id: relation for relation in relations}
        snapshots: list[WorkflowRunSnapshot] = []
        async with self._owner.new_agent_server_client() as client:
            for run_id in run_ids:
                relation = by_run.get(run_id)
                if relation is None:
                    snapshots.append(WorkflowRunSnapshot(run_id=run_id, status="not_found"))
                    continue
                output = await client.runs.join(relation.thread_id, relation.run_id)
                run = await client.runs.get(relation.thread_id, relation.run_id)
                snapshots.append(
                    self._snapshot_value(
                        relation,
                        official_status(run),
                        output=output if isinstance(output, dict) else {},
                    )
                )
        return snapshots

    async def cancel_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._selected_relations(caller, run_ids)
        by_run = {relation.run_id: relation for relation in relations}
        snapshots: list[WorkflowRunSnapshot] = []
        async with self._owner.new_agent_server_client() as client:
            for run_id in run_ids:
                relation = by_run.get(run_id)
                if relation is None:
                    snapshots.append(WorkflowRunSnapshot(run_id=run_id, status="not_found"))
                    continue
                await client.runs.cancel(relation.thread_id, relation.run_id, wait=True)
                run = await client.runs.get(relation.thread_id, relation.run_id)
                snapshots.append(self._snapshot_value(relation, official_status(run)))
        return snapshots

    async def disconnect(self) -> None:
        """Apply each active Run's frozen policy to one user disconnect event."""

        if not self._lifecycle_id:
            return
        self._disconnected = True
        async with self._owner.new_agent_server_client() as client:
            for relation in tuple(self._relations.values()):
                if relation.on_disconnect != "cancel":
                    continue
                with suppress(Exception):
                    run = await client.runs.get(relation.thread_id, relation.run_id)
                    if official_status(run) in ACTIVE_RUN_STATUSES:
                        await client.runs.cancel(
                            relation.thread_id,
                            relation.run_id,
                            wait=False,
                        )

    def terminate_response(self) -> None:
        """Stop the in-flight request-entry response of this one Lifecycle."""

        if not self._lifecycle_id:
            return
        self._response_terminated.set()

    async def _record_relation(
        self,
        client: Any,
        relation: GraphRunCallRelation,
        *,
        detached: bool = False,
    ) -> None:
        existing = self._relations.get(relation.run_id)
        if existing is not None:
            if existing != relation:
                raise RuntimeError("one official Run has conflicting Lifecycle relations")
            return
        await save_lifecycle_run_relation(client, relation)
        self._relations[relation.run_id] = relation
        if detached:
            self._detached_run_ids.add(relation.run_id)
            self._detached_tasks.create(
                self._watch_detached_run(relation),
                name=f"lifecycle-run-retention:{relation.run_id}",
            )
        await self._owner.register_run_relation(self, relation)
        if self._disconnected and relation.on_disconnect == "cancel":
            await self.cancel_official_run(relation.thread_id, relation.run_id)

    async def _watch_detached_run(self, relation: GraphRunCallRelation) -> None:
        try:
            async with self._owner.new_agent_server_client() as client:
                await client.runs.join(relation.thread_id, relation.run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            self._detached_run_ids.discard(relation.run_id)
            self._release_if_finished()

    async def cancel_official_run(self, thread_id: str, run_id: str) -> None:
        if not thread_id or not run_id:
            return
        async with self._owner.new_agent_server_client() as client:
            run = await client.runs.get(thread_id, run_id)
            if official_status(run) in ACTIVE_RUN_STATUSES:
                await client.runs.cancel(thread_id, run_id)

    async def official_output(self, thread_id: str) -> object:
        session = self._sessions.get(thread_id)
        if session is not None:
            state = await session.client.threads.get_state(thread_id)
        else:
            async with self._owner.new_agent_server_client() as client:
                state = await client.threads.get_state(thread_id)
        return state.get("values", {})

    async def close_official_session(self, thread_id: str) -> None:
        session = self._sessions.pop(thread_id, None)
        if session is None:
            return
        try:
            await session.stream.close()
        finally:
            await session.client.aclose()
        self._release_if_finished()

    def _new_binding(
        self,
        workflow: Mapping[str, Any],
        *,
        request_id: str,
        lifecycle_id: str,
        public_model: str,
        caller_run_id: str = "",
        operation_id: str = "",
        initial_shared_vars: Mapping[str, Any] | None = None,
        response_consumer: bool = False,
    ) -> _RunBinding:
        document = self._snapshot.workflow_document(str(workflow["id"]))
        if document is None:
            raise RuntimeError("the captured Workflow no longer exists")
        loop = asyncio.get_running_loop()
        return _RunBinding(
            workflow=workflow,
            document=document,
            request_id=request_id,
            lifecycle_id=lifecycle_id,
            public_model=public_model,
            caller_run_id=caller_run_id,
            operation_id=operation_id,
            initial_shared_vars=initial_shared_vars or {},
            response_consumer=response_consumer,
            run_id_ready=loop.create_future(),
            execution_ready=loop.create_future(),
        )

    async def _open_run_session(self, binding: _RunBinding) -> tuple[Any, Any]:
        client = self._owner.new_agent_server_client()
        try:
            assistant = await _ensure_assistant(
                client.assistants,
                LANGGRAPH_WORKFLOW_GRAPH_ID,
                name=str(binding.workflow["name"]),
                config={"configurable": {"workflow_id": str(binding.workflow["id"])}},
                metadata={
                    "graph_kind": "workflow",
                    "workflow_id": str(binding.workflow["id"]),
                },
                assistant_id=str(binding.workflow["id"]),
            )
            binding.assistant_id = str(assistant["assistant_id"])
            thread = await client.threads.create(
                metadata={
                    "lifecycle_id": binding.lifecycle_id,
                    "request_id": binding.request_id,
                    "graph_kind": "workflow",
                    "workflow_id": str(binding.workflow["id"]),
                    "caller_run_id": binding.caller_run_id,
                    "operation_id": binding.operation_id,
                },
            )
            binding.thread_id = str(thread["thread_id"])
            stream = client.threads.stream(
                binding.thread_id,
                assistant_id=binding.assistant_id,
            )
            await stream.__aenter__()
            binding.protocol_stream = _OfficialRunEventStream(
                stream.events,
                self,
                binding.thread_id,
            )
            self._sessions[binding.thread_id] = _OfficialSession(client, stream)
            return client, stream
        except BaseException:
            await client.aclose()
            raise

    async def _open_agent_run_session(
        self,
        binding: _AgentRunBinding,
        *,
        existing_thread_id: str | None = None,
    ) -> tuple[Any, Any]:
        client = self._owner.new_agent_server_client()
        try:
            agent_id = str(binding.main_agent["id"])
            assistant = await _ensure_assistant(
                client.assistants,
                LANGGRAPH_AGENT_GRAPH_ID,
                name=str(binding.main_agent["name"]),
                config={"configurable": {"main_agent_id": agent_id}},
                metadata={"graph_kind": "agent", "main_agent_id": agent_id},
                assistant_id=main_agent_assistant_id(agent_id),
            )
            binding.assistant_id = str(assistant["assistant_id"])
            if existing_thread_id is not None:
                if existing_thread_id in self._sessions:
                    raise AgentRuntimeError(
                        "agent_run_thread_busy",
                        "The selected Main Agent Thread already has an active Run.",
                        status_code=409,
                    )
                thread = await client.threads.get(existing_thread_id)
                metadata_value = thread.get("metadata")
                metadata = (
                    metadata_value if isinstance(metadata_value, Mapping) else {}
                )
                if (
                    metadata.get("graph_kind") != "agent"
                    or metadata.get("main_agent_id") != agent_id
                    or metadata.get("lifecycle_id") != binding.lifecycle_id
                ):
                    raise AgentRuntimeError(
                        "agent_run_thread_mismatch",
                        "The selected Thread does not belong to this Lifecycle and Main Agent.",
                        status_code=409,
                    )
            else:
                thread = await client.threads.create(
                    metadata=self._agent_thread_metadata(binding),
                )
            binding.thread_id = str(thread["thread_id"])
            stream = await self._attach_agent_run_stream(binding, client)
            return client, stream
        except BaseException:
            await client.aclose()
            raise

    async def _attach_agent_run_stream(
        self,
        binding: _AgentRunBinding,
        client: Any,
    ) -> Any:
        stream = client.threads.stream(
            binding.thread_id,
            assistant_id=binding.assistant_id,
        )
        await stream.__aenter__()
        binding.protocol_stream = _OfficialRunEventStream(
            stream.events,
            self,
            binding.thread_id,
        )
        self._sessions[binding.thread_id] = _OfficialSession(client, stream)
        return stream

    @staticmethod
    def _agent_thread_metadata(binding: _AgentRunBinding) -> dict[str, str]:
        return {
            "lifecycle_id": binding.lifecycle_id,
            "request_id": binding.request_id,
            "graph_kind": "agent",
            "main_agent_id": str(binding.main_agent["id"]),
            "caller_run_id": binding.caller_run_id,
            "operation_id": binding.operation_id,
        }

    def _run_start_config(self, **configurable: str) -> dict[str, Any]:
        config = self._snapshot.run_config()
        existing = config.get("configurable")
        config["configurable"] = {
            **(dict(existing) if isinstance(existing, Mapping) else {}),
            **configurable,
        }
        return config

    async def _start_bound_run(self, binding: _RunBinding, stream: Any) -> Mapping[str, Any]:
        return await stream.run.start(
            input={
                "shared_vars": deepcopy(dict(binding.initial_shared_vars)),
            },
            config=self._run_start_config(
                workflow_id=str(binding.workflow["id"]),
                request_id=binding.request_id,
                lifecycle_id=binding.lifecycle_id,
                caller_run_id=binding.caller_run_id,
                operation_id=binding.operation_id,
            ),
            metadata={
                "lifecycle_id": binding.lifecycle_id,
                "request_id": binding.request_id,
                "graph_kind": "workflow",
                "workflow_id": str(binding.workflow["id"]),
                "workflow_name": str(binding.workflow["name"]),
                "caller_run_id": binding.caller_run_id,
                "operation_id": binding.operation_id,
            },
        )

    async def _start_bound_agent_run(
        self,
        binding: _AgentRunBinding,
        stream: Any,
    ) -> Mapping[str, Any]:
        agent_id = str(binding.main_agent["id"])
        return await stream.run.start(
            input={"messages": deepcopy(binding.messages)},
            config=self._run_start_config(
                main_agent_id=agent_id,
                request_id=binding.request_id,
                lifecycle_id=binding.lifecycle_id,
                caller_run_id=binding.caller_run_id,
                operation_id=binding.operation_id,
            ),
            metadata={
                "lifecycle_id": binding.lifecycle_id,
                "request_id": binding.request_id,
                "graph_kind": "agent",
                "main_agent_id": agent_id,
                "main_agent_name": str(binding.main_agent["name"]),
                "caller_run_id": binding.caller_run_id,
                "operation_id": binding.operation_id,
            },
        )

    @staticmethod
    def _bind_official_run_id(
        binding: _RunBinding,
        result: Mapping[str, Any],
    ) -> None:
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("the official Workflow Run did not return run_id")
        binding.run_id = run_id
        assert binding.run_id_ready is not None
        binding.run_id_ready.set_result(run_id)

    @staticmethod
    def _run_id_from_result(
        result: Mapping[str, Any],
        *,
        graph_kind: str,
    ) -> str:
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError(f"the official {graph_kind} Run did not return run_id")
        return run_id

    @staticmethod
    def _bind_agent_run_id(
        binding: _AgentRunBinding,
        run_id: str,
    ) -> None:
        binding.run_id = run_id
        assert binding.run_id_ready is not None
        binding.run_id_ready.set_result(run_id)

    @staticmethod
    def _cancel_binding_futures(binding: _RunBinding) -> None:
        for future in (binding.run_id_ready, binding.execution_ready):
            if future is not None and not future.done():
                future.cancel()

    @staticmethod
    def _cancel_agent_binding_futures(binding: _AgentRunBinding) -> None:
        for future in (binding.run_id_ready, binding.execution_ready):
            if future is not None and not future.done():
                future.cancel()

    async def _consume_spawned(self, execution: RunExecution) -> None:
        try:
            await execution.execute()
        except (AgentRuntimeError, asyncio.CancelledError):
            pass
        except Exception:
            pass

    async def _relation_for_operation(
        self,
        caller: RunCaller,
        operation_id: str,
        *,
        graph_kind: str = "workflow",
    ) -> GraphRunCallRelation | None:
        relations = await self._lifecycle_relations(caller, graph_kind=graph_kind)
        return next(
            (
                relation
                for relation in relations
                if relation.caller_run_id == caller.run_id
                and relation.operation_id == operation_id
            ),
            None,
        )

    async def _lifecycle_relations(
        self,
        caller: RunCaller,
        *,
        graph_kind: str = "workflow",
    ) -> list[GraphRunCallRelation]:
        if caller.lifecycle_id != self._lifecycle_id:
            raise AgentRuntimeError(
                "workflow_lifecycle_mismatch",
                "The Workflow Run caller belongs to another Lifecycle.",
                status_code=409,
            )
        async with self._owner.new_agent_server_client() as client:
            return await search_lifecycle_run_relations(
                client,
                caller.lifecycle_id,
                graph_kind=graph_kind,
            )

    async def _selected_relations(
        self,
        caller: RunCaller,
        run_ids: Sequence[str],
    ) -> list[GraphRunCallRelation]:
        relations = await self._lifecycle_relations(caller)
        return select_run_relations(
            relations,
            run_ids=run_ids,
        )

    def _validate_run_caller(self, caller: RunCaller) -> None:
        if caller.lifecycle_id != self._lifecycle_id:
            raise AgentRuntimeError(
                "agent_run_lifecycle_mismatch",
                "The Agent Run caller belongs to another Lifecycle.",
                status_code=409,
            )

    async def _agent_relation_for_identity(
        self,
        caller: RunCaller,
        thread_id: str,
        run_id: str,
    ) -> GraphRunCallRelation | None:
        self._validate_run_caller(caller)
        relations = await self._lifecycle_relations(caller, graph_kind="agent")
        return next(
            (
                relation
                for relation in relations
                if relation.thread_id == thread_id and relation.run_id == run_id
            ),
            None,
        )

    async def _run_snapshot(
        self,
        client: Any,
        relation: GraphRunCallRelation,
        run: Mapping[str, Any],
    ) -> WorkflowRunSnapshot:
        status = official_status(run)
        output = None
        if status not in ACTIVE_RUN_STATUSES:
            state = await client.threads.get_state(relation.thread_id)
            values = state.get("values") if isinstance(state, Mapping) else None
            output = values if isinstance(values, dict) else {}
        return self._snapshot_value(relation, status, output=output)

    @staticmethod
    def _handle(
        relation: GraphRunCallRelation,
        run: Mapping[str, Any],
    ) -> WorkflowRunHandle:
        return WorkflowRunHandle(
            operation_id=relation.operation_id,
            workflow_id=relation.resource_id,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=official_status(run),
        )

    @staticmethod
    def _snapshot_value(
        relation: GraphRunCallRelation,
        status: RunStatus,
        *,
        output: dict[str, Any] | None = None,
    ) -> WorkflowRunSnapshot:
        return WorkflowRunSnapshot(
            operation_id=relation.operation_id,
            caller_run_id=relation.caller_run_id,
            workflow_id=relation.resource_id,
            workflow_name=relation.resource_name,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=status,
            output=output,
        )

    async def _agent_run_snapshot(
        self,
        client: Any,
        relation: GraphRunCallRelation,
        run: Mapping[str, Any],
    ) -> AgentRunSnapshot:
        status = official_status(run)
        output = None
        if status not in ACTIVE_RUN_STATUSES:
            state = await client.threads.get_state(relation.thread_id)
            values = state.get("values") if isinstance(state, Mapping) else None
            output = values if isinstance(values, dict) else {}
        return self._agent_snapshot_value(relation, status, output=output)

    @staticmethod
    def _agent_handle(
        relation: GraphRunCallRelation,
        run: Mapping[str, Any],
    ) -> AgentRunHandle:
        return AgentRunHandle(
            operation_id=relation.operation_id,
            main_agent_id=relation.resource_id,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=official_status(run),
        )

    @staticmethod
    def _agent_snapshot_value(
        relation: GraphRunCallRelation,
        status: RunStatus,
        *,
        output: dict[str, Any] | None = None,
    ) -> AgentRunSnapshot:
        return AgentRunSnapshot(
            operation_id=relation.operation_id,
            caller_run_id=relation.caller_run_id,
            main_agent_id=relation.resource_id,
            main_agent_name=relation.resource_name,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=status,
            output=output,
        )

    @staticmethod
    def _workflow_relation(binding: _RunBinding) -> GraphRunCallRelation:
        return GraphRunCallRelation(
            lifecycle_id=binding.lifecycle_id,
            graph_kind="workflow",
            operation_id=binding.operation_id,
            caller_run_id=binding.caller_run_id,
            resource_id=str(binding.workflow["id"]),
            resource_name=str(binding.workflow["name"]),
            on_disconnect=(
                "continue"
                if binding.workflow.get("on_disconnect") == "continue"
                else "cancel"
            ),
            assistant_id=binding.assistant_id,
            thread_id=binding.thread_id,
            run_id=binding.run_id,
        )

    @staticmethod
    def _agent_relation(binding: _AgentRunBinding) -> GraphRunCallRelation:
        return GraphRunCallRelation(
            lifecycle_id=binding.lifecycle_id,
            graph_kind="agent",
            operation_id=binding.operation_id,
            caller_run_id=binding.caller_run_id,
            resource_id=str(binding.main_agent["id"]),
            resource_name=str(binding.main_agent["name"]),
            on_disconnect=(
                "continue"
                if binding.main_agent.get("on_disconnect") == "continue"
                else "cancel"
            ),
            assistant_id=binding.assistant_id,
            thread_id=binding.thread_id,
            run_id=binding.run_id,
        )

    def _release_if_finished(self) -> None:
        if not self._sessions and not self._detached_run_ids:
            self._owner.release_active_lifecycle(self)


class RequestSnapshotRuntime:
    """Capture the latest committed file configuration for Agent construction."""

    def __init__(
        self,
        configuration: FileConfigRepository,
        *,
        python_packages_dir: Path | Callable[[], Path],
        runtime_dir: Path,
        skills_dir: Path | Callable[[], Path],
        provider_http_clients: ProviderHttpClients,
        files: FileManagerService,
        workflow_data: WorkflowDataService,
        detached_tasks: DetachedTaskManager,
        runtime_diagnostics: RuntimeDiagnostics,
        workflow_lifecycle_settings: WorkflowLifecycleSettingsStore,
        response_stream_policy_provider: Callable[[], ResponseStreamPolicy],
        configuration_mutations: ConfigurationMutationCoordinator,
        model_resources: ModelResourceStore | None = None,
        mcp_resources: McpResourceStore | None = None,
        run_config: Mapping[str, Any],
        agent_server_url: str,
        agent_server_token: str,
    ) -> None:
        self._configuration = configuration
        self._python_packages_dir_source = python_packages_dir
        self._runtime_dir = runtime_dir
        self._skills_dir_source = skills_dir
        self._provider_http_clients = provider_http_clients
        self._files = files
        self._workflow_data = workflow_data
        self._detached_tasks = detached_tasks
        self._runtime_diagnostics = runtime_diagnostics
        self._response_stream_policy_provider = response_stream_policy_provider
        self._configuration_mutations = configuration_mutations
        self._model_resources = model_resources or ModelResourceStore(configuration.data_root)
        self._mcp_resources = mcp_resources or McpResourceStore(configuration.data_root)
        self._run_config = dict(run_config)
        self._agent_server_url = agent_server_url
        self._agent_server_headers = {"Authorization": f"Bearer {agent_server_token}"}
        self._active_lifecycles: dict[str, LifecycleRunCoordinator] = {}
        self._run_lifecycles: dict[str, LifecycleRunCoordinator] = {}
        self._langgraph_lifecycles = LangGraphLifecycleService(
            self.new_agent_server_client,
            workflow_lifecycle_settings,
        )

    def new_agent_server_client(self):
        return get_client(url=self._agent_server_url, headers=self._agent_server_headers)

    @property
    def langgraph_lifecycles(self) -> LangGraphLifecycleService:
        return self._langgraph_lifecycles

    @property
    def runtime_diagnostics(self) -> RuntimeDiagnostics:
        return self._runtime_diagnostics

    async def enforce_lifecycle_retention(self) -> None:
        await self._langgraph_lifecycles.enforce_retention()

    def register_active_lifecycle(self, coordinator: LifecycleRunCoordinator) -> None:
        lifecycle_id = coordinator.lifecycle_id
        if not lifecycle_id or lifecycle_id in self._active_lifecycles:
            raise RuntimeError("the active Workflow Lifecycle identity is invalid")
        self._active_lifecycles[lifecycle_id] = coordinator

    async def register_run_relation(
        self,
        coordinator: LifecycleRunCoordinator,
        relation: GraphRunCallRelation,
    ) -> None:
        existing = self._run_lifecycles.get(relation.run_id)
        if existing is not None and existing is not coordinator:
            raise RuntimeError("one official Run belongs to multiple Lifecycles")
        self._run_lifecycles[relation.run_id] = coordinator

    def active_lifecycle(self, lifecycle_id: str) -> LifecycleRunCoordinator | None:
        return self._active_lifecycles.get(lifecycle_id)

    def terminate_active_response(self, lifecycle_id: str) -> bool:
        """Stop the in-flight request response of one active Lifecycle."""

        coordinator = self._active_lifecycles.get(lifecycle_id)
        if coordinator is None:
            return False
        coordinator.terminate_response()
        return True

    def release_active_lifecycle(self, coordinator: LifecycleRunCoordinator) -> None:
        lifecycle_id = coordinator.lifecycle_id
        if self._active_lifecycles.get(lifecycle_id) is coordinator:
            self._active_lifecycles.pop(lifecycle_id, None)
            for run_id, owner in tuple(self._run_lifecycles.items()):
                if owner is coordinator:
                    self._run_lifecycles.pop(run_id, None)
            self._detached_tasks.create(
                self.enforce_lifecycle_retention(),
                name="langgraph-lifecycle-retention",
            )

    async def capture(self) -> RequestRuntimeSnapshot:
        """Freeze one request configuration without blocking the server loop."""

        return await asyncio.to_thread(self._capture)

    def _capture(self) -> RequestRuntimeSnapshot:
        with self._configuration_mutations.mutation():
            response_stream_policy = self._response_stream_policy_provider()
            with self._configuration.request_snapshot_context() as context:
                current_repository, python_packages_dir, skills_dir, repository_id = context
            repository_config = self._published_repository_config(current_repository)
            repository = FileConfigRepository.from_snapshot(
                current_repository.data_root,
                repository_config,
                repository_id=repository_id,
                repository_name=current_repository.repository_name,
                repository_root=current_repository.config_root,
            )
            model_resources = self._model_resources.snapshot()
            mcp_resources = self._mcp_resources.snapshot()
            configuration = {
                "schema_version": LIFECYCLE_CONFIGURATION_SCHEMA_VERSION,
                "repository": {
                    "id": repository_id,
                    "name": repository.repository_name,
                    "root": str(repository.config_root),
                    "python_packages_root": str(python_packages_dir),
                    "skill_packages_root": str(skills_dir),
                    "config": repository_config,
                },
                "model": model_resources.frozen_projection(repository_id),
                "mcp": mcp_resources.frozen_projection(repository_id),
                "runtime": {
                    "response_stream_scheduling": response_stream_policy.model_dump(
                        mode="json"
                    ),
                    "run_config": deepcopy(self._run_config),
                },
            }
            validated = LifecycleConfigurationSnapshot.model_validate(
                {
                    **configuration,
                    "entry_graph": {"graph_kind": "agent", "resource_id": ""},
                }
            ).as_store_value()
            validated.pop("entry_graph")
            configuration = validated
        return self._materialize_snapshot(
            repository,
            model_resources=model_resources,
            mcp_resources=mcp_resources,
            response_stream_policy=response_stream_policy,
            run_config=self._run_config,
            configuration=configuration,
        )

    def _published_repository_config(
        self,
        current_repository: FileConfigRepository,
    ) -> dict[str, Any]:
        repository_config = current_repository.config()
        repository_config["main_agents"] = [
            main_agent
            for main_agent in repository_config.get("main_agents", [])
            if isinstance(main_agent, dict)
            and main_agent.get("enabled") is True
        ]
        repository_config["workflows"] = [
            workflow
            for workflow in repository_config.get("workflows", [])
            if isinstance(workflow, dict)
            and workflow.get("enabled") is True
        ]
        return repository_config

    def _materialize_snapshot(
        self,
        repository: FileConfigRepository,
        *,
        model_resources: ModelResourceSnapshot,
        mcp_resources: McpResourceSnapshot,
        response_stream_policy: ResponseStreamPolicy,
        run_config: Mapping[str, Any],
        configuration: dict[str, Any],
    ) -> RequestRuntimeSnapshot:
        python_packages_dir = repository.python_packages_root
        skills_dir = repository.skill_packages_root
        repository_id = repository.repository_id
        blocks = BlockStore(repository)
        configs = AgentConfigStore(repository)
        workflows = WorkflowStore(repository)
        secrets = ProviderSecretResolver(repository, model_resources)
        python_package_validation = PythonPackageValidationService(
            packages_dir=python_packages_dir,
            runtime_root=self._runtime_dir,
        )
        validation = ConfigurationValidationService(
            blocks,
            configs,
            python_package_validation,
            repository=repository,
        )

        def runtime_factory(graph_store: BaseStore | None = None) -> AgentRuntime:
            if graph_store is None:
                raise RuntimeError("the LangGraph Store is unavailable")
            return AgentRuntime(
                AgentBuilder(
                    secrets,
                    python_packages_dir=python_packages_dir,
                    data_root=repository.data_root,
                    runtime_dir=self._runtime_dir,
                    skills_dir=skills_dir,
                    validation=validation,
                    provider_http_clients=self._provider_http_clients,
                    store=graph_store,
                    model_resources=model_resources,
                    mcp_resources=mcp_resources,
                    repository_id=repository_id,
                ),
                self._files,
                python_packages_dir=python_packages_dir,
                runtime_dir=self._runtime_dir,
                blocks=blocks,
                workflow_data=self._workflow_data,
                runtime_diagnostics=self._runtime_diagnostics,
                run_config=run_config,
                graph_store=graph_store,
            )

        return RequestRuntimeSnapshot(
            _workflows=workflows,
            _agents=configs,
            _runtime_factory=runtime_factory,
            _response_stream_policy=response_stream_policy,
            _configuration=deepcopy(configuration),
            _run_config=deepcopy(dict(run_config)),
        )

    async def load_lifecycle_snapshot(
        self,
        store: BaseStore,
        lifecycle_id: str,
    ) -> RequestRuntimeSnapshot:
        """Load the persisted configuration owner for a Lifecycle Graph factory."""

        item = await store.aget(
            lifecycle_configuration_namespace(lifecycle_id),
            LIFECYCLE_CONFIGURATION_KEY,
        )
        if item is None or not isinstance(item.value, Mapping):
            raise RuntimeError("the Lifecycle configuration snapshot is unavailable")
        frozen = LifecycleConfigurationSnapshot.model_validate(item.value)
        return await asyncio.to_thread(self._hydrate_lifecycle_snapshot, frozen)

    def _hydrate_lifecycle_snapshot(
        self,
        frozen: LifecycleConfigurationSnapshot,
    ) -> RequestRuntimeSnapshot:
        repository_value = frozen.repository
        with self._configuration_mutations.mutation():
            repository = FileConfigRepository.from_snapshot(
                self._configuration.data_root,
                repository_value.config,
                repository_id=repository_value.id,
                repository_name=repository_value.name,
                repository_root=Path(repository_value.root),
            )
            if (
                Path(repository_value.python_packages_root).resolve()
                != repository.python_packages_root
                or Path(repository_value.skill_packages_root).resolve()
                != repository.skill_packages_root
            ):
                raise ValueError("Lifecycle Repository asset roots are invalid")
            model_resources = self._model_resources.snapshot_from_frozen_projection(
                repository_value.id,
                frozen.model.model_dump(mode="json"),
            )
            mcp_resources = self._mcp_resources.snapshot_from_frozen_projection(
                repository_value.id,
                frozen.mcp.model_dump(mode="json"),
            )
        runtime_value = frozen.runtime
        response_value = runtime_value.get("response_stream_scheduling")
        run_config = runtime_value.get("run_config")
        if not isinstance(response_value, Mapping) or not isinstance(run_config, Mapping):
            raise ValueError("Lifecycle runtime configuration snapshot is invalid")
        configuration = frozen.as_store_value()
        configuration.pop("entry_graph", None)
        return self._materialize_snapshot(
            repository,
            model_resources=model_resources,
            mcp_resources=mcp_resources,
            response_stream_policy=ResponseStreamPolicy.model_validate(response_value),
            run_config=run_config,
            configuration=configuration,
        )

    def create_lifecycle_coordinator(
        self,
        snapshot: RequestRuntimeSnapshot,
    ) -> LifecycleRunCoordinator:
        return LifecycleRunCoordinator(
            _owner=self,
            _snapshot=snapshot,
            _detached_tasks=self._detached_tasks,
        )
