from __future__ import annotations

from agent_shell.validation.capability_assembly import (
    CapabilityAssemblySubject,
    capability_assembly_issues,
)


def test_effective_capability_subject_reports_required_and_filesystem_mode() -> None:
    subject = CapabilityAssemblySubject(
        references={"skill": "skill-id"},
        required_types=frozenset({"model-requirement", "agent-event-output"}),
        scope="route",
        owner_id="router-id",
        owner_name="research-route",
    )

    issues = capability_assembly_issues(subject)

    assert [issue.code for issue in issues] == [
        "assembly.required_capability_missing",
        "assembly.required_capability_missing",
    ]
    assert subject.filesystem_mode == "default-shared"
    assert all(issue.scope == "route" for issue in issues)
    assert all(issue.owner_id == "router-id" for issue in issues)
    assert all(issue.owner_name == "research-route" for issue in issues)


def test_filesystem_mode_uses_final_effective_selection() -> None:
    configured = CapabilityAssemblySubject(
        references={"filesystem": "filesystem-id", "skill": "skill-id"},
        scope="main_agent",
    )
    skill_only = CapabilityAssemblySubject(
        references={"skill": "skill-id"},
        scope="subagent",
    )
    default = CapabilityAssemblySubject(
        references={"model-requirement": "requirement-id"},
        scope="subagent",
    )

    assert configured.filesystem_mode == "configured-shared"
    assert skill_only.filesystem_mode == "default-shared"
    assert default.filesystem_mode == "default-shared"
    assert capability_assembly_issues(configured) == []
    assert capability_assembly_issues(skill_only) == []
    assert capability_assembly_issues(default) == []
