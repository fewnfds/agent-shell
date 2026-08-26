from __future__ import annotations

from agent_shell.validation.capability_assembly import (
    CapabilityAssemblySubject,
    capability_assembly_issues,
)


def test_effective_capability_subject_reports_required_capabilities() -> None:
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
    assert all(issue.scope == "route" for issue in issues)
    assert all(issue.owner_id == "router-id" for issue in issues)
    assert all(issue.owner_name == "research-route" for issue in issues)
