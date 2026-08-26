from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from .app_support import make_client


def _repository_path(client) -> str:
    response = client.get(
        "/api/file-manager",
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
        root = client.get("/api/file-manager")
        created_directory = client.post(
            "/api/file-manager/directories",
            json={"path": "data/files/notes/drafts"},
        )
        created_file = client.post(
            "/api/file-manager/text-files",
            json={"path": "data/files/notes/drafts/idea.txt"},
        )
        client.post(
            "/api/file-manager/directories",
            json={"path": "data/files/notes/empty"},
        )
        opened = client.get(
            "/api/file-manager/text",
            params={"path": "data/files/notes/drafts/idea.txt"},
        )
        saved = client.put(
            "/api/file-manager/text",
            json={
                "path": "data/files/notes/drafts/idea.txt",
                "content": "第一版内容\n",
                "revision": opened.json()["revision"],
            },
        )
        listing = client.get(
            "/api/file-manager",
            params={"path": "data/files/notes/drafts"},
        )
        renamed = client.patch(
            "/api/file-manager",
            json={
                "path": "data/files/notes/drafts/idea.txt",
                "name": "final.txt",
            },
        )
        downloaded = client.get(
            "/api/file-manager/download",
            params={"path": "data/files/notes/drafts/final.txt"},
        )
        archived = client.get(
            "/api/file-manager/download",
            params={"path": "data/files/notes"},
        )
        deleted = client.delete(
            "/api/file-manager",
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
            "/api/file-manager",
            params={"path": repository_path},
        )
        config_text = client.get(
            "/api/file-manager/text",
            params={"path": f"{repository_path}/components/example/record.yaml"},
        )
        config_write = client.put(
            "/api/file-manager/text",
            json={
                "path": f"{repository_path}/components/example/record.yaml",
                "content": "name: bypassed\n",
                "revision": config_text.json()["revision"],
            },
        )
        config_create = client.post(
            "/api/file-manager/text-files",
            json={"path": f"{repository_path}/components/example/other.yaml"},
        )
        template_create = client.post(
            "/api/file-manager/text-files",
            json={"path": "data/templates/custom/example.yaml"},
        )
        template_open = client.get(
            "/api/file-manager/text",
            params={"path": "data/templates/custom/example.yaml"},
        )
        template_write = client.put(
            "/api/file-manager/text",
            json={
                "path": "data/templates/custom/example.yaml",
                "content": "enabled: true\n",
                "revision": template_open.json()["revision"],
            },
        )
        hidden = [
            client.get("/api/file-manager", params={"path": "data/config"}),
            client.get("/api/file-manager", params={"path": "data/state"}),
            client.get(
                "/api/file-manager/text",
                params={"path": f"{repository_path}/repository.json"},
            ),
            client.get(
                "/api/file-manager",
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


def test_file_manager_uses_the_configured_text_editor_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        current = client.get("/api/system/runtime-policy").json()
        update = {
            key: value
            for key, value in current.items()
            if key not in {"defaults", "minimums", "configurable"}
        }
        update["text_edit_bytes"] = 4
        assert client.put("/api/system/runtime-policy", json=update).status_code == 200
        assert client.post(
            "/api/file-manager/text-files",
            json={"path": "data/files/small.txt"},
        ).status_code == 200
        opened = client.get(
            "/api/file-manager/text", params={"path": "data/files/small.txt"}
        )
        saved = client.put(
            "/api/file-manager/text",
            json={
                "path": "data/files/small.txt",
                "content": "12345",
                "revision": opened.json()["revision"],
            },
        )

    assert saved.status_code == 413
    assert saved.json()["detail"]["message_args"] == {"max_bytes": 4}


def test_file_upload_streams_nested_paths_and_requires_explicit_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        path = "data/skills-template/outline/references/example.md"
        uploaded = client.put(
            "/api/file-manager/upload", params={"path": path}, content=b"first"
        )
        conflict = client.put(
            "/api/file-manager/upload", params={"path": path}, content=b"second"
        )
        replaced = client.put(
            "/api/file-manager/upload",
            params={"path": path, "overwrite": "true"},
            content=b"second",
        )
        downloaded = client.get(
            "/api/file-manager/download", params={"path": path}
        )

    assert uploaded.status_code == 200
    assert uploaded.json()["path"] == path
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "file_already_exists"
    assert replaced.status_code == 200
    assert downloaded.content == b"second"


def test_archive_preview_supports_mixed_selection_and_cleans_temporary_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.put(
            "/api/file-manager/upload",
            params={"path": "data/files/readme.txt"},
            content=b"root",
        )
        client.put(
            "/api/file-manager/upload",
            params={"path": "data/files/documents/nested/note.txt"},
            content=b"nested",
        )
        client.post(
            "/api/file-manager/directories",
            json={"path": "data/files/documents/empty"},
        )
        selection = {
            "paths": [
                "data/files/readme.txt",
                "data/files/documents",
                "data/files/documents",
            ]
        }
        preview = client.post("/api/file-manager/archive/preview", json=selection)
        archived = client.post("/api/file-manager/archive", json=selection)

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
            "/api/file-manager/upload", params={"path": path}, content=b"original"
        )
        opened = client.get("/api/file-manager/text", params={"path": path}).json()
        disk_path = tmp_path / "data" / "files" / "shared.txt"
        disk_path.write_text("external change", encoding="utf-8")
        conflict = client.put(
            "/api/file-manager/text",
            json={
                "path": path,
                "content": "stale edit",
                "revision": opened["revision"],
            },
        )
        client.put(
            "/api/file-manager/upload",
            params={"path": "data/files/binary.bin"},
            content=b"\xff\xfe",
        )
        binary = client.get(
            "/api/file-manager/text", params={"path": "data/files/binary.bin"}
        )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "text_file_revision_conflict"
    assert disk_path.read_text(encoding="utf-8") == "external change"
    assert binary.status_code == 415
    assert binary.json()["detail"]["code"] == "text_file_invalid_encoding"


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
            "/api/file-manager/upload", params={"path": path}, content=b"blocked"
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
            "/api/file-manager", params={"path": "data/files/linked"}
        )
        archived = client.post(
            "/api/file-manager/archive/preview",
            json={"paths": ["data/files/archive"]},
        )

    assert linked.status_code == 422
    assert linked.json()["detail"]["code"] == "file_link_unsupported"
    assert archived.status_code == 422
    assert archived.json()["detail"]["code"] == "file_link_unsupported"
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"
