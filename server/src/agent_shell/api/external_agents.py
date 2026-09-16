"""Zero-consumption runtime probe for the pinned Antigravity CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter

from agent_shell.external_agents.binary import probe_antigravity_cli
from agent_shell.http_surface import management_api_router


def build_external_agent_router(*, runtime_root: Path) -> APIRouter:
    router = management_api_router()

    @router.get("/external-agents/runtime/status")
    async def external_agent_runtime_status() -> dict[str, object]:
        # Hashing the pinned executable proves identity without starting a
        # model call, so this probe never spends subscription quota.
        probe = await asyncio.to_thread(probe_antigravity_cli, runtime_root)
        return {
            "provider": "antigravity-cli",
            "available": probe.available,
            "expected_path": str(probe.expected_path),
            "version": probe.version,
            "sha256": probe.binary.sha256 if probe.binary is not None else None,
            "detail": probe.detail,
            "guidance": probe.guidance,
        }

    return router


__all__ = ["build_external_agent_router"]
