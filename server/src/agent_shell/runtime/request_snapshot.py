from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_shell.file_manager import FileManagerService
from agent_shell.python_packages.validation import PythonPackageValidationService
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.provider_secrets import ProviderSecretResolver
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_runtime import AgentRuntime, RunExecution
from agent_shell.runtime.background_commands import BackgroundRunCaller
from agent_shell.runtime.background_tasks import (
    BackgroundTaskHandle,
    BackgroundTaskManager,
    BackgroundTaskSnapshot,
    BackgroundTaskStatus,
)
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.response_scheduler import LifecycleResponseScheduler
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.model_connections import ModelResourceSnapshot, ModelResourceStore
from agent_shell.storage.mcp_connections import McpResourceStore
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.workflow import WorkflowGraphDocumentV1


@dataclass(frozen=True, slots=True)
class RequestRuntimeSnapshot:
    """Immutable configuration catalog and runtime materialization inputs."""

    _workflows: WorkflowStore
    _runtime: AgentRuntime
    _runtime_factory: Callable[[], AgentRuntime]

    def workflow_by_name(self, name: str) -> dict[str, Any] | None:
        return self._workflows.get_item_by_name(name)

    def workflow_by_id(self, workflow_id: str) -> dict[str, Any] | None:
        return self._workflows.get_item(workflow_id)

    def workflow_document(
        self,
        workflow_id: str,
    ) -> WorkflowGraphDocumentV1 | None:
        return self._workflows.get_graph(workflow_id)

    def parent_runtime(self) -> AgentRuntime:
        return self._runtime

    def new_child_runtime(self) -> AgentRuntime:
        return self._runtime_factory()


@dataclass(slots=True)
class LifecycleRunCoordinator:
    """Mutable parent/child Run coordination for one request Lifecycle."""

    _snapshot: RequestRuntimeSnapshot
    _workflow_lifecycle: WorkflowLifecycleService
    _background_tasks: BackgroundTaskManager
    _response_scheduler: LifecycleResponseScheduler | None = field(
        default=None,
        init=False,
    )

    async def start_parent_workflow(
        self,
        workflow: Mapping[str, Any],
        raw_messages: object,
        **kwargs: Any,
    ) -> RunExecution:
        document = self._snapshot.workflow_document(str(workflow["id"]))
        if document is None:
            raise RuntimeError("the captured Workflow no longer exists")
        execution = await self._snapshot.parent_runtime().start_workflow(
            document,
            raw_messages,
            workflow_snapshot=workflow,
            background_runtime=self,
            **kwargs,
        )
        self._response_scheduler = execution.response_scheduler
        return execution

    async def start_background_workflow(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        caller: BackgroundRunCaller,
        shared_vars: Mapping[str, Any],
        workflow_task: Mapping[str, Any] | None = None,
    ) -> BackgroundTaskHandle:
        target = self._snapshot.workflow_by_id(target_workflow_id)
        if (
            target is None
            or not target["enabled"]
            or target["workflow_role"] != "child"
        ):
            raise AgentRuntimeError(
                "background_workflow_target_not_found",
                "The selected child Workflow does not exist or is disabled.",
                status_code=422,
            )
        document = self._snapshot.workflow_document(target_workflow_id)
        if document is None:
            raise AgentRuntimeError(
                "background_workflow_target_not_found",
                "The selected child Workflow does not exist.",
                status_code=422,
            )
        frozen_shared_vars = deepcopy(dict(shared_vars))
        frozen_workflow_task = (
            deepcopy(dict(workflow_task)) if workflow_task is not None else None
        )

        async def build_execution(identity):
            messages = await self._workflow_lifecycle.messages(
                caller.lifecycle_id
            )
            child_runtime = self._snapshot.new_child_runtime()
            response_scheduler = self._response_scheduler
            return await child_runtime.start_workflow(
                document,
                messages,
                workflow_snapshot=target,
                request_id=caller.request_id,
                public_model=str(target["name"]),
                lifecycle_id=caller.lifecycle_id,
                workflow_run_id=identity.child_run_id,
                checkpoint_thread_id=identity.checkpoint_thread_id,
                parent_workflow_run_id=caller.workflow_run_id,
                background_task_id=identity.task_id,
                run_depth=identity.run_depth,
                initial_shared_vars=frozen_shared_vars,
                initial_workflow_task=frozen_workflow_task,
                background_runtime=self,
                public_output=response_scheduler is not None,
                response_scheduler=response_scheduler,
                response_consumer=False,
            )

        return await self._background_tasks.start_workflow(
            lifecycle_id=caller.lifecycle_id,
            request_id=caller.request_id,
            launcher_run_id=caller.workflow_run_id,
            operation_id=operation_id,
            caller_run_depth=caller.run_depth,
            target_id=target_workflow_id,
            target_name=str(target["name"]),
            target_document=document,
            checkpoint_thread_id=(
                str(uuid4()) if target.get("checkpointer_id") is not None else None
            ),
            cancel_on_upstream_termination=bool(
                target["cancel_on_upstream_termination"]
            ),
            execution_factory=build_execution,
        )

    async def cancel_children_on_parent_termination(
        self,
        lifecycle_id: str,
        parent_run_id: str,
    ) -> None:
        await self._background_tasks.cancel_children_on_parent_termination(
            lifecycle_id,
            parent_run_id,
        )

    async def check_background_tasks(
        self,
        task_ids: list[str],
        *,
        caller: BackgroundRunCaller,
    ) -> list[BackgroundTaskSnapshot]:
        return await self._background_tasks.check(
            caller.lifecycle_id,
            task_ids,
        )

    async def list_background_tasks(
        self,
        *,
        caller: BackgroundRunCaller,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]:
        return await self._background_tasks.list(
            caller.lifecycle_id,
            statuses=statuses,
        )

    async def cancel_background_tasks(
        self,
        task_ids: list[str],
        *,
        caller: BackgroundRunCaller,
    ) -> list[BackgroundTaskSnapshot]:
        return await self._background_tasks.cancel(
            caller.lifecycle_id,
            task_ids,
        )


