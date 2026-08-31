"""Generate THIRD_PARTY_NOTICES.md from the locked runtime and frontend graph.

Run with the repository development environment after `uv sync --frozen`.
The command is intentionally offline: versions come from lock files and
license metadata comes from the already-installed, version-checked wheels.
"""

from __future__ import annotations

import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import tomllib
from typing import Any


def _normalize(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _source_url(name: str, version: str) -> str:
    return f"https://pypi.org/project/{name}/{version}/"


def _license(dist: metadata.Distribution) -> str:
    expression = dist.metadata.get("License-Expression")
    if expression:
        return expression
    raw = (dist.metadata.get("License") or "").strip()
    if raw and "\n" not in raw and len(raw) <= 120:
        return raw
    return "NOASSERTION"


def _package_metadata(name: str, version: str) -> tuple[str, str]:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError as exc:
        raise SystemExit(f"locked package is not installed in this environment: {name}") from exc
    installed = dist.version
    if installed != version:
        raise SystemExit(
            f"installed package does not match uv.lock: {name} {installed} != {version}"
        )
    return _license(dist), _source_url(name, version)


def _runtime_packages(root: Path) -> list[tuple[str, str, str, str, str]]:
    lock = tomllib.loads((root / "server/uv.lock").read_text(encoding="utf-8"))
    packages = {
        item["name"]: item
        for item in lock["package"]
        if item["name"] != "agent-shell-server"
    }
    root_package = next(item for item in lock["package"] if item["name"] == "agent-shell-server")
    wanted: set[str] = set()
    pending = [item["name"] for item in root_package.get("dependencies", [])]
    while pending:
        name = pending.pop()
        if name in wanted:
            continue
        wanted.add(name)
        package = packages[name]
        pending.extend(item["name"] for item in package.get("dependencies", []))
    rows = []
    for name in sorted(wanted, key=_normalize):
        version = packages[name]["version"]
        license_name, source = _package_metadata(name, version)
        rows.append(("pypi", name, version, license_name, source))
    return rows


def _resolve_node_package(packages: dict[str, Any], importer: str, name: str) -> str:
    base = importer
    while True:
        candidate = f"{base + '/' if base else ''}node_modules/{name}"
        if candidate in packages:
            return candidate
        marker = "/node_modules/"
        index = base.rfind(marker)
        if index < 0:
            break
        base = base[:index]
    candidate = f"node_modules/{name}"
    if candidate in packages:
        return candidate
    raise SystemExit(f"frontend lock dependency cannot be resolved: {name} from {importer}")


def _frontend_packages(root: Path) -> list[tuple[str, str, str, str, str]]:
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    packages: dict[str, Any] = lock["packages"]
    seen: set[str] = set()

    def visit(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        package = packages[path]
        for name in package.get("dependencies", {}):
            visit(_resolve_node_package(packages, path, name))
        for name in package.get("optionalDependencies", {}):
            try:
                visit(_resolve_node_package(packages, path, name))
            except SystemExit:
                continue

    root_package = packages[""]
    for name in root_package.get("dependencies", {}):
        visit(_resolve_node_package(packages, "", name))

    rows = []
    for path in sorted(
        seen,
        key=lambda item: (
            _normalize(item.rsplit("node_modules/", 1)[-1]),
            item,
        ),
    ):
        package = packages[path]
        name = path.rsplit("node_modules/", 1)[-1]
        source = f"https://www.npmjs.com/package/{name}/v/{package['version']}"
        rows.append(("npm", name, package["version"], package.get("license", "NOASSERTION"), source))
    return rows


def _render(root: Path) -> str:
    rows = _frontend_packages(root) + _runtime_packages(root)
    runtime_lock = json.loads((root / "packaging/windows/runtime-lock.json").read_text(encoding="utf-8"))
    mcp_runtime_lock = json.loads((root / "packaging/windows/mcp-runtime-lock.json").read_text(encoding="utf-8"))
    rows.extend(
        [
            ("runtime", "CPython", runtime_lock["python"], "PSF-2.0", "https://www.python.org/"),
            ("runtime", "Node.js", mcp_runtime_lock["node"]["version"], "MIT", "https://nodejs.org/"),
            ("runtime", "uv", runtime_lock["uv"]["version"], "Apache-2.0 OR MIT", "https://github.com/astral-sh/uv"),
        ]
    )
    rows.sort(key=lambda row: (row[0], _normalize(row[1])))
    counts: dict[str, int] = {}
    for ecosystem, *_ in rows:
        counts[ecosystem] = counts.get(ecosystem, 0) + 1
    lines = [
        "# Third-party notices",
        "",
        "Agent Shell is licensed under the MIT License. This file is generated from the locked production frontend dependency closure, the non-dev `server/uv.lock` closure, `packaging/windows/runtime-lock.json`, and `packaging/windows/mcp-runtime-lock.json`.",
        f"Counts: npm {counts['npm']}, pypi {counts['pypi']}, runtime {counts['runtime']}. Run `server/.venv/Scripts/python.exe packaging/development/generate_third_party_notices.py` after changing a lock file.",
        "",
        "`Declared license` is the SPDX expression from package metadata when available; `NOASSERTION` means the upstream metadata did not provide a machine-readable expression. `Source` points to the versioned package or project page.",
        "",
        "| Ecosystem | Component | Version | Declared license | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(f"| {ecosystem} | {name} | `{version}` | {license_name} | {source} |" for ecosystem, name, version, license_name, source in rows)
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.project_root.resolve()
    (root / "THIRD_PARTY_NOTICES.md").write_text(_render(root), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
