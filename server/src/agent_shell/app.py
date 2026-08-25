from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agent_shell.api.routes import build_router
from agent_shell.api.configuration_bundles import build_configuration_bundle_router
from agent_shell.api.configuration_repositories import build_configuration_repository_router
from agent_shell.api.agent_configs import build_agent_config_router
from agent_shell.api.python_packages import build_python_package_router
from agent_shell.api.errors import localized_error_detail
from agent_shell.api.system import build_system_router
from agent_shell.api.api_server import (
    ApiServerEventHub,
    MessageInterceptionState,
    build_api_server_router,
)
from agent_shell.api.event_feed import build_event_feed_router
from agent_shell.api.runtime_diagnostics import build_runtime_diagnostics_router
from agent_shell.api.file_manager import build_file_manager_router
from agent_shell.api.provider_integrations import build_provider_integrations_router
from agent_shell.api.system_settings import build_system_settings_router
from agent_shell.api.model_connections import build_model_connection_router
from agent_shell.api.validation import build_validation_router
from agent_shell.api.workflows import build_workflow_router
from agent_shell.api.workflow_lifecycles import build_workflow_lifecycle_router
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.provider_secrets import ProviderSecretResolver
from agent_shell.langsmith_tracing import configure_project_langsmith_tracing
from agent_shell.runtime.request_snapshot import RequestSnapshotRuntime
from agent_shell.runtime.background_tasks import BackgroundTaskManager
from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.settings import (
    Settings,
    SettingsError,
    get_settings,
)
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.event_feed import EventFeedService
from agent_shell.redaction import redact_for_boundary
from agent_shell.readiness import ReadinessService
from agent_shell.security_events import SecurityEventLogger
from agent_shell.security import (
    ApiKeyPolicyError,
    ScopeAuthenticationMiddleware,
    TrustedProxyHeadersMiddleware,
    validate_api_key_policy,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.database import SQLiteDatabase, SQLiteFile
from agent_shell.storage.file_config import (
    ActiveRepositoryChangedError,
    FileConfigRepository,
)
from agent_shell.storage.history_retention import HistoryRetentionStore
from agent_shell.storage.media_outputs import MediaOutputStore
from agent_shell.storage.runtime_diagnostic_details import RuntimeDiagnosticDetailStore
from agent_shell.storage.runtime_diagnostics import RuntimeDiagnosticStore
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.storage.system_log_settings import MIB_BYTES, SystemLogSettingsStore
from agent_shell.storage.validation_settings import ConfigurationValidationSettingsStore
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.storage.environment import InstanceEnvironmentStore
from agent_shell.storage.model_connections import ModelResourceStore
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.validation.repository import RepositoryValidationService
from agent_shell.python_packages.validation import PythonPackageValidationService
from agent_shell.python_packages.authoring import PythonPackageAuthoringService
from agent_shell.skills.authoring import SkillPackageAuthoringService
from agent_shell.file_manager import FileManagerService
from agent_shell.system_settings import SystemSettingsService
from agent_shell.storage.permissions import secure_directory, secure_file
from agent_shell.configuration.component_mutations import ComponentMutationService
from agent_shell.configuration.bundles.journal import recover_configuration_imports
from agent_shell.configuration.bundles.service import ConfigurationBundleService
from agent_shell.configuration.repository_management import (
    ConfigurationRepositoryManagementService,
)


def create_app(
    *,
    settings: Settings | None = None,
    serve_frontend: bool | None = None,
) -> FastAPI:
    application_home = (
        settings.application_home if settings is not None else Path.cwd().resolve()
    )
    if settings is None:
        settings = get_settings(application_home=application_home)
    langsmith_client = configure_project_langsmith_tracing(settings)
    settings.ensure_directories()
    recover_configuration_imports(settings.data_root)

    environment_permissions = ()
    environment_path = settings.environment_file
    if environment_path.exists():
        environment_permission = secure_file(environment_path)
        if not environment_permission.enforced:
            raise SettingsError(
                ("data/config/agent-shell.env",),
                "Restrict the management settings file to the service account.",
            )
        environment_permissions = (environment_permission,)
    python_templates_dir = settings.resolved_python_templates_dir()
    skill_templates_dir = settings.resolved_skill_templates_dir()

    runtime_dir = settings.resolved_runtime_dir()
    logs_dir = settings.resolved_logs_dir()
    runtime_permissions = tuple(
        secure_directory(path)
        for path in (
            runtime_dir,
            runtime_dir / "cache",
            runtime_dir / "tmp",
            runtime_dir / "home",
        )
    )
    application_database = SQLiteDatabase(
        settings.resolved_application_database_path()
    )
    workflow_checkpoint_database = SQLiteFile(
        settings.resolved_workflow_checkpoint_database_path(),
        create=False,
    )
    workflow_store_database = SQLiteFile(
        settings.resolved_workflow_store_database_path()
    )
    configuration_mutations = ConfigurationMutationCoordinator()
    environment = InstanceEnvironmentStore(
        settings.environment_file,
        mutations=configuration_mutations,
    )
    configuration = FileConfigRepository(
        settings.data_root,
        mutations=configuration_mutations,
        environment=environment,
    )
    model_resources = ModelResourceStore(
        settings.data_root,
        environment=environment,
        mutations=configuration_mutations,
    )
    python_package_instances_dir = configuration.python_package_instances_root
    skill_package_instances_dir = configuration.skill_package_instances_root
    runtime_policy = RuntimePolicyStore(configuration)
    media_outputs = MediaOutputStore(
        application_database,
        settings.resolved_media_outputs_dir(),
        runtime_policy,
    )
    system_log_settings = SystemLogSettingsStore(configuration)
    event_logger = SecurityEventLogger(
        logs_dir,
        max_bytes=system_log_settings.snapshot()["max_size_mib"] * MIB_BYTES,
    )
    history_retention = HistoryRetentionStore(configuration)
    workflow_checkpoints = WorkflowCheckpointService(workflow_checkpoint_database)
    runtime_diagnostic_details = RuntimeDiagnosticDetailStore(logs_dir / "diagnostics")
    configuration_validation_settings = ConfigurationValidationSettingsStore(configuration)
    runtime_diagnostic_store = RuntimeDiagnosticStore(
        application_database, history_retention
    )
    block_store = BlockStore(configuration, event_logger)
    config_store = AgentConfigStore(configuration, event_logger)
    workflow_store = WorkflowStore(configuration, event_logger)
    python_package_validation = PythonPackageValidationService(
        packages_dir=lambda: configuration.python_package_instances_root,
        runtime_root=runtime_dir,
    )
    workflow_lifecycle = WorkflowLifecycleService(
        application_database,
        store_database=workflow_store_database,
        data_root=settings.data_root,
    )
    python_package_authoring = PythonPackageAuthoringService(
        templates_root=python_templates_dir,
        examples_root=application_home / "examples",
        instances_root=lambda: configuration.python_package_instances_root,
        runtime_root=runtime_dir,
    )
    skill_package_authoring = SkillPackageAuthoringService(
        templates_root=skill_templates_dir,
        instances_root=lambda: configuration.skill_package_instances_root,
    )
    configuration_validation = ConfigurationValidationService(
        block_store,
        config_store,
        python_package_validation,
    )
    component_mutations = ComponentMutationService(
        configuration,
        block_store,
        configuration_validation,
        python_package_authoring,
        skill_package_authoring,
    )
    repository_validation = RepositoryValidationService(
        configuration,
        block_store,
        configuration_validation,
        model_resources=model_resources,
    )
    configuration_bundles = ConfigurationBundleService(
        configuration,
        packages_dir=lambda: configuration.python_package_instances_root,
        skills_dir=lambda: configuration.skill_package_instances_root,
        runtime_root=runtime_dir,
    )
    configuration_repository_management = (
        ConfigurationRepositoryManagementService(
            configuration,
            model_resources,
        )
    )
    api_server_store = ApiServerStore(
        application_database,
        configuration,
        environment,
        configuration_mutations,
        event_logger,
    )
    try:
        validate_api_key_policy(settings, api_server_store.api_key())
    except ApiKeyPolicyError as exc:
        raise SettingsError(
            ("API Server API Key",), exc.safe_message
        ) from None
    api_server_events = ApiServerEventHub()
    message_interception = MessageInterceptionState()
    event_logger.set_publisher(api_server_events.publish_nowait)
    runtime_diagnostics = RuntimeDiagnostics(
        api_server_events.publish_nowait,
        store=runtime_diagnostic_store,
        details=runtime_diagnostic_details,
    )
    background_tasks = BackgroundTaskManager(
        workflow_lifecycle,
        runtime_diagnostics=runtime_diagnostics,
    )
    event_logger.set_failure_reporter(
        lambda exc, request_id: runtime_diagnostics.observation_error(
            exc,
            code="security_event_record_failed",
            component="security",
            context=RuntimeDiagnosticContext(
                request_id=request_id,
                subject_kind="persistence",
                subject_name="system event log",
            ),
        )
    )
    event_feed = EventFeedService(
        event_logger,
        runtime_diagnostics,
        system_log_settings,
    )
    secret_resolver = ProviderSecretResolver(configuration, model_resources)
    provider_http_clients = ProviderHttpClients(runtime_policy)
    file_manager = FileManagerService(
        settings.data_root,
        settings.resolved_runtime_dir() / "tmp",
        runtime_policy,
    )
    system_settings = SystemSettingsService(
        settings,
        api_server_store.api_key,
        configuration,
        environment,
        configuration_mutations,
    )
    agent_runtime = RequestSnapshotRuntime(
        configuration,
        python_packages_dir=lambda: configuration.python_package_instances_root,
        runtime_dir=runtime_dir,
        skills_dir=lambda: configuration.skill_package_instances_root,
        provider_http_clients=provider_http_clients,
        media_outputs=media_outputs,
        workflow_checkpoints=workflow_checkpoints,
        workflow_lifecycle=workflow_lifecycle,
        background_tasks=background_tasks,
        runtime_diagnostics=runtime_diagnostics,
        runtime_policy=runtime_policy,
        model_resources=model_resources,
    )

    frontend_dir = Path(__file__).resolve().parents[3] / "runtime" / "frontend_dist"
    frontend_available = (
        (frontend_dir / "index.html").is_file()
        and (frontend_dir / "assets").is_dir()
    )
    if serve_frontend is None:
        serve_frontend = frontend_available
    elif serve_frontend and not frontend_available:
        raise RuntimeError(
            "The production frontend build is missing. Build the frontend before "
            "starting the Agent Shell source instance."
        )
    startup_permission_statuses = (
        *environment_permissions,
        *runtime_permissions,
        application_database.directory_permission,
        *application_database.file_permissions,
        *workflow_checkpoint_database.file_permissions,
        *workflow_store_database.file_permissions,
        media_outputs.directory_permission,
        *event_logger.permission_statuses,
        runtime_diagnostic_details.directory_permission,
    )
    readiness = ReadinessService(
        settings=settings,
        startup_permission_statuses=startup_permission_statuses,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await workflow_lifecycle.start()
        await background_tasks.start()
        try:
            event_logger.emit(
                "security_configuration_loaded",
                {
                    "deployment_mode": settings.deployment_mode,
                    "management_scope": "configured",
                    "api_scope": (
                        "configured"
                        if api_server_store.api_key() is not None
                        else "unavailable"
                    ),
                    "trusted_proxy": bool(settings.trusted_proxy_cidrs),
                },
            )
            event_logger.emit(
                "service_started", {"deployment_mode": settings.deployment_mode}
            )
            yield
        finally:
            try:
                await background_tasks.close()
            finally:
                try:
                    await provider_http_clients.aclose()
                finally:
                    try:
                        await workflow_checkpoints.close()
                    finally:
                        try:
                            await workflow_lifecycle.close()
                        finally:
                            event_logger.emit(
                                "service_stopped", {"reason": "application_shutdown"}
                            )
                            runtime_diagnostics.close()
                            if langsmith_client is not None:
                                langsmith_client.close(timeout=5.0)

    app = FastAPI(
        title=settings.app_name,
        description="Agent configuration shell with OpenAI-compatible Main Agent execution.",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    def record_management_failure(
        request: Request,
        *,
        status_code: int,
        detail: object,
    ) -> None:
        if request.url.path != "/api" and not request.url.path.startswith("/api/"):
            return
        code = "request_failed"
        issue_count = 0
        if isinstance(detail, dict):
            code = str(detail.get("code", code))
            validation = detail.get("validation")
            issues = (
                validation.get("issues", [])
                if isinstance(validation, dict)
                else detail.get("issues", [])
            )
            issue_count = len(issues) if isinstance(issues, list) else 0
        event_logger.emit(
            "management_request_failed",
            {
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "code": code,
                "issue_count": issue_count,
            },
        )

    @app.exception_handler(HTTPException)
    async def safe_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        headers = dict(exc.headers or {})
        request_id = getattr(request.state, "request_id", "")
        if request_id:
            headers["X-Request-ID"] = request_id
        detail = redact_for_boundary("http-error", exc.detail)
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            if not isinstance(detail, dict) or not isinstance(
                detail.get("message_key"), str
            ):
                detail = localized_error_detail(
                    code=(
                        str(detail.get("code", "request_failed"))
                        if isinstance(detail, dict)
                        else "request_failed"
                    ),
                    message_key="errors.requestFailed",
                    message="The management request failed.",
                )
        record_management_failure(
            request,
            status_code=exc.status_code,
            detail=detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={"detail": detail},
        )

    @app.exception_handler(ActiveRepositoryChangedError)
    async def repository_changed_error(
        request: Request, exc: ActiveRepositoryChangedError
    ) -> JSONResponse:
        return await safe_http_error(
            request,
            HTTPException(
                status_code=409,
                detail=localized_error_detail(
                    code="configuration_repository_changed",
                    message_key="errors.configurationRepositoryChanged",
                    message=(
                        "The active Configuration Repository changed while the "
                        "request was being prepared. Reload and try again."
                    ),
                ),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def safe_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {
                key: error[key]
                for key in ("type", "loc", "msg")
                if key in error
            }
            for error in exc.errors()
        ]
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            detail: object = {
                **localized_error_detail(
                    code="request_validation_failed",
                    message_key="errors.requestValidationFailed",
                    message="The management request payload is invalid.",
                    message_args={"count": len(safe_errors)},
                ),
                "issues": safe_errors,
            }
        else:
            detail = safe_errors
        record_management_failure(request, status_code=422, detail=detail)
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
            content={
                "detail": redact_for_boundary(
                    "http-error",
                    detail,
                )
            },
        )

    @app.exception_handler(Exception)
    async def safe_internal_error(request: Request, exc: Exception) -> JSONResponse:
        runtime_diagnostics.runtime_error(
            exc,
            code="internal_error",
            component="api",
            context=RuntimeDiagnosticContext(
                request_id=getattr(request.state, "request_id", ""),
                subject_kind="api",
                subject_name=request.url.path,
            ),
        )
        request_id = getattr(request.state, "request_id", "")
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            content: dict[str, object] = {
                "detail": localized_error_detail(
                    code="internal_error",
                    message_key="errors.internalError",
                    message="An internal management operation failed.",
                ),
                "request_id": request_id,
            }
        else:
            content = {
                "error": {
                    "message": "An internal operation failed.",
                    "type": "internal_error",
                    "param": None,
                    "code": "internal_error",
                },
                "request_id": request_id,
            }
        record_management_failure(
            request,
            status_code=500,
            detail=content.get("detail") or content.get("error") or {},
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content=content,
        )
    app.state.settings = settings
    app.state.startup_storage_permissions = startup_permission_statuses
    app.state.security_events = event_logger
    app.state.agent_runtime = agent_runtime
    app.state.runtime_diagnostics = runtime_diagnostics
    app.state.runtime_diagnostic_store = runtime_diagnostic_store
    app.state.runtime_diagnostic_details = runtime_diagnostic_details
    app.state.api_server_store = api_server_store
    app.state.message_interception = message_interception
    app.state.media_outputs = media_outputs
    app.state.runtime_policy = runtime_policy
    app.state.provider_http_clients = provider_http_clients
    app.state.event_feed = event_feed
    app.state.workflow_checkpoints = workflow_checkpoints
    app.state.workflow_lifecycle = workflow_lifecycle
    app.state.background_tasks = background_tasks
    app.state.system_log_settings = system_log_settings
    app.state.model_resources = model_resources
    app.add_middleware(
        ScopeAuthenticationMiddleware,
        settings=settings,
        api_key_provider=api_server_store.api_key,
        event_logger=event_logger,
    )
    if settings.trusted_proxy_cidrs:
        app.add_middleware(
            TrustedProxyHeadersMiddleware,
            trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
        )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization", "Content-Type", "X-Request-ID"
            ],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    app.include_router(build_system_router(readiness))
    app.include_router(build_configuration_bundle_router(configuration_bundles))
    app.include_router(
        build_configuration_repository_router(
            configuration,
            configuration_repository_management,
            repository_validation,
            runtime_root=runtime_dir,
        )
    )
    app.include_router(
        build_router(
            configuration,
            block_store,
            config_store,
            skill_templates_dir,
            secret_resolver,
            provider_http_clients,
            workflow_store,
            python_package_authoring,
            skill_package_authoring,
            component_mutations,
            runtime_policy,
        )
    )
    app.include_router(
        build_model_connection_router(
            configuration,
            block_store,
            model_resources,
        )
    )
    app.include_router(
        build_agent_config_router(
            config_store,
            configuration_validation,
            workflow_store,
        )
    )
    app.include_router(
        build_workflow_router(
            workflow_store,
            block_store,
            configuration_validation,
        )
    )
    app.include_router(
        build_workflow_lifecycle_router(
            workflow_lifecycle,
            background_tasks,
            workflow_checkpoints,
            runtime_diagnostics,
            settings.resolved_runtime_dir() / "tmp",
        )
    )
    app.include_router(
        build_validation_router(
            configuration_validation,
            repository_validation,
            configuration_validation_settings,
        )
    )
    app.include_router(
        build_python_package_router(python_package_authoring)
    )
    app.include_router(build_runtime_diagnostics_router(runtime_diagnostics))
    app.include_router(
        build_event_feed_router(
            event_feed,
            api_server_events,
        )
    )
    app.include_router(build_file_manager_router(file_manager))
    app.include_router(build_provider_integrations_router())
    app.include_router(build_system_settings_router(system_settings, runtime_policy))
    app.include_router(
        build_api_server_router(
            api_server_store,
            workflow_store,
            agent_runtime,
            settings,
            api_server_events,
            message_interception,
            runtime_policy,
            background_tasks,
        )
    )

    if serve_frontend:
        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/admin", status_code=307)

        assets_dir = frontend_dir / "assets"
        app.mount("/admin/assets", StaticFiles(directory=assets_dir), name="admin-assets")

        @app.get("/admin", include_in_schema=False)
        async def admin_page() -> FileResponse:
            return FileResponse(
                frontend_dir / "index.html",
                headers={"Content-Security-Policy": "frame-ancestors 'none'"},
            )

        @app.get("/admin/favicon.ico", include_in_schema=False)
        async def admin_favicon() -> FileResponse:
            return FileResponse(frontend_dir / "favicon.ico", media_type="image/x-icon")

    return app
