from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.storage.runtime_policy import RUNTIME_POLICY_DEFAULTS, RuntimePolicy


MAX_URL_CHARS = 8192
MAX_FILE_ID_CHARS = 2048

_MIME_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$"
)
_AUDIO_FORMAT_MIME = {
    "aac": "audio/aac",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "mp4": "audio/mp4",
    "mpeg": "audio/mpeg",
    "oga": "audio/ogg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
}
_MEDIA_TYPES = frozenset({"image", "audio", "video", "file"})


@dataclass(slots=True)
class _ValidationBudget:
    enforce_limits: bool
    policy: RuntimePolicy
    blocks: int = 0
    decoded_bytes: int = 0

    def add_block(self, path: str) -> None:
        self.blocks += 1
        if self.enforce_limits and self.blocks > self.policy.content_blocks:
            _invalid(
                "input_content_parts_too_many",
                f"messages content may not exceed {self.policy.content_blocks} blocks.",
                path,
            )

    def decode_base64(self, value: object, path: str) -> str:
        if not isinstance(value, str) or not value:
            _invalid(
                "input_content_source_invalid",
                f"{path} must be a non-empty base64 string.",
                path,
            )
        if self.enforce_limits:
            maximum_encoded = ((self.policy.decoded_block_bytes + 2) // 3) * 4
            if len(value) > maximum_encoded:
                _invalid(
                    "input_content_block_too_large",
                    f"{path} exceeds the decoded media limit.",
                    path,
                )
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AgentRuntimeError(
                "input_content_base64_invalid",
                f"{path} must contain canonical base64 data.",
                status_code=422,
            ) from exc
        if self.enforce_limits and len(decoded) > self.policy.decoded_block_bytes:
            _invalid(
                "input_content_block_too_large",
                f"{path} may not decode to more than {self.policy.decoded_block_bytes} bytes.",
                path,
            )
        self.decoded_bytes += len(decoded)
        if self.enforce_limits and self.decoded_bytes > self.policy.decoded_total_bytes:
            _invalid(
                "input_content_total_too_large",
                "messages contain too much decoded base64 media.",
                path,
            )
        return value


def _invalid(code: str, message: str, _path: str) -> None:
    raise AgentRuntimeError(code, message, status_code=422)


def _plain_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid("input_content_part_invalid", f"{path} must be an object.", path)
    return {str(key): item for key, item in value.items()}


def _only_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _invalid(
            "input_content_part_invalid",
            f"{path} contains unsupported fields: {', '.join(unknown)}.",
            path,
        )


def _mime(value: object, block_type: str, path: str) -> str:
    if not isinstance(value, str):
        _invalid("input_content_mime_invalid", f"{path} must be a MIME type.", path)
    normalized = value.strip().lower()
    if not _MIME_PATTERN.fullmatch(normalized):
        _invalid("input_content_mime_invalid", f"{path} is not a valid MIME type.", path)
    if block_type != "file" and not normalized.startswith(f"{block_type}/"):
        _invalid(
            "input_content_mime_invalid",
            f"{path} must use the {block_type}/ media family.",
            path,
        )
    return normalized


def _url(value: object, path: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_CHARS:
        _invalid(
            "input_content_url_invalid",
            f"{path} must be a non-empty URL no longer than {MAX_URL_CHARS} characters.",
            path,
        )
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _invalid(
            "input_content_url_invalid",
            f"{path} must be an absolute http or https URL.",
            path,
        )
    if parsed.username is not None or parsed.password is not None:
        _invalid(
            "input_content_url_invalid",
            f"{path} may not contain URL credentials.",
            path,
        )
    return value


def _file_id(value: object, path: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_FILE_ID_CHARS:
        _invalid(
            "input_content_file_id_invalid",
            f"{path} must be a non-empty Provider file ID no longer than {MAX_FILE_ID_CHARS} characters.",
            path,
        )
    return value


def _data_uri(value: object, block_type: str, path: str, budget: _ValidationBudget) -> tuple[str, str]:
    if not isinstance(value, str) or not value.startswith("data:"):
        _invalid(
            "input_content_data_uri_invalid",
            f"{path} must be a base64 data URI.",
            path,
        )
    header, separator, encoded = value.partition(",")
    if not separator or not header.endswith(";base64"):
        _invalid(
            "input_content_data_uri_invalid",
            f"{path} must be a base64 data URI.",
            path,
        )
    mime_type = _mime(header[5:-7], block_type, f"{path}.mime_type")
    return budget.decode_base64(encoded, path), mime_type


def _optional_metadata(
    block: Mapping[str, Any],
    result: dict[str, Any],
    *,
    path: str,
    allow_filename: bool,
) -> None:
    if "id" in block:
        if not isinstance(block["id"], str) or not block["id"]:
            _invalid("input_content_part_invalid", f"{path}.id must be a non-empty string.", path)
        result["id"] = block["id"]
    if "extras" in block:
        result["extras"] = deepcopy(_plain_mapping(block["extras"], f"{path}.extras"))
    if allow_filename and "filename" in block:
        filename = block["filename"]
        if not isinstance(filename, str) or not filename or len(filename) > 255:
            _invalid(
                "input_content_filename_invalid",
                f"{path}.filename must be a non-empty string no longer than 255 characters.",
                path,
            )
        result["filename"] = filename


def _standard_media_block(
    block: Mapping[str, Any],
    path: str,
    budget: _ValidationBudget,
) -> dict[str, Any]:
    block_type = str(block["type"])
    allowed = {"type", "url", "base64", "file_id", "mime_type", "id", "extras"}
    if block_type == "file":
        allowed.add("filename")
    _only_keys(block, allowed, path)
    sources = [key for key in ("url", "base64", "file_id") if key in block]
    if len(sources) != 1:
        _invalid(
            "input_content_source_invalid",
            f"{path} must contain exactly one of url, base64, or file_id.",
            path,
        )
    source = sources[0]
    result: dict[str, Any] = {"type": block_type}
    if source == "url":
        result["url"] = _url(block["url"], f"{path}.url")
    elif source == "file_id":
        result["file_id"] = _file_id(block["file_id"], f"{path}.file_id")
    else:
        if "mime_type" not in block:
            _invalid(
                "input_content_mime_invalid",
                f"{path}.mime_type is required for base64 data.",
                path,
            )
        result["mime_type"] = _mime(
            block["mime_type"], block_type, f"{path}.mime_type"
        )
        result["base64"] = budget.decode_base64(
            block["base64"], f"{path}.base64"
        )
    if "mime_type" in block and source != "base64":
        result["mime_type"] = _mime(
            block["mime_type"], block_type, f"{path}.mime_type"
        )
    _optional_metadata(
        block, result, path=path, allow_filename=block_type == "file"
    )
    return result


def _openai_image_block(
    block: Mapping[str, Any], path: str, budget: _ValidationBudget
) -> dict[str, Any]:
    _only_keys(block, {"type", "image_url"}, path)
    image = _plain_mapping(block.get("image_url"), f"{path}.image_url")
    _only_keys(image, {"url", "detail"}, f"{path}.image_url")
    value = image.get("url")
    result: dict[str, Any] = {"type": "image"}
    if isinstance(value, str) and value.startswith("data:"):
        encoded, mime_type = _data_uri(value, "image", f"{path}.image_url.url", budget)
        result.update({"base64": encoded, "mime_type": mime_type})
    else:
        result["url"] = _url(value, f"{path}.image_url.url")
    if "detail" in image:
        detail = image["detail"]
        if detail not in {"auto", "low", "high"}:
            _invalid(
                "input_content_part_invalid",
                f"{path}.image_url.detail must be auto, low, or high.",
                path,
            )
        result["extras"] = {"detail": detail}
    return result


def _openai_audio_block(
    block: Mapping[str, Any], path: str, budget: _ValidationBudget
) -> dict[str, Any]:
    _only_keys(block, {"type", "input_audio"}, path)
    audio = _plain_mapping(block.get("input_audio"), f"{path}.input_audio")
    _only_keys(audio, {"data", "format"}, f"{path}.input_audio")
    audio_format = audio.get("format")
    if not isinstance(audio_format, str) or audio_format.lower() not in _AUDIO_FORMAT_MIME:
        _invalid(
            "input_content_mime_invalid",
            f"{path}.input_audio.format is not supported.",
            path,
        )
    return {
        "type": "audio",
        "base64": budget.decode_base64(audio.get("data"), f"{path}.input_audio.data"),
        "mime_type": _AUDIO_FORMAT_MIME[audio_format.lower()],
    }


def _openai_file_block(
    block: Mapping[str, Any], path: str, budget: _ValidationBudget
) -> dict[str, Any]:
    _only_keys(block, {"type", "file"}, path)
    file = _plain_mapping(block.get("file"), f"{path}.file")
    _only_keys(file, {"file_id", "file_data", "filename"}, f"{path}.file")
    sources = [key for key in ("file_id", "file_data") if key in file]
    if len(sources) != 1:
        _invalid(
            "input_content_source_invalid",
            f"{path}.file must contain exactly one of file_id or file_data.",
            path,
        )
    result: dict[str, Any] = {"type": "file"}
    if sources[0] == "file_id":
        result["file_id"] = _file_id(file["file_id"], f"{path}.file.file_id")
    else:
        encoded, mime_type = _data_uri(
            file["file_data"], "file", f"{path}.file.file_data", budget
        )
        result.update({"base64": encoded, "mime_type": mime_type})
    if "filename" in file:
        filename = file["filename"]
        if not isinstance(filename, str) or not filename or len(filename) > 255:
            _invalid(
                "input_content_filename_invalid",
                f"{path}.file.filename must be a non-empty string no longer than 255 characters.",
                path,
            )
        result["filename"] = filename
    return result


def _content_part(
    value: object, path: str, budget: _ValidationBudget
) -> dict[str, Any]:
    block = _plain_mapping(value, path)
    block_type = block.get("type")
    if block_type == "text":
        _only_keys(block, {"type", "text"}, path)
        if not isinstance(block.get("text"), str):
            _invalid("input_content_part_invalid", f"{path}.text must be a string.", path)
        return {"type": "text", "text": block["text"]}
    if block_type == "image_url":
        return _openai_image_block(block, path, budget)
    if block_type == "input_audio":
        return _openai_audio_block(block, path, budget)
    if block_type == "file" and "file" in block:
        return _openai_file_block(block, path, budget)
    if block_type in _MEDIA_TYPES:
        return _standard_media_block(block, path, budget)
    _invalid(
        "input_content_part_unsupported",
        f"{path}.type is not a supported input content block.",
        path,
    )


def _validate_messages(
    value: object,
    *,
    require_non_empty: bool,
    enforce_limits: bool,
    policy: RuntimePolicy,
) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or (
        require_non_empty and not value
    ):
        raise AgentRuntimeError(
            "input_messages_required",
            "messages must be a non-empty array.",
            status_code=422,
        )
    budget = _ValidationBudget(enforce_limits=enforce_limits, policy=policy)
    messages: list[dict[str, Any]] = []
    for index, raw_item in enumerate(value):
        if not isinstance(raw_item, Mapping):
            raise AgentRuntimeError(
                "input_message_invalid",
                f"messages[{index}] must be an object.",
                status_code=422,
            )
        item = {str(key): part for key, part in raw_item.items()}
        _only_keys(item, {"role", "content", "name"}, f"messages[{index}]")
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"}:
            raise AgentRuntimeError(
                "input_message_role_unsupported",
                f"messages[{index}].role is not supported by the current runtime.",
                status_code=422,
            )
        if isinstance(content, str):
            normalized_content: str | list[dict[str, Any]] = content
        elif isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            normalized_content = []
            for block_index, part in enumerate(content):
                budget.add_block(f"messages[{index}].content[{block_index}]")
                normalized = _content_part(
                    part,
                    f"messages[{index}].content[{block_index}]",
                    budget,
                )
                if role == "system" and normalized["type"] != "text":
                    _invalid(
                        "input_system_content_unsupported",
                        f"messages[{index}] system content only supports text blocks.",
                        f"messages[{index}].content[{block_index}]",
                    )
                normalized_content.append(normalized)
        else:
            raise AgentRuntimeError(
                "input_message_content_unsupported",
                f"messages[{index}].content must be a string or supported content-parts array.",
                status_code=422,
            )
        message: dict[str, Any] = {"role": role, "content": normalized_content}
        name = item.get("name")
        if name is not None:
            if not isinstance(name, str) or not name:
                raise AgentRuntimeError(
                    "input_message_name_invalid",
                    f"messages[{index}].name must be a non-empty string.",
                    status_code=422,
                )
            message["name"] = name
        messages.append(message)
    return messages


def validate_client_messages(
    value: object,
    policy: RuntimePolicy = RUNTIME_POLICY_DEFAULTS,
) -> list[dict[str, Any]]:
    return _validate_messages(
        value,
        require_non_empty=True,
        enforce_limits=True,
        policy=policy,
    )


def validate_prepared_messages(value: object) -> list[dict[str, Any]]:
    return _validate_messages(
        value,
        require_non_empty=False,
        enforce_limits=False,
        policy=RUNTIME_POLICY_DEFAULTS,
    )


def client_messages_sha(messages: list[dict[str, Any]]) -> str:
    """Return a stable SHA-256 for already-normalized client messages."""

    payload = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
