from __future__ import annotations

from collections.abc import Iterable, Mapping

from pydantic import ValidationError

from agent_shell.localization import MessageArg
from agent_shell.redaction import redact_for_boundary
from agent_shell.validation.models import ValidationIssue, ValidationReport


_ERROR_CODES = {
    "extra_forbidden": "contract.unknown_field",
    "missing": "contract.field_required",
    "string_too_short": "contract.text_too_short",
    "string_too_long": "contract.text_too_long",
    "string_pattern_mismatch": "contract.invalid_format",
    "value_error": "contract.invalid_value",
    "too_short": "contract.collection_too_short",
    "too_long": "contract.collection_too_long",
    "literal_error": "contract.invalid_choice",
    "enum": "contract.invalid_choice",
    "finite_number": "contract.number_not_finite",
    "greater_than": "contract.number_greater_than",
    "greater_than_equal": "contract.number_at_least",
    "less_than": "contract.number_less_than",
    "less_than_equal": "contract.number_at_most",
    "int_type": "contract.integer_required",
    "int_parsing": "contract.integer_required",
    "float_type": "contract.number_required",
    "float_parsing": "contract.number_required",
    "bool_type": "contract.boolean_required",
    "bool_parsing": "contract.boolean_required",
    "string_type": "contract.text_required",
    "list_type": "contract.collection_required",
    "tuple_type": "contract.collection_required",
    "set_type": "contract.collection_required",
    "dict_type": "contract.object_required",
    "mapping_type": "contract.object_required",
    "model_type": "contract.object_required",
    "model_attributes_type": "contract.object_required",
}

_ERROR_MESSAGE_KEYS = {
    "extra_forbidden": "validation.issue.contract.unknownField",
    "missing": "validation.issue.contract.fieldRequired",
    "string_too_short": "validation.issue.contract.textTooShort",
    "string_too_long": "validation.issue.contract.textTooLong",
    "string_pattern_mismatch": "validation.issue.contract.invalidFormat",
    "value_error": "validation.issue.contract.invalidValue",
    "too_short": "validation.issue.contract.collectionTooShort",
    "too_long": "validation.issue.contract.collectionTooLong",
    "literal_error": "validation.issue.contract.invalidChoice",
    "enum": "validation.issue.contract.invalidChoice",
    "finite_number": "validation.issue.contract.numberNotFinite",
    "greater_than": "validation.issue.contract.numberGreaterThan",
    "greater_than_equal": "validation.issue.contract.numberAtLeast",
    "less_than": "validation.issue.contract.numberLessThan",
    "less_than_equal": "validation.issue.contract.numberAtMost",
    "int_type": "validation.issue.contract.integerRequired",
    "int_parsing": "validation.issue.contract.integerRequired",
    "float_type": "validation.issue.contract.numberRequired",
    "float_parsing": "validation.issue.contract.numberRequired",
    "bool_type": "validation.issue.contract.booleanRequired",
    "bool_parsing": "validation.issue.contract.booleanRequired",
    "string_type": "validation.issue.contract.textRequired",
    "list_type": "validation.issue.contract.collectionRequired",
    "tuple_type": "validation.issue.contract.collectionRequired",
    "set_type": "validation.issue.contract.collectionRequired",
    "dict_type": "validation.issue.contract.objectRequired",
    "mapping_type": "validation.issue.contract.objectRequired",
    "model_type": "validation.issue.contract.objectRequired",
    "model_attributes_type": "validation.issue.contract.objectRequired",
}

_ERROR_ARG_KEYS = {
    "string_too_short": ("min_length",),
    "string_too_long": ("max_length",),
    "too_short": ("min_length",),
    "too_long": ("max_length",),
    "greater_than": ("gt",),
    "greater_than_equal": ("ge",),
    "less_than": ("lt",),
    "less_than_equal": ("le",),
    "literal_error": ("expected",),
    "enum": ("expected",),
}


