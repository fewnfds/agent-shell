from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from pathlib import Path
import threading
from zipfile import ZipFile

import pytest

from agent_shell.file_manager import FileManagerError, FileManagerService
import agent_shell.file_manager as file_manager_module

from .app_support import make_client


def _repository_path(client) -> str:
    response = client.get(
        "/agent-shell/api/file-manager",
        params={"path": "data/config_repos"},
    )
    assert response.status_code == 200, response.text
    repositories = response.json()["items"]
    assert len(repositories) == 1
    return repositories[0]["path"]


def test_file_manager_uses_real_data_paths_for_common_file_workflows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        root = client.get("/agent-shell/api/file-manager")
        created_directory = client.post(
            "/agent-shell/api/file-manager/directories",
            json={"path": "data/files/notes/drafts"},
        )
        created_file = client.post(
            "/agent-shell/api/file-manager/text-files",
            json={"path": "data/files/notes/drafts/idea.txt"},
        )
        client.post(
            "/agent-shell/api/file-manager/directories",
            json={"path": "data/files/notes/empty"},
        )
        opened = client.get(
            "/agent-shell/api/file-manager/text",
            params={"path": "data/files/notes/drafts/idea.txt"},
        )
        saved = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": "data/files/notes/drafts/idea.txt",
                "content": "第一版内容\n",
                "revision": opened.json()["revision"],
            },
        )
        listing = client.get(
            "/agent-shell/api/file-manager",
            params={"path": "data/files/notes/drafts"},
        )
        renamed = client.patch(
            "/agent-shell/api/file-manager",
            json={
                "path": "data/files/notes/drafts/idea.txt",
                "name": "final.txt",
            },
        )
        downloaded = client.get(
            "/agent-shell/api/file-manager/download",
            params={"path": "data/files/notes/drafts/final.txt"},
        )
        archived = client.get(
            "/agent-shell/api/file-manager/download",
            params={"path": "data/files/notes"},
        )
        deleted = client.delete(
            "/agent-shell/api/file-manager",
            params={"path": "data/files/notes"},
        )

    assert root.status_code == 200
    assert root.json()["path"] == "data"
    assert [item["name"] for item in root.json()["items"]] == [
        "config_repos",
        "files",
        "skills-template",
        "templates",
    ]
    assert created_directory.json() == {
        "path": "data/files/notes/drafts",
        "kind": "directory",
    }
    assert created_file.status_code == 200
    assert opened.json()["content"] == ""
    assert opened.json()["capabilities"]["write"] is True
    assert saved.status_code == 200
    assert saved.json()["revision"] != opened.json()["revision"]
    assert [(item["name"], item["kind"]) for item in listing.json()["items"]] == [
        ("idea.txt", "file")
    ]
    assert renamed.json()["path"] == "data/files/notes/drafts/final.txt"
    assert downloaded.content == "第一版内容\n".encode()
    assert 'filename="final.txt"' in downloaded.headers["content-disposition"]
    assert archived.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archived.content)) as archive:
        assert set(archive.namelist()) == {
            "notes/",
            "notes/drafts/",
            "notes/drafts/final.txt",
            "notes/empty/",
        }
    assert deleted.json() == {"path": "data/files/notes", "deleted": True}


def test_file_manager_filters_hidden_data_and_enforces_root_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        repository_path = _repository_path(client)
        repository_name = repository_path.rsplit("/", 1)[-1]
        repository_root = tmp_path / "data" / "config_repos" / repository_name
        config_file = repository_root / "components" / "example" / "record.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("name: Managed\n", encoding="utf-8")

        repository = client.get(
            "/agent-shell/api/file-manager",
            params={"path": repository_path},
        )
        config_text = client.get(
            "/agent-shell/api/file-manager/text",
            params={"path": f"{repository_path}/components/example/record.yaml"},
        )
        config_write = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": f"{repository_path}/components/example/record.yaml",
                "content": "name: bypassed\n",
                "revision": config_text.json()["revision"],
            },
        )
        config_create = client.post(
            "/agent-shell/api/file-manager/text-files",
            json={"path": f"{repository_path}/components/example/other.yaml"},
        )
        template_create = client.post(
            "/agent-shell/api/file-manager/text-files",
            json={"path": "data/templates/custom/example.yaml"},
        )
        template_open = client.get(
            "/agent-shell/api/file-manager/text",
            params={"path": "data/templates/custom/example.yaml"},
        )
        template_write = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": "data/templates/custom/example.yaml",
                "content": "enabled: true\n",
                "revision": template_open.json()["revision"],
            },
        )
        hidden = [
            client.get("/agent-shell/api/file-manager", params={"path": "data/config"}),
            client.get("/agent-shell/api/file-manager", params={"path": "data/state"}),
            client.get(
                "/agent-shell/api/file-manager/text",
                params={"path": f"{repository_path}/repository.json"},
            ),
            client.get(
                "/agent-shell/api/file-manager",
                params={"path": f"{repository_path}/configuration_imports"},
            ),
        ]

    assert [item["name"] for item in repository.json()["items"]] == [
        "agents",
        "components",
        "python_packages",
        "skill_packages",
        "workflows",
    ]
    assert config_text.status_code == 200
    assert config_text.json()["capabilities"]["read"] is True
    assert config_text.json()["capabilities"]["write"] is False
    assert config_write.status_code == 403
    assert config_write.json()["detail"]["code"] == "file_operation_denied"
    assert config_create.status_code == 403
    assert config_file.read_text(encoding="utf-8") == "name: Managed\n"
    assert template_create.status_code == 200
    assert template_write.status_code == 200
    assert (tmp_path / "data" / "templates" / "custom" / "example.yaml").read_text(
        encoding="utf-8"
    ) == "enabled: true\n"
    assert all(response.status_code == 404 for response in hidden)


