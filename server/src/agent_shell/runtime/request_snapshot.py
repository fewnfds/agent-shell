from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
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
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.errors import AgentRuntimeError, decode_server_run_error
from agent_shell.runtime.input_messages import client_messages_sha, validate_client_messages
from agent_shell.runtime.langgraph_lifecycle import LangGraphLifecycleService
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
    LIFECYCLE_INPUT_KEY,
    lifecycle_input_namespace,
)
from agent_shell.runtime.workflow_data import WorkflowDataService
from agent_shell.runtime.workflow_run_calls import (
    WorkflowRunHandle,
    WorkflowRunSnapshot,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import McpResourceStore
from agent_shell.storage.model_connections import ModelResourceStore
from agent_shell.storage.workflow_lifecycle_settings import (
    WorkflowLifecycleSettingsStore,
)
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.workflow import WorkflowGraphDocumentV1


LANGGRAPH_WORKFLOW_GRAPH_ID = "agent-shell-workflow"
LANGGRAPH_AGENT_GRAPH_ID = "agent-shell-agent"


def _root_terminal_status(event: Mapping[str, object]) -> str:
    if event.get("method") != "lifecycle":
        return ""
    params = event.get("params")
    if not isinstance(params, Mapping) or params.get("namespace") not in (None, []):
        return ""
    data = params.get("data")
    if not isinstance(data, Mapping):
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

    async def __aenter__(self) -> _OfficialRunEventStream:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._coordinator.close_official_session(self._thread_id)

    def __aiter__(self) -> AsyncIterator[Mapping[str, object]]:
        return self._until_terminal()

    async def _until_terminal(self) -> AsyncIterator[Mapping[str, object]]:
        async for event in self._events:
            yield event
            status = _root_terminal_status(event)
            if status:
                if status in {"failed", "error"}:
                    params = event.get("params")
                    data = params.get("data") if isinstance(params, Mapping) else None
                    error = (
                        decode_server_run_error(data.get("error"))
                        if isinstance(data, Mapping)
                        else None
                    )
                    if error is not None:
                        raise error
                    raise RuntimeError("The official Workflow Run failed.")
                if status in {"interrupted", "cancelled"}:
                    raise asyncio.CancelledError
                if status in {"timeout", "timed_out"}:
                    raise TimeoutError("The official Workflow Run timed out.")
                return

    async def output(self) -> object:
        return await self._coordinator.official_output(self._thread_id)


class _OfficialRunEventGraph:
    """Keep RunExecution's projector while Agent Server owns Graph execution."""

    def __init__(self, stream: _OfficialRunEventStream) -> None:
        self._stream = stream

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
    delete_thread_on_close: bool = False
    delete_thread_with_lifecycle: bool = False


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

    def new_runtime(self, *, store: BaseStore) -> AgentRuntime:
        return self._runtime_factory(store)

    def response_stream_policy(self) -> ResponseStreamPolicy:
        return self._response_stream_policy.model_copy(deep=True)


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
    _bindings: dict[str, _RunBinding] = field(default_factory=dict, init=False)
    _agent_bindings: dict[str, _AgentRunBinding] = field(
        default_factory=dict,
        init=False,
    )
    _sessions: dict[str, _OfficialSession] = field(default_factory=dict, init=False)
    _deferred_thread_deletions: set[str] = field(default_factory=set, init=False)

    @property
    def lifecycle_id(self) -> str:
        return self._lifecycle_id

    def _begin_lifecycle(self, lifecycle_id: str) -> None:
        if self._lifecycle_id or self._response_scheduler is not None:
            raise RuntimeError("the request Lifecycle has already started")
        self._lifecycle_id = lifecycle_id
        self._response_scheduler = LifecycleResponseScheduler(
            self._snapshot.response_stream_policy(),
            lifecycle_id=lifecycle_id,
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
        try:
            client, _thread_stream = await self._open_run_session(binding)
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
            result = await self._start_bound_run(binding, client)
            self._bind_official_run_id(binding, result)
            await save_lifecycle_run_relation(
                client,
                self._workflow_relation(binding),
            )
            assert binding.execution_ready is not None
            return await binding.execution_ready
        except BaseException:
            self._cancel_binding_futures(binding)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
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
        stateless = main_agent.get("checkpoint_mode") == "disabled"
        client: Any | None = None
        try:
            client, _thread_stream = await self._open_agent_run_session(
                binding,
                stateless=stateless,
            )
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
            result = await self._start_bound_agent_run(binding, client)
            run_id, result_thread_id = self._agent_run_result_ids(result)
            if stateless:
                binding.thread_id = result_thread_id
                await client.threads.update(
                    result_thread_id,
                    metadata=self._agent_thread_metadata(binding),
                )
                await self._attach_agent_run_stream(
                    binding,
                    client,
                    delete_thread_on_close=True,
                )
            elif result_thread_id != binding.thread_id:
                raise RuntimeError(
                    "the official Main Agent Run returned an unexpected thread_id"
                )
            self._bind_agent_run_id(binding, run_id)
            await save_lifecycle_run_relation(
                client,
                self._agent_relation(binding),
            )
            assert binding.execution_ready is not None
            return await binding.execution_ready
        except BaseException:
            self._cancel_agent_binding_futures(binding)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            if client is not None and binding.thread_id not in self._sessions:
                with suppress(Exception):
                    await client.aclose()
            self._release_if_finished()
            raise

    async def build_server_agent_graph(
        self,
        *,
        main_agent_id: str,
        store: BaseStore,
        context: Any,
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
            execution = await self._snapshot.new_runtime(
                store=store
            ).start_main_agent(
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
            if binding.response_consumer:
                self._response_scheduler = execution.response_scheduler
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
            execution = await self._snapshot.new_runtime(store=store).start_workflow(
                binding.document,
                messages,
                workflow_snapshot=binding.workflow,
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
            if binding.response_consumer:
                self._response_scheduler = execution.response_scheduler
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
                "workflow_run_target_not_found",
                "The selected Workflow does not exist or is disabled.",
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
            client, _thread_stream = await self._open_run_session(binding)
            result = await self._start_bound_run(binding, client)
            self._bind_official_run_id(binding, result)
            relation = self._workflow_relation(binding)
            await save_lifecycle_run_relation(client, relation)
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
                "agent_run_target_not_found",
                "The selected Main Agent does not exist.",
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
            if target.get("checkpoint_mode") == "disabled":
                raise AgentRuntimeError(
                    "agent_run_thread_unsupported",
                    "A stateless Main Agent cannot continue an existing Thread.",
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
        stateless = target.get("checkpoint_mode") == "disabled"
        client: Any | None = None
        try:
            client, _thread_stream = await self._open_agent_run_session(
                binding,
                stateless=stateless,
                existing_thread_id=requested_thread_id,
            )
            result = await self._start_bound_agent_run(binding, client)
            run_id, result_thread_id = self._agent_run_result_ids(result)
            if stateless:
                binding.thread_id = result_thread_id
                await client.threads.update(
                    result_thread_id,
                    metadata=self._agent_thread_metadata(binding),
                )
                await self._attach_agent_run_stream(
                    binding,
                    client,
                    delete_thread_with_lifecycle=True,
                )
            elif result_thread_id != binding.thread_id:
                raise RuntimeError(
                    "the official Main Agent Run returned an unexpected thread_id"
                )
            self._bind_agent_run_id(binding, run_id)
            relation = self._agent_relation(binding)
            await save_lifecycle_run_relation(client, relation)
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

    async def cancel_active_runs(self) -> None:
        if not self._lifecycle_id:
            return
        await self._owner.langgraph_lifecycles.cancel_active(self._lifecycle_id)

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
        if session.delete_thread_with_lifecycle:
            self._deferred_thread_deletions.add(thread_id)
        try:
            await session.stream.close()
        finally:
            try:
                if session.delete_thread_on_close:
                    await session.client.threads.delete(thread_id)
            finally:
                await session.client.aclose()
        if not self._sessions and self._deferred_thread_deletions:
            pending = tuple(self._deferred_thread_deletions)
            self._deferred_thread_deletions.clear()
            async with self._owner.new_agent_server_client() as client:
                for pending_thread_id in pending:
                    with suppress(Exception):
                        await client.threads.delete(pending_thread_id)
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
            assistant = await client.assistants.create(
                LANGGRAPH_WORKFLOW_GRAPH_ID,
                config={"configurable": {"workflow_id": str(binding.workflow["id"])}},
                metadata={
                    "graph_kind": "workflow",
                    "workflow_id": str(binding.workflow["id"]),
                },
                assistant_id=str(binding.workflow["id"]),
                if_exists="do_nothing",
                name=str(binding.workflow["name"]),
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
        stateless: bool = False,
        existing_thread_id: str | None = None,
    ) -> tuple[Any, Any]:
        client = self._owner.new_agent_server_client()
        try:
            agent_id = str(binding.main_agent["id"])
            assistant = await client.assistants.create(
                LANGGRAPH_AGENT_GRAPH_ID,
                config={"configurable": {"main_agent_id": agent_id}},
                metadata={"graph_kind": "agent", "main_agent_id": agent_id},
                assistant_id=main_agent_assistant_id(agent_id),
                if_exists="do_nothing",
                name=str(binding.main_agent["name"]),
            )
            binding.assistant_id = str(assistant["assistant_id"])
            if stateless:
                return client, None
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
        *,
        delete_thread_on_close: bool = False,
        delete_thread_with_lifecycle: bool = False,
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
        self._sessions[binding.thread_id] = _OfficialSession(
            client,
            stream,
            delete_thread_on_close=delete_thread_on_close,
            delete_thread_with_lifecycle=delete_thread_with_lifecycle,
        )
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

    async def _start_bound_run(self, binding: _RunBinding, client: Any) -> Mapping[str, Any]:
        configurable = {
            "workflow_id": str(binding.workflow["id"]),
            "request_id": binding.request_id,
            "lifecycle_id": binding.lifecycle_id,
            "caller_run_id": binding.caller_run_id,
            "operation_id": binding.operation_id,
        }
        return await client.runs.create(
            binding.thread_id,
            binding.assistant_id,
            input={
                "shared_vars": deepcopy(dict(binding.initial_shared_vars)),
            },
            config={
                **self._owner.run_config(),
                "configurable": configurable,
            },
            metadata={
                "lifecycle_id": binding.lifecycle_id,
                "request_id": binding.request_id,
                "graph_kind": "workflow",
                "workflow_id": str(binding.workflow["id"]),
                "workflow_name": str(binding.workflow["name"]),
                "caller_run_id": binding.caller_run_id,
                "operation_id": binding.operation_id,
            },
            durability=str(binding.workflow["durability"]),
        )

    async def _start_bound_agent_run(
        self,
        binding: _AgentRunBinding,
        client: Any,
    ) -> Mapping[str, Any]:
        agent_id = str(binding.main_agent["id"])
        configurable = {
            "main_agent_id": agent_id,
            "request_id": binding.request_id,
            "lifecycle_id": binding.lifecycle_id,
            "caller_run_id": binding.caller_run_id,
            "operation_id": binding.operation_id,
        }
        return await client.runs.create(
            (
                None
                if binding.main_agent.get("checkpoint_mode") == "disabled"
                else binding.thread_id
            ),
            binding.assistant_id,
            input={"messages": deepcopy(binding.messages)},
            config={
                **self._owner.run_config(),
                "configurable": configurable,
            },
            context={
                "request_id": binding.request_id,
                "lifecycle_id": binding.lifecycle_id,
                "caller_run_id": binding.caller_run_id,
                "operation_id": binding.operation_id,
            },
            metadata={
                "lifecycle_id": binding.lifecycle_id,
                "request_id": binding.request_id,
                "graph_kind": "agent",
                "main_agent_id": agent_id,
                "main_agent_name": str(binding.main_agent["name"]),
                "caller_run_id": binding.caller_run_id,
                "operation_id": binding.operation_id,
            },
            durability=str(binding.main_agent["durability"]),
            on_completion=(
                "keep"
                if binding.main_agent.get("checkpoint_mode") == "disabled"
                else None
            ),
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
    def _agent_run_result_ids(
        result: Mapping[str, Any],
    ) -> tuple[str, str]:
        run_id = result.get("run_id")
        thread_id = result.get("thread_id")
        if not isinstance(run_id, str) or not run_id:
            raise RuntimeError("the official Main Agent Run did not return run_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("the official Main Agent Run did not return thread_id")
        return run_id, thread_id

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
        checkpoint_mode = relation.checkpoint_mode
        if checkpoint_mode is None:
            raise RuntimeError("the Agent Run relation omits checkpoint_mode")
        return AgentRunHandle(
            operation_id=relation.operation_id,
            main_agent_id=relation.resource_id,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=official_status(run),
            checkpoint_mode=checkpoint_mode,
        )

    @staticmethod
    def _agent_snapshot_value(
        relation: GraphRunCallRelation,
        status: RunStatus,
        *,
        output: dict[str, Any] | None = None,
    ) -> AgentRunSnapshot:
        checkpoint_mode = relation.checkpoint_mode
        if checkpoint_mode is None:
            raise RuntimeError("the Agent Run relation omits checkpoint_mode")
        return AgentRunSnapshot(
            operation_id=relation.operation_id,
            caller_run_id=relation.caller_run_id,
            main_agent_id=relation.resource_id,
            main_agent_name=relation.resource_name,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=status,
            checkpoint_mode=checkpoint_mode,
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
            checkpoint_mode=(
                "disabled"
                if binding.main_agent.get("checkpoint_mode") == "disabled"
                else "enabled"
            ),
            assistant_id=binding.assistant_id,
            thread_id=binding.thread_id,
            run_id=binding.run_id,
        )

    def _release_if_finished(self) -> None:
        if not self._sessions:
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
        self._model_resources = model_resources or ModelResourceStore(configuration.data_root)
        self._mcp_resources = mcp_resources or McpResourceStore(configuration.data_root)
        self._run_config = dict(run_config)
        self._agent_server_url = agent_server_url
        self._agent_server_headers = {"Authorization": f"Bearer {agent_server_token}"}
        self._active_lifecycles: dict[str, LifecycleRunCoordinator] = {}
        self._langgraph_lifecycles = LangGraphLifecycleService(
            self.new_agent_server_client,
            workflow_lifecycle_settings,
        )

    def new_agent_server_client(self):
        return get_client(url=self._agent_server_url, headers=self._agent_server_headers)

    def run_config(self) -> dict[str, Any]:
        return dict(self._run_config)

    @property
    def langgraph_lifecycles(self) -> LangGraphLifecycleService:
        return self._langgraph_lifecycles

    async def enforce_lifecycle_retention(self) -> None:
        await self._langgraph_lifecycles.enforce_retention()

    def register_active_lifecycle(self, coordinator: LifecycleRunCoordinator) -> None:
        lifecycle_id = coordinator.lifecycle_id
        if not lifecycle_id or lifecycle_id in self._active_lifecycles:
            raise RuntimeError("the active Workflow Lifecycle identity is invalid")
        self._active_lifecycles[lifecycle_id] = coordinator

    def active_lifecycle(self, lifecycle_id: str) -> LifecycleRunCoordinator | None:
        return self._active_lifecycles.get(lifecycle_id)

    def release_active_lifecycle(self, coordinator: LifecycleRunCoordinator) -> None:
        lifecycle_id = coordinator.lifecycle_id
        if self._active_lifecycles.get(lifecycle_id) is coordinator:
            self._active_lifecycles.pop(lifecycle_id, None)
            self._detached_tasks.create(
                self.enforce_lifecycle_retention(),
                name="langgraph-lifecycle-retention",
            )

    async def capture(self) -> RequestRuntimeSnapshot:
        """Freeze one request configuration without blocking the server loop."""

        return await asyncio.to_thread(self._capture)

    def _capture(self) -> RequestRuntimeSnapshot:
        response_stream_policy = self._response_stream_policy_provider()
        with self._configuration.request_snapshot_context() as context:
            repository, python_packages_dir, skills_dir, repository_id = context
        blocks = BlockStore(repository)
        configs = AgentConfigStore(repository)
        workflows = WorkflowStore(repository)
        model_resources = self._model_resources.snapshot()
        mcp_resources = self._mcp_resources.snapshot()
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
                run_config=self._run_config,
                graph_store=graph_store,
            )

        return RequestRuntimeSnapshot(
            _workflows=workflows,
            _agents=configs,
            _runtime_factory=runtime_factory,
            _response_stream_policy=response_stream_policy,
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
