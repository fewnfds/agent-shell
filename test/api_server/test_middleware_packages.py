from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware

from agent_shell.middleware_packages.runtime import MiddlewareOwner, MiddlewarePackageRuntime
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.storage.file_config import FileConfigRepository

from .support import make_client


OWNER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def write_middleware_template(
    tmp_path: Path,
    *,
    source: str,
    key: str = "request-label",
) -> Path:
    folder = tmp_path / "data" / "templates" / "agent" / "custom_middleware" / key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(source, encoding="utf-8")
    return folder


def write_private_middleware(
    tmp_path: Path,
    package_id: str,
    source: str,
    *,
    owner_id: str = OWNER_ID,
) -> tuple[str, Path]:
    folder_name = owner_id
    folder = (
        FileConfigRepository(tmp_path / "data").python_package_instances_root
        / "agent-middleware"
        / folder_name
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "package.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "id": owner_id,
                "family": "middleware",
                "adapter": "agent-middleware",
            }
        ),
        encoding="utf-8",
    )
    (folder / "main.py").write_text(source, encoding="utf-8")
    return folder_name, folder


def test_middleware_template_catalog_and_private_package_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "from langchain.agents.middleware import AgentMiddleware\n"
        "class RequestLabel(AgentMiddleware):\n"
        "    pass\n"
        "def create_middleware(agent):\n"
        "    return RequestLabel()\n"
    )
    write_middleware_template(tmp_path, source=source)

    with make_client(tmp_path, monkeypatch) as client:
        catalog = client.get("/api/python-package-templates/middleware")
        selected = catalog.json()["catalog"][0]
        created = client.post(
            "/api/blocks/custom-middleware",
            json={
                "name": "Request label",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )

    assert catalog.status_code == 200
    assert [item["key"] for item in catalog.json()["catalog"]] == ["request-label"]
    assert "dependency_status" not in catalog.json()["catalog"][0]
    assert created.status_code == 200, created.text
    assert created.json()["python_package"] == {"folder": created.json()["id"]}


def test_middleware_requires_a_template_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/api/blocks/custom-middleware",
            json={
                "name": "From empty template",
                "python_package": {"folder": ""},
            },
        )

    assert created.status_code == 422, created.text
    assert created.json()["detail"]["code"] == "python_package_template_required"


