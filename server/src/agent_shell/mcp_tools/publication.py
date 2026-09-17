from __future__ import annotations

import asyncio
from typing import Any

from langgraph_sdk import get_client

from agent_shell.runtime.request_snapshot import LANGGRAPH_MCP_TOOL_GRAPH_ID
from agent_shell.storage.mcp_tools import McpToolStore


class McpToolPublicationService:
    """Keep published MCP Tool records aligned with official Assistants."""

    def __init__(self, store: McpToolStore) -> None:
        self._store = store

    async def _sync(self, mcp_tool_id: str, *, enabled: bool) -> None:
        item = await asyncio.to_thread(self._store.get_item, mcp_tool_id)
        if item is None:
            return
        client = await asyncio.to_thread(get_client, url=None)
        try:
            assistant = await client.assistants.create(
                LANGGRAPH_MCP_TOOL_GRAPH_ID,
                assistant_id=mcp_tool_id,
                if_exists="do_nothing",
                name=str(item["name"]),
                description=str(item.get("description", "")),
                config={
                    "configurable": {
                        "mcp_tool_id": mcp_tool_id,
                    }
                },
                metadata={
                    "owner": "agent-shell",
                    "graph_kind": "mcp_tool",
                    "mcp_tool_id": mcp_tool_id,
                    "agent_shell_mcp_tool": enabled,
                },
            )
            await client.assistants.update(
                str(assistant["assistant_id"]),
                graph_id=LANGGRAPH_MCP_TOOL_GRAPH_ID,
                name=str(item["name"]),
                description=str(item.get("description", "")),
                config={
                    "configurable": {
                        "mcp_tool_id": mcp_tool_id,
                    }
                },
                metadata={
                    "owner": "agent-shell",
                    "graph_kind": "mcp_tool",
                    "mcp_tool_id": mcp_tool_id,
                    "agent_shell_mcp_tool": enabled,
                },
            )
        finally:
            await client.aclose()

    async def publish(self, mcp_tool_id: str) -> None:
        await self._sync(mcp_tool_id, enabled=True)

    async def unpublish(self, mcp_tool_id: str) -> None:
        await self._sync(mcp_tool_id, enabled=False)

    async def delete(self, mcp_tool_id: str) -> None:
        await self.unpublish(mcp_tool_id)


__all__ = ["McpToolPublicationService"]
