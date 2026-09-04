from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import agent_shell.contracts as contracts_module
from agent_shell.contracts import (
    CustomMiddlewareBlock,
    FilesystemBlock,
    FilesystemToolsBlock,
    MainAgentProfile,
    SubagentProfile,
    SystemPromptBlock,
)
from agent_shell.workflow.catalog import AgentNodeConfig
from agent_shell.workflow_contracts import WorkflowDefinition
from agent_shell.validation import (
    ValidationIssue,
    ValidationReport,
    report_from_validation_error,
)
from agent_shell.validation.repository import RepositoryValidationService


def test_contract_errors_become_safe_structured_validation_issues() -> None:
    try:
        SystemPromptBlock.model_validate(
            {
                "name": "",
                "system_prompt": "",
                "legacy_field": r"C:\private\legacy.json",
            }
        )
    except ValidationError as exc:
        report = report_from_validation_error(
            exc,
            stage="block_save",
            scope="block",
            owner_id="block-id",
            owner_name="旧配置",
        )
    else:  # pragma: no cover - the strict contract must reject this payload
        raise AssertionError("invalid payload unexpectedly passed")

    payload = report.as_dict()
    assert payload["valid"] is False
    assert payload["stage"] == "block_save"
    assert {issue["path"] for issue in payload["issues"]} == {
        "name",
        "system_prompt",
        "legacy_field",
    }
    assert any(
        issue["code"] == "contract.unknown_field"
        for issue in payload["issues"]
    )
    assert all(issue["scope"] == "block" for issue in payload["issues"])
    assert {issue["message_key"] for issue in payload["issues"]} == {
        "validation.issue.contract.textTooShort",
        "validation.issue.contract.unknownField",
    }
    assert {
        issue["path"]: issue["message_args"]
        for issue in payload["issues"]
    } == {
        "name": {"min_length": 1},
        "system_prompt": {"min_length": 1},
        "legacy_field": {},
    }
    assert all("private" not in issue["message"] for issue in payload["issues"])
    assert all("legacy.json" not in issue["message"] for issue in payload["issues"])


def test_filesystem_contract_rejects_linked_virtual_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "note.txt"
    source_file.write_text("source", encoding="utf-8")

    cases = (
        (
            source_dir,
            {
                "name": "Linked directory",
                "virtual_directories": [
                    {"virtual_path": "/source/", "source_path": str(source_dir)}
                ],
            },
        ),
        (
            source_file,
            {
                "name": "Linked file",
                "virtual_files": [
                    {"virtual_path": "/source/note.txt", "source_path": str(source_file)}
                ],
            },
        ),
        (
            source_file,
            {
                "name": "Nested linked source",
                "virtual_directories": [
                    {"virtual_path": "/source/", "source_path": str(source_dir)}
                ],
            },
        ),
    )

    for linked_path, payload in cases:
        monkeypatch.setattr(
            contracts_module,
            "is_reparse_point",
            lambda path, linked_path=linked_path: Path(path) == linked_path,
        )
        with pytest.raises(ValidationError, match="links? or reparse points?"):
            FilesystemBlock.model_validate(payload)


def test_validation_issue_redacts_user_controlled_owner_path_and_message() -> None:
    issue = ValidationIssue(
        code="contract.invalid_value",
        scope="block",
        owner_id=r"C:\private\owner-id",
        owner_name="sk-1234567890-private",
        path=r"legacy.C:\private\field.json",
        message=r"Invalid C:\private\payload.json with Bearer top-secret-token",
        message_key="validation.issue.contract.invalidValue",
        message_args={
            "detail": r"Invalid C:\private\payload.json with Bearer top-secret-token"
        },
    ).as_dict()

    serialized = str(issue)
    assert "C:\\private" not in serialized
    assert "sk-1234567890-private" not in serialized
    assert "top-secret-token" not in serialized
    assert "[LOCAL_PATH]" in serialized
    assert "[REDACTED]" in serialized
    assert issue["message_key"] == "validation.issue.contract.invalidValue"


def test_validation_issue_rejects_non_primitive_message_arguments() -> None:
    with pytest.raises(TypeError, match="finite JSON primitive"):
        ValidationIssue(
            code="contract.invalid_value",
            scope="block",
            path="name",
            message="Invalid value.",
            message_key="validation.issue.contract.invalidValue",
            message_args={"detail": {"nested": "value"}},  # type: ignore[dict-item]
        )


