from __future__ import annotations

import json

import pytest

from agent_shell.provider_secrets import ProviderCredentialError, ProviderSecretResolver
from agent_shell.storage.environment import (
    InstanceEnvironmentStore,
    MODEL_CONNECTION_ENVIRONMENT_OWNER,
)
from agent_shell.storage.file_config import FileConfigRepository

from .provider_secret_support import *


def resolver_for(data_root: Path) -> ProviderSecretResolver:
    return ProviderSecretResolver(FileConfigRepository(data_root))


def test_instance_environment_does_not_fall_back_to_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "AGENT_SHELL_TEST_EMPTY_SECRET"
    monkeypatch.setenv(name, "process-value")
    environment = InstanceEnvironmentStore(
        tmp_path / "data" / "config" / "agent-shell.env"
    )

    assert environment.get(name) is None

def test_local_secret_is_write_only_and_separated_from_block_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)

    created = client.post("/api/model-connections", json=model_payload())
    assert created.status_code == 200, created.text
    block = created.json()
    block_id = block["id"]
    responses = [
        created,
        client.get("/api/model-connections"),
        client.get(f"/api/model-connections/{block_id}"),
    ]

    assert block["credential"] == {"status": "masked"}
    assert all(LOCAL_SECRET not in response.text for response in responses)
    assert all("reference" not in response.text for response in responses)
    stored, secrets = connection_storage_payload(data_root, block_id)
    assert LOCAL_SECRET not in json.dumps(stored)
    assert stored["credential"]["reference"] == secrets[0]["id"]
    assert secrets[0]["secret_value"] == LOCAL_SECRET

    resolver = resolver_for(data_root)
    assert resolver.resolve_model(block_id) == LOCAL_SECRET

def test_keep_rename_replace_and_masked_round_trip_are_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)
    block = client.post("/api/model-connections", json=model_payload()).json()
    block_id = block["id"]
    original_payload, _ = connection_storage_payload(data_root, block_id)
    original_reference = original_payload["credential"]["reference"]

    kept_payload = model_payload("Renamed model", None)
    kept = client.put(f"/api/model-connections/{block_id}", json=kept_payload)
    assert kept.status_code == 200, kept.text
    kept_internal, kept_secrets = connection_storage_payload(data_root, block_id)
    assert kept.json()["id"] == block_id
    assert kept.json()["name"] == "Renamed model"
    assert kept_internal["credential"]["reference"] == original_reference
    assert [row["secret_value"] for row in kept_secrets] == [LOCAL_SECRET]

    masked = model_payload(
        "Masked overwrite",
        "••••••••",
    )
    rejected = client.put(f"/api/model-connections/{block_id}", json=masked)
    assert rejected.status_code == 422
    assert resolver_for(data_root).resolve_model(
        block_id
    ) == LOCAL_SECRET

    replacement = model_payload("Rotated model", REPLACEMENT_SECRET)
    rotated = client.put(f"/api/model-connections/{block_id}", json=replacement)
    assert rotated.status_code == 200, rotated.text
    rotated_internal, rotated_secrets = connection_storage_payload(data_root, block_id)
    assert rotated_internal["credential"]["reference"] == original_reference
    assert [row["secret_value"] for row in rotated_secrets] == [REPLACEMENT_SECRET]
    assert resolver_for(data_root).resolve_model(
        block_id
    ) == REPLACEMENT_SECRET

def test_endpoint_change_without_replacement_clears_saved_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)
    block = client.post("/api/model-connections", json=model_payload()).json()
    changed = model_payload("Changed endpoint", None)
    changed["base_url"] = "https://other-provider.example/v1"

    response = client.put(f"/api/model-connections/{block['id']}", json=changed)

    assert response.status_code == 200, response.text
    assert response.json()["credential"] == {"status": "missing"}
    stored, secrets = connection_storage_payload(data_root, block["id"])
    assert stored["base_url"] == "https://other-provider.example/v1"
    assert stored["credential"] is None
    assert secrets == []
    assert resolver_for(data_root).resolve_model(
        block["id"]
    ) is None

def test_provider_change_without_replacement_clears_saved_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)
    block = client.post("/api/model-connections", json=model_payload()).json()
    changed = model_payload("Changed Provider", None)
    changed["provider"] = "anthropic"
    changed["provider_settings"] = {"max_tokens_to_sample": 1024}

    response = client.put(f"/api/model-connections/{block['id']}", json=changed)

    assert response.status_code == 200, response.text
    assert response.json()["credential"] == {"status": "missing"}
    stored, secrets = connection_storage_payload(data_root, block["id"])
    assert stored["provider"] == "anthropic"
    assert stored["credential"] is None
    assert secrets == []

def test_copy_uses_independent_reference_and_each_delete_removes_owned_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)
    source = client.post("/api/model-connections", json=model_payload()).json()

    copied = client.post(
        f"/api/model-connections/{source['id']}/copy", json={"name": "Copied model"}
    )
    assert copied.status_code == 200, copied.text
    copy_id = copied.json()["id"]
    source_internal, secrets = connection_storage_payload(data_root, source["id"])
    copy_internal, _ = connection_storage_payload(data_root, copy_id)
    assert source_internal["credential"]["reference"] != (
        copy_internal["credential"]["reference"]
    )
    assert len(secrets) == 2
    assert LOCAL_SECRET not in copied.text

    source_reference = source_internal["credential"]["reference"]
    assert client.delete(f"/api/model-connections/{source['id']}").status_code == 200
    assert resolver_for(data_root).resolve_model(
        copy_id
    ) == LOCAL_SECRET
    environment = InstanceEnvironmentStore(data_root / "config" / "agent-shell.env")
    assert environment.get(source_reference) is None
    copy_reference = copy_internal["credential"]["reference"]
    assert client.delete(f"/api/model-connections/{copy_id}").status_code == 200
    assert environment.get(copy_reference) is None

def test_no_key_is_valid_but_a_broken_reference_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, data_root = make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "must-not-be-read")
    no_key = client.post(
        "/api/model-connections", json=model_payload("No-key model", None)
    )
    assert no_key.status_code == 200, no_key.text
    assert no_key.json()["credential"] == {"status": "missing"}
    assert resolver_for(data_root).resolve_model(no_key.json()["id"]) is None

    block = client.post("/api/model-connections", json=model_payload()).json()
    internal, _ = connection_storage_payload(data_root, block["id"])
    reference = internal["credential"]["reference"]
    InstanceEnvironmentStore(
        data_root / "config" / "agent-shell.env"
    ).patch(
        MODEL_CONNECTION_ENVIRONMENT_OWNER,
        remove_keys={reference},
    )
    with pytest.raises(ProviderCredentialError) as captured:
        resolver_for(data_root).resolve_model(block["id"])
    assert captured.value.code == "provider_secret_reference_missing"