def test_missing_private_middleware_is_rejected_when_inspected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        "from langchain.agents.middleware import AgentMiddleware\n"
        "def create_middleware(agent):\n"
        "    return AgentMiddleware()\n"
    )
    write_middleware_template(tmp_path, source=source)
    with make_client(tmp_path, monkeypatch) as client:
        selected = client.get("/api/python-package-templates/middleware").json()["catalog"][0]
        created = client.post(
            "/api/blocks/custom-middleware",
            json={
                "name": "Missing package",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )
        assert created.status_code == 200, created.text
        folder = created.json()["python_package"]["folder"]
        shutil.rmtree(
            FileConfigRepository(tmp_path / "data").python_package_instances_root
            / "agent-middleware"
            / folder
        )
        assert client.get(
            f"/api/blocks/custom-middleware/{created.json()['id']}"
        ).status_code == 200
        response = client.get(
            f"/api/blocks/custom-middleware/{created.json()['id']}/python-package"
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "python_package_not_found"


def test_package_materializes_official_langchain_middleware(tmp_path: Path) -> None:
    folder_name, _folder = write_private_middleware(
        tmp_path,
        "33333333-3333-4333-8333-333333333333",
        "from langchain.agents.middleware import ModelCallLimitMiddleware\n"
        "def create_middleware(agent):\n"
        "    return ModelCallLimitMiddleware(run_limit=2)\n",
    )
    runtime = MiddlewarePackageRuntime(
        request_id="request-1",
        owners=[
            MiddlewareOwner(
                id="main",
                type="main_agent",
                name="Main",
                packages=((
                    OWNER_ID,
                    {"folder": folder_name},
                ),),
            )
        ],
        packages_dir=FileConfigRepository(tmp_path / "data").python_package_instances_root,
        runtime_root=tmp_path / "runtime",
    )

    materialized = runtime.middleware_for("main")

    assert len(materialized) == 1
    assert isinstance(materialized[0], ModelCallLimitMiddleware)
    asyncio.run(runtime.close())


def test_package_factory_can_request_runtime_context_by_name(tmp_path: Path) -> None:
    folder_name, _folder = write_private_middleware(
        tmp_path,
        "66666666-6666-4666-8666-666666666666",
        "from langchain.agents.middleware import AgentMiddleware\n"
        "class Configured(AgentMiddleware):\n"
        "    def __init__(self, config, backend, marker):\n"
        "        super().__init__()\n"
        "        self.config = config\n"
        "        self.backend = backend\n"
        "        self.marker = marker\n"
        "def create_middleware(config, backend, marker, **kwargs):\n"
        "    return Configured(config, backend, marker)\n",
    )
    backend = object()
    runtime = MiddlewarePackageRuntime(
        request_id="request-context",
        owners=[
            MiddlewareOwner(
                id="main",
                type="main_agent",
                name="Main",
                packages=((
                    OWNER_ID,
                    {"folder": folder_name},
                ),),
            )
        ],
        packages_dir=FileConfigRepository(tmp_path / "data").python_package_instances_root,
        runtime_root=tmp_path / "runtime",
    )

    materialized = runtime.middleware_for(
        "main",
        context={"config": {"enabled": True}, "backend": backend, "marker": "ok"},
    )

    assert materialized[0].config == {"enabled": True}
    assert materialized[0].backend is backend
    assert materialized[0].marker == "ok"
    asyncio.run(runtime.close())


def test_package_runtime_preserves_ordered_middleware_references(tmp_path: Path) -> None:
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    first_folder, _ = write_private_middleware(
        tmp_path,
        first_id,
        "from langchain.agents.middleware import AgentMiddleware\n"
        "class First(AgentMiddleware):\n"
        "    pass\n"
        "def create_middleware(agent):\n"
        "    return First()\n",
        owner_id=first_id,
    )
    second_folder, _ = write_private_middleware(
        tmp_path,
        second_id,
        "from langchain.agents.middleware import AgentMiddleware\n"
        "class Second(AgentMiddleware):\n"
        "    pass\n"
        "def create_middleware(agent):\n"
        "    return Second()\n",
        owner_id=second_id,
    )
    runtime = MiddlewarePackageRuntime(
        request_id="request-order",
        owners=[
            MiddlewareOwner(
                id="main",
                type="main_agent",
                name="Main",
                packages=(
                    (second_id, {"folder": second_folder}),
                    (first_id, {"folder": first_folder}),
                ),
            )
        ],
        packages_dir=FileConfigRepository(tmp_path / "data").python_package_instances_root,
        runtime_root=tmp_path / "runtime",
    )

    assert [type(item).__name__ for item in runtime.middleware_for("main")] == [
        "Second",
        "First",
    ]
    asyncio.run(runtime.close())


def test_package_runtime_rejects_multiple_middleware_result(tmp_path: Path) -> None:
    folder_name, _ = write_private_middleware(
        tmp_path,
        OWNER_ID,
        "from langchain.agents.middleware import AgentMiddleware\n"
        "def create_middleware(agent):\n"
        "    return [AgentMiddleware(), AgentMiddleware()]\n",
    )
    runtime = MiddlewarePackageRuntime(
        request_id="request-group-result",
        owners=[
            MiddlewareOwner(
                id="main",
                type="main_agent",
                name="Main",
                packages=((
                    OWNER_ID,
                    {"folder": folder_name},
                ),),
            )
        ],
        packages_dir=FileConfigRepository(tmp_path / "data").python_package_instances_root,
        runtime_root=tmp_path / "runtime",
    )

    with pytest.raises(AgentRuntimeError) as caught:
        runtime.middleware_for("main")

    assert caught.value.code == "middleware_package_result_invalid"
    asyncio.run(runtime.close())


def test_async_agent_runtime_rejects_sync_only_middleware_hooks(tmp_path: Path) -> None:
    folder_name, _folder = write_private_middleware(
        tmp_path,
        "55555555-5555-4555-8555-555555555555",
        "from langchain.agents.middleware import AgentMiddleware\n"
        "class SyncOnly(AgentMiddleware):\n"
        "    def before_agent(self, state, runtime):\n"
        "        return None\n"
        "def create_middleware(agent):\n"
        "    return SyncOnly()\n",
    )
    runtime = MiddlewarePackageRuntime(
        request_id="request-1",
        owners=[
            MiddlewareOwner(
                id="main",
                type="main_agent",
                name="Main",
                packages=((
                    OWNER_ID,
                    {"folder": folder_name},
                ),),
            )
        ],
        packages_dir=FileConfigRepository(tmp_path / "data").python_package_instances_root,
        runtime_root=tmp_path / "runtime",
    )

    with pytest.raises(AgentRuntimeError) as caught:
        runtime.middleware_for("main")

    assert caught.value.code == "middleware_package_async_hook_required"
    assert caught.value.safe_message.endswith("before_agent without abefore_agent.")
    asyncio.run(runtime.close())
