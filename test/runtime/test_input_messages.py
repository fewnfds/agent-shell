from __future__ import annotations

import base64

import pytest

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.input_messages import (
    client_messages_sha,
    validate_client_messages,
)
from agent_shell.storage.runtime_policy import RuntimePolicy


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def test_openai_and_standard_parts_normalize_in_message_order() -> None:
    image = encoded(b"image")
    audio = encoded(b"audio")

    messages = validate_client_messages(
        [
            {
                "role": "system",
                "content": [{"type": "text", "text": "system"}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image}",
                            "detail": "high",
                        },
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio, "format": "mp3"},
                    },
                    {
                        "type": "video",
                        "url": "https://media.example/video.mp4",
                        "mime_type": "video/mp4",
                    },
                    {
                        "type": "file",
                        "file": {"file_id": "provider-file-1"},
                    },
                ],
            },
        ]
    )

    assert messages[0]["content"] == [{"type": "text", "text": "system"}]
    assert [part["type"] for part in messages[1]["content"]] == [
        "text",
        "image",
        "audio",
        "video",
        "file",
    ]
    assert messages[1]["content"][1] == {
        "type": "image",
        "base64": image,
        "mime_type": "image/png",
        "extras": {"detail": "high"},
    }
    assert messages[1]["content"][2]["mime_type"] == "audio/mpeg"
    assert messages[1]["content"][3]["url"].startswith("https://")
    assert messages[1]["content"][4]["file_id"] == "provider-file-1"


@pytest.mark.parametrize(
    ("part", "code"),
    [
        ({"type": "unknown", "value": "x"}, "input_content_part_unsupported"),
        (
            {"type": "image", "url": "file:///tmp/image.png"},
            "input_content_url_invalid",
        ),
        (
            {"type": "image", "base64": "aW1hZ2U=", "mime_type": "video/mp4"},
            "input_content_mime_invalid",
        ),
        (
            {"type": "image", "url": "https://a", "file_id": "also-set"},
            "input_content_source_invalid",
        ),
    ],
)
def test_invalid_content_parts_fail_before_provider(part: dict, code: str) -> None:
    with pytest.raises(AgentRuntimeError) as error:
        validate_client_messages([{"role": "user", "content": [part]}])

    assert error.value.code == code


def test_system_media_and_configured_decoded_media_limit_are_rejected() -> None:
    image_part = {
        "type": "image",
        "base64": encoded(b"abc"),
        "mime_type": "image/png",
    }
    with pytest.raises(AgentRuntimeError) as system_error:
        validate_client_messages([{"role": "system", "content": [image_part]}])
    assert system_error.value.code == "input_system_content_unsupported"

    with pytest.raises(AgentRuntimeError) as size_error:
        validate_client_messages(
            [{"role": "user", "content": [image_part]}],
            RuntimePolicy(decoded_block_bytes=2),
        )
    assert size_error.value.code == "input_content_block_too_large"


def test_client_messages_sha_is_stable_for_normalized_mapping_order() -> None:
    left = [{"role": "user", "content": "hello", "name": "client"}]
    right = [{"name": "client", "content": "hello", "role": "user"}]

    assert client_messages_sha(left) == client_messages_sha(right)
    assert len(client_messages_sha(left)) == 64
