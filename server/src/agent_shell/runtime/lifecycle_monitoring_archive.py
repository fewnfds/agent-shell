from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import re
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile


@dataclass(frozen=True, slots=True)
class LifecycleMonitoringArchive:
    filename: str
    content: bytes


def build_lifecycle_monitoring_archive(
    lifecycle_id: str,
    manifest: Mapping[str, Any],
    files: Mapping[str, Any],
) -> LifecycleMonitoringArchive:
    """Serialize one on-demand monitoring snapshot without reading runtime files."""

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for path, value in sorted(files.items()):
            archive.writestr(path, _json_bytes(value))
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", lifecycle_id)
    return LifecycleMonitoringArchive(
        filename=f"lifecycle-monitoring-{safe_id}.zip",
        content=output.getvalue(),
    )


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        default=str,
    ).encode("utf-8")


__all__ = [
    "LifecycleMonitoringArchive",
    "build_lifecycle_monitoring_archive",
]
