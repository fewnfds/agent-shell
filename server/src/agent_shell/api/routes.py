from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from agent_shell import __version__
from agent_shell.api.errors import management_error
from agent_shell.authoring import editor_defaults
from agent_shell.contracts import (
    BLOCK_CATALOG,
    MANAGED_COMPONENT_MODELS,
    validate_provider_credential,
)
from agent_shell.api.agent_configs import (
    ConfigurationBulkDelete,
    main_agent_block_reference_owner,
)
from agent_shell.capability_manifest import CAPABILITY_BY_TYPE
from agent_shell.configuration.component_mutations import (
    ComponentMutationError,
    ComponentMutationService,
    ComponentMutationValidationError,
)
from agent_shell.registries.skills import scan_skills
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.provider_integrations import bundled_provider_ids
from agent_shell.provider_secrets import ProviderCredentialError, ProviderSecretResolver
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.validation.models import validation_failure_detail
from agent_shell.python_packages.authoring import (
    PythonPackageAuthoringError,
    PythonPackageAuthoringService,
)
from agent_shell.skills.authoring import (
    SkillPackageAuthoringError,
    SkillPackageAuthoringService,
)


WORKFLOW_COMPONENT_CATALOG = (
    {
        "type": "workflow-event-output",
        "terminology_key": "workflow-event-output",
        "label": "Workflow Event Output",
        "order": 1,
        "icon_key": "braces",
        "editor_key": "workflow_event_output",
    },
    {
        "type": "command",
        "terminology_key": "command",
        "label": "Command Node",
        "order": 2,
        "icon_key": "circle-half",
        "editor_key": "command",
    },
    {
        "type": "task-dispatcher",
        "terminology_key": "task-dispatcher",
        "label": "Task Dispatcher",
        "order": 3,
        "icon_key": "boxes",
        "editor_key": "task_dispatcher",
    },
)


