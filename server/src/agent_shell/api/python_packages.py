from __future__ import annotations

from fastapi import APIRouter

from agent_shell.python_packages.authoring import PythonPackageAuthoringService


def build_python_package_router(
    authoring: PythonPackageAuthoringService,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/python-package-templates/custom-tool")
    async def custom_tool_templates() -> dict[str, object]:
        return authoring.template_catalog("custom-tool")

    @router.get("/api/python-package-templates/middleware")
    async def middleware_templates() -> dict[str, object]:
        return authoring.template_catalog("custom-middleware")

    @router.get("/api/python-package-templates/agent-event-output")
    async def agent_event_output_templates() -> dict[str, object]:
        return authoring.template_catalog("agent-event-output")

    @router.get("/api/python-package-templates/workflow-event-output")
    async def workflow_event_output_templates() -> dict[str, object]:
        return authoring.template_catalog("workflow-event-output")

    @router.get("/api/python-package-templates/command")
    async def command_templates() -> dict[str, object]:
        return authoring.template_catalog("command")

    return router
