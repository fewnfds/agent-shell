from __future__ import annotations

from pathlib import Path
import sys

from agent_shell.python_packages.loader import PythonPackageLoader


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
