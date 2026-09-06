from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from agent_shell.capability_manifest import (
    CAPABILITY_BY_TYPE,
    CAPABILITY_MANIFESTS,
    DEFAULT_MIDDLEWARE_CAPABILITY_TYPES,
    FILESYSTEM_TOOL_NAMES,
)
from agent_shell.contracts import (
    BLOCK_MODELS,
    MANAGED_COMPONENT_MODELS,
    CapabilityReference,
    FilesystemToolConfigs,
    MainAgentProfile,
    SubagentProfile,
)
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.python_packages.validation import PythonPackageValidationService
from agent_shell.validation.assembly import (
    ResolvedAsyncSubagent,
    ResolvedSubagent,
    ResolvedSubagentEdge,
    ResolvedMcpReference,
    StaticAssembly,
    SubagentNodeKey,
)
from agent_shell.validation.capability_assembly import (
    CapabilityAssemblySubject,
    FilesystemMode,
    capability_assembly_issues,
)
from agent_shell.validation.contracts import report_from_validation_error
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.validation.references import (
    reference_not_found_issue,
    reference_type_mismatch_issue,
)
from agent_shell.validation.subagent_references import (
    async_subagent_reference_issues,
    subagent_reference_issues,
)


_MAIN_AGENT_REQUIRED_CAPABILITY_TYPES = frozenset(
    manifest.type for manifest in CAPABILITY_MANIFESTS if manifest.required
)
_SUBAGENT_REQUIRED_CAPABILITY_TYPES = frozenset(
    manifest.type
    for manifest in CAPABILITY_MANIFESTS
    if manifest.required and manifest.subagent_policy == "inherit"
)


