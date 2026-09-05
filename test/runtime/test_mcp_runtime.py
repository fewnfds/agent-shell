from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import json
import socket

from langchain_core.messages import ToolMessage
from mcp.server.fastmcp import FastMCP
import pytest
import uvicorn

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.mcp import McpRunRuntime
from agent_shell.storage.mcp_connections import McpResourceStore
from agent_shell.validation.assembly import ResolvedMcpReference


REPOSITORY_ID = "11111111-1111-4111-8111-111111111111"
REQUIREMENT_ID = "22222222-2222-4222-8222-222222222222"
CONNECTION_ID = "33333333-3333-4333-8333-333333333333"


def resolved_reference(*, tools: list[str] | None = None) -> ResolvedMcpReference:
    return ResolvedMcpReference(
        reference={
            "requirement_id": REQUIREMENT_ID,
            "tool_selection": (
                {"mode": "include", "tools": tools}
                if tools is not None
                else {"mode": "all", "tools": []}
            ),
        },
        requirement={
            "id": REQUIREMENT_ID,
            "name": "Calculator",
            "description": "Calculator Tools.",
            "namespace": "calc",
        },
    )


def managed_resources(tmp_path: Path) -> McpResourceStore:
    lock_root = tmp_path / "packaging" / "windows"
    lock_root.mkdir(parents=True)
    (lock_root / "runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "python": "3.12.13",
            "uv": {"version": "0.12.2", "url": "uv", "sha256": "uv"},
        }),
        encoding="utf-8",
    )
    (lock_root / "mcp-runtime-lock.json").write_text(
        json.dumps({
            "schema": 1,
            "platform": "windows-x64",
            "node": {"version": "22.23.2", "url": "node", "sha256": "node"},
        }),
        encoding="utf-8",
    )
    return McpResourceStore(tmp_path, runtime_root=tmp_path / "runtime")


def test_empty_mcp_references_leave_runtime_disabled(tmp_path: Path) -> None:
    resources = McpResourceStore(tmp_path)

    runtime = asyncio.run(
        McpRunRuntime.discover(
            resources.snapshot(),
            REPOSITORY_ID,
            (),
        )
    )

    assert runtime is None


async def discover_and_call(resources: McpResourceStore) -> None:
    reference = resolved_reference(tools=["add", "fail"])
    runtime = await McpRunRuntime.discover(
        resources.snapshot(),
        REPOSITORY_ID,
        (reference, reference),
    )
    assert runtime is not None
    tools = runtime.tools_for((reference,))
    assert [tool.name for tool in tools] == ["calc_add", "calc_fail"]
    assert "5" in str(await tools[0].ainvoke({"a": 2, "b": 3}))
    commands = runtime.commands_for((reference,))
    assert commands.available_tools() == {"calc": ("add", "fail")}
    success = await commands.call_tool("calc", "add", {"a": 4, "b": 5})
    assert isinstance(success, ToolMessage)
    assert success.status == "success"
    assert "9" in str(success.content)
    failure = await commands.call_tool("calc", "fail")
    assert isinstance(failure, ToolMessage)
    assert failure.status == "error"
    assert "expected failure" in str(failure.content)
    blobs = await commands.get_resources("calc", uris="memo://welcome")
    assert [blob.as_string() for blob in blobs] == ["Calculator resource"]
    messages = await commands.get_prompt(
        "calc",
        "calculation_prompt",
        arguments={"expression": "2 + 3"},
    )
    assert [message.content for message in messages] == ["Calculate 2 + 3"]


def test_uninstalled_local_mcp_is_resolved_outside_the_event_loop(
    tmp_path: Path,
) -> None:
    resources = managed_resources(tmp_path)
    resources.save_connection(
        CONNECTION_ID,
        {
            "name": "Calculator stdio",
            "transport": "stdio",
            "package_source": "pypi",
            "package": "calculator-mcp",
            "version": "1.0.0",
            "args": [],
            "env": {},
        },
    )
    resources.set_binding(REPOSITORY_ID, REQUIREMENT_ID, CONNECTION_ID)

    snapshot = resources.snapshot()

    class LoopCheckingSnapshot:
        def get_binding(self, repository_id: str, requirement_id: str) -> str | None:
            return snapshot.get_binding(repository_id, requirement_id)

        def resolve_connection(self, connection_id: str) -> dict:
            with pytest.raises(RuntimeError):
                asyncio.get_running_loop()
            return snapshot.resolve_connection(connection_id)

    with pytest.raises(AgentRuntimeError) as raised:
        asyncio.run(
            McpRunRuntime.discover(
                LoopCheckingSnapshot(),  # type: ignore[arg-type]
                REPOSITORY_ID,
                (resolved_reference(),),
            )
        )
    assert raised.value.code == "mcp_installation_not_ready"


def test_streamable_http_mcp_adapter_discovers_and_calls_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        mcp = FastMCP("Calculator", stateless_http=True, json_response=True)

        @mcp.tool()
        def add(a: int, b: int) -> int:
            return a + b

        @mcp.tool()
        def fail() -> None:
            raise ValueError("expected failure")

        @mcp.resource("memo://welcome")
        def welcome() -> str:
            return "Calculator resource"

        @mcp.prompt()
        def calculation_prompt(expression: str) -> str:
            return f"Calculate {expression}"

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            config = uvicorn.Config(
                mcp.streamable_http_app(),
                log_level="error",
                lifespan="on",
            )
            server = uvicorn.Server(config)
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            while not server.started:
                if server_task.done():
                    await server_task
                await asyncio.sleep(0)
            resources = McpResourceStore(tmp_path)
            resources.save_connection(
                CONNECTION_ID,
                {
                    "name": "Calculator HTTP",
                    "transport": "http",
                    "url": f"http://127.0.0.1:{port}/mcp",
                    "headers": {},
                },
            )
            resources.set_binding(REPOSITORY_ID, REQUIREMENT_ID, CONNECTION_ID)
            try:
                await discover_and_call(resources)
            finally:
                server.should_exit = True
                await server_task

    asyncio.run(scenario())