def test_repository_validation_cache_tracks_repository_and_model_revisions() -> None:
    class Repository:
        repository_id = "repository-id"
        revision = 1
        reads = 0
        components: dict[str, list[dict[str, object]]] = {}

        def repository_context(self) -> tuple[str, int]:
            return self.repository_id, self.revision

        def config(self) -> dict[str, object]:
            self.reads += 1
            return {
                "components": self.components,
                "main_agents": [],
                "subagents": [],
                "workflows": [],
            }

    class ModelResources:
        current_revision = 1

        def revision(self) -> int:
            return self.current_revision

        def list_connections(self) -> list[dict[str, object]]:
            return []

    class ConfigurationValidation:
        stored_block_reads = 0

        def validate_stored_block(
            self,
            _block_type: str,
            _block: dict[str, object],
            *,
            stage: str,
        ) -> ValidationReport:
            self.stored_block_reads += 1
            return ValidationReport(stage=stage)

    repository = Repository()
    models = ModelResources()
    configuration_validation = ConfigurationValidation()
    service = RepositoryValidationService(
        repository,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        configuration_validation,  # type: ignore[arg-type]
        model_resources=models,  # type: ignore[arg-type]
    )

    first = service.validate_repository()
    assert service.validate_repository() is first
    assert repository.reads == 1

    repository.revision += 1
    assert service.validate_repository() is not first
    assert repository.reads == 2

    models.current_revision += 1
    service.validate_repository()
    assert repository.reads == 3

    repository.components = {
        "custom-tool": [
            {
                "id": "10000000-0000-4000-8000-000000000001",
                "name": "Tool",
                "python_package": {
                    "folder": "10000000-0000-4000-8000-000000000001"
                },
            }
        ]
    }
    repository.revision += 1
    service.validate_repository()
    service.validate_repository()
    assert repository.reads == 5
    assert configuration_validation.stored_block_reads == 2


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            MainAgentProfile,
            {
                "name": "Invalid reference",
                "capability_refs": [
                    {"type": "model-requirement", "block_id": "not-a-uuid"}
                ],
            },
        ),
        (
            SubagentProfile,
            {
                "component_name": "Invalid reference",
                "name": "worker",
                "description": "Invalid reference.",
                "settings": {
                    "capability_overrides": [
                        {
                            "type": "model-requirement",
                            "mode": "replace",
                            "block_id": "not-a-uuid",
                        }
                    ]
                },
            },
        ),
        (
            WorkflowDefinition,
            {
                "name": "Invalid reference",
                "workflow_event_output_id": "not-a-uuid",
            },
        ),
        (
            AgentNodeConfig,
            {"main_agent_id": "not-a-uuid"},
        ),
    ],
)
def test_declared_configuration_references_require_canonical_uuid4(
    model: type,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload", "scope", "owner_type", "expected"),
    [
        (
            FilesystemToolsBlock,
            {"name": "Filesystem tools", "grep_max_count": 0},
            "block",
            "filesystem-tools",
            (
                "contract.number_at_least",
                "validation.issue.contract.numberAtLeast",
                "grep_max_count",
                {"ge": 1},
            ),
        ),
        (
            SubagentProfile,
            {
                "component_name": "Worker",
                "name": "bad name",
                "description": "Delegated work.",
                "settings": {},
            },
            "subagent",
            "",
            (
                "contract.subagent_name_format_invalid",
                "validation.issue.contract.subagentNameFormatInvalid",
                "name",
                {},
            ),
        ),
        (
            CustomMiddlewareBlock,
            {
                "name": "Invalid package",
                "python_package": {
                    "folder": "invalid/folder",
                },
            },
            "block",
            "custom-middleware",
            (
                "contract.python_package_folder_format_invalid",
                "validation.issue.contract.pythonPackageFolderFormatInvalid",
                "python_package.folder",
                {},
            ),
        ),
    ],
)
def test_common_schema_rules_have_specific_safe_issue_identities(
    model: type,
    payload: dict[str, object],
    scope: str,
    owner_type: str,
    expected: tuple[str, str, str, dict[str, object]],
) -> None:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)

    issue = report_from_validation_error(
        caught.value,
        stage="draft_validation",
        scope=scope,
        owner_type=owner_type,
    ).as_dict()["issues"][0]

    code, message_key, path, message_args = expected
    assert issue["code"] == code
    assert issue["message_key"] == message_key
    assert issue["path"] == path
    assert issue["message_args"] == message_args
    assert "pattern" not in str(issue["message"])