class ConfigurationValidationService:
    def __init__(
        self,
        blocks: BlockStore,
        agent_configs: AgentConfigStore,
        python_package_validation: PythonPackageValidationService,
        *,
        repository: FileConfigRepository,
    ) -> None:
        self._blocks = blocks
        self._agent_configs = agent_configs
        self._python_package_validation = python_package_validation
        self._repository = repository

    def validate_main_agent(
        self,
        payload: dict[str, Any],
        *,
        stage: str,
        owner_id: str = "",
        stored: bool = False,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
        profile_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[ValidationReport, dict[str, Any] | None, StaticAssembly | None]:
        owner_name = str(payload.get("name", ""))
        try:
            model = MainAgentProfile.model_validate(
                (
                    {key: value for key, value in payload.items() if key != "id"}
                    if stored
                    else payload
                )
            )
        except ValidationError as exc:
            contract_report = report_from_validation_error(
                exc,
                stage=stage,
                scope="main_agent",
                owner_id=owner_id,
                owner_name=owner_name,
            )
            reference_issues = self._reference_issues_from_invalid_main_agent(
                payload,
                owner_id=owner_id,
                owner_name=owner_name,
                block_overrides=block_overrides,
            )
            return (
                ValidationReport(
                    stage=stage,
                    issues=contract_report.issues + tuple(reference_issues),
                ),
                None,
                None,
            )
        main_agent = model.model_dump(mode="json")
        report, assembly = self._assemble_main_agent(
            main_agent,
            stage=stage,
            owner_id=owner_id,
            block_overrides=block_overrides,
            profile_overrides=profile_overrides,
        )
        return report, main_agent, assembly

    def validate_block(
        self,
        block_type: str,
        payload: dict[str, Any],
        *,
        stage: str,
        owner_id: str = "",
    ) -> tuple[ValidationReport, dict[str, Any] | None]:
        model = MANAGED_COMPONENT_MODELS[block_type]
        try:
            validated_model = model.model_validate(payload)
        except ValidationError as exc:
            return (
                report_from_validation_error(
                    exc,
                    stage=stage,
                    scope="block",
                    owner_id=owner_id,
                    owner_name=str(payload.get("name", "")),
                    owner_type=block_type,
                ),
                None,
            )
        validated = validated_model.model_dump(mode="json")
        issues = self._block_resource_issues(
            block_type,
            validated,
            owner_id=owner_id,
        )
        if not owner_id:
            return ValidationReport(stage=stage, issues=tuple(issues)), validated
        current = self._blocks.get_block_internal(block_type, owner_id)
        if current is None:
            return ValidationReport(stage=stage, issues=tuple(issues)), validated
        prospective = dict(validated)
        prospective["id"] = owner_id
        issues.extend(
            self._impact_issues_for_block(
                block_type,
                owner_id,
                prospective,
                stage=stage,
            )
        )
        return ValidationReport(stage=stage, issues=tuple(issues)), validated

    def validate_block_copy(
        self,
        block_type: str,
        source: dict[str, Any],
        *,
        name: str,
        stage: str = "block_copy",
    ) -> ValidationReport:
        payload, storage_issue = self._stored_block_payload(block_type, source)
        payload["name"] = name
        if storage_issue is not None:
            return ValidationReport(stage=stage, issues=(storage_issue,))
        try:
            validated = MANAGED_COMPONENT_MODELS[block_type].model_validate(payload).model_dump(
                mode="json"
            )
        except ValidationError as exc:
            return report_from_validation_error(
                exc,
                stage=stage,
                scope="block",
                owner_id=str(source.get("id", "")),
                owner_name=name,
                owner_type=block_type,
            )
        issues = self._block_resource_issues(
            block_type,
            validated,
            owner_id=str(source.get("id", "")),
        )
        return ValidationReport(stage=stage, issues=tuple(issues))

    def validate_stored_block(
        self,
        block_type: str,
        block: dict[str, Any],
        *,
        stage: str,
        check_dependencies: bool = False,
    ) -> ValidationReport:
        payload, storage_issue = self._stored_block_payload(block_type, block)
        if storage_issue is not None:
            return ValidationReport(stage=stage, issues=(storage_issue,))
        try:
            validated = MANAGED_COMPONENT_MODELS[block_type].model_validate(payload).model_dump(
                mode="json"
            )
        except ValidationError as exc:
            return report_from_validation_error(
                exc,
                stage=stage,
                scope="block",
                owner_id=str(block.get("id", "")),
                owner_name=str(block.get("name", "")),
                owner_type=block_type,
            )
        issues = self._block_resource_issues(
            block_type,
            validated,
            owner_id=str(block.get("id", "")),
            check_dependencies=check_dependencies,
        )
        return ValidationReport(stage=stage, issues=tuple(issues))

    def _block_resource_issues(
        self,
        block_type: str,
        payload: dict[str, Any],
        *,
        owner_id: str,
        check_dependencies: bool = False,
    ) -> list[ValidationIssue]:
        arguments = {
            "scope": "block",
            "owner_id": owner_id,
            "package_owner_id": owner_id,
            "owner_name": str(payload.get("name", "")),
            "path_prefix": "python_package",
            "check_dependencies": check_dependencies,
        }
        reference = payload.get("python_package", {})
        if not isinstance(reference, dict):
            reference = {}
        if block_type == "custom-tool":
            return self._python_package_validation.tool_issues(
                reference,
                **arguments,
            )
        if block_type == "custom-middleware":
            return self._python_package_validation.middleware_issues(
                reference,
                **arguments,
            )
        if block_type == "agent-event-output":
            return self._python_package_validation.agent_event_output_issues(
                reference,
                **arguments,
            )
        if block_type == "workflow-event-output":
            return self._python_package_validation.workflow_event_output_issues(
                reference,
                **arguments,
            )
        if block_type == "command":
            return self._python_package_validation.command_issues(
                reference,
                **arguments,
            )
        if block_type == "filesystem":
            skill_package_id = payload.get("skill_package_id")
            if skill_package_id is not None and self._blocks.get_block_internal(
                "skill", str(skill_package_id)
            ) is None:
                return [
                    self.reference_issue(
                        scope="block",
                        owner_id=owner_id,
                        owner_name=str(payload.get("name", "")),
                        owner_type="filesystem",
                        path="skill_package_id",
                        reference_id=str(skill_package_id),
                        expected_type="skill",
                    )
                ]
        return []

    def validate_subagent(
        self,
        payload: dict[str, Any],
        *,
        stage: str,
        owner_id: str = "",
        stored: bool = False,
    ) -> tuple[ValidationReport, dict[str, Any] | None]:
        try:
            model = SubagentProfile.model_validate(
                (
                    {key: value for key, value in payload.items() if key != "id"}
                    if stored
                    else payload
                )
            )
        except ValidationError as exc:
            return (
                report_from_validation_error(
                    exc,
                    stage=stage,
                    scope="subagent",
                    owner_id=owner_id,
                    owner_name=str(payload.get("component_name", "")),
                ),
                None,
            )
        validated = model.model_dump(mode="json")
        settings = validated["settings"]
        references = {
            item["type"]: item["block_id"]
            for item in settings["capability_overrides"]
            if item["mode"] == "replace"
        }
        selected, issues = self._load_references(
            references,
            scope="subagent",
            owner_id=owner_id,
            owner_name=validated["component_name"],
            path_prefix="settings.capability_overrides",
        )
        _, middleware_issues = self._load_middleware_references(
            settings["middleware_refs"],
            scope="subagent",
            owner_id=owner_id,
            owner_name=validated["component_name"],
            path_prefix="settings.middleware_refs",
        )
        issues.extend(middleware_issues)
        _, tool_issues = self._load_tool_references(
            settings["tool_refs"],
            scope="subagent",
            owner_id=owner_id,
            owner_name=validated["component_name"],
            path_prefix="settings.tool_refs",
        )
        issues.extend(tool_issues)
        if owner_id and not issues:
            prospective = dict(validated)
            prospective["id"] = owner_id
            issues.extend(
                self._impact_issues_for_subagent(
                    owner_id,
                    prospective,
                    stage=stage,
                )
            )
        return ValidationReport(stage=stage, issues=tuple(issues)), validated

    def resolve_main_agent(
        self,
        main_agent_id: str,
        *,
        stage: str = "request_assembly",
    ) -> tuple[ValidationReport, StaticAssembly | None]:
        main_agent = self._agent_configs.get_item("main_agents", main_agent_id)
        if main_agent is None:
            issue = self.reference_issue(
                scope="main_agent",
                owner_id=main_agent_id,
                owner_name="",
                owner_type="main_agent",
                path="id",
                reference_id=main_agent_id,
                expected_type="main_agent",
            )
            return ValidationReport(stage=stage, issues=(issue,)), None
        report, _, assembly = self.validate_main_agent(
            main_agent,
            stage=stage,
            owner_id=main_agent_id,
            stored=True,
        )
        if assembly is not None:
            assembly = replace(
                assembly,
                main_agent={"id": main_agent_id, **assembly.main_agent},
            )
        return report, assembly

    @staticmethod
    def _reference_map(profile: dict[str, Any]) -> dict[str, str]:
        return {
            str(item["type"]): str(item["block_id"])
            for item in profile.get("capability_refs", [])
        }

    def _reference_issues_from_invalid_main_agent(
        self,
        payload: dict[str, Any],
        *,
        owner_id: str,
        owner_name: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> list[ValidationIssue]:
        references: dict[str, str] = {}
        items = payload.get("capability_refs", [])
        if not isinstance(items, list):
            return []
        for item in items:
            try:
                reference = CapabilityReference.model_validate(item)
            except ValidationError:
                continue
            references[reference.type] = reference.block_id
        _, issues = self._load_references(
            references,
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
            block_overrides=block_overrides,
        )
        return issues

    @staticmethod
    def _stored_block_payload(
        capability_type: str, block: dict[str, Any]
    ) -> tuple[dict[str, Any], ValidationIssue | None]:
        payload = {key: value for key, value in block.items() if key != "id"}
        return payload, None

    def _block_contract_issue(
        self,
        capability_type: str,
        block: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        path: str,
        stored: bool = True,
    ) -> ValidationIssue | None:
        if stored:
            payload, storage_issue = self._stored_block_payload(capability_type, block)
        else:
            payload = {key: value for key, value in block.items() if key != "id"}
            storage_issue = None
        if storage_issue is not None:
            detail = storage_issue.message
        else:
            try:
                BLOCK_MODELS[capability_type].model_validate(payload)
                return None
            except (ValidationError, KeyError) as exc:
                if isinstance(exc, ValidationError):
                    report = report_from_validation_error(
                        exc,
                        stage="referenced_block",
                        scope="block",
                        owner_id=str(block.get("id", "")),
                        owner_name=str(block.get("name", "")),
                        owner_type=capability_type,
                    )
                    detail = (
                        report.issues[0].message
                        if report.issues
                        else "The configuration structure is invalid."
                    )
                else:
                    detail = "The configuration type is not supported."
        block_name = str(block.get("name", "")) or "Unnamed configuration"
        return ValidationIssue(
            code="assembly.referenced_block_invalid",
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
            path=path,
            message=(
                f"Referenced {capability_type} configuration {block_name!r} "
                f"does not satisfy the current contract: {detail}"
            ),
            message_key="validation.issue.assembly.referencedBlockInvalid",
            message_args={
                "capability_type": capability_type,
                "block_name": block_name,
                "detail": detail,
            },
        )

    def reference_issue(
        self,
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        owner_type: str,
        path: str,
        reference_id: str,
        expected_type: str,
    ) -> ValidationIssue:
        actual_type = self._repository.configuration_entity_type(reference_id)
        arguments = {
            "scope": scope,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "owner_type": owner_type,
            "path": path,
            "reference_id": reference_id,
            "expected_type": expected_type,
        }
        if actual_type is None or actual_type == expected_type:
            return reference_not_found_issue(**arguments)
        return reference_type_mismatch_issue(
            **arguments,
            actual_type=actual_type,
        )

    def _load_references(
        self,
        references: dict[str, str],
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
        path_prefix: str = "capability_refs",
    ) -> tuple[dict[str, dict[str, Any]], list[ValidationIssue]]:
        selected: dict[str, dict[str, Any]] = {}
        issues: list[ValidationIssue] = []
        for capability_type, block_id in references.items():
            path = f"{path_prefix}.{capability_type}"
            override_key = (capability_type, block_id)
            prospective = bool(block_overrides and override_key in block_overrides)
            block = (
                block_overrides[override_key]
                if prospective
                else self._blocks.get_block_internal(capability_type, block_id)
            )
            if block is None:
                issues.append(
                    self.reference_issue(
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        owner_type=scope,
                        path=path,
                        reference_id=block_id,
                        expected_type=capability_type,
                    )
                )
                continue
            selected[capability_type] = block
            issue = self._block_contract_issue(
                capability_type,
                block,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                stored=not prospective,
            )
            if issue is not None:
                issues.append(issue)
        return selected, issues

    def _load_tool_references(
        self,
        references: list[dict[str, Any]],
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        path_prefix: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> tuple[tuple[dict[str, Any], ...], list[ValidationIssue]]:
        selected: list[dict[str, Any]] = []
        issues: list[ValidationIssue] = []
        for index, reference in enumerate(references):
            block_id = str(reference.get("tool_id", ""))
            path = f"{path_prefix}[{index}].tool_id"
            override_key = ("custom-tool", block_id)
            prospective = bool(block_overrides and override_key in block_overrides)
            block = (
                block_overrides[override_key]
                if prospective
                else self._blocks.get_block_internal("custom-tool", block_id)
            )
            if block is None:
                issues.append(
                    self.reference_issue(
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        owner_type=scope,
                        path=path,
                        reference_id=block_id,
                        expected_type="custom-tool",
                    )
                )
                continue
            selected.append(block)
            issue = self._block_contract_issue(
                "custom-tool",
                block,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                stored=not prospective,
            )
            if issue is not None:
                issues.append(issue)
                continue
            issues.extend(
                self._python_package_validation.tool_issues(
                    block.get("python_package", {}),
                    scope=scope,
                    owner_id=owner_id,
                    package_owner_id=str(block.get("id", "")),
                    owner_name=owner_name,
                    path_prefix=f"{path_prefix}[{index}].python_package",
                )
            )
        return tuple(selected), issues

    def _load_middleware_references(
        self,
        references: list[dict[str, Any]],
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        path_prefix: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> tuple[tuple[dict[str, Any], ...], list[ValidationIssue]]:
        selected: list[dict[str, Any]] = []
        issues: list[ValidationIssue] = []
        for index, reference in enumerate(references):
            block_id = str(reference.get("middleware_id", ""))
            path = f"{path_prefix}[{index}].middleware_id"
            override_key = ("custom-middleware", block_id)
            prospective = bool(block_overrides and override_key in block_overrides)
            block = (
                block_overrides[override_key]
                if prospective
                else self._blocks.get_block_internal("custom-middleware", block_id)
            )
            if block is None:
                issues.append(
                    self.reference_issue(
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        owner_type=scope,
                        path=path,
                        reference_id=block_id,
                        expected_type="custom-middleware",
                    )
                )
                continue
            selected.append(block)
            issue = self._block_contract_issue(
                "custom-middleware",
                block,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                stored=not prospective,
            )
            if issue is not None:
                issues.append(issue)
                continue
            issues.extend(
                self._python_package_validation.middleware_issues(
                    block.get("python_package", {}),
                    scope=scope,
                    owner_id=owner_id,
                    package_owner_id=str(block.get("id", "")),
                    owner_name=owner_name,
                    path_prefix=f"{path_prefix}[{index}].python_package",
                )
            )
        return tuple(selected), issues

    def _load_mcp_references(
        self,
        references: list[dict[str, Any]],
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        path_prefix: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> tuple[tuple[ResolvedMcpReference, ...], list[ValidationIssue]]:
        selected: list[ResolvedMcpReference] = []
        issues: list[ValidationIssue] = []
        for index, reference in enumerate(references):
            requirement_id = str(reference.get("requirement_id", ""))
            path = f"{path_prefix}[{index}].requirement_id"
            override_key = ("mcp-requirement", requirement_id)
            prospective = bool(block_overrides and override_key in block_overrides)
            requirement = (
                block_overrides[override_key]
                if prospective
                else self._blocks.get_block_internal("mcp-requirement", requirement_id)
            )
            if requirement is None:
                issues.append(
                    self.reference_issue(
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        owner_type=scope,
                        path=path,
                        reference_id=requirement_id,
                        expected_type="mcp-requirement",
                    )
                )
                continue
            issue = self._block_contract_issue(
                "mcp-requirement",
                requirement,
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                stored=not prospective,
            )
            if issue is not None:
                issues.append(issue)
                continue
            selected.append(
                ResolvedMcpReference(
                    reference=dict(reference),
                    requirement=requirement,
                )
            )
        return tuple(selected), issues

    def _resolve_capability_subject(
        self,
        references: dict[str, str],
        *,
        required_types: frozenset[str],
        scope: str,
        owner_id: str,
        owner_name: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[ValidationIssue],
        FilesystemMode,
    ]:
        subject = CapabilityAssemblySubject(
            references=references,
            required_types=required_types,
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
        )
        issues = capability_assembly_issues(subject)
        selected, selected_issues = self._load_references(
            references,
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
            block_overrides=block_overrides,
        )
        issues.extend(selected_issues)
        filesystem = selected.get("filesystem")
        filesystem_mode: FilesystemMode = (
            "local-shell"
            if filesystem is not None
            and filesystem.get("backend_type") == "local-shell"
            else "composite"
        )
        if filesystem is not None and filesystem_mode == "composite":
            skill_package_id = filesystem.get("skill_package_id")
            if isinstance(skill_package_id, str) and skill_package_id:
                skill_override_key = ("skill", skill_package_id)
                skill_package = (
                    block_overrides[skill_override_key]
                    if block_overrides and skill_override_key in block_overrides
                    else self._blocks.get_block_internal("skill", skill_package_id)
                )
                if skill_package is None:
                    issues.append(
                        self.reference_issue(
                            scope=scope,
                            owner_id=owner_id,
                            owner_name=owner_name,
                            owner_type=scope,
                            path="capability_refs.filesystem.skill_package_id",
                            reference_id=skill_package_id,
                            expected_type="skill",
                        )
                    )
                else:
                    selected["_filesystem-skill-package"] = skill_package
                    issue = self._block_contract_issue(
                        "skill",
                        skill_package,
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        path="capability_refs.filesystem.skill_package_id",
                    )
                    if issue is not None:
                        issues.append(issue)
        return selected, issues, filesystem_mode

    def _static_tool_issue(
        self,
        references: dict[str, str],
        blocks: dict[str, dict[str, Any]],
        *,
        has_subagents: bool,
        filesystem_mode: FilesystemMode,
        scope: str,
        owner_id: str,
        owner_name: str,
    ) -> ValidationIssue | None:
        seen: dict[str, str] = {
            name: "Deep Agents filesystem harness"
            for name in self._visible_filesystem_tools(blocks, filesystem_mode)
        }
        if has_subagents:
            seen["task"] = "Deep Agents default harness"
        for capability_type in references:
            manifest = CAPABILITY_BY_TYPE.get(capability_type)
            block = blocks.get(capability_type)
            if manifest is None or block is None:
                continue
            names = list(manifest.tool_names)
            if capability_type == "filesystem-tools":
                continue
            for name in names:
                previous = seen.get(name)
                if previous is not None:
                    return ValidationIssue(
                        code="assembly.tool_name_conflict",
                        scope=scope,
                        owner_id=owner_id,
                        owner_name=owner_name,
                        path=f"tools.{name}",
                        message=(
                            f"Model-visible tool name {name!r} is provided by both "
                            f"{previous} and {capability_type}."
                        ),
                        message_key="validation.issue.assembly.toolNameConflict",
                        message_args={
                            "tool_name": name,
                            "first_capability_type": previous,
                            "second_capability_type": capability_type,
                        },
                    )
                seen[name] = capability_type
        return None

    @staticmethod
    def _visible_filesystem_tools(
        blocks: dict[str, dict[str, Any]],
        filesystem_mode: FilesystemMode,
    ) -> tuple[str, ...]:
        configs = FilesystemToolConfigs().model_dump(mode="json")
        filesystem_tools = blocks.get("filesystem-tools")
        if filesystem_tools is not None and isinstance(
            filesystem_tools.get("tool_configs"), dict
        ):
            configs.update(filesystem_tools["tool_configs"])
        return tuple(
            name
            for name in FILESYSTEM_TOOL_NAMES
            if isinstance(configs.get(name), dict)
            and configs[name].get("visible") is True
            and not (filesystem_mode == "composite" and name == "execute")
        )

    def _subagent_profile(
        self,
        profile_id: str,
        *,
        owner_id: str,
        owner_name: str,
        path: str,
        profile_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, ValidationIssue | None]:
        profile = (
            profile_overrides[profile_id]
            if profile_overrides and profile_id in profile_overrides
            else self._agent_configs.get_item("subagents", profile_id)
        )
        if profile is None:
            return None, self.reference_issue(
                scope="main_agent",
                owner_id=owner_id,
                owner_name=owner_name,
                owner_type="main_agent",
                path=path,
                reference_id=profile_id,
                expected_type="subagent",
            )
        try:
            model = SubagentProfile.model_validate(
                {key: value for key, value in profile.items() if key != "id"}
            )
        except ValidationError as exc:
            detail_report = report_from_validation_error(
                exc,
                stage="referenced_subagent",
                scope="subagent",
                owner_id=owner_id,
                owner_name=owner_name,
            )
            detail = (
                detail_report.issues[0].message
                if detail_report.issues
                else "The configuration structure is invalid."
            )
            component_name = str(profile.get("component_name", ""))
            return None, ValidationIssue(
                code="assembly.subagent_invalid",
                scope="subagent",
                owner_id=owner_id,
                owner_name=owner_name,
                path=path,
                message=(
                    f"Referenced Subagent {component_name!r} does not "
                    f"satisfy the current contract: {detail}"
                ),
                message_key="validation.issue.assembly.subagentInvalid",
                message_args={
                    "component_name": component_name,
                    "detail": detail,
                },
            )
        return model.model_dump(mode="json"), None

    def _resolve_async_subagents(
        self,
        references: list[dict[str, Any]],
        *,
        owner_id: str,
        owner_name: str,
    ) -> tuple[list[ValidationIssue], tuple[ResolvedAsyncSubagent, ...]]:
        issues = async_subagent_reference_issues(
            references,
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
        )
        resolved: list[ResolvedAsyncSubagent] = []
        for index, reference in enumerate(references):
            target_id = str(reference.get("main_agent_id", ""))
            if self._agent_configs.get_item("main_agents", target_id) is None:
                issues.append(
                    self.reference_issue(
                        scope="main_agent",
                        owner_id=owner_id,
                        owner_name=owner_name,
                        owner_type="main_agent",
                        path=f"async_subagents[{index}].main_agent_id",
                        reference_id=target_id,
                        expected_type="main_agent",
                    )
                )
                continue
            resolved.append(
                ResolvedAsyncSubagent(
                    main_agent_id=target_id,
                    name=str(reference["name"]),
                    description=str(reference["description"]),
                )
            )
        return issues, tuple(resolved)

    def _assemble_main_agent(
        self,
        main_agent: dict[str, Any],
        *,
        stage: str,
        owner_id: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
        profile_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[ValidationReport, StaticAssembly | None]:
        owner_name = str(main_agent.get("name", ""))
        references = self._reference_map(main_agent)
        selected, issues, filesystem_mode = self._resolve_capability_subject(
            references,
            required_types=_MAIN_AGENT_REQUIRED_CAPABILITY_TYPES,
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
            block_overrides=block_overrides,
        )
        agent_event_output = selected.get("agent-event-output")
        if agent_event_output is not None:
            issues.extend(
                self._python_package_validation.agent_event_output_issues(
                    agent_event_output.get("python_package", {}),
                    scope="main_agent",
                    owner_id=owner_id,
                    package_owner_id=str(agent_event_output.get("id", "")),
                    owner_name=owner_name,
                    path_prefix="capability_refs.agent-event-output.python_package",
                )
            )
        disabled_capabilities = frozenset(
            DEFAULT_MIDDLEWARE_CAPABILITY_TYPES.difference(references)
        )
        tool_blocks, tool_issues = self._load_tool_references(
            list(main_agent.get("tool_refs", [])),
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
            path_prefix="tool_refs",
            block_overrides=block_overrides,
        )
        issues.extend(tool_issues)
        middleware_blocks, middleware_issues = self._load_middleware_references(
            list(main_agent.get("middleware_refs", [])),
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
            path_prefix="middleware_refs",
            block_overrides=block_overrides,
        )
        issues.extend(middleware_issues)
        mcp_references, mcp_issues = self._load_mcp_references(
            list(main_agent.get("mcp_refs", [])),
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
            path_prefix="mcp_refs",
            block_overrides=block_overrides,
        )
        issues.extend(mcp_issues)
        async_subagent_issues, resolved_async_subagents = (
            self._resolve_async_subagents(
                list(main_agent.get("async_subagents", [])),
                owner_id=owner_id,
                owner_name=owner_name,
            )
        )
        issues.extend(async_subagent_issues)

        delegation_selected = selected.get("subagent") is not None
        root_references = list(main_agent.get("subagents", []))
        active_roots = root_references if delegation_selected else []
        if delegation_selected and not active_roots:
            issues.append(
                ValidationIssue(
                    code="assembly.subagent_reference_required",
                    scope="main_agent",
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path="subagents",
                    message=(
                        "At least one valid Subagent reference is required when "
                        "delegation is enabled."
                    ),
                    message_key=(
                        "validation.issue.assembly.subagentReferenceRequired"
                    ),
                    message_args={},
                )
            )

        tool_issue = self._static_tool_issue(
            references,
            selected,
            has_subagents=bool(active_roots),
            filesystem_mode=filesystem_mode,
            scope="main_agent",
            owner_id=owner_id,
            owner_name=owner_name,
        )
        if tool_issue is not None:
            issues.append(tool_issue)

        subagent_nodes: dict[SubagentNodeKey, ResolvedSubagent] = {}
        known_profiles: dict[str, dict[str, Any]] = {}
        resolved_edges: list[ResolvedSubagentEdge] = []
        for index, reference in enumerate(active_roots):
            profile_id = str(reference.get("subagent_id", ""))
            profile, profile_issue = self._subagent_profile(
                profile_id,
                owner_id=owner_id,
                owner_name=owner_name,
                path=f"subagents[{index}].subagent_id",
                profile_overrides=profile_overrides,
            )
            if profile_issue is not None:
                issues.append(profile_issue)
                continue
            assert profile is not None
            known_profiles[profile_id] = profile
            settings = profile["settings"]
            child_references = {
                capability_type: block_id
                for capability_type, block_id in references.items()
                if (
                    CAPABILITY_BY_TYPE.get(capability_type) is None
                    or CAPABILITY_BY_TYPE[capability_type].subagent_policy == "inherit"
                )
            }
            child_disabled_capabilities = set(
                disabled_capabilities & DEFAULT_MIDDLEWARE_CAPABILITY_TYPES
            )
            for selection in settings["capability_overrides"]:
                capability_type = selection["type"]
                if selection["mode"] == "replace":
                    child_references[capability_type] = selection["block_id"]
                    child_disabled_capabilities.discard(capability_type)
                elif selection["mode"] == "disabled":
                    child_references.pop(capability_type, None)
                    if capability_type in DEFAULT_MIDDLEWARE_CAPABILITY_TYPES:
                        child_disabled_capabilities.add(capability_type)

            child_middleware_blocks, child_middleware_issues = (
                self._load_middleware_references(
                    settings["middleware_refs"],
                    scope="subagent",
                    owner_id=profile_id,
                    owner_name=str(profile["name"]),
                    path_prefix="settings.middleware_refs",
                    block_overrides=block_overrides,
                )
            )
            child_tool_blocks, child_tool_issues = self._load_tool_references(
                settings["tool_refs"],
                scope="subagent",
                owner_id=profile_id,
                owner_name=str(profile["name"]),
                path_prefix="settings.tool_refs",
                block_overrides=block_overrides,
            )
            child_mcp_references, child_mcp_issues = self._load_mcp_references(
                settings["mcp_refs"],
                scope="subagent",
                owner_id=profile_id,
                owner_name=str(profile["name"]),
                path_prefix="settings.mcp_refs",
                block_overrides=block_overrides,
            )

            subagent_name = str(profile["name"])
            child_blocks, child_issues, child_filesystem_mode = (
                self._resolve_capability_subject(
                    child_references,
                    required_types=_SUBAGENT_REQUIRED_CAPABILITY_TYPES,
                    scope="subagent",
                    owner_id=profile_id,
                    owner_name=subagent_name,
                    block_overrides=block_overrides,
                )
            )
            child_tool_issue = self._static_tool_issue(
                child_references,
                child_blocks,
                has_subagents=False,
                filesystem_mode=child_filesystem_mode,
                scope="subagent",
                owner_id=profile_id,
                owner_name=subagent_name,
            )
            if child_tool_issue is not None:
                child_issues.append(child_tool_issue)
            child_issues.extend(child_tool_issues)
            child_issues.extend(child_middleware_issues)
            child_issues.extend(child_mcp_issues)
            issues.extend(child_issues)
            if child_issues:
                continue
            subagent_nodes[profile_id] = ResolvedSubagent(
                key=profile_id,
                component_name=str(profile["component_name"]),
                name=subagent_name,
                description=str(profile["description"]),
                references=child_references,
                blocks=child_blocks,
                tool_blocks=child_tool_blocks,
                middleware_blocks=child_middleware_blocks,
                mcp_references=child_mcp_references,
                filesystem_mode=child_filesystem_mode,
                disabled_capabilities=frozenset(child_disabled_capabilities),
            )
            resolved_edges.append(ResolvedSubagentEdge(target_key=profile_id))

        resolved_subagents = tuple(resolved_edges)
        if not delegation_selected:
            for index, reference in enumerate(root_references):
                profile_id = str(reference.get("subagent_id", ""))
                profile, profile_issue = self._subagent_profile(
                    profile_id,
                    owner_id=owner_id,
                    owner_name=owner_name,
                    path=f"subagents[{index}].subagent_id",
                    profile_overrides=profile_overrides,
                )
                if profile_issue is not None:
                    issues.append(profile_issue)
                elif profile is not None:
                    known_profiles[profile_id] = profile
        issues.extend(
            subagent_reference_issues(
                root_references,
                profiles=known_profiles,
                scope="main_agent",
                owner_id=owner_id,
                owner_name=owner_name,
            )
        )

        report = ValidationReport(stage=stage, issues=tuple(issues))
        if not report.valid:
            return report, None
        return report, StaticAssembly(
            main_agent=main_agent,
            references=references,
            blocks=selected,
            tool_blocks=tool_blocks,
            middleware_blocks=middleware_blocks,
            mcp_references=mcp_references,
            async_subagents=resolved_async_subagents,
            filesystem_mode=filesystem_mode,
            disabled_capabilities=disabled_capabilities,
            subagents=resolved_subagents,
            subagent_nodes=subagent_nodes,
        )

    @staticmethod
    def _issue_key(issue: ValidationIssue) -> tuple[str, str, str, str, str, str]:
        return (
            issue.code,
            issue.severity,
            issue.scope,
            issue.owner_id,
            issue.owner_name,
            issue.path,
        )

    def _new_impact_issues(
        self,
        main_agent: dict[str, Any],
        *,
        stage: str,
        block_overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
        profile_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list[ValidationIssue]:
        main_agent_id = str(main_agent.get("id", ""))
        baseline, _, _ = self.validate_main_agent(
            main_agent,
            stage=stage,
            owner_id=main_agent_id,
            stored=True,
        )
        prospective, _, _ = self.validate_main_agent(
            main_agent,
            stage=stage,
            owner_id=main_agent_id,
            stored=True,
            block_overrides=block_overrides,
            profile_overrides=profile_overrides,
        )
        baseline_keys = {self._issue_key(issue) for issue in baseline.issues}
        return [
            issue
            for issue in prospective.issues
            if self._issue_key(issue) not in baseline_keys
        ]

    def _impact_issues_for_block(
        self,
        block_type: str,
        block_id: str,
        prospective: dict[str, Any],
        *,
        stage: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        referencing_filesystem_ids = {
            str(filesystem.get("id", ""))
            for filesystem in self._blocks.list_blocks_internal("filesystem")
            if block_type == "skill"
            and filesystem.get("skill_package_id") == block_id
        }
        for main_agent in self._agent_configs.list_items("main_agents"):
            references = main_agent.get("capability_refs", [])
            if not isinstance(references, list):
                references = []
            direct = any(
                isinstance(item, dict)
                and item.get("type") == block_type
                and item.get("block_id") == block_id
                for item in references
            )
            if block_type == "custom-tool":
                tool_refs = main_agent.get("tool_refs", [])
                direct = isinstance(tool_refs, list) and any(
                    isinstance(item, dict)
                    and item.get("tool_id") == block_id
                    for item in tool_refs
                )
            if block_type == "custom-middleware":
                middleware_refs = main_agent.get("middleware_refs", [])
                direct = isinstance(middleware_refs, list) and any(
                    isinstance(item, dict)
                    and item.get("middleware_id") == block_id
                    for item in middleware_refs
                )
            subagent_references = main_agent.get("subagents", [])
            if not isinstance(subagent_references, list):
                subagent_references = []
            indirect = self._direct_subagents_reference_block(
                subagent_references, block_type, block_id
            )
            if referencing_filesystem_ids:
                direct = direct or any(
                    isinstance(item, dict)
                    and item.get("type") == "filesystem"
                    and item.get("block_id") in referencing_filesystem_ids
                    for item in references
                )
                indirect = indirect or any(
                    self._direct_subagents_reference_block(
                        subagent_references, "filesystem", filesystem_id
                    )
                    for filesystem_id in referencing_filesystem_ids
                )
            if direct or indirect:
                issues.extend(
                    self._new_impact_issues(
                        main_agent,
                        stage=stage,
                        block_overrides={(block_type, block_id): prospective},
                    )
                )
        return issues

    def _impact_issues_for_subagent(
        self,
        profile_id: str,
        prospective: dict[str, Any],
        *,
        stage: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for main_agent in self._agent_configs.list_items("main_agents"):
            subagent_references = main_agent.get("subagents", [])
            if not isinstance(subagent_references, list):
                continue
            if not self._references_include_subagent(
                subagent_references, profile_id
            ):
                continue
            issues.extend(
                self._new_impact_issues(
                    main_agent,
                    stage=stage,
                    profile_overrides={profile_id: prospective},
                )
            )
        return issues

    def _direct_subagents_reference_block(
        self,
        references: list[Any],
        block_type: str,
        block_id: str,
    ) -> bool:
        for reference in references:
            if not isinstance(reference, dict):
                continue
            profile_id = str(reference.get("subagent_id", ""))
            if not profile_id:
                continue
            profile = self._agent_configs.get_item("subagents", profile_id)
            if not profile:
                continue
            settings = profile.get("settings", {})
            if not isinstance(settings, dict):
                continue
            selections = settings.get("capability_overrides", [])
            if block_type == "custom-tool":
                tool_refs = settings.get("tool_refs", [])
                if isinstance(tool_refs, list) and any(
                    isinstance(item, dict)
                    and item.get("tool_id") == block_id
                    for item in tool_refs
                ):
                    return True
            if block_type == "custom-middleware":
                middleware_refs = settings.get("middleware_refs", [])
                if isinstance(middleware_refs, list) and any(
                    isinstance(item, dict)
                    and item.get("middleware_id") == block_id
                    for item in middleware_refs
                ):
                    return True
            if isinstance(selections, list) and any(
                isinstance(item, dict)
                and item.get("type") == block_type
                and item.get("mode") == "replace"
                and item.get("block_id") == block_id
                for item in selections
            ):
                return True
        return False

    @staticmethod
    def _references_include_subagent(
        references: list[Any],
        target_id: str,
    ) -> bool:
        return any(
            isinstance(reference, dict)
            and str(reference.get("subagent_id", "")) == target_id
            for reference in references
        )
