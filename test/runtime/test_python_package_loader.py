from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.runtime.agent_runtime import AgentRuntime
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1


def _write_package(folder: Path, value: str) -> None:
    folder.mkdir(parents=True)
    (folder / "main.py").write_text(
        "from .helper import VALUE\n\n"
        "def create_command():\n"
        "    return VALUE\n",
        encoding="utf-8",
    )
    (folder / "helper.py").write_text(
        f"VALUE = {value!r}\n",
        encoding="utf-8",
    )


def test_package_loaders_own_unique_module_namespaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_folder = tmp_path / "first"
    second_folder = tmp_path / "second"
    _write_package(first_folder, "first")
    _write_package(second_folder, "second")

    def resolve(folder: str, *_args, **_kwargs):
        package_dir = first_folder if folder == "first" else second_folder
        return ({"dependency_status": "ready"}, package_dir)

    monkeypatch.setattr(
        "agent_shell.python_packages.loader.resolve_python_package",
        resolve,
    )

    def loader() -> PythonPackageLoader:
        return PythonPackageLoader(
            request_id="shared-request",
            packages_dir=tmp_path,
            runtime_root=tmp_path / "runtime",
            family="workflow-node",
            adapter="command",
            factory_name="create_command",
            factory_parameters=(),
        )

    first = loader()
    second = loader()
    first_module, _, _ = first.load(
        "owner-first",
        "command",
        0,
        "first",
        package_owner_id="package-first",
    )
    second_module, _, _ = second.load(
        "owner-second",
        "command",
        0,
        "second",
        package_owner_id="package-second",
    )

    assert first_module.__name__ != second_module.__name__
    assert first_module.__name__ in sys.modules
    assert second_module.__name__ in sys.modules
    assert f"{first_module.__name__}.helper" in sys.modules
    assert f"{second_module.__name__}.helper" in sys.modules

    first.close()
    assert first_module.__name__ not in sys.modules
    assert f"{first_module.__name__}.helper" not in sys.modules
    assert second_module.__name__ in sys.modules
    assert f"{second_module.__name__}.helper" in sys.modules
    assert second_module.create_command() == "second"

    second.close()
    assert second_module.__name__ not in sys.modules
    assert f"{second_module.__name__}.helper" not in sys.modules


def test_cancelled_graph_construction_releases_imported_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation joins the package import before its runtime is closed."""

    command_id = "11111111-1111-4111-8111-111111111111"
    barrier_name = f"_package_cancel_test_{uuid4().hex}"
    barrier = ModuleType(barrier_name)
    barrier.release = threading.Event()
    monkeypatch.setitem(sys.modules, barrier_name, barrier)
    package_dir = tmp_path / "packages" / "command" / "cancel-command"
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        json.dumps({
            "format_version": 1,
            "family": "workflow-node",
            "adapter": "command",
            "id": command_id,
        }),
        encoding="utf-8",
    )
    (package_dir / "main.py").write_text(
        f"from {barrier_name} import entered, release\n"
        "entered(__name__)\n"
        "assert release.wait(5), 'package import was not released'\n"
        "def create_command():\n"
        "    async def command(state, runtime):\n"
        "        from langgraph.types import Command\n"
        "        return Command(goto='end')\n"
        "    return command\n",
        encoding="utf-8",
    )
    document = WorkflowGraphDocumentV1.model_validate({
        "definition": {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "command", "type": "command", "config": {"command_id": command_id}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "start-command", "source": "start", "source_handle": "next", "target": "command", "target_handle": "in"},
                {"id": "command-end", "source": "command", "source_handle": "next", "target": "end", "target_handle": "in"},
            ],
        },
    })
    command = {
        "id": command_id,
        "name": "Cancellation command",
        "python_package": {"folder": package_dir.name},
    }

    async def discover_mcp(_references):
        return None

    runtime = AgentRuntime(
        builder=SimpleNamespace(discover_mcp=discover_mcp),
        files=None,
        blocks=SimpleNamespace(get_block_internal=lambda _kind, _id: command),
        python_packages_dir=package_dir.parent.parent,
        runtime_dir=tmp_path / "runtime",
        workflow_data=None,
        graph_store=None,
    )
    loaded_module_names: list[str] = []

    async def scenario() -> None:
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()

        def import_entered(module_name: str) -> None:
            loaded_module_names.append(module_name)
            loop.call_soon_threadsafe(entered.set)

        barrier.entered = import_entered
        construction = asyncio.create_task(
            runtime.build_mcp_tool_graph(
                document,
                mcp_tool_id="22222222-2222-4222-8222-222222222222",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            construction.cancel()
            # Cancellation runs before the import is released on the next turn.
            loop.call_soon(barrier.release.set)
            with pytest.raises(asyncio.CancelledError):
                await construction
        finally:
            barrier.release.set()
            if not construction.done():
                construction.cancel()
            await asyncio.gather(construction, return_exceptions=True)

    try:
        # asyncio.run also joins its executor, so inspection cannot race a worker.
        asyncio.run(scenario())
        assert loaded_module_names
        assert all(name not in sys.modules for name in loaded_module_names)
    finally:
        for name in loaded_module_names:
            sys.modules.pop(name, None)
