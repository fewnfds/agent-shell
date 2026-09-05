from __future__ import annotations

import pytest

from .app_support import *


def test_model_request_settings_accept_only_current_json_shapes(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    for index, update in enumerate(
        (
            {"tool_choice": ["auto"]},
            {"response_format": ["object"]},
            {"response_format": {"title": "Missing description"}},
            {"model_settings": ["parallel_tool_calls"]},
            {"model_settings": {"tool_choice": "required"}},
        )
    ):
        payload = {**model_payload(f"Invalid request settings {index}"), **update}
        response = client.post("/agent-shell/api/model-connections", json=payload)
        assert response.status_code == 422, response.text


def test_model_request_settings_must_be_explicitly_present(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    for field in ("tool_choice", "response_format", "model_settings"):
        payload = model_payload(f"Missing {field}")
        payload.pop(field)
        response = client.post("/agent-shell/api/model-connections", json=payload)

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "model_connection_invalid"


def test_model_provider_is_required_and_limited_to_release_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    missing = model_payload("Missing Provider")
    missing.pop("provider")
    unsupported = model_payload("Unsupported Provider")
    unsupported["provider"] = "automatic"
    aliased = model_payload("Aliased Provider")
    aliased["provider"] = "google-vertexai"
    aliased["provider_settings"] = {}
    aliased["credential"] = None
    deepseek = model_payload("DeepSeek Provider")
    deepseek["provider"] = "deepseek"
    deepseek["provider_settings"] = {"max_tokens": 4096}
    openrouter = model_payload("OpenRouter Provider")
    openrouter["provider"] = "openrouter"

    assert client.post("/agent-shell/api/model-connections", json=missing).status_code == 422
    assert client.post("/agent-shell/api/model-connections", json=unsupported).status_code == 422
    assert client.post("/agent-shell/api/model-connections", json=aliased).status_code == 422
    response = client.post("/agent-shell/api/model-connections", json=deepseek)
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "deepseek"
    response = client.post("/agent-shell/api/model-connections", json=openrouter)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("provider", "provider_settings", "credential"),
    [
        (
            "openai",
            {"max_completion_tokens": 512, "use_responses_api": True},
            "secret",
        ),
        ("anthropic", {"max_tokens_to_sample": 512, "effort": "high"}, "secret"),
        ("google_genai", {"max_tokens": 512, "retries": 2}, "secret"),
        (
            "google_vertexai",
            {"max_tokens": 512, "thinking_budget": 128},
            None,
        ),
        ("deepseek", {"max_tokens": 512, "reasoning_effort": "high"}, "secret"),
        ("xai", {"max_tokens": 512, "reasoning_effort": "high"}, "secret"),
    ],
)
def test_model_provider_settings_use_each_official_constructor_contract(
    tmp_path: Path,
    monkeypatch,
    provider: str,
    provider_settings: dict,
    credential: str | None,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    payload = model_payload(f"{provider} native settings")
    payload.update(
        provider=provider,
        provider_settings=provider_settings,
        credential=credential,
    )

    response = client.post("/agent-shell/api/model-connections", json=payload)

    assert response.status_code == 200, response.text
    expected_defaults = {"temperature": 1, "top_p": 1}
    if provider != "anthropic":
        expected_defaults.update(presence_penalty=0, frequency_penalty=0)
    assert response.json()["provider_settings"] == {
        **expected_defaults,
        **provider_settings,
    }


@pytest.mark.parametrize(
    ("provider", "provider_settings", "credential"),
    [
        ("openai", {"max_tokens": 512}, "secret"),
        ("anthropic", {"max_completion_tokens": 512}, "secret"),
        ("google_genai", {"max_tokens_to_sample": 512}, "secret"),
        ("google_vertexai", {"max_tokens": 512}, "string-is-not-adc"),
    ],
)
def test_model_provider_settings_reject_cross_provider_parameters(
    tmp_path: Path,
    monkeypatch,
    provider: str,
    provider_settings: dict,
    credential: str | None,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    payload = model_payload(f"Invalid {provider} settings")
    payload.update(
        provider=provider,
        provider_settings=provider_settings,
        credential=credential,
    )

    response = client.post("/agent-shell/api/model-connections", json=payload)

    assert response.status_code == 422


def test_model_parameters_reject_non_finite_numbers_before_storage(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    created = client.post("/agent-shell/api/model-connections", json=model_payload("Valid model"))
    assert created.status_code == 200, created.text

    for index, literal in enumerate(("NaN", "Infinity", "-Infinity", "1e999")):
        payload = model_payload(f"Invalid model {index}")
        raw = json.dumps(payload, separators=(",", ":")).replace(
            '"temperature":0', f'"temperature":{literal}'
        )
        response = client.post(
            "/agent-shell/api/model-connections",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, (literal, response.text)

    update_payload = model_payload("Invalid update")
    update_payload["credential"] = None
    raw_update = json.dumps(update_payload, separators=(",", ":")).replace(
        '"temperature":0', '"temperature":NaN'
    )
    updated = client.put(
        f"/agent-shell/api/model-connections/{created.json()['id']}",
        content=raw_update,
        headers={"Content-Type": "application/json"},
    )
    listed = client.get("/agent-shell/api/model-connections")

    assert updated.status_code == 422, updated.text
    assert listed.status_code == 200, listed.text
    assert [
        (item["name"], item["provider_settings"]["temperature"])
        for item in listed.json()
    ] == [
        ("Valid model", 0)
    ]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("temperature", "definitely-not-a-number"),
        ("max_completion_tokens", "4096"),
        ("max_completion_tokens", 0),
        ("seed", 1.5),
        ("timeout", 0),
        ("max_retries", -1),
        ("stream_usage", "true"),
        ("streaming", 1),
        ("reasoning_effort", False),
        ("service_tier", 1),
        ("logprobs", "false"),
        ("top_logprobs", -1),
        ("use_responses_api", 1),
    ],
)
def test_model_parameters_reject_wrong_types_and_impossible_values_before_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid: object,
) -> None:
    client = make_client(tmp_path, monkeypatch)
    payload = model_payload(f"Invalid {field}")
    payload["provider_settings"][field] = invalid

    response = client.post("/agent-shell/api/model-connections", json=payload)

    assert response.status_code == 422, response.text
    assert client.get("/agent-shell/api/model-connections").json() == []
