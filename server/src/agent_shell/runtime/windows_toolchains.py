from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any
from urllib.request import urlopen
from uuid import uuid4
from zipfile import ZipFile


def _safe_extract_uv(archive: Path, destination: Path) -> Path:
    with ZipFile(archive) as bundle:
        members = bundle.infolist()
        for member in members:
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("The uv archive contains an unsafe path.")
        bundle.extractall(destination)
    candidates = list(destination.rglob("uv.exe"))
    if len(candidates) != 1:
        raise ValueError("The uv archive does not contain exactly one uv.exe.")
    return candidates[0]


def ensure_uv(runtime_root: Path, manifest: dict[str, Any]) -> Path:
    """Return the pinned software-owned uv executable, downloading it if absent."""

    bootstrap = runtime_root / "bootstrap"
    uv_path = bootstrap / "uv.exe"
    version_path = bootstrap / "uv-version.txt"
    expected_version = str(manifest.get("uv", ""))
    installed_version = (
        version_path.read_text(encoding="ascii").strip()
        if version_path.is_file()
        else ""
    )
    if uv_path.is_file() and installed_version == expected_version:
        return uv_path

    url = str(manifest.get("uv_url", ""))
    expected_hash = str(manifest.get("uv_sha256", "")).lower()
    if not expected_version or not url.startswith("https://") or len(expected_hash) != 64:
        raise ValueError("The Windows runtime manifest lacks the pinned uv download.")

    temporary_root = runtime_root / "tmp" / f"uv-toolchain-{uuid4().hex}"
    archive = temporary_root / "uv.zip"
    extracted = temporary_root / "extract"
    temporary_root.mkdir(parents=True)
    extracted.mkdir()
    try:
        digest = sha256()
        with urlopen(url) as response, archive.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                stream.write(chunk)
        if digest.hexdigest().lower() != expected_hash:
            raise ValueError("The uv download failed SHA-256 verification.")
        downloaded = _safe_extract_uv(archive, extracted)
        bootstrap.mkdir(parents=True, exist_ok=True)
        temporary_uv = bootstrap / f"uv.{uuid4().hex}.tmp"
        shutil.copy2(downloaded, temporary_uv)
        os.replace(temporary_uv, uv_path)
        version_path.write_text(expected_version, encoding="ascii")
        return uv_path
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


__all__ = ["ensure_uv"]
