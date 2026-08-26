from __future__ import annotations

from agent_shell.configuration.dependencies import (
    iter_configuration_entities,
    iter_configuration_references,
)
from agent_shell.configuration.bundles.contracts import FilesystemBindingResolution
from agent_shell.configuration.bundles.filesystem import (
    apply_filesystem_bindings,
    collect_filesystem_bindings,
)


def test_configuration_dependency_owner_enumerates_declared_references() -> None:
    ids = {
        "main": "11111111-1111-4111-8111-111111111111",
        "subagent": "22222222-2222-4222-8222-222222222222",
        "model_requirement": "33333333-3333-4333-8333-333333333333",
        "tool": "44444444-4444-4444-8444-444444444444",
        "middleware": "55555555-5555-4555-8555-555555555555",
        "filesystem": "66666666-6666-4666-8666-666666666666",
        "skill": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "workflow": "77777777-7777-4777-8777-777777777777",
        "workflow_output": "88888888-8888-4888-8888-888888888888",
        "checkpointer": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "command": "99999999-9999-4999-8999-999999999999",
        "dispatcher": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }
    config = {
        "components": {
            "filesystem": [
                {
                    "id": ids["filesystem"],
                    "name": "Workspace",
                    "skill_package_id": ids["skill"],
                }
            ],
            "skill": [
                {"id": ids["skill"], "name": "Writing skills"}
            ],
        },
        "main_agents": [
            {
                "id": ids["main"],
                "name": "Main",
                "capability_refs": [
                    {
                        "type": "model-requirement",
                        "block_id": ids["model_requirement"],
                    }
                ],
                "tool_refs": [{"tool_id": ids["tool"]}],
                "middleware_refs": [
                    {"middleware_id": ids["middleware"]}
                ],
                "subagents": [{"subagent_id": ids["subagent"]}],
            }
        ],
        "subagents": [
            {
                "id": ids["subagent"],
                "component_name": "Worker",
                "name": "worker",
                "settings": {
                    "capability_overrides": [
                        {
                            "type": "filesystem",
                            "mode": "replace",
                            "block_id": ids["filesystem"],
                        },
                        {
                            "type": "todo-list",
                            "mode": "disabled",
                            "block_id": "",
                        },
                    ],
                    "tool_refs": [{"tool_id": ids["tool"]}],
                    "middleware_refs": [
                        {"middleware_id": ids["middleware"]}
                    ],
                },
            }
        ],
        "workflows": [
            {
                "id": ids["workflow"],
                "name": "Workflow",
                "checkpointer_id": ids["checkpointer"],
                "workflow_event_output_id": ids["workflow_output"],
                "definition": {
                    "nodes": [
                        {
                            "id": "agent",
                            "type": "agent",
                            "config": {"main_agent_id": ids["main"]},
                        },
                        {
                            "id": "command",
                            "type": "command",
                            "config": {"command_id": ids["command"]},
                        },
                        {
                            "id": "dispatcher",
                            "type": "task-dispatcher",
                            "config": {
                                "task_dispatcher_id": ids["dispatcher"]
                            },
                        },
                    ]
                },
            }
        ],
    }

    references = {
        (
            owner.kind,
            reference.path,
            reference.target_kind,
            reference.target_component_type,
            reference.target_id,
        )
        for owner in iter_configuration_entities(config)
        for reference in iter_configuration_references(owner)
    }

    assert references == {
        (
            "component",
            "skill_package_id",
            "component",
            "skill",
            ids["skill"],
        ),
        (
            "main_agent",
            "capability_refs[0].block_id",
            "component",
            "model-requirement",
            ids["model_requirement"],
        ),
        ("main_agent", "tool_refs[0].tool_id", "component", "custom-tool", ids["tool"]),
        (
            "main_agent",
            "middleware_refs[0].middleware_id",
            "component",
            "custom-middleware",
            ids["middleware"],
        ),
        ("main_agent", "subagents[0].subagent_id", "subagent", "", ids["subagent"]),
        (
            "subagent",
            "settings.capability_overrides[0].block_id",
            "component",
            "filesystem",
            ids["filesystem"],
        ),
        ("subagent", "settings.tool_refs[0].tool_id", "component", "custom-tool", ids["tool"]),
        (
            "subagent",
            "settings.middleware_refs[0].middleware_id",
            "component",
            "custom-middleware",
            ids["middleware"],
        ),
        (
            "workflow",
            "checkpointer_id",
            "component",
            "checkpointer",
            ids["checkpointer"],
        ),
        (
            "workflow",
            "workflow_event_output_id",
            "component",
            "workflow-event-output",
            ids["workflow_output"],
        ),
        (
            "workflow",
            "definition.nodes[0].config.main_agent_id",
            "main_agent",
            "",
            ids["main"],
        ),
        (
            "workflow",
            "definition.nodes[1].config.command_id",
            "component",
            "command",
            ids["command"],
        ),
        (
            "workflow",
            "definition.nodes[2].config.task_dispatcher_id",
            "component",
            "task-dispatcher",
            ids["dispatcher"],
        ),
    }


def test_local_shell_workspace_is_a_rebindable_filesystem_directory(
    tmp_path,
) -> None:
    filesystem_id = "11111111-1111-4111-8111-111111111111"
    payload = {
        "backend_type": "local-shell",
        "workspace": {
            "local_path": "H:\\source-workspace",
            "path_origin": "absolute",
        },
    }
    bindings = collect_filesystem_bindings(
        {filesystem_id: ("filesystem", "Local workspace", payload)}
    )

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.kind == "local-shell-workspace"
    assert binding.path == "workspace.local_path"
    assert binding.required is True

    target = tmp_path / "target-workspace"
    target.mkdir()
    rebound, errors = apply_filesystem_bindings(
        {filesystem_id: payload},
        bindings,
        {
            binding.binding_id: FilesystemBindingResolution(
                value=str(target.resolve()),
                path_origin="absolute",
            )
        },
        data_root=tmp_path,
        require_resolved=True,
    )

    assert errors == []
    assert rebound[filesystem_id]["workspace"] == {
        "local_path": str(target.resolve()),
        "path_origin": "absolute",
    }