class RequestSnapshotRuntime:
    """Capture the latest committed file configuration for each Agent construction."""

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
        background_tasks: BackgroundTaskManager,
        runtime_diagnostics: RuntimeDiagnostics,
        runtime_policy: RuntimePolicyStore,
        model_resources: ModelResourceStore | None = None,
        mcp_resources: McpResourceStore | None = None,
    ) -> None:
        self._configuration = configuration
        self._python_packages_dir_source = python_packages_dir
        self._runtime_dir = runtime_dir
        self._skills_dir_source = skills_dir
        self._provider_http_clients = provider_http_clients
        self._files = files
        self._workflow_checkpoints = workflow_checkpoints
        self._workflow_lifecycle = workflow_lifecycle
        self._background_tasks = background_tasks
        self._runtime_diagnostics = runtime_diagnostics
        self._runtime_policy = runtime_policy
        self._model_resources = model_resources or ModelResourceStore(configuration.data_root)
        self._mcp_resources = mcp_resources or McpResourceStore(configuration.data_root)

    def capture(self) -> RequestRuntimeSnapshot:
        with self._configuration.request_snapshot_context() as context:
            repository, python_packages_dir, skills_dir, _repository_id = context
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
        def runtime_factory() -> AgentRuntime:
            return AgentRuntime(
                AgentBuilder(
                    secrets,
                    python_packages_dir=python_packages_dir,
                    runtime_dir=self._runtime_dir,
                    skills_dir=skills_dir,
                    validation=validation,
                    provider_http_clients=self._provider_http_clients,
                    store=self._workflow_lifecycle.store,
                    model_resources=model_resources,
                    mcp_resources=mcp_resources,
                    repository_id=_repository_id,
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
            )

        runtime = runtime_factory()
        return RequestRuntimeSnapshot(
            _workflows=workflows,
            _runtime=runtime,
            _runtime_factory=runtime_factory,
        )

    def create_lifecycle_coordinator(
        self,
        snapshot: RequestRuntimeSnapshot,
    ) -> LifecycleRunCoordinator:
        return LifecycleRunCoordinator(
            _snapshot=snapshot,
            _workflow_lifecycle=self._workflow_lifecycle,
            _background_tasks=self._background_tasks,
        )