def test_file_upload_streams_nested_paths_and_requires_explicit_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        path = "data/skills-template/outline/references/example.md"
        uploaded = client.put(
            "/agent-shell/api/file-manager/upload", params={"path": path}, content=b"first"
        )
        conflict = client.put(
            "/agent-shell/api/file-manager/upload", params={"path": path}, content=b"second"
        )
        replaced = client.put(
            "/agent-shell/api/file-manager/upload",
            params={"path": path, "overwrite": "true"},
            content=b"second",
        )
        downloaded = client.get(
            "/agent-shell/api/file-manager/download", params={"path": path}
        )

    assert uploaded.status_code == 200
    assert uploaded.json()["path"] == path
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "file_already_exists"
    assert replaced.status_code == 200
    assert downloaded.content == b"second"


@pytest.mark.parametrize("overwrite", [False, True])
def test_file_upload_respects_overwrite_when_another_upload_finishes_first(
    tmp_path: Path, overwrite: bool
) -> None:
    data_root = tmp_path / "data"
    target = data_root / "files" / "shared.txt"
    target.parent.mkdir(parents=True)
    files = FileManagerService(data_root, tmp_path / "temporary")

    async def upload_in_order() -> None:
        paused = asyncio.Event()
        resume = asyncio.Event()

        async def slow_chunks():
            yield b"slow-"
            paused.set()
            await resume.wait()
            yield b"upload"

        async def fast_chunks():
            yield b"fast-"
            yield b"upload"

        slow_upload = asyncio.create_task(
            files.upload("data/files/shared.txt", slow_chunks(), overwrite=overwrite)
        )
        await paused.wait()
        try:
            assert not target.exists()
            completed = await files.upload(
                "data/files/shared.txt", fast_chunks(), overwrite=False
            )
            assert completed == {
                "path": "data/files/shared.txt",
                "kind": "file",
                "size": len(b"fast-upload"),
            }
            assert target.read_bytes() == b"fast-upload"
        finally:
            resume.set()

        if overwrite:
            result = await slow_upload
            assert result["size"] == len(b"slow-upload")
        else:
            with pytest.raises(FileManagerError) as conflict:
                await slow_upload
            assert conflict.value.status_code == 409
            assert conflict.value.code == "file_already_exists"

        assert target.read_bytes() == (b"slow-upload" if overwrite else b"fast-upload")
        assert list(target.parent.iterdir()) == [target]

    asyncio.run(upload_in_order())


def test_archive_preview_supports_mixed_selection_and_cleans_temporary_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.put(
            "/agent-shell/api/file-manager/upload",
            params={"path": "data/files/readme.txt"},
            content=b"root",
        )
        client.put(
            "/agent-shell/api/file-manager/upload",
            params={"path": "data/files/documents/nested/note.txt"},
            content=b"nested",
        )
        client.post(
            "/agent-shell/api/file-manager/directories",
            json={"path": "data/files/documents/empty"},
        )
        selection = {
            "paths": [
                "data/files/readme.txt",
                "data/files/documents",
                "data/files/documents",
            ]
        }
        preview = client.post("/agent-shell/api/file-manager/archive/preview", json=selection)
        archived = client.post("/agent-shell/api/file-manager/archive", json=selection)

    assert preview.json() == {
        "total_size": 10,
        "file_count": 2,
        "directory_count": 3,
    }
    assert archived.status_code == 200
    with ZipFile(BytesIO(archived.content)) as archive:
        assert set(archive.namelist()) == {
            "readme.txt",
            "documents/",
            "documents/nested/",
            "documents/nested/note.txt",
            "documents/empty/",
        }
    assert not list((tmp_path / "runtime" / "tmp").glob("*.zip"))


