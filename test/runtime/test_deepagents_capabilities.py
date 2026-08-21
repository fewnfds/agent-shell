from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest
from pydantic import ValidationError

from agent_shell.contracts import (
    FilesystemBlock,
    FilesystemPermissionsBlock,
    SkillBlock,
)
from agent_shell.runtime.capabilities import (
    DeepAgentsCapabilityError,
    build_deepagents_capabilities,
)
from agent_shell.runtime.capabilities import deepagents as deepagents_capability


def test_default_workspace_exposes_only_required_read_tool(tmp_path: Path) -> None:
    from deepagents.backends import StateBackend

    capabilities = build_deepagents_capabilities(
        None,
        None,
        filesystem_mode="default-shared",
        skills_dir=tmp_path / "skills",
    )

    filesystem = capabilities.middleware[-1]
    assert [tool.name for tool in filesystem.tools] == ["read_file"]
    assert isinstance(capabilities.backend.default, StateBackend)


def test_filesystem_runtime_options_and_tool_switches_are_compiled(tmp_path: Path) -> None:
    mapped = tmp_path / "mapped"
    mapped.mkdir()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Workspace",
            "mapped_directories": [
                {"virtual_path": "/workspace/", "local_path": str(mapped)}
            ],
            "system_prompt_override": "Use the configured workspace only.",
            "tool_token_limit_before_evict": 4096,
            "human_message_token_limit_before_evict": 8192,
            "grep_max_count": 321,
            "max_execute_timeout": 45,
            "tool_configs": {
                "ls": {"visible": False},
                "read_file": {
                    "visible": True,
                    "description_override": "Read a configured workspace file.",
                },
                "delete": {
                    "visible": True,
                    "description_override": "Delete a configured workspace path.",
                },
            },
        }
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
    )
    middleware = capabilities.middleware[0]

    assert middleware.backend is capabilities.backend
    assert [tool.name for tool in middleware.tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
    ]
    assert middleware._enabled_tools == frozenset(
        {"read_file", "write_file", "edit_file", "delete", "glob", "grep"}
    )
    assert middleware._custom_system_prompt == "Use the configured workspace only."
    assert middleware._custom_tool_descriptions == {
        "read_file": "Read a configured workspace file.",
        "delete": "Delete a configured workspace path.",
    }
    assert middleware._tool_token_limit_before_evict == 4096
    assert middleware._human_message_token_limit_before_evict == 8192
    assert middleware._grep_max_count == 321
    assert middleware._max_execute_timeout == 45


def test_agents_share_state_backend_but_keep_independent_mapped_routes(
    tmp_path: Path,
) -> None:
    main_root = tmp_path / "main"
    child_root = tmp_path / "child"
    main_root.mkdir()
    child_root.mkdir()
    (main_root / "probe.txt").write_text("main route", encoding="utf-8")
    (child_root / "probe.txt").write_text("child route", encoding="utf-8")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    main_filesystem = FilesystemBlock.model_validate(
        {
            "name": "Main workspace",
            "mapped_directories": [
                {
                    "virtual_path": "/workspace/",
                    "local_path": str(main_root),
                }
            ],
        }
    )
    child_filesystem = FilesystemBlock.model_validate(
        {
            "name": "Child workspace",
            "mapped_directories": [
                {
                    "virtual_path": "/workspace/",
                    "local_path": str(child_root),
                }
            ],
        }
    )

    main = build_deepagents_capabilities(
        main_filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
        mapped_directory_paths={"/workspace/": main_root},
    )
    child = build_deepagents_capabilities(
        child_filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
        workspace=main.workspace,
        mapped_directory_paths={"/workspace/": child_root},
    )

    assert child.workspace.default_backend is main.workspace.default_backend
    assert child.workspace.routes is not main.workspace.routes
    main_result = main.workspace.routes["/workspace/"].read("/probe.txt")
    child_result = child.workspace.routes["/workspace/"].read("/probe.txt")
    assert main_result.file_data is not None
    assert child_result.file_data is not None
    assert main_result.file_data["content"] == "main route"
    assert child_result.file_data["content"] == "child route"


def test_configured_workspace_route_preserves_recursive_glob_contract(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    (workspace / "top.py").write_text("top", encoding="utf-8")
    (nested / "child.py").write_text("child", encoding="utf-8")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Workspace",
            "mapped_directories": [
                {"virtual_path": "/workspace/", "local_path": str(workspace)}
            ],
        }
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
    )

    recursive = capabilities.backend.glob("*.py", "/workspace/")
    top_level = capabilities.backend.glob("/*.py", "/workspace/")

    assert recursive.error is None
    assert top_level.error is None
    assert {match["path"] for match in recursive.matches} == {
        "/workspace/top.py",
        "/workspace/nested/child.py",
    }
    assert {match["path"] for match in top_level.matches} == {"/workspace/top.py"}


