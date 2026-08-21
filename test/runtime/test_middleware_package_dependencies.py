from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_shell.python_packages import dependencies
from agent_shell.python_packages.dependencies import prepare_windows_dependencies
from agent_shell.python_requirements import parse_python_requirements
from agent_shell.middleware_packages.packages import scan_middleware_package
from agent_shell.registries.errors import ResourceScanError
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository


def test_requirements_parser_has_no_product_size_or_package_count_ceiling() -> None:
    lines = ["# " + "x" * (70 * 1024)]
    lines.extend(f"package-{index}==1.0" for index in range(250))

    parsed = parse_python_requirements(lines)

    assert len(parsed.values) == 250


def write_package(root: Path, owner_id: str, package_id: str) -> tuple[str, Path]:
    folder_name = owner_id
    folder = root / "agent-middleware" / folder_name
    folder.mkdir(parents=True)
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
    (folder / "main.py").write_text(
        "from langchain.agents.middleware import AgentMiddleware\n"
        "def create_middleware(agent):\n"
        "    return AgentMiddleware()\n",
        encoding="utf-8",
    )
    return folder_name, folder


def write_tool_package(root: Path, owner_id: str) -> tuple[str, Path]:
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
    (folder / "main.py").write_text(
        "from langchain.tools import tool\n"
        "@tool\n"
        "def dependency_tool(value: str) -> str:\n"
        "    \"\"\"Return a value.\"\"\"\n"
        "    return value\n"
        "def create_tool():\n"
        "    return dependency_tool\n",
        encoding="utf-8",
    )
    return owner_id, folder


def write_runtime_manifest(runtime_root: Path) -> None:
    manifest = runtime_root / "app" / "runtime-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "platform": "windows-x64",
                "python": "3.12.9",
                "uv": "0.11.28",
                "uv_url": "https://example.invalid/uv.zip",
                "uv_sha256": "0" * 64,
                "build_fingerprint": "core-fingerprint",
            }
        ),
        encoding="utf-8",
    )


def test_requirements_are_normalized_and_need_runtime_state(tmp_path: Path) -> None:
    packages = tmp_path / "packages"
    owner_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    package_id = "11111111-1111-4111-8111-111111111111"
    _folder_name, folder = write_package(packages, owner_id, package_id)
    (folder / "requirements.txt").write_text(
        "# package dependencies\nPillow>=11,<13\nhttpx; python_version >= '3.12'\n",
        encoding="utf-8",
    )

    package = scan_middleware_package(folder, owner_id=owner_id)

    assert package["python_requirements"] == [
        'httpx; python_version >= "3.12"',
        "Pillow<13,>=11",
    ]
    assert package["dependency_status"] == "restart_required"

    (folder / "requirements.txt").write_text(
        "--extra-index-url https://packages.example/simple\n",
        encoding="utf-8",
    )
    with pytest.raises(ResourceScanError) as caught:
        scan_middleware_package(folder, owner_id=owner_id)
    assert caught.value.message_key == "resource.error.pythonPackage.requirementsInvalid"


