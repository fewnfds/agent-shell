from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import stat
from typing import Any
import zlib
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from pydantic import ValidationError

from agent_shell.configuration.bundles.contracts import BundleManifest, SkillPackageAsset


_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID_FILENAME_CHARACTERS = frozenset('\"*<>?|')


def is_windows_reserved_name(value: str) -> bool:
    return value.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES


class BundleArchiveError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedBundle:
    manifest: BundleManifest
    files: dict[str, bytes]
    bundle_sha256: str
    manifest_sha256: str

    def asset_files(self, prefix: str) -> dict[str, bytes]:
        return {
            path.removeprefix(prefix): content
            for path, content in self.files.items()
            if path.startswith(prefix)
        }


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_tree_sha256(files: dict[str, bytes]) -> str:
    digest = sha256()
    for path, content in sorted(files.items()):
        encoded = path.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _validate_relative_path(value: str, *, directory: bool = False) -> str:
    normalized = value[:-1] if directory and value.endswith("/") else value
    if (
        not normalized
        or "\\" in normalized
        or "\x00" in normalized
        or ":" in normalized
    ):
        raise BundleArchiveError("bundle paths must be normalized relative POSIX paths")
    path = PurePosixPath(normalized)
    if path.is_absolute() or path.as_posix() != normalized:
        raise BundleArchiveError("bundle paths must be normalized relative POSIX paths")
    for segment in path.parts:
        if (
            segment in {"", ".", ".."}
            or segment.endswith((" ", "."))
            or any(ord(character) < 32 for character in segment)
            or any(
                character in _WINDOWS_INVALID_FILENAME_CHARACTERS
                for character in segment
            )
        ):
            raise BundleArchiveError("bundle paths contain an unsafe segment")
        if is_windows_reserved_name(segment):
            raise BundleArchiveError("bundle paths contain a reserved filesystem name")
    return value


def snapshot_directory(
    folder: Path,
    *,
    exclude_python_runtime: bool = False,
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if not folder.is_dir() or _is_link(folder):
        raise BundleArchiveError(f"asset folder is unavailable: {folder.name}")
    for path in sorted(folder.rglob("*")):
        if _is_link(path):
            raise BundleArchiveError("asset folders may not contain links or reparse points")
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        if exclude_python_runtime and (
            "__pycache__" in PurePosixPath(relative).parts
            or path.suffix.casefold() == ".pyc"
        ):
            continue
        _validate_relative_path(relative)
        files[relative] = path.read_bytes()
    return files


def _is_link(path: Path) -> bool:
    metadata = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def build_bundle(
    manifest: BundleManifest,
    asset_files: dict[str, bytes],
) -> bytes:
    manifest_bytes = canonical_json_bytes(
        manifest.model_dump(mode="json", by_alias=True)
    )
    entries = {"manifest.json": manifest_bytes, **asset_files}
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
        for path, content in sorted(entries.items()):
            _validate_relative_path(path)
            info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, content)
    return output.getvalue()


def parse_bundle(content: bytes) -> ParsedBundle:
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            names: set[str] = set()
            casefold_names: set[str] = set()
            files: dict[str, bytes] = {}
            for info in infos:
                name = info.filename
                _validate_relative_path(name, directory=info.is_dir())
                if info.is_dir():
                    raise BundleArchiveError(
                        "bundle archives must not contain directory entries"
                    )
                folded = name.casefold()
                if name in names or folded in casefold_names:
                    raise BundleArchiveError("bundle archive paths must be unique")
                names.add(name)
                casefold_names.add(folded)
                unix_mode = info.external_attr >> 16
                unix_file_type = stat.S_IFMT(unix_mode)
                dos_attributes = info.external_attr & 0xFFFF
                if (
                    stat.S_ISLNK(unix_mode)
                    or (unix_file_type and not stat.S_ISREG(unix_mode))
                    or dos_attributes & 0x400
                ):
                    raise BundleArchiveError(
                        "bundle archive may not contain links or reparse points"
                    )
                files[name] = archive.read(info)
            for name in names:
                parts = PurePosixPath(name).parts
                if any(
                    "/".join(parts[:index]) in names
                    for index in range(1, len(parts))
                ):
                    raise BundleArchiveError(
                        "bundle archive paths cannot be both files and directories"
                    )
    except (
        BadZipFile,
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zlib.error,
    ) as exc:
        raise BundleArchiveError("configuration bundle is not a readable ZIP archive") from exc

    manifest_bytes = files.get("manifest.json")
    if manifest_bytes is None:
        raise BundleArchiveError("configuration bundle is missing manifest.json")
    try:
        raw_manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
        manifest = BundleManifest.model_validate(raw_manifest)
    except (UnicodeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        raise BundleArchiveError(
            "configuration bundle manifest does not satisfy the current contract"
        ) from exc
    if manifest_bytes != canonical_json_bytes(
        manifest.model_dump(mode="json", by_alias=True)
    ):
        raise BundleArchiveError("configuration bundle manifest must use canonical JSON")

    expected_paths = {"manifest.json"}
    for asset in manifest.assets:
        prefix = _validate_relative_path(asset.path, directory=True)
        if not prefix.endswith("/"):
            raise BundleArchiveError("bundle asset paths must name directories")
        matches = {
            path.removeprefix(prefix): body
            for path, body in files.items()
            if path.startswith(prefix)
        }
        if (not matches and not isinstance(asset, SkillPackageAsset)) or any(
            not path for path in matches
        ):
            raise BundleArchiveError("bundle asset directory is empty or invalid")
        if canonical_tree_sha256(matches) != asset.sha256:
            raise BundleArchiveError("bundle asset hash does not match its manifest")
        expected_paths.update(prefix + path for path in matches)
    if set(files) != expected_paths:
        raise BundleArchiveError("bundle archive contains undeclared files")

    return ParsedBundle(
        manifest=manifest,
        files=files,
        bundle_sha256=sha256(content).hexdigest(),
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
    )


def materialize_files(folder: Path, files: dict[str, bytes]) -> None:
    validated = [
        (PurePosixPath(_validate_relative_path(relative)), content)
        for relative, content in sorted(files.items())
    ]
    folder.mkdir(parents=True, exist_ok=False)
    for relative, content in validated:
        target = folder.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


__all__ = [
    "BundleArchiveError",
    "ParsedBundle",
    "build_bundle",
    "canonical_json_bytes",
    "canonical_tree_sha256",
    "is_windows_reserved_name",
    "materialize_files",
    "parse_bundle",
    "snapshot_directory",
]
