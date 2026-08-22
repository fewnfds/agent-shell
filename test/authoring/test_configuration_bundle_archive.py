from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zlib
from zipfile import ZipFile

import pytest

from agent_shell.configuration.bundles.archive import (
    BundleArchiveError,
    ParsedBundle,
    build_bundle,
    canonical_json_bytes,
    canonical_tree_sha256,
    materialize_files,
    parse_bundle,
)
from agent_shell.configuration.bundles.assets import materialize_package_assets
from agent_shell.configuration.bundles.contracts import (
    BundleManifest,
    BundleRecord,
    BundleRoot,
    PythonPackageAsset,
    SkillPackageAsset,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"


def _manifest(*, skill: bool = False) -> tuple[BundleManifest, dict[str, bytes]]:
    files: dict[str, bytes] = {}
    assets = []
    payload: dict[str, object]
    if skill:
        content = (
            b"---\nname: outline\ndescription: Build an outline.\n---\n\nSteps.\n"
        )
        tree = {"outline/SKILL.md": content}
        files = {f"assets/skill-packages/{SOURCE_ID}/outline/SKILL.md": content}
        assets = [
            SkillPackageAsset(
                kind="skill-package",
                owner_source_id=SOURCE_ID,
                path=f"assets/skill-packages/{SOURCE_ID}/",
                sha256=canonical_tree_sha256(tree),
            )
        ]
        payload = {
            "skill_package": {"folder": SOURCE_ID},
            "system_prompt_enabled": True,
            "instruction_override": None,
        }
        component_type = "skill"
    else:
        payload = {"system_prompt": "Be precise."}
        component_type = "system-prompt"
    root = BundleRoot(kind="component", type=component_type, source_id=SOURCE_ID)
    return (
        BundleManifest(
            source_application_version="0.2.0",
            root=root,
            records=[
                BundleRecord(
                    kind="component",
                    type=component_type,
                    source_id=SOURCE_ID,
                    name="Portable configuration",
                    payload=payload,
                )
            ],
            assets=assets,
        ),
        files,
    )


def _rewrite_entry(bundle: bytes, name: str, content: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(bundle)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(
                info,
                content if info.filename == name else source.read(info),
            )
    return output.getvalue()


def test_bundle_archive_is_deterministic_and_hashes_canonical_content() -> None:
    manifest, files = _manifest(skill=True)

    first = build_bundle(manifest, files)
    second = build_bundle(manifest, files)
    parsed = parse_bundle(first)

    assert first == second
    assert parsed.bundle_sha256 == sha256(first).hexdigest()
    assert parsed.manifest_sha256 == sha256(
        canonical_json_bytes(manifest.model_dump(mode="json", by_alias=True))
    ).hexdigest()
    assert parsed.manifest == manifest


def test_bundle_archive_rejects_path_traversal_unknown_version_and_asset_tampering() -> None:
    manifest, files = _manifest(skill=True)
    bundle = build_bundle(manifest, files)

    unsafe = BytesIO(bundle)
    with ZipFile(unsafe, "a") as archive:
        archive.writestr("../outside.txt", b"outside")
    with pytest.raises(BundleArchiveError, match="unsafe segment"):
        parse_bundle(unsafe.getvalue())

    conflicting = BytesIO(bundle)
    with ZipFile(conflicting, "a") as archive:
        prefix = f"assets/skill-packages/{SOURCE_ID}/outline/"
        archive.writestr(f"{prefix}nested", b"file")
        archive.writestr(f"{prefix}nested/child.txt", b"child")
    with pytest.raises(BundleArchiveError, match="files and directories"):
        parse_bundle(conflicting.getvalue())

    raw_manifest = manifest.model_dump(mode="json", by_alias=True)
    raw_manifest["format_version"] = 1
    unknown_version = _rewrite_entry(
        bundle,
        "manifest.json",
        canonical_json_bytes(raw_manifest),
    )
    with pytest.raises(BundleArchiveError, match="current contract"):
        parse_bundle(unknown_version)

    raw_manifest = manifest.model_dump(mode="json", by_alias=True)
    raw_manifest["root"]["type"] = "filesystem-permissions"
    mismatched_root_type = _rewrite_entry(
        bundle,
        "manifest.json",
        canonical_json_bytes(raw_manifest),
    )
    with pytest.raises(BundleArchiveError, match="current contract"):
        parse_bundle(mismatched_root_type)

    tampered = _rewrite_entry(
        bundle,
        f"assets/skill-packages/{SOURCE_ID}/outline/SKILL.md",
        b"different",
    )
    with pytest.raises(BundleArchiveError, match="hash"):
        parse_bundle(tampered)


def test_bundle_archive_classifies_corrupt_deflate_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, files = _manifest()
    bundle = build_bundle(manifest, files)

    def fail_read(*_args, **_kwargs):
        raise zlib.error("corrupt deflate data")

    monkeypatch.setattr(
        "agent_shell.configuration.bundles.archive.ZipFile.read",
        fail_read,
    )

    with pytest.raises(BundleArchiveError, match="readable ZIP archive"):
        parse_bundle(bundle)


@pytest.mark.parametrize(
    "path",
    [
        "asset/control\x01.txt",
        "asset/tab\t.txt",
        'asset/quote".txt',
        "asset/star*.txt",
        "asset/less<.txt",
        "asset/greater>.txt",
        "asset/pipe|.txt",
        "asset/question?.txt",
    ],
)
def test_bundle_materialization_rejects_windows_invalid_paths_before_writing(
    tmp_path: Path,
    path: str,
) -> None:
    destination = tmp_path / "destination"

    with pytest.raises(BundleArchiveError, match="unsafe segment"):
        materialize_files(destination, {path: b"content"})

    assert not destination.exists()


def test_python_package_requirements_must_use_utf8(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _files = _manifest()
    prefix = f"assets/python-packages/{SOURCE_ID}/"
    asset = PythonPackageAsset(
        kind="python-package",
        owner_source_id=SOURCE_ID,
        path=prefix,
        sha256="0" * 64,
    )
    parsed = ParsedBundle(
        manifest=manifest,
        files={
            f"{prefix}package.json": b"{}",
            f"{prefix}requirements.txt": b"\xff",
        },
        bundle_sha256="0" * 64,
        manifest_sha256="0" * 64,
    )
    monkeypatch.setattr(
        "agent_shell.configuration.bundles.assets.scan_python_package",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(BundleArchiveError, match="requirements.txt must use UTF-8"):
        materialize_package_assets(
            parsed,
            {SOURCE_ID: asset},
            {SOURCE_ID: "custom-tool"},
            {SOURCE_ID: "22222222-2222-4222-8222-222222222222"},
            tmp_path / "packages",
            runtime_root=tmp_path / "runtime",
        )
