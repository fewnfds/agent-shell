from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_shell.runtime.state import AgentShellStateMiddleware
from agent_shell.runtime.subagents import build_subagent_specs
from agent_shell.validation.assembly import ResolvedSubagent, ResolvedSubagentEdge


def test_direct_subagents_become_official_dictionary_specs_with_shared_workspace() -> None:
    workspace = object()
    materialized_workspaces: list[object] = []

    def materialize(
        _references,
        _blocks,
        *,
        filesystem_mode,
        scope,
        owner_id,
        owner_name,
        workflow_node_id,
        workspace,
        mapped_directory_paths_by_filesystem,
        disabled_capabilities,
    ):
        assert filesystem_mode == "configured-shared"
        assert scope == "subagent"
        assert owner_id in {"reader-id", "writer-id"}
        assert disabled_capabilities == frozenset()
        assert workflow_node_id is None
        assert mapped_directory_paths_by_filesystem == {
            "reader-filesystem": {"/reader/": Path("reader-root")}
        }
        materialized_workspaces.append(workspace)
        return SimpleNamespace(
            model=object(),
            system_prompt=None,
            tools=(),
            middleware=(),
            package_middleware=(),
            extra_middleware=(),
            tool_choice=None,
            model_settings={},
            response_format=None,
            permissions=(f"{owner_name}-permission",),
            exception_retry=None,
            model_provider="openai",
            model_name="test-model",
            backend=object(),
            initial_files={},
            skill_sources=(),
            workspace=workspace,
        )

    nodes = {
        "reader-id": ResolvedSubagent(
            key="reader-id",
            component_name="Reader component",
            name="reader",
            description="Reads shared files.",
            references={},
            blocks={},
            filesystem_mode="configured-shared",
        ),
        "writer-id": ResolvedSubagent(
            key="writer-id",
            component_name="Writer component",
            name="writer",
            description="Writes shared files.",
            references={},
            blocks={},
            filesystem_mode="configured-shared",
        ),
    }

    specs = build_subagent_specs(
        roots=(
            ResolvedSubagentEdge(target_key="reader-id"),
            ResolvedSubagentEdge(target_key="writer-id"),
        ),
        nodes=nodes,
        workspace=workspace,
        materialize_profile=materialize,
        mapped_directory_paths_by_filesystem={
            "reader-filesystem": {"/reader/": Path("reader-root")}
        },
    )

    assert [item["name"] for item in specs] == ["reader", "writer"]
    assert materialized_workspaces == [workspace, workspace]
    assert specs[0]["permissions"] == ["reader-permission"]
    assert specs[1]["permissions"] == ["writer-permission"]
    assert any(
        isinstance(item, AgentShellStateMiddleware)
        for item in specs[0]["middleware"]
    )
    assert all("graph" not in item and "runnable" not in item for item in specs)