def build_router(
    configuration: FileConfigRepository,
    block_store: BlockStore,
    config_store: AgentConfigStore,
    skills_dir: Path,
    secret_resolver: ProviderSecretResolver,
    provider_http_clients: ProviderHttpClients,
    workflow_store: WorkflowStore,
    python_package_authoring: PythonPackageAuthoringService,
    skill_package_authoring: SkillPackageAuthoringService,
    component_mutations: ComponentMutationService,
    runtime_policy: RuntimePolicyStore,
) -> APIRouter:
    router = APIRouter()

    def configuration_mutation(endpoint):
        @wraps(endpoint)
        async def guarded(*args, **kwargs):
            expected_repository_id = configuration.repository_id
            with configuration.exclusive_config_mutation(
                expected_repository_id=expected_repository_id
            ):
                return await endpoint(*args, **kwargs)

        return guarded

    def check_type(block_type: str) -> None:
        if block_type not in MANAGED_COMPONENT_MODELS:
            raise management_error(
                404,
                code="unknown_configuration_type",
                message_key="errors.unknownConfigurationType",
                message="The configuration type is unknown.",
                message_args={"type": block_type},
            )

    def package_reference(payload: dict) -> dict:
        value = payload.get("python_package")
        return dict(value) if isinstance(value, dict) else {}

    def authoring_error(exc: PythonPackageAuthoringError) -> HTTPException:
        parts = exc.code.split("_")
        message_key = parts[0] + "".join(part.capitalize() for part in parts[1:])
        return management_error(
            exc.status_code,
            code=exc.code,
            message_key=f"errors.{message_key}",
            message=str(exc),
        )

    def skill_authoring_error(exc: SkillPackageAuthoringError) -> HTTPException:
        parts = exc.code.split("_")
        message_key = parts[0] + "".join(part.capitalize() for part in parts[1:])
        return management_error(
            exc.status_code,
            code=exc.code,
            message_key=f"errors.{message_key}",
            message=str(exc),
        )

    def component_mutation_error(exc: ComponentMutationError) -> HTTPException:
        return management_error(
            exc.status_code,
            code=exc.code,
            message_key=exc.message_key,
            message=str(exc),
            message_args=exc.message_args,
        )

    def perform_component_mutation(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except ComponentMutationValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=validation_failure_detail(exc.report),
            ) from exc
        except ComponentMutationError as exc:
            raise component_mutation_error(exc) from exc
        except PythonPackageAuthoringError as exc:
            raise authoring_error(exc) from exc
        except SkillPackageAuthoringError as exc:
            raise skill_authoring_error(exc) from exc

    def project_block(
        block_type: str,
        block: dict | None,
        *,
        include_package_details: bool = False,
    ) -> dict | None:
        if block is None:
            return None
        if block_type == "skill" and include_package_details:
            return {
                **block,
                "skill_package_contents": skill_package_authoring.inspect(
                    str(block.get("id", ""))
                ),
            }
        return block

    def reject_workflow_event_output_reference(
        block_type: str, block_id: str
    ) -> None:
        if block_type != "workflow-event-output":
            return
        owner = workflow_store.get_item_by_event_output(block_id)
        if owner is None:
            return
        raise management_error(
            409,
            code="configuration_referenced",
            message_key="errors.configurationReferencedByWorkflow",
            message="The configuration is still referenced by a Workflow.",
            message_args={"owner": owner["name"]},
        )

    def reject_command_reference(block_type: str, block_id: str) -> None:
        if block_type != "command":
            return
        owner = workflow_store.get_item_by_command(block_id)
        if owner is None:
            return
        raise management_error(
            409,
            code="configuration_referenced",
            message_key="errors.configurationReferencedByWorkflow",
            message="The configuration is still referenced by a Workflow.",
            message_args={"owner": owner["name"]},
        )

    def reject_task_dispatcher_reference(block_type: str, block_id: str) -> None:
        if block_type != "task-dispatcher":
            return
        owner = workflow_store.get_item_by_task_dispatcher(block_id)
        if owner is None:
            return
        raise management_error(
            409,
            code="configuration_referenced",
            message_key="errors.configurationReferencedByWorkflow",
            message="The configuration is still referenced by a Workflow.",
            message_args={"owner": owner["name"]},
        )

    @router.get("/api/catalog")
    async def catalog() -> dict:
        return {
            "block_types": BLOCK_CATALOG,
            "workflow_component_types": WORKFLOW_COMPONENT_CATALOG,
            "editor_defaults": editor_defaults(),
        }

    @router.post("/api/fetch-models")
    async def fetch_models(request: Request) -> list[str]:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {
            "provider",
            "base_url",
            "credential",
            "block_id",
        }:
            raise management_error(
                422,
                code="invalid_model_catalog_request",
                message_key="errors.modelCatalogRequestInvalid",
                message="The model catalog request contains invalid fields.",
            )
        provider = body.get("provider")
        if not isinstance(provider, str) or provider not in bundled_provider_ids():
            raise management_error(
                422,
                code="invalid_model_catalog_request",
                message_key="errors.modelCatalogRequestInvalid",
                message="The model catalog request contains invalid fields.",
            )
        base_url = str(body.get("base_url", "")).strip().rstrip("/")
        block_id = str(body["block_id"]).strip()
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise management_error(
                400,
                code="invalid_model_endpoint",
                message_key="errors.modelEndpointInvalid",
                message="The model endpoint must be a complete HTTP(S) URL.",
            )
        try:
            credential = validate_provider_credential(body["credential"])
            api_key = secret_resolver.resolve_request(
                credential,
                provider=provider,
                block_id=block_id,
                base_url=base_url,
            )
        except ValidationError as exc:
            raise management_error(
                422,
                code="provider_credential_invalid",
                message_key="errors.providerCredentialInvalid",
                message="The provider credential input is invalid.",
                message_args={"count": len(exc.errors())},
            ) from exc
        except ProviderCredentialError as exc:
            if exc.code == "model_connection_not_found":
                raise management_error(
                    404,
                    code=exc.code,
                    message_key="errors.modelConnectionNotFound",
                    message="The model connection does not exist.",
                ) from exc
            raise management_error(
                422,
                code=exc.code,
                message_key="errors.providerCredentialInvalid",
                message="The provider credential input is invalid.",
            ) from exc
        headers = {"User-Agent": f"Agent-Shell/{__version__}"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = await provider_http_clients.async_client.get(
                f"{base_url}/models",
                headers=headers,
                timeout=runtime_policy.snapshot().provider_catalog_timeout_seconds,
            )
            if (
                response.status_code == 403
                and response.headers.get("cf-mitigated", "").lower()
                == "challenge"
            ):
                raise management_error(
                    502,
                    code="model_catalog_browser_challenge",
                    message_key="errors.modelCatalogBrowserChallenge",
                    message=(
                        "Cloudflare rejected the server-side API client with a "
                        "browser challenge."
                    ),
                )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise management_error(
                502,
                code="model_catalog_upstream_error",
                message_key="errors.modelCatalogUpstreamError",
                message="The model service could not complete the catalog request.",
            ) from exc
        except httpx.HTTPError as exc:
            raise management_error(
                502,
                code="model_catalog_unreachable",
                message_key="errors.modelCatalogUnreachable",
                message="The model service could not be reached.",
            ) from exc
        except ValueError as exc:
            raise management_error(
                502,
                code="invalid_model_catalog_response",
                message_key="errors.modelCatalogResponseInvalid",
                message="The model service returned an invalid model catalog response.",
            ) from exc
        models = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(models, list):
            raise management_error(
                502,
                code="invalid_model_catalog_response",
                message_key="errors.modelCatalogResponseInvalid",
                message="The model service returned an invalid model catalog response.",
            )
        model_ids: list[str] = []
        for item in models:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
            ):
                raise management_error(
                    502,
                    code="invalid_model_catalog_response",
                    message_key="errors.modelCatalogResponseInvalid",
                    message="The model service returned an invalid model catalog response.",
                )
            model_ids.append(item["id"])
        return model_ids

    @router.get("/api/skills")
    async def skills() -> dict:
        return scan_skills(skills_dir)

    @router.get("/api/blocks/skill/{block_id}/skills")
    async def private_skills(block_id: str) -> dict:
        if block_store.get_block_internal("skill", block_id) is None:
            raise management_error(
                404,
                code="block_not_found",
                message_key="errors.blockNotFound",
                message="The Skill component configuration does not exist.",
            )
        return skill_package_authoring.inspect(block_id)

    @router.post("/api/blocks/skill/{block_id}/skills")
    async def add_private_skill(block_id: str, payload: dict) -> dict:
        if set(payload) != {"template_path"}:
            raise management_error(
                422,
                code="skill_template_path_invalid",
                message_key="errors.skillTemplatePathInvalid",
                message="A Skill Template path is required.",
            )
        return perform_component_mutation(
            lambda: component_mutations.add_skill(block_id, payload["template_path"])
        )

    @router.delete("/api/blocks/skill/{block_id}/skills/{folder_name}")
    async def delete_private_skill(block_id: str, folder_name: str) -> dict:
        return perform_component_mutation(
            lambda: component_mutations.remove_skill(block_id, folder_name)
        )

    @router.get("/api/blocks/{block_type}")
    async def list_blocks(block_type: str) -> list[dict]:
        check_type(block_type)
        return [project_block(block_type, item) for item in block_store.list_blocks(block_type)]

    @router.delete("/api/unsupported-blocks/{block_id}")
    @configuration_mutation
    async def delete_unsupported_block(block_id: str) -> dict[str, bool]:
        mutation_repository_id = block_store.repository_id()
        block = block_store.get_block_header(block_id)
        if block is None or block["block_type"] in MANAGED_COMPONENT_MODELS:
            raise management_error(
                404,
                code="unsupported_block_not_found",
                message_key="errors.blockNotFound",
                message="An unsupported component configuration does not exist.",
            )
        block_type = block["block_type"]
        if not block_store.delete_block(
            block_type,
            block_id,
            detach_references=True,
            expected_repository_id=mutation_repository_id,
        ):
            raise management_error(
                404,
                code="unsupported_block_not_found",
                message_key="errors.blockNotFound",
                message="An unsupported component configuration does not exist.",
            )
        return {"ok": True}

    @router.post("/api/blocks/{block_type}/delete")
    async def delete_blocks(
        block_type: str,
        payload: ConfigurationBulkDelete,
    ) -> dict[str, int]:
        check_type(block_type)
        ids = list(dict.fromkeys(payload.ids))
        for block_id in ids:
            if block_store.get_block(block_type, block_id) is None:
                raise management_error(
                    404,
                    code="block_not_found",
                    message_key="errors.blockNotFound",
                    message="A component configuration does not exist.",
                )
            reject_workflow_event_output_reference(block_type, block_id)
            reject_command_reference(block_type, block_id)
            reject_task_dispatcher_reference(block_type, block_id)
            manifest = CAPABILITY_BY_TYPE.get(block_type)
            if manifest is not None and manifest.required:
                owner = main_agent_block_reference_owner(
                    config_store,
                    block_type,
                    block_id,
                )
                if owner is None:
                    continue
                _, owner_name = owner
                raise management_error(
                    409,
                    code="configuration_referenced",
                    message_key="errors.configurationReferencedByMainAgent",
                    message="The configuration is still referenced.",
                    message_args={"owner": owner_name},
                )
        deleted = perform_component_mutation(
            lambda: component_mutations.delete_many(block_type, ids)
        )
        return {"deleted": deleted}

    @router.get("/api/blocks/{block_type}/{block_id}")
    async def get_block(block_type: str, block_id: str) -> dict:
        check_type(block_type)
        block = block_store.get_block(block_type, block_id)
        if block is None:
            raise management_error(
                404,
                code="block_not_found",
                message_key="errors.blockNotFound",
                message="The component configuration does not exist.",
            )
        return project_block(block_type, block, include_package_details=True)

    @router.get("/api/blocks/{block_type}/{block_id}/python-package")
    @configuration_mutation
    async def inspect_python_package(
        block_type: str,
        block_id: str,
    ) -> dict:
        check_type(block_type)
        repository_id = block_store.repository_id()
        block = block_store.get_block_internal(block_type, block_id)
        if block is None:
            raise management_error(
                404,
                code="block_not_found",
                message_key="errors.blockNotFound",
                message="The component configuration does not exist.",
            )
        if not python_package_authoring.supports(block_type):
            raise management_error(
                422,
                code="python_package_component_unsupported",
                message_key="errors.pythonPackageComponentUnsupported",
                message="The component type does not own a Python package.",
            )
        try:
            return python_package_authoring.project(
                block_type,
                block_id,
                package_reference(block),
                repository_id=repository_id,
            )
        except PythonPackageAuthoringError as exc:
            raise authoring_error(exc) from exc

    @router.post("/api/blocks/{block_type}")
    async def create_block(block_type: str, payload: dict) -> dict:
        check_type(block_type)
        created = perform_component_mutation(
            lambda: component_mutations.create(block_type, payload)
        )
        return project_block(
            block_type,
            created,
            include_package_details=True,
        )

    @router.post("/api/blocks/{block_type}/{block_id}/copy")
    async def copy_block(block_type: str, block_id: str, payload: dict) -> dict:
        check_type(block_type)
        if set(payload) != {"name"} or not isinstance(payload.get("name"), str):
            raise management_error(
                422,
                code="invalid_copy_request",
                message_key="errors.copyRequestInvalid",
                message="The copy request must contain only a configuration name.",
            )
        name = payload["name"].strip()
        if not name or len(name) > 120:
            raise management_error(
                422,
                code="invalid_configuration_name_length",
                message_key="errors.configurationNameLength",
                message="The configuration name must contain 1 to 120 characters.",
                message_args={"minimum": 1, "maximum": 120},
            )
        copied = perform_component_mutation(
            lambda: component_mutations.copy(
                block_type,
                block_id,
                name=name,
            )
        )
        return project_block(block_type, copied, include_package_details=True)

    @router.put("/api/blocks/{block_type}/{block_id}")
    async def update_block(block_type: str, block_id: str, payload: dict) -> dict:
        check_type(block_type)
        updated = perform_component_mutation(
            lambda: component_mutations.update(block_type, block_id, payload)
        )
        return project_block(
            block_type,
            updated,
            include_package_details=True,
        )

    @router.delete("/api/blocks/{block_type}/{block_id}")
    async def delete_block(block_type: str, block_id: str) -> dict[str, bool]:
        check_type(block_type)
        reject_workflow_event_output_reference(block_type, block_id)
        reject_command_reference(block_type, block_id)
        reject_task_dispatcher_reference(block_type, block_id)
        manifest = CAPABILITY_BY_TYPE.get(block_type)
        if manifest is not None and manifest.required:
            owner = main_agent_block_reference_owner(config_store, block_type, block_id)
            if owner is not None:
                _, owner_name = owner
                raise management_error(
                    409,
                    code="configuration_referenced",
                    message_key="errors.configurationReferencedByMainAgent",
                    message="The configuration is still referenced.",
                    message_args={"owner": owner_name},
                )
        perform_component_mutation(
            lambda: component_mutations.delete(block_type, block_id)
        )
        return {"ok": True}

    return router
