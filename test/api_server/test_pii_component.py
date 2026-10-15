from __future__ import annotations

import asyncio
from io import BytesIO
import json
from zipfile import ZipFile

from langchain.agents.middleware import PIIMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.store.memory import InMemoryStore

from agent_shell.runtime import agent_builder
from .support import create_main_agent, main_agent_payload, make_client


def test_pii_crud_snapshot_subagent_assembly_and_bundle(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    monkeypatch.setattr(
        agent_builder, "_build_chat_model",
        lambda *_args: FakeListChatModel(responses=["ok"]),
    )
    with make_client(source_root, monkeypatch) as source:
        defaults = source.get("/agent-shell/api/catalog").json()["editor_defaults"]["pii"]
        rule = defaults["default_value"]["rules"][0]
        first = source.post("/agent-shell/api/blocks/pii", json={"name": "Input PII"})
        assert first.status_code == 200, first.text
        pii = first.json()
        rules = [rule, {**rule, "pii_type": "access_code", "detector": r" code-\d+ ", "apply_to_output": True}]
        updated = source.put(
            f"/agent-shell/api/blocks/pii/{pii['id']}",
            json={"name": pii["name"], "rules": rules},
        )
        assert updated.status_code == 200, updated.text
        assert source.get(f"/agent-shell/api/blocks/pii/{pii['id']}").json()["rules"] == rules
        second = source.post(
            "/agent-shell/api/blocks/pii",
            json={"name": "Output PII", "rules": [{**rule, "pii_type": "ip", "apply_to_output": True}]},
        ).json()
        for bad_rules in ([], [{**rule, "detector": "["}], [{**rule, "pii_type": "custom"}], [rule, rule]):
            invalid = source.post("/agent-shell/api/blocks/pii", json={"name": "Invalid PII", "rules": bad_rules})
            assert invalid.status_code == 422, invalid.text
            assert invalid.json()["detail"]["validation"]["issues"]

        delegation = source.post("/agent-shell/api/blocks/subagent", json={"name": "Delegation"}).json()
        children = []
        for mode in ("inherit", "replace", "disabled"):
            selection = {"type": "pii", "mode": mode}
            if mode == "replace":
                selection["block_id"] = second["id"]
            child = source.post("/agent-shell/api/subagents", json={
                "component_name": f"PII {mode}", "name": mode,
                "description": f"PII {mode} worker",
                "settings": {"capability_overrides": [] if mode == "inherit" else [selection]},
            })
            assert child.status_code == 200, child.text
            children.append({"subagent_id": child.json()["id"]})
        main = create_main_agent(source, include_filesystem=False)
        payload = main_agent_payload(main)
        payload["capability_refs"] += [
            {"type": "pii", "block_id": pii["id"]},
            {"type": "subagent", "block_id": delegation["id"]},
        ]
        payload["subagents"] = children
        published = source.put(f"/agent-shell/api/main-agents/{main['id']}/publish", json=payload)
        assert published.status_code == 200, published.text

        snapshot = asyncio.run(source.app.state.agent_runtime.capture())
        # Resolve and materialize the same frozen configuration used by real Runs.
        builder = snapshot._runtime_factory(InMemoryStore())._builder
        assembly = builder.resolve(main["id"])
        materialized = builder._materialize_agent_resources(
            assembly.references, assembly.blocks, filesystem_mode=assembly.filesystem_mode,
            scope="main_agent", owner_id=main["id"], owner_name=main["name"],
        )
        assert [item.pii_type for item in materialized.pii_middleware] == ["email", "access_code"]
        for child in assembly.subagent_nodes.values():
            resources = builder._materialize_agent_resources(
                child.references, child.blocks, filesystem_mode=child.filesystem_mode,
                scope="subagent", owner_id=child.key, owner_name=child.name,
            )
            expected = {"inherit": ["email", "access_code"], "replace": ["ip"], "disabled": []}[child.name]
            assert [item.pii_type for item in resources.pii_middleware] == expected
            assert all(isinstance(item, PIIMiddleware) for item in resources.pii_middleware)
            assert all(item is not main_item for item in resources.pii_middleware for main_item in materialized.pii_middleware)

        exported = source.post("/agent-shell/api/configuration-bundles/export", json={"kind": "main_agent", "source_id": main["id"]})
        assert exported.status_code == 200, exported.text
        bundle = exported.content
        # A subsequent edit must not change the already captured rules.
        changed = source.put(f"/agent-shell/api/blocks/pii/{pii['id']}", json={"name": pii["name"], "rules": [rule]})
        assert changed.status_code == 200, changed.text
        assert snapshot._blocks.get_block("pii", pii["id"])["rules"] == rules

    with ZipFile(BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    pii_records = [record for record in manifest["records"] if record.get("type") == "pii"]
    assert len(pii_records) == 2
    assert next(record for record in pii_records if record["name"] == pii["name"])["payload"]["rules"] == rules

    target_root = tmp_path / "target"
    target_root.mkdir()
    with make_client(target_root, monkeypatch) as target:
        uploaded = {"bundle": ("pii.zip", bundle, "application/zip")}
        preview = target.post("/agent-shell/api/configuration-bundles/preview", files=uploaded)
        assert preview.status_code == 200, preview.text
        plan = preview.json()
        assert plan["ready"] is True, plan
        imported = target.post("/agent-shell/api/configuration-bundles/import", files=uploaded, data={"request": json.dumps({
            "bundle_sha256": plan["bundle_sha256"], "plan_token": plan["plan_token"],
            "resolutions": {"target_ids": plan["target_ids"]},
        })})
        assert imported.status_code == 200, imported.text
        imported_id = plan["target_ids"][pii["id"]]
        assert target.get(f"/agent-shell/api/blocks/pii/{imported_id}").json()["rules"] == rules
        imported_main = target.get(f"/agent-shell/api/main-agents/{plan['target_ids'][main['id']]}").json()
        assert {"type": "pii", "block_id": imported_id} in imported_main["capability_refs"]