def test_text_save_detects_external_changes_and_rejects_binary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        path = "data/files/shared.txt"
        client.put(
            "/agent-shell/api/file-manager/upload", params={"path": path}, content=b"original"
        )
        opened = client.get("/agent-shell/api/file-manager/text", params={"path": path}).json()
        disk_path = tmp_path / "data" / "files" / "shared.txt"
        disk_path.write_text("external change", encoding="utf-8")
        conflict = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": path,
                "content": "stale edit",
                "revision": opened["revision"],
            },
        )
        client.put(
            "/agent-shell/api/file-manager/upload",
            params={"path": "data/files/binary.bin"},
            content=b"\xff\xfe",
        )
        binary = client.get(
            "/agent-shell/api/file-manager/text", params={"path": "data/files/binary.bin"}
        )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "text_file_revision_conflict"
    assert disk_path.read_text(encoding="utf-8") == "external change"
    assert binary.status_code == 415
    assert binary.json()["detail"]["code"] == "text_file_invalid_encoding"


@pytest.mark.parametrize("later_operation", ["save", "upload"])
def test_text_save_preserves_concurrent_file_manager_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    later_operation: str,
) -> None:
    data_root = tmp_path / "data"
    target = data_root / "files" / "shared.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    files = FileManagerService(data_root, tmp_path / "temporary")
    revision = files.read_text("data/files/shared.txt")["revision"]
    first_ready = threading.Event()
    release_first = threading.Event()
    later_started = threading.Event()
    later_finished = threading.Event()
    original_write = file_manager_module.write_bytes_atomic

    def pause_first_write(path: Path, content: bytes, **kwargs) -> None:
        if path == target and content == b"first edit":
            first_ready.set()
            assert release_first.wait(timeout=5)
        original_write(path, content, **kwargs)

    monkeypatch.setattr(file_manager_module, "write_bytes_atomic", pause_first_write)

    def save(content: str):
        try:
            return files.save_text("data/files/shared.txt", content, revision)
        except FileManagerError as exc:
            return exc

    def later_change():
        later_started.set()
        try:
            if later_operation == "save":
                return save("second edit")

            async def chunks():
                yield b"uploaded content"

            return asyncio.run(
                files.upload("data/files/shared.txt", chunks(), overwrite=True)
            )
        finally:
            later_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(save, "first edit")
        assert first_ready.wait(timeout=5)
        later = executor.submit(later_change)
        try:
            assert later_started.wait(timeout=5)
            # Allow the competing command to finish if it can. The accepted
            # outcomes below depend on file contents and revisions, not locks.
            later_finished.wait(timeout=0.2)
        finally:
            release_first.set()
        first_result = first.result(timeout=5)
        later_result = later.result(timeout=5)

    if later_operation == "save":
        results = [first_result, later_result]
        errors = [result for result in results if isinstance(result, FileManagerError)]
        assert len(errors) == 1
        assert errors[0].status_code == 409
        assert errors[0].code == "text_file_revision_conflict"
        successful_index = next(
            index for index, result in enumerate(results)
            if not isinstance(result, FileManagerError)
        )
        assert target.read_text(encoding="utf-8") == ["first edit", "second edit"][successful_index]
    else:
        assert not isinstance(later_result, FileManagerError)
        assert target.read_bytes() == b"uploaded content"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize(
    "path",
    [
        "outside.txt",
        "data/../outside.txt",
        "/data/files/absolute.txt",
        "data/files/nested\\escape.txt",
        "C:/data/files/drive.txt",
    ],
)
def test_file_manager_rejects_noncanonical_or_out_of_root_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.put(
            "/agent-shell/api/file-manager/upload", params={"path": path}, content=b"blocked"
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "file_path_invalid"
    assert not (tmp_path / "outside.txt").exists()


def test_file_manager_rejects_links_in_visible_and_archived_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    with make_client(tmp_path, monkeypatch) as client:
        link = tmp_path / "data" / "files" / "linked"
        archive_directory = tmp_path / "data" / "files" / "archive"
        archive_directory.mkdir()
        nested_link = archive_directory / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
            os.symlink(outside, nested_link, target_is_directory=True)
        except OSError:
            pytest.skip("This Windows account cannot create symbolic links.")
        linked = client.get(
            "/agent-shell/api/file-manager", params={"path": "data/files/linked"}
        )
        archived = client.post(
            "/agent-shell/api/file-manager/archive/preview",
            json={"paths": ["data/files/archive"]},
        )

    assert linked.status_code == 422
    assert linked.json()["detail"]["code"] == "file_link_unsupported"
    assert archived.status_code == 422
    assert archived.json()["detail"]["code"] == "file_link_unsupported"
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"
