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
from agent_shell.python_packages.validation import PythonPackageValidationService
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.provider_secrets import ProviderSecretResolver
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_runtime import AgentRuntime, RunExecution
from agent_shell.runtime.workflow_run_commands import WorkflowRunCaller
from agent_shell.runtime.detached_tasks import DetachedTaskManager
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.errors import AgentRuntimeError, decode_server_run_error
from agent_shell.runtime.input_messages import client_messages_sha, validate_client_messages
from agent_shell.runtime.response_scheduler import LifecycleResponseScheduler
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import (
    LIFECYCLE_INPUT_KEY,
    WorkflowLifecycleService,
    lifecycle_input_namespace,
)
from agent_shell.runtime.workflow_run_calls import (
    ACTIVE_WORKFLOW_RUN_STATUSES,
    WorkflowRunCallRelation,
    WorkflowRunHandle,
    WorkflowRunSnapshot,
    WorkflowRunStatus,
    official_status,
    relation_key,
    search_run_call_relations,
    select_relations,
    workflow_run_calls_namespace,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.mcp_connections import McpResourceStore
from agent_shell.storage.model_connections import ModelResourceStore
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.workflow import WorkflowGraphDocumentV1


LANGGRAPH_WORKFLOW_GRAPH_ID = "agent-shell-workflow"


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
    initial_workflow_task: Mapping[str, Any] | None = None
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


@dataclass(frozen=True, slots=True)
class RequestRuntimeSnapshot:
    """Immutable configuration catalog and runtime materialization inputs."""

    _workflows: WorkflowStore
    _runtime_factory: Callable[[BaseStore | None], AgentRuntime]

    def workflow_by_name(self, name: str) -> dict[str, Any] | None:
        return self._workflows.get_item_by_name(name)

    def workflow_by_id(self, workflow_id: str) -> dict[str, Any] | None:
        return self._workflows.get_item(workflow_id)

    def workflow_document(self, workflow_id: str) -> WorkflowGraphDocumentV1 | None:
        return self._workflows.get_graph(workflow_id)

    def new_runtime(self, *, store: BaseStore) -> AgentRuntime:
        return self._runtime_factory(store)


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
    _sessions: dict[str, _OfficialSession] = field(default_factory=dict, init=False)
    _root_thread_id: str = field(default="", init=False)
    _root_finished: bool = field(default=False, init=False)

    @property
    def lifecycle_id(self) -> str:
        return self._lifecycle_id

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
        messages = validate_client_messages(
            raw_messages,
            self._owner.runtime_policy_snapshot(),
        )
        lifecycle_id = str(uuid4())
        self._lifecycle_id = lifecycle_id
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
            self._root_thread_id = binding.thread_id
            result = await self._start_bound_run(binding, thread_stream)
            self._bind_official_run_id(binding, result)
            assert binding.execution_ready is not None
            return await binding.execution_ready
        except BaseException:
            self._cancel_binding_futures(binding)
            with suppress(Exception):
                await self.close_official_session(binding.thread_id)
            self._root_finished = True
            self._release_if_finished()
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
                initial_workflow_task=binding.initial_workflow_task,
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
        caller: WorkflowRunCaller,
        shared_vars: Mapping[str, Any],
        workflow_task: Mapping[str, Any] | None = None,
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
            if existing.workflow_id != target_workflow_id:
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
            initial_workflow_task=(
                deepcopy(dict(workflow_task)) if workflow_task is not None else None
            ),
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
            relation = WorkflowRunCallRelation(
                lifecycle_id=binding.lifecycle_id,
                operation_id=binding.operation_id,
                caller_run_id=binding.caller_run_id,
                workflow_id=str(target["id"]),
                workflow_name=str(target["name"]),
                assistant_id=binding.assistant_id,
                thread_id=binding.thread_id,
                run_id=binding.run_id,
                cancel_on_caller_termination=bool(
                    target["cancel_on_caller_termination"]
                ),
            )
            await client.store.put_item(
                workflow_run_calls_namespace(binding.lifecycle_id),
                binding.key,
                relation.model_dump(mode="json"),
                index=False,
            )
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

    async def check_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: WorkflowRunCaller,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._caller_relations(caller)
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
        caller: WorkflowRunCaller,
        statuses: frozenset[WorkflowRunStatus] | None = None,
    ) -> list[WorkflowRunSnapshot]:
        relations = await self._caller_relations(caller)
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
        caller: WorkflowRunCaller,
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
        caller: WorkflowRunCaller,
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

    async def cancel_spawned_runs_on_caller_termination(
        self,
        lifecycle_id: str,
        caller_run_id: str,
    ) -> None:
        caller = WorkflowRunCaller("", lifecycle_id, caller_run_id)
        relations = await self._caller_relations(caller)
        async with self._owner.new_agent_server_client() as client:
            for relation in relations:
                if not relation.cancel_on_caller_termination:
                    continue
                run = await client.runs.get(relation.thread_id, relation.run_id)
                if official_status(run) in ACTIVE_WORKFLOW_RUN_STATUSES:
                    await client.runs.cancel(
                        relation.thread_id,
                        relation.run_id,
                        wait=False,
                    )

    async def cancel_official_run(self, thread_id: str, run_id: str) -> None:
        if not thread_id or not run_id:
            return
        async with self._owner.new_agent_server_client() as client:
            run = await client.runs.get(thread_id, run_id)
            if official_status(run) in ACTIVE_WORKFLOW_RUN_STATUSES:
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
        if thread_id == self._root_thread_id:
            self._root_finished = True
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
        initial_workflow_task: Mapping[str, Any] | None = None,
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
            initial_workflow_task=initial_workflow_task,
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
                metadata={"workflow_id": str(binding.workflow["id"])},
                assistant_id=str(binding.workflow["id"]),
                if_exists="do_nothing",
                name=str(binding.workflow["name"]),
            )
            binding.assistant_id = str(assistant["assistant_id"])
            thread = await client.threads.create(
                metadata={
                    "lifecycle_id": binding.lifecycle_id,
                    "request_id": binding.request_id,
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

    async def _start_bound_run(self, binding: _RunBinding, stream: Any) -> Mapping[str, Any]:
        configurable = {
            "workflow_id": str(binding.workflow["id"]),
            "request_id": binding.request_id,
            "lifecycle_id": binding.lifecycle_id,
            "caller_run_id": binding.caller_run_id,
            "operation_id": binding.operation_id,
        }
        return await stream.run.start(
            input={
                "shared_vars": deepcopy(dict(binding.initial_shared_vars)),
                "agent_invocations": {},
                **(
                    {"workflow_task": deepcopy(dict(binding.initial_workflow_task))}
                    if binding.initial_workflow_task is not None
                    else {}
                ),
            },
            config={
                "recursion_limit": int(binding.workflow["recursion_limit"]),
                "max_concurrency": int(binding.workflow["max_concurrency"]),
                "configurable": configurable,
            },
            metadata={
                "lifecycle_id": binding.lifecycle_id,
                "request_id": binding.request_id,
                "workflow_id": str(binding.workflow["id"]),
                "workflow_name": str(binding.workflow["name"]),
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
    def _cancel_binding_futures(binding: _RunBinding) -> None:
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
        caller: WorkflowRunCaller,
        operation_id: str,
    ) -> WorkflowRunCallRelation | None:
        relations = await self._caller_relations(caller)
        return next(
            (
                relation
                for relation in relations
                if relation.operation_id == operation_id
            ),
            None,
        )

    async def _caller_relations(
        self,
        caller: WorkflowRunCaller,
    ) -> list[WorkflowRunCallRelation]:
        async with self._owner.new_agent_server_client() as client:
            relations = await search_run_call_relations(client, caller.lifecycle_id)
        return select_relations(relations, caller_run_id=caller.run_id)

    async def _selected_relations(
        self,
        caller: WorkflowRunCaller,
        run_ids: Sequence[str],
    ) -> list[WorkflowRunCallRelation]:
        relations = await self._caller_relations(caller)
        return select_relations(
            relations,
            caller_run_id=caller.run_id,
            run_ids=run_ids,
        )

    async def _run_snapshot(
        self,
        client: Any,
        relation: WorkflowRunCallRelation,
        run: Mapping[str, Any],
    ) -> WorkflowRunSnapshot:
        status = official_status(run)
        output = None
        if status not in ACTIVE_WORKFLOW_RUN_STATUSES:
            state = await client.threads.get_state(relation.thread_id)
            values = state.get("values") if isinstance(state, Mapping) else None
            output = values if isinstance(values, dict) else {}
        return self._snapshot_value(relation, status, output=output)

    @staticmethod
    def _handle(
        relation: WorkflowRunCallRelation,
        run: Mapping[str, Any],
    ) -> WorkflowRunHandle:
        return WorkflowRunHandle(
            operation_id=relation.operation_id,
            workflow_id=relation.workflow_id,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=official_status(run),
        )

    @staticmethod
    def _snapshot_value(
        relation: WorkflowRunCallRelation,
        status: WorkflowRunStatus,
        *,
        output: dict[str, Any] | None = None,
    ) -> WorkflowRunSnapshot:
        return WorkflowRunSnapshot(
            operation_id=relation.operation_id,
            caller_run_id=relation.caller_run_id,
            workflow_id=relation.workflow_id,
            workflow_name=relation.workflow_name,
            assistant_id=relation.assistant_id,
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            status=status,
            output=output,
        )

    def _release_if_finished(self) -> None:
        if self._root_finished and not self._sessions:
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
        workflow_checkpoints: WorkflowCheckpointService,
        workflow_lifecycle: WorkflowLifecycleService,
        detached_tasks: DetachedTaskManager,
        runtime_diagnostics: RuntimeDiagnostics,
        runtime_policy: RuntimePolicyStore,
        model_resources: ModelResourceStore | None = None,
        mcp_resources: McpResourceStore | None = None,
        agent_server_url: str,
        agent_server_token: str,
    ) -> None:
        self._configuration = configuration
        self._python_packages_dir_source = python_packages_dir
        self._runtime_dir = runtime_dir
        self._skills_dir_source = skills_dir
        self._provider_http_clients = provider_http_clients
        self._files = files
        self._workflow_checkpoints = workflow_checkpoints
        self._workflow_lifecycle = workflow_lifecycle
        self._detached_tasks = detached_tasks
        self._runtime_diagnostics = runtime_diagnostics
        self._runtime_policy = runtime_policy
        self._model_resources = model_resources or ModelResourceStore(configuration.data_root)
        self._mcp_resources = mcp_resources or McpResourceStore(configuration.data_root)
        self._agent_server_url = agent_server_url
        self._agent_server_headers = {"Authorization": f"Bearer {agent_server_token}"}
        self._active_lifecycles: dict[str, LifecycleRunCoordinator] = {}

    def runtime_policy_snapshot(self):
        return self._runtime_policy.snapshot()

    def new_agent_server_client(self):
        return get_client(url=self._agent_server_url, headers=self._agent_server_headers)

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

    def capture(self) -> RequestRuntimeSnapshot:
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
            effective_store = graph_store or self._workflow_lifecycle.store
            return AgentRuntime(
                AgentBuilder(
                    secrets,
                    python_packages_dir=python_packages_dir,
                    runtime_dir=self._runtime_dir,
                    skills_dir=skills_dir,
                    validation=validation,
                    provider_http_clients=self._provider_http_clients,
                    store=effective_store,
                    model_resources=model_resources,
                    mcp_resources=mcp_resources,
                    repository_id=repository_id,
                    runtime_policy=self._runtime_policy,
                ),
                self._files,
                python_packages_dir=python_packages_dir,
                runtime_dir=self._runtime_dir,
                blocks=blocks,
                workflow_checkpoints=self._workflow_checkpoints,
                workflow_lifecycle=self._workflow_lifecycle,
                runtime_diagnostics=self._runtime_diagnostics,
                runtime_policy=self._runtime_policy,
                graph_store=effective_store,
            )

        return RequestRuntimeSnapshot(
            _workflows=workflows,
            _runtime_factory=runtime_factory,
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
