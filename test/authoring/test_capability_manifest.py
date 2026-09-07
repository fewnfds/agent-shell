from __future__ import annotations

import subprocess
import sys

import pytest

from agent_shell.authoring import (
    editor_defaults,
)
from agent_shell.capability_manifest import (
    CAPABILITY_BY_TYPE,
    CAPABILITY_MANIFESTS,
    validate_capability_manifests,
)
from agent_shell.contracts import (
    AgentEventOutputBlock,
    BLOCK_MODELS,
    FilesystemToolsBlock,
)
from agent_shell.workflow_event_output import WorkflowEventOutputBlock


def test_manifest_matches_current_blocks_and_form_order() -> None:
    assert [manifest.type for manifest in CAPABILITY_MANIFESTS] == [
        "model-requirement",
        "system-prompt",
        "filesystem",
        "filesystem-tools",
        "todo-list",
        "custom-tool",
        "skill",
        "custom-middleware",
        "agent-event-output",
        "exception-retry",
        "subagent",
        "summarization",
        "prompt-caching",
    ]
    assert {manifest.type for manifest in CAPABILITY_MANIFESTS} == set(BLOCK_MODELS)
    assert CAPABILITY_MANIFESTS[0].required is True
    manifests = {manifest.type: manifest for manifest in CAPABILITY_MANIFESTS}
    assert manifests["custom-middleware"].subagent_overrideable is False
    assert manifests["custom-middleware"].subagent_policy == "force-remove"
    assert manifests["filesystem"].subagent_overrideable is True
    assert manifests["filesystem"].subagent_policy == "inherit"
    assert manifests["filesystem"].required is True
    assert manifests["filesystem-tools"].subagent_overrideable is True
    assert manifests["filesystem-tools"].subagent_policy == "inherit"
    assert manifests["filesystem-tools"].required is True
    assert manifests["skill"].agent_selectable is False
    assert manifests["agent-event-output"].subagent_overrideable is False
    assert manifests["agent-event-output"].required is True
    assert manifests["agent-event-output"].subagent_policy == "top-level-only"
    assert manifests["agent-event-output"].tool_names == ()
    assert manifests["exception-retry"].subagent_overrideable is True
    assert manifests["exception-retry"].subagent_policy == "inherit"
    assert manifests["exception-retry"].tool_names == ()
    assert manifests["subagent"].subagent_overrideable is False
    assert manifests["subagent"].subagent_policy == "top-level-only"
    assert manifests["summarization"].subagent_overrideable is True
    assert manifests["summarization"].subagent_policy == "inherit"
    assert manifests["prompt-caching"].subagent_overrideable is True
    assert manifests["prompt-caching"].subagent_policy == "inherit"
    assert manifests["todo-list"].subagent_overrideable is True
    assert manifests["todo-list"].tool_names == ("write_todos",)


def test_manifest_rejects_invalid_catalog_structure() -> None:
    with pytest.raises(ValueError, match="types must be unique"):
        validate_capability_manifests((*CAPABILITY_MANIFESTS, CAPABILITY_MANIFESTS[0]))

    with pytest.raises(ValueError, match="orders must be unique and ordered"):
        validate_capability_manifests(tuple(reversed(CAPABILITY_MANIFESTS)))



def test_editor_defaults_are_derived_from_current_authoring_contracts() -> None:
    defaults = editor_defaults()
    filesystem = defaults["filesystem"]
    filesystem_tools = defaults["filesystem_tools"]
    agent_event_output = defaults["agent_event_output"]

    assert [tool["name"] for tool in filesystem_tools["tools"]] == list(
        CAPABILITY_BY_TYPE["filesystem-tools"].tool_names
    )
    tools = {tool["name"]: tool for tool in filesystem_tools["tools"]}
    assert tools["read_file"]["configurable"] is False
    assert tools["read_file"]["visible"] is True
    assert tools["delete"]["configurable"] is True
    assert tools["delete"]["visible"] is False
    assert tools["execute"]["configurable"] is True
    assert tools["execute"]["visible"] is False
    assert filesystem["system_prompt"] == ""
    assert defaults["subagent"]["system_prompt"] == ""
    assert set(defaults["subagent"]) == {"system_prompt", "tool_description"}
    assert set(defaults["todo_list"]) == {"system_prompt", "tool_description"}
    assert filesystem_tools["tool_token_limit_before_evict"] == (
        FilesystemToolsBlock.model_fields["tool_token_limit_before_evict"].default
    )
    assert filesystem_tools["human_message_token_limit_before_evict"] == 50_000
    assert filesystem_tools["grep_max_count"] == 1_000
    assert filesystem_tools["max_execute_timeout"] == 120
    assert defaults["summarization"]["trigger"] == {
        "type": "auto",
        "value": None,
    }
    assert all(
        "enabled" not in defaults[capability]
        for capability in (
            "summarization",
            "prompt_caching",
        )
    )
    from deepagents.middleware.summarization import DEEPAGENTS_DEFAULT_SUMMARY_PROMPT

    assert defaults["summarization"]["summary_prompt_default"] == (
        DEEPAGENTS_DEFAULT_SUMMARY_PROMPT
    )
    assert defaults["prompt_caching"] == {
        "type": "ephemeral",
        "ttl": "5m",
        "min_messages_to_cache": 0,
    }
    assert agent_event_output == {}
    assert defaults["workflow_event_output"] == {}
    reference = {
        "folder": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }
    assert AgentEventOutputBlock.model_validate(
        {"name": "Agent output", "python_package": reference}
    ).python_package.folder == reference["folder"]
    assert WorkflowEventOutputBlock.model_validate(
        {"name": "Workflow output", "python_package": reference}
    ).python_package.folder == reference["folder"]


def test_editor_catalog_import_does_not_load_optional_runtime_packages() -> None:
    program = """
import builtins
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'deepagents' or name.startswith('deepagents.') or name == 'langchain' or name.startswith('langchain.'):
        raise AssertionError(f'optional runtime import during editor catalog construction: {name}')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
from agent_shell.authoring import editor_defaults
assert editor_defaults()['filesystem_tools']['tools']
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