def test_filesystem_permissions_atomically_override_tools_prompt_and_paths(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Workspace",
            "system_prompt_override": "Base filesystem prompt",
            "tool_configs": {
                "ls": {
                    "visible": True,
                    "description_override": "Base list description",
                },
                "write_file": {"visible": True},
            },
        }
    )
    permissions = FilesystemPermissionsBlock.model_validate(
        {
            "name": "Reviewer",
            "permissions": [
                {"path": "/source/**", "permission": "read-only"},
                {"path": "/output/**", "permission": "read-write"},
                {"path": "/private/**", "permission": "no-access"},
                {"path": "/skills/**", "permission": "no-access"},
            ],
            "system_prompt_override": {"value": "Policy prompt"},
            "tool_overrides": {
                "ls": {"visible": False, "description_override": None},
                "write_file": {
                    "visible": True,
                    "description_override": "Policy write description",
                },
            },
        }
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        None,
        filesystem_permissions=permissions,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
    )
    middleware = capabilities.middleware[0]

    assert "ls" not in {tool.name for tool in middleware.tools}
    assert middleware._custom_system_prompt == "Policy prompt"
    assert middleware._custom_tool_descriptions == {
        "write_file": "Policy write description"
    }
    rules = [
        (tuple(rule.operations), tuple(rule.paths), rule.mode)
        for rule in capabilities.permissions
    ]
    assert rules == [
        (("read",), ("/skills/**",), "allow"),
        (("write",), ("/skills/**",), "deny"),
        (("read",), ("/source/**",), "allow"),
        (("write",), ("/source/**",), "deny"),
        (("read", "write"), ("/output/**",), "allow"),
        (("read", "write"), ("/private/**",), "deny"),
        (("read", "write"), ("/skills/**",), "deny"),
    ]
    assert middleware._permissions == list(capabilities.permissions)
    from deepagents.middleware.filesystem import _check_fs_permission

    assert (
        _check_fs_permission(
            list(capabilities.permissions), "read", "/skills/demo/SKILL.md"
        )
        == "allow"
    )
    assert (
        _check_fs_permission(
            list(capabilities.permissions), "write", "/skills/demo/SKILL.md"
        )
        == "deny"
    )

def test_request_seed_file_data_uses_string_content_for_text_and_binary(
    tmp_path: Path,
) -> None:
    text_source = tmp_path / "note.txt"
    text_source.write_text("request text", encoding="utf-8")
    binary_source = tmp_path / "payload.bin"
    binary_source.write_bytes(b"\xff\x00")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Seed files",
            "virtual_files": [
                {"virtual_path": "/input/note.txt", "source_path": str(text_source)},
                {
                    "virtual_path": "/input/payload.bin",
                    "source_path": str(binary_source),
                },
            ],
        }
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
    )

    text_data = capabilities.initial_files["/input/note.txt"]
    binary_data = capabilities.initial_files["/input/payload.bin"]
    assert isinstance(text_data["content"], str)
    assert text_data["content"] == "request text"
    assert text_data["encoding"] == "utf-8"
    assert isinstance(binary_data["content"], str)
    assert binary_data["content"] == "/wA="
    assert binary_data["encoding"] == "base64"

def test_virtual_directory_rejects_links_before_reading_outside_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside sentinel", encoding="utf-8")
    link = source / "leak.txt"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable in this environment: {exc}")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Linked source",
            "virtual_directories": [
                {"virtual_path": "/source/", "source_path": str(source)}
            ],
        }
    )

    with pytest.raises(
        DeepAgentsCapabilityError,
        match="links and reparse points are not supported",
    ):
        build_deepagents_capabilities(
            filesystem,
            None,
            filesystem_mode="configured-shared",
            skills_dir=skills_dir,
        )

def test_virtual_source_rejects_windows_reparse_points(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class ReparsePointStat:
        st_mode = stat.S_IFREG
        st_file_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

    monkeypatch.setattr(
        deepagents_capability,
        "_source_stat",
        lambda path: ReparsePointStat(),
    )

    with pytest.raises(
        DeepAgentsCapabilityError,
        match="links and reparse points are not supported",
    ):
        deepagents_capability._assert_plain_source(tmp_path / "reparse-source")

def test_filesystem_runtime_options_keep_upstream_defaults_or_disable_eviction(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    filesystem = FilesystemBlock.model_validate(
        {
            "name": "Thread files",
            "tool_token_limit_before_evict": None,
        }
    )

    capabilities = build_deepagents_capabilities(
        filesystem,
        None,
        filesystem_mode="configured-shared",
        skills_dir=skills_dir,
    )
    middleware = capabilities.middleware[0]

    assert middleware._custom_system_prompt is None
    assert middleware._tool_token_limit_before_evict is None
    assert "delete" not in {tool.name for tool in middleware.tools}
