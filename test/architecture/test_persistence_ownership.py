from __future__ import annotations

import ast
from pathlib import Path


SOURCE_ROOT = (
    Path(__file__).resolve().parents[2] / "server" / "src" / "agent_shell"
)
API_ROOT = SOURCE_ROOT / "api"

# Each entry is a semantic writer, a low-level primitive, or an explicitly
# temporary/runtime owner documented by the instance-data contract.
REGISTERED_WRITE_MODULES = {
    "configuration/bundles/archive.py",
    "configuration/bundles/assets.py",
    "configuration/bundles/exporting.py",
    "configuration/bundles/filesystem.py",
    "configuration/bundles/journal.py",
    "configuration/bundles/planning.py",
    "configuration/bundles/transactions.py",
    "configuration/repositories.py",
    "file_manager.py",
    "mcp/installation.py",
    "mcp/installation_npm.py",
    "mcp/installation_pypi.py",
    "python_packages/authoring.py",
    "python_packages/dependencies.py",
    "runtime/workflow_data.py",
    "runtime/windows_toolchains.py",
    "security_events.py",
    "settings.py",
    "skills/authoring.py",
    "storage/atomic_files.py",
    "storage/database.py",
    "storage/file_config.py",
    "storage/model_connections.py",
    "storage/mcp_connections.py",
    "storage/permissions.py",
    "storage/runtime_diagnostic_details.py",
}

PATH_WRITE_METHODS = {
    "mkdir",
    "rmdir",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
PATH_READ_METHODS = {"glob", "iterdir", "read_bytes", "read_text", "rglob"}
PHYSICAL_PATH_ATTRIBUTES = {
    "bindings_path",
    "components_root",
    "config_root",
    "data_root",
    "python_packages_root",
    "skill_packages_root",
    "system_path",
    "workflows_root",
}
OS_WRITE_FUNCTIONS = {"mkdir", "makedirs", "remove", "replace", "rmdir", "unlink"}
SHUTIL_WRITE_FUNCTIONS = {"copy", "copy2", "copytree", "move", "rmtree"}


def _qualified_name(node: ast.expr) -> tuple[str, ...]:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def _open_writes(node: ast.Call) -> bool:
    name = _qualified_name(node.func)
    if name not in {("open",), ("Path", "open")} and name[-1:] != ("open",):
        return False
    mode: ast.expr | None = node.args[1] if len(node.args) > 1 else None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(
        marker in mode.value for marker in "wax+"
    )


_SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _annotation_contains_path(node: ast.expr | None) -> bool:
    if node is None:
        return False
    return any(
        isinstance(item, (ast.Name, ast.Attribute))
        and _qualified_name(item)[-1:] == ("Path",)
        for item in ast.walk(node)
    )


def _scope_nodes(scope: ast.AST):
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, _SCOPES):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def _assigned_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {
            name
            for item in node.elts
            for name in _assigned_names(item)
        }
    return set()


def _is_path_expression(node: ast.expr, path_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in path_names
    if isinstance(node, ast.Call):
        name = _qualified_name(node.func)
        if name[-1:] == ("Path",):
            return True
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {"absolute", "expanduser", "relative_to", "resolve", "with_name", "with_suffix"}
            and _is_path_expression(node.func.value, path_names)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_expression(node.left, path_names)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        return _is_path_expression(node.value, path_names)
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
    ):
        return _is_path_expression(node.value.value, path_names)
    return False


def _scope_path_names(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = (
            [*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs]
            + ([scope.args.vararg] if scope.args.vararg is not None else [])
            + ([scope.args.kwarg] if scope.args.kwarg is not None else [])
        )
        names.update(
            argument.arg
            for argument in arguments
            if _annotation_contains_path(argument.annotation)
        )

    nodes = list(_scope_nodes(scope))
    for node in nodes:
        if (
            isinstance(node, ast.AnnAssign)
            and _annotation_contains_path(node.annotation)
        ):
            names.update(_assigned_names(node.target))

    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, (ast.For, ast.AsyncFor)):
                iterator = node.iter
                if (
                    isinstance(iterator, ast.Call)
                    and isinstance(iterator.func, ast.Attribute)
                    and iterator.func.attr in {"glob", "iterdir", "rglob"}
                    and _is_path_expression(iterator.func.value, names)
                ):
                    discovered = _assigned_names(node.target)
                    if not discovered.issubset(names):
                        names.update(discovered)
                        changed = True
                continue
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            if value is None or not _is_path_expression(value, names):
                continue
            discovered = {
                name for target in targets for name in _assigned_names(target)
            }
            if not discovered.issubset(names):
                names.update(discovered)
                changed = True
    return names


def _nearest_scope(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST:
    current = node
    while not isinstance(current, _SCOPES):
        current = parents[current]
    return current


def _path_mutation(node: ast.Call, path_names: set[str]) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"rename", "replace"}
        and _is_path_expression(node.func.value, path_names)
    )


