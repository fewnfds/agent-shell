from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_shell.runtime import subagents
from agent_shell.runtime.subagents import build_subagent_specs
from agent_shell.validation.assembly import (
    ResolvedSubagent,
    ResolvedSubagentEdge,
)


def _middleware(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, tools=(), state_schema=None)


def test_direct_subagents_become_explicit_dictionary_specs_with_shared_workspace(
    monkeypatch,
) -> None:
    workspace = SimpleNamespace(initial_files={})
    materialized_workspaces: list[object] = []
    skill = _middleware("Skills")
    filesystem = _middleware("Filesystem")
    summarization = _middleware("Summarization")
    model_call_limit = _middleware("ModelCallLimit")
    tool_call_limit = _middleware("ToolCallLimit")
    todo = _middleware("Todo")
    retry = _middleware("Retry")
    package = _middleware("Package")
    prompt_caching = _middleware("PromptCaching")
    patch = _middleware("Patch")
    tool_boundary = _middleware("ToolBoundary")
    model_settings = _middleware("ModelSettings")
    provider_boundary = _middleware("ProviderBoundary")
    empty_prompt = _middleware("EmptyPrompt")

    monkeypatch.setattr(
        subagents, "materialize_patch_tool_calls_middleware", lambda: patch
    )
    monkeypatch.setattr(
        subagents, "ToolErrorBoundaryMiddleware", lambda: tool_boundary
    )
    monkeypatch.setattr(
        subagents,
        "make_model_request_settings_middleware",
        lambda **_kwargs: model_settings,
    )
    monkeypatch.setattr(
        subagents, "ProviderErrorBoundaryMiddleware", lambda: provider_boundary
    )
    monkeypatch.setattr(
        subagents, "EmptySystemMessageMiddleware", lambda: empty_prompt
    )

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
        mcp_references,
    ):
        assert filesystem_mode == "composite"
        assert scope == "subagent"
        assert owner_id in {"reader-id", "writer-id"}
        assert owner_name in {"reader", "writer"}
        assert mcp_references == ()
        assert workflow_node_id is None
        assert mapped_directory_paths_by_filesystem == {
            "reader-filesystem": {"/reader/": Path("reader-root")}
        }
        materialized_workspaces.append(workspace)
        return SimpleNamespace(
            model=object(),
            system_prompt=None,
            tools=(),
            foundation_middleware=(skill, filesystem),
            todo_middleware=todo,
            summarization_middleware=summarization,
            model_call_limit_middleware=model_call_limit,
            tool_call_limit_middleware=tool_call_limit,
            prompt_caching_middleware=prompt_caching,
            package_middleware=(package,),
            tool_choice="auto",
            model_settings={"temperature": 0},
            response_format=None,
            exception_retry=SimpleNamespace(after_provider_boundary=(retry,)),
            backend=object(),
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
            filesystem_mode="composite",
        ),
        "writer-id": ResolvedSubagent(
            key="writer-id",
            component_name="Writer component",
            name="writer",
            description="Writes shared files.",
            references={},
            blocks={},
            filesystem_mode="composite",
        ),
    }

    specs = build_subagent_specs(
        roots=(
            ResolvedSubagentEdge(target_key="reader-id"),
            ResolvedSubagentEdge(target_key="writer-id"),
        ),
        nodes=nodes,
        workspace=workspace,
        materialize_resources=materialize,
        mapped_directory_paths_by_filesystem={
            "reader-filesystem": {"/reader/": Path("reader-root")}
        },
    )

    assert [item["name"] for item in specs] == ["reader", "writer"]
    assert materialized_workspaces == [workspace, workspace]
    assert all("permissions" not in item for item in specs)
    assert all("graph" not in item and "runnable" not in item for item in specs)
    assert specs[0]["middleware"] == [
        skill,
        filesystem,
        summarization,
        patch,
        model_call_limit,
        tool_call_limit,
        tool_boundary,
        todo,
        model_settings,
        provider_boundary,
        retry,
        package,
        empty_prompt,
        prompt_caching,
    ]