def test_dependency_preparation_replaces_only_successful_package_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    runtime_root = tmp_path / "runtime"
    packages = FileConfigRepository(data_root).python_package_instances_root
    owner_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    package_id = "11111111-1111-4111-8111-111111111111"
    folder_name, folder = write_package(packages, owner_id, package_id)
    unused_owner_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    unused_package_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    _unused_name, unused_folder = write_package(
        packages, unused_owner_id, unused_package_id
    )
    (unused_folder / "requirements.txt").write_text(
        "idna==3.10\n", encoding="utf-8"
    )
    (folder / "requirements.txt").write_text("Pillow==12.0.0\n", encoding="utf-8")
    tool_owner_id = "56565656-5656-4656-8656-565656565656"
    tool_folder_name, tool_folder = write_tool_package(packages, tool_owner_id)
    (tool_folder / "requirements.txt").write_text("idna==3.10\n", encoding="utf-8")
    invalid_owner_id = "12121212-1212-4212-8212-121212121212"
    invalid_package_id = "34343434-3434-4434-8434-343434343434"
    invalid_folder_name, invalid_folder = write_package(
        packages, invalid_owner_id, invalid_package_id
    )
    (invalid_folder / "main.py").write_text("not valid Python (\n", encoding="utf-8")
    write_runtime_manifest(runtime_root)
    repository = FileConfigRepository(data_root)
    block_store = BlockStore(repository)
    block_store.save_block(
        "custom-middleware",
        owner_id,
        {
            "name": "middleware",
            "python_package": {"folder": folder_name},
        },
    )
    block_store.save_block(
        "custom-tool",
        tool_owner_id,
        {
            "name": "dependency tool",
            "python_package": {"folder": tool_folder_name},
        },
    )
    block_store.save_block(
        "custom-middleware",
        invalid_owner_id,
        {
            "name": "invalid middleware",
            "python_package": {"folder": invalid_folder_name},
        },
    )
    main_agent_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    AgentConfigStore(repository).save_item(
        "main_agents",
        main_agent_id,
        {
            "name": "Main",
            "capability_refs": [],
            "tool_refs": [{"tool_id": tool_owner_id}],
            "middleware_refs": [
                {"middleware_id": owner_id},
                {"middleware_id": invalid_owner_id},
            ],
            "subagents": [],
        },
    )
    repository.update_config(
        lambda config: config.setdefault("workflows", []).append(
            {
                "id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                "name": "Enabled workflow",
                "description": "Dependency reachability test.",
                "workflow_event_output_id": None,
                "enabled": True,
                "definition": {
                    "nodes": [
                        {
                            "id": "agent",
                            "type": "agent",
                            "config": {"main_agent_id": main_agent_id},
                        }
                    ],
                    "edges": [],
                },
                "layout": {},
            }
        )
    )
    fake_uv = tmp_path / "uv.exe"
    fake_uv.write_bytes(b"fake")
    monkeypatch.setattr(dependencies, "_ensure_uv", lambda *_args: fake_uv)
    monkeypatch.setattr(dependencies, "_core_constraints", lambda: ("pydantic==2.12.5",))
    calls: list[list[str]] = []

    def successful_install(arguments: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(arguments)
        target = Path(arguments[arguments.index("--target") + 1])
        (target / "PIL").mkdir()
        (target / "idna").mkdir()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dependencies.subprocess, "run", successful_install)
    prepare_windows_dependencies(data_root=data_root, runtime_root=runtime_root)
    output = capsys.readouterr().out
    assert "resource.error.pythonPackage.syntax" in output
    assert "Python requirements:" in output
    assert "Pillow==12.0.0" in output
    assert "idna==3.10" in output

    state = dependencies.load_dependency_state(runtime_root)
    assert state is not None
    assert state["status"] == "ready"
    assert set(state["records"]) == {
        f"python-package:{owner_id}",
        f"python-package:{tool_owner_id}",
    }
    assert f"python-package:{unused_owner_id}" not in state["records"]
    assert f"python-package:{invalid_owner_id}" not in state["records"]
    assert all(item["status"] == "ready" for item in state["records"].values())
    assert (dependencies.package_site_packages(runtime_root) / "PIL").is_dir()
    assert "--only-binary" in calls[0]
    assert "--quiet" not in calls[0]
    ready = scan_middleware_package(
        folder, owner_id=owner_id, runtime_root=runtime_root
    )
    assert ready["dependency_status"] == "ready"

    monkeypatch.setattr(
        dependencies.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )
    (folder / "requirements.txt").write_text("Pillow==13.0.0\n", encoding="utf-8")
    prepare_windows_dependencies(data_root=data_root, runtime_root=runtime_root)

    failed_state = dependencies.load_dependency_state(runtime_root)
    assert failed_state is not None
    assert failed_state["status"] == "failed"
    assert failed_state["records"][f"python-package:{owner_id}"]["status"] == "failed"
    assert (dependencies.package_site_packages(runtime_root) / "PIL").is_dir()
    failed = scan_middleware_package(
        folder, owner_id=owner_id, runtime_root=runtime_root
    )
    assert failed["dependency_status"] == "failed"