def _zipfile_write(node: ast.Call) -> bool:
    name = _qualified_name(node.func)
    if name[-1:] != ("ZipFile",):
        return False
    mode: ast.expr | None = node.args[1] if len(node.args) > 1 else None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    return (
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and any(marker in mode.value for marker in "wax+")
    )


def _temporary_write(node: ast.Call) -> bool:
    return _qualified_name(node.func) in {
        ("tempfile", "NamedTemporaryFile"),
        ("tempfile", "TemporaryDirectory"),
        ("tempfile", "TemporaryFile"),
        ("tempfile", "mkdtemp"),
        ("tempfile", "mkstemp"),
    }


def _write_call_lines(source: str, *, filename: str = "<source>") -> list[int]:
    tree = ast.parse(source, filename=filename)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    scope_names: dict[ast.AST, set[str]] = {}
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_name(node.func)
        scope = _nearest_scope(node, parents)
        path_names = scope_names.setdefault(scope, _scope_path_names(scope))
        is_write = (
            (
                len(name) >= 2
                and name[-1] in PATH_WRITE_METHODS
                and isinstance(node.func, ast.Attribute)
            )
            or _path_mutation(node, path_names)
            or (len(name) >= 2 and name[-2] == "os" and name[-1] in OS_WRITE_FUNCTIONS)
            or (
                len(name) >= 2
                and name[-2] == "shutil"
                and name[-1] in SHUTIL_WRITE_FUNCTIONS
            )
            or name == ("sqlite3", "connect")
            or _open_writes(node)
            or _temporary_write(node)
            or _zipfile_write(node)
        )
        if is_write:
            lines.append(node.lineno)
    return sorted(set(lines))


def _write_calls(path: Path) -> list[int]:
    return _write_call_lines(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def _read_call_lines(source: str, *, filename: str = "<source>") -> list[int]:
    tree = ast.parse(source, filename=filename)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    scope_names: dict[ast.AST, set[str]] = {}
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        scope = _nearest_scope(node, parents)
        path_names = scope_names.setdefault(scope, _scope_path_names(scope))
        if (
            node.func.attr in PATH_READ_METHODS
            and _is_path_expression(node.func.value, path_names)
        ):
            lines.append(node.lineno)
            continue
        if node.func.attr != "open" or not _is_path_expression(
            node.func.value, path_names
        ):
            continue
        mode: ast.expr | None = node.args[0] if node.args else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if mode is None or (
            isinstance(mode, ast.Constant)
            and isinstance(mode.value, str)
            and not any(marker in mode.value for marker in "wax+")
        ):
            lines.append(node.lineno)
    return sorted(set(lines))


def _physical_path_capability_lines(
    source: str,
    *,
    filename: str = "<source>",
) -> list[int]:
    tree = ast.parse(source, filename=filename)
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in PHYSICAL_PATH_ATTRIBUTES
        }
    )


def test_path_detection_distinguishes_paths_from_same_named_services() -> None:
    source = """
import dataclasses
from dataclasses import replace
from pathlib import Path

def mutate(path: Path, value: str, files) -> None:
    path.replace(Path("target"))
    Path("source").replace("target")
    dataclasses.replace(object())
    replace(object())
    value.replace("a", "b")
    files.rename("a", "b")
    files.read_text("a")
    for child in path.iterdir():
        child.read_text()
"""

    assert _write_call_lines(source) == [7, 8]
    assert _read_call_lines(source) == [14, 15]
    assert _physical_path_capability_lines(
        "def leak(repository):\n    return repository.python_packages_root\n"
    ) == [2]


def test_production_write_calls_belong_to_registered_owner_modules() -> None:
    observed = {
        path.relative_to(SOURCE_ROOT).as_posix(): lines
        for path in SOURCE_ROOT.rglob("*.py")
        if (lines := _write_calls(path))
    }
    unregistered = {
        module: lines
        for module, lines in observed.items()
        if module not in REGISTERED_WRITE_MODULES
    }
    stale = REGISTERED_WRITE_MODULES.difference(observed)

    assert not unregistered, f"unregistered persistence writers: {unregistered}"
    assert not stale, f"stale persistence owner registrations: {sorted(stale)}"


def test_api_modules_do_not_perform_physical_persistence_crud() -> None:
    violations: dict[str, dict[str, list[int]]] = {}
    for path in API_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        reads = _read_call_lines(source, filename=str(path))
        writes = _write_call_lines(source, filename=str(path))
        path_capabilities = _physical_path_capability_lines(
            source,
            filename=str(path),
        )
        if reads or writes or path_capabilities:
            violations[path.relative_to(SOURCE_ROOT).as_posix()] = {
                "reads": reads,
                "writes": writes,
                "path_capabilities": path_capabilities,
            }

    assert not violations, f"API modules bypass persistence owners: {violations}"
