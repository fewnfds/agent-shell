from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from langgraph_sdk import get_client

from agent_shell.runtime.request_snapshot import LANGGRAPH_MCP_TOOL_GRAPH_ID
from agent_shell.storage.mcp_tools import McpToolStore


class McpToolPublicationService:
    """Keep published MCP Tool records aligned with official Assistants."""

    def __init__(self, store: McpToolStore) -> None:
        self._store = store

    @staticmethod
    def _metadata(mcp_tool_id: str, *, enabled: bool) -> dict[str, Any]:
        return {
            "owner": "agent-shell",
            "graph_kind": "mcp_tool",
            "mcp_tool_id": mcp_tool_id,
            "agent_shell_mcp_tool": enabled,
        }

    @staticmethod
    def _config(mcp_tool_id: str) -> dict[str, Any]:
        return {"configurable": {"mcp_tool_id": mcp_tool_id}}

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
                config=self._config(mcp_tool_id),
                metadata=self._metadata(mcp_tool_id, enabled=enabled),
            )
            await client.assistants.update(
                str(assistant["assistant_id"]),
                graph_id=LANGGRAPH_MCP_TOOL_GRAPH_ID,
                name=str(item["name"]),
                description=str(item.get("description", "")),
                config=self._config(mcp_tool_id),
                metadata=self._metadata(mcp_tool_id, enabled=enabled),
            )
        finally:
            await client.aclose()

    async def _published_assistants(self, client: Any) -> list[dict[str, Any]]:
        """Collect official MCP Tool Assistants before any of them is hidden."""

        assistants: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await client.assistants.search(
                graph_id=LANGGRAPH_MCP_TOOL_GRAPH_ID,
                offset=offset,
            )
            if not page:
                return assistants
            assistants.extend(page)
            offset += len(page)

    async def reconcile(self, *, include_empty: bool = False) -> None:
        """Align official MCP Tool Assistants with stored publication flags."""

        items = await asyncio.to_thread(self._store.list_items)
        if not items and not include_empty:
            return
        tracked_ids = {str(item["id"]) for item in items}
        for item in items:
            await self._sync(str(item["id"]), enabled=bool(item["enabled"]))
        client = await asyncio.to_thread(get_client, url=None)
        try:
            for assistant in await self._published_assistants(client):
                metadata = assistant.get("metadata")
                if not isinstance(metadata, Mapping):
                    continue
                if metadata.get("agent_shell_mcp_tool") is not True:
                    continue
                if str(metadata.get("mcp_tool_id") or "") in tracked_ids:
                    continue
                await client.assistants.update(
                    str(assistant["assistant_id"]),
                    metadata={
                        **dict(metadata),
                        "agent_shell_mcp_tool": False,
                    },
                )
        finally:
            await client.aclose()

    async def unpublish_disabled(self) -> None:
        """Hide every Assistant whose MCP Tool is not published."""

        items = await asyncio.to_thread(self._store.list_items)
        for item in items:
            if item["enabled"]:
                continue
            await self._sync(str(item["id"]), enabled=False)

    async def publish(self, mcp_tool_id: str) -> None:
        await self._sync(mcp_tool_id, enabled=True)

    async def unpublish(self, mcp_tool_id: str) -> None:
        await self._sync(mcp_tool_id, enabled=False)

    async def delete(self, mcp_tool_id: str) -> None:
        await self.unpublish(mcp_tool_id)


__all__ = ["McpToolPublicationService"]