def _specific_contract_identity(
    *,
    error_type: str,
    path: str,
    scope: str,
    owner_type: str,
    detail: str,
) -> tuple[str, str] | None:
    """Return a stable, user-facing identity for well-known format rules.

    Pydantic reports all regex failures as ``string_pattern_mismatch``.  The
    pattern itself is an implementation detail, so map the few current
    contracts with an explicit user-facing rule instead of exposing a regex.
    """
    if (
        error_type == "string_pattern_mismatch"
        and scope == "subagent"
        and path == "name"
    ):
        return (
            "contract.subagent_name_format_invalid",
            "validation.issue.contract.subagentNameFormatInvalid",
        )
    if (
        error_type in {"string_pattern_mismatch", "value_error"}
        and owner_type
        in {
            "custom-middleware",
            "command",
            "agent-event-output",
            "workflow-event-output",
        }
        and path == "python_package.folder"
    ):
        return (
            "contract.python_package_folder_format_invalid",
            "validation.issue.contract.pythonPackageFolderFormatInvalid",
        )
    return None


_ERROR_MESSAGES = {
    "extra_forbidden": "The field is not accepted by the current contract.",
    "missing": "A required field is missing.",
    "string_too_short": "The text is shorter than the allowed range.",
    "string_too_long": "The text is longer than the allowed range.",
    "string_pattern_mismatch": "The value does not match the allowed format.",
    "too_short": "The collection contains too few items.",
    "too_long": "The collection contains too many items.",
    "literal_error": "The value is not one of the allowed choices.",
    "enum": "The value is not one of the allowed choices.",
    "finite_number": "The value must be a finite number.",
    "greater_than": "The value is not greater than the required limit.",
    "greater_than_equal": "The value is below the required minimum.",
    "less_than": "The value is not less than the required limit.",
    "less_than_equal": "The value exceeds the allowed maximum.",
    "int_type": "The value must be an integer.",
    "int_parsing": "The value must be an integer.",
    "float_type": "The value must be a number.",
    "float_parsing": "The value must be a number.",
    "bool_type": "The value must be true or false.",
    "bool_parsing": "The value must be true or false.",
    "string_type": "The value must be text.",
    "list_type": "The value must be a list.",
    "tuple_type": "The value must be a list.",
    "set_type": "The value must be a list.",
    "dict_type": "The value must be an object.",
    "mapping_type": "The value must be an object.",
    "model_type": "The value must be an object.",
    "model_attributes_type": "The value must be an object.",
}


def _path(loc: Iterable[object]) -> str:
    result = ""
    for part in loc:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += ("." if result else "") + str(part)
    return result


def _safe_message(error: dict[str, object]) -> str:
    error_type = str(error.get("type", ""))
    known = _ERROR_MESSAGES.get(error_type)
    if known:
        return known
    raw = str(error.get("msg") or "The value does not satisfy the contract.")
    if raw.startswith("Value error, "):
        raw = raw[len("Value error, ") :]
    safe = redact_for_boundary("preflight-diagnostic", raw)
    return (
        safe
        if isinstance(safe, str) and safe
        else "The value does not satisfy the contract."
    )


def _message_args(
    error_type: str, error: dict[str, object]
) -> dict[str, MessageArg]:
    context = error.get("ctx")
    if not isinstance(context, dict):
        return {}
    result: dict[str, MessageArg] = {}
    for key in _ERROR_ARG_KEYS.get(error_type, ()):
        value = context.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


def _issue_path(
    error_type: str,
    error: dict[str, object],
    message_args: Mapping[str, MessageArg],
) -> str:
    return _path(error.get("loc", ()))


def report_from_validation_error(
    exc: ValidationError,
    *,
    stage: str,
    scope: str,
    owner_id: str = "",
    owner_name: str = "",
    owner_type: str = "",
) -> ValidationReport:
    issues = []
    for error in exc.errors(
        include_url=False,
        include_context=True,
        include_input=False,
    ):
        error_type = str(error.get("type", ""))
        message_args = _message_args(error_type, error)
        path = _issue_path(error_type, error, message_args)
        specific_identity = _specific_contract_identity(
            error_type=error_type,
            path=path,
            scope=scope,
            owner_type=owner_type,
            detail=str(error.get("msg", "")).removeprefix("Value error, "),
        )
        issues.append(
            ValidationIssue(
                code=(
                    specific_identity[0]
                    if specific_identity is not None
                    else _ERROR_CODES.get(error_type, "contract.invalid_value")
                ),
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                owner_type=owner_type,
                path=path,
                message=_safe_message(error),
                message_key=(
                    specific_identity[1]
                    if specific_identity is not None
                    else _ERROR_MESSAGE_KEYS.get(
                        error_type,
                        "validation.issue.contract.invalidValue",
                    )
                ),
                message_args=message_args,
            )
        )
    return ValidationReport(stage=stage, issues=tuple(issues))
