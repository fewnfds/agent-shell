from __future__ import annotations

import ast


def validate_module_function(source: str, name: str, *, asynchronous: bool) -> None:
    try:
        tree = ast.parse(source, filename=f"{name}.py")
    except SyntaxError as exc:
        raise ValueError(f"{name} source contains invalid Python") from exc
    expected = ast.AsyncFunctionDef if asynchronous else ast.FunctionDef
    opposite = ast.FunctionDef if asynchronous else ast.AsyncFunctionDef
    functions = [
        node for node in tree.body if isinstance(node, expected) and node.name == name
    ]
    if any(isinstance(node, opposite) and node.name == name for node in tree.body):
        kind = "asynchronous" if asynchronous else "synchronous"
        raise ValueError(f"{name} must be an {kind} function")
    if len(functions) != 1:
        raise ValueError(f"source must define exactly one module-level {name}")


__all__ = ["validate_module_function"]
