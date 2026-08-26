from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.tool_packages import ToolPackageRuntime
from agent_shell.validation.assembly import StaticAssembly


def _write_tool_package(
    root: Path,
    owner_id: str,
    *,
    body: str,
) -> dict:
    folder = root / "agent-tool" / owner_id
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "id": owner_id,
                "family": "tool",
                "adapter": "agent-tool",
            }
        ),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(body, encoding="utf-8")
    (folder / "requirements.txt").write_text("", encoding="utf-8")
    return {
        "id": owner_id,
        "name": "Tool package",
        "python_package": {"folder": owner_id},
    }


def _assembly(blocks: tuple[dict, ...]) -> StaticAssembly:
    return StaticAssembly(
        main_agent={"id": "main", "name": "Main"},
        references={},
        blocks={},
        filesystem_mode="composite",
        disabled_capabilities=frozenset(),
        subagents=(),
        subagent_nodes={},
        tool_blocks=blocks,
    )


def test_tool_package_runtime_materializes_one_langchain_tool_per_reference(
    tmp_path: Path,
) -> None:
    owner_id = "11111111-1111-4111-8111-111111111111"
    block = _write_tool_package(
        tmp_path / "packages",
        owner_id,
        body=(
            "from langchain.tools import tool\n"
            "@tool\n"
            "def word_count(text: str) -> int:\n"
            "    \"\"\"Count words.\"\"\"\n"
            "    return len(text.split())\n"
            "def create_tool():\n"
            "    return word_count\n"
        ),
    )
    runtime = ToolPackageRuntime.from_assembly(
        _assembly((block,)),
        main_agent_id="main",
        request_id="tool-test",
        packages_dir=tmp_path / "packages",
        runtime_root=tmp_path / "runtime",
    )

    tools = runtime.tools_for("main")

    assert len(tools) == 1
    assert tools[0].name == "word_count"
    assert tools[0].invoke({"text": "one two three"}) == 3
    assert runtime.tools_for("main") is tools
    asyncio.run(runtime.close())


def test_tool_package_runtime_rejects_non_tool_factory_result(tmp_path: Path) -> None:
    owner_id = "22222222-2222-4222-8222-222222222222"
    block = _write_tool_package(
        tmp_path / "packages",
        owner_id,
        body="def create_tool():\n    return object()\n",
    )
    runtime = ToolPackageRuntime.from_assembly(
        _assembly((block,)),
        main_agent_id="main",
        request_id="invalid-tool-test",
        packages_dir=tmp_path / "packages",
        runtime_root=tmp_path / "runtime",
    )

    with pytest.raises(AgentRuntimeError) as caught:
        runtime.tools_for("main")

    assert caught.value.code == "tool_package_result_invalid"
    asyncio.run(runtime.close())
