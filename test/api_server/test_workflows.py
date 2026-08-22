from __future__ import annotations

from copy import deepcopy
import json
import shutil

from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.workflows import WorkflowStore
from .support import *


def test_workflow_runtime_boundaries_are_managed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(client, name="Managed boundaries")
        updated = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                "name": workflow["name"],
                "workflow_role": workflow["workflow_role"],
                "description": workflow["description"],
                "recursion_limit": 250,
                "execution_timeout_seconds": 900,
                "max_concurrency": 32,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["max_concurrency"] == 32


def test_workflow_copy_preserves_graph_layout_and_role_as_a_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        source = create_workflow(
            client,
            name="Source Child",
            workflow_role="child",
        )
        document = save_linear_workflow_graph(client, source, main_agent)
        assert client.get(f"/api/workflows/{source['id']}").json()["enabled"] is True

        copied = client.post(
            f"/api/workflows/{source['id']}/copy",
            json={"name": "Copied Child"},
        )

        assert copied.status_code == 200, copied.text
        copied_item = copied.json()
        assert copied_item["id"] != source["id"]
        assert copied_item["name"] == "Copied Child"
        assert copied_item["workflow_role"] == "child"
        assert copied_item["enabled"] is False
        assert client.get(
            f"/api/workflows/{copied_item['id']}/graph"
        ).json() == document
        assert [item["id"] for item in client.get(
            "/api/workflows?workflow_role=child"
        ).json()] == [copied_item["id"], source["id"]]

        conflict = client.post(
            f"/api/workflows/{source['id']}/copy",
            json={"name": "Copied Child"},
        )
        missing = client.post(
            "/api/workflows/00000000-0000-4000-8000-000000000099/copy",
            json={"name": "Missing copy"},
        )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "workflow_name_conflict"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "workflow_not_found"


def test_workflow_event_output_is_a_reusable_component_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        output = client.post(
            "/api/blocks/workflow-event-output",
            json=workflow_event_output_payload(client, "Public workflow events"),
        )
        assert output.status_code == 200, output.text
        workflow = create_workflow(client, name="Event Workflow")
        updated = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                **{key: workflow[key] for key in (
                        "name", "workflow_role", "description",
                        "recursion_limit",
                        "execution_timeout_seconds", "max_concurrency"
                    )},
                "workflow_event_output_id": output.json()["id"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["workflow_event_output_id"] == output.json()["id"]
        protected = client.delete(
            f"/api/blocks/workflow-event-output/{output.json()['id']}"
        )
        assert protected.status_code == 409

    with make_client(tmp_path, monkeypatch) as client:
        saved = client.get(f"/api/workflows/{workflow['id']}").json()
        assert saved["workflow_event_output_id"] == output.json()["id"]


def test_workflow_validation_reports_a_missing_event_output_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        output = client.post(
            "/api/blocks/workflow-event-output",
            json=workflow_event_output_payload(client, "Missing during validation"),
        )
        assert output.status_code == 200, output.text
        workflow = create_workflow(client, name="Missing event output")
        updated = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                **{
                    key: workflow[key]
                    for key in (
                        "name",
                        "workflow_role",
                        "description",
                        "recursion_limit",
                        "execution_timeout_seconds",
                        "max_concurrency",
                    )
                },
                "workflow_event_output_id": output.json()["id"],
            },
        )
        assert updated.status_code == 200, updated.text
        document = save_linear_workflow_graph(client, workflow, main_agent)

        original_get = BlockStore.get_block_internal

        def hide_event_output(self, block_type: str, block_id: str):
            if (
                block_type == "workflow-event-output"
                and block_id == output.json()["id"]
            ):
                return None
            return original_get(self, block_type, block_id)

        monkeypatch.setattr(BlockStore, "get_block_internal", hide_event_output)
        report = client.post(
            f"/api/workflows/{workflow['id']}/validate", json=document
        )
        published = client.put(
            f"/api/workflows/{workflow['id']}/graph", json=document
        )

    assert report.status_code == 200, report.text
    issue = next(
        item
        for item in report.json()["issues"]
        if item["code"] == "workflow_event_output_not_found"
    )
    assert issue["scope"] == "workflow"
    assert issue["owner_id"] == workflow["id"]
    assert issue["path"] == "workflow_event_output_id"
    assert report.json()["valid"] is False
    assert published.status_code == 422


def test_workflow_roles_filter_management_and_public_model_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        assert client.get("/v1/models").json()["data"] == []

        created = create_workflow(
            client,
            name="Research Workflow",
        )
        child = create_workflow(
            client,
            name="Research Child",
            workflow_role="child",
        )
        assert client.get(f"/api/workflows/{created['id']}").json() == created
        assert client.get("/api/workflows").json() == [child, created]
        assert client.get(
            "/api/workflows?workflow_role=parent"
        ).json() == [created]
        assert client.get(
            "/api/workflows?workflow_role=child"
        ).json() == [child]
        assert client.get("/v1/models").json()["data"] == []
        save_linear_workflow_graph(client, created, main_agent)
        save_linear_workflow_graph(client, child, main_agent)
        assert [item["id"] for item in client.get("/v1/models").json()["data"]] == [
            "Research Workflow"
        ]
        assert created["workflow_role"] == "parent"
        assert child["workflow_role"] == "child"
        protected = client.delete(f"/api/main-agents/{main_agent['id']}")
        assert protected.status_code == 409
        assert protected.json()["detail"] == {
            "code": "configuration_referenced",
            "message_key": "errors.configurationReferencedByWorkflow",
            "message": "The Main Agent is still referenced by a Workflow.",
            "message_args": {"owner": "Research Workflow"},
        }

        copied = client.post(
            f"/api/main-agents/{main_agent['id']}/copy",
            json={"name": "Unreferenced Main Agent"},
        )
        assert copied.status_code == 200, copied.text
        bulk_protected = client.post(
            "/api/main-agents/delete",
            json={"ids": [copied.json()["id"], main_agent["id"]]},
        )
        assert bulk_protected.status_code == 409
        assert {item["id"] for item in client.get("/api/main-agents").json()} == {
            copied.json()["id"],
            main_agent["id"],
        }

        disabled = client.put(
            f"/api/workflows/{created['id']}/draft",
            json=client.get(f"/api/workflows/{created['id']}/graph").json(),
        )
        assert disabled.status_code == 200, disabled.text
        assert client.get("/v1/models").json()["data"] == []

        deleted = client.delete(f"/api/workflows/{created['id']}")
        assert deleted.json() == {"ok": True}


def test_workflow_rejects_duplicate_names_and_removed_main_agent_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        existing = create_workflow(client, name="Unique Workflow")
        duplicate = client.post(
            "/api/workflows",
            json={
                "name": "Unique Workflow",
                "workflow_role": "parent",
                "description": "Duplicate.",
            },
        )
        removed_field = client.post(
            "/api/workflows",
            json={
                "name": "Legacy Workflow",
                "workflow_role": "parent",
                "description": "Rejected legacy shape.",
                "main_agent_id": "missing-agent",
            },
        )
        enabled_field = client.post(
            "/api/workflows",
            json={
                "name": "Manual enable",
                "workflow_role": "parent",
                "description": "Rejected publication bypass.",
                "enabled": True,
            },
        )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "workflow_name_conflict"
    assert removed_field.status_code == 422
    assert removed_field.json()["detail"]["code"] == "workflow_invalid"
    assert enabled_field.status_code == 422
    assert enabled_field.json()["detail"]["code"] == "workflow_invalid"


def test_workflow_rejects_removed_filesystem_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        legacy = client.post(
            "/api/workflows",
            json={
                "name": "Legacy Filesystem owner",
                "workflow_role": "parent",
                "description": "Rejected legacy shape.",
                "filesystem_id": "00000000-0000-0000-0000-000000000000",
            },
        )

    assert legacy.status_code == 422
    assert legacy.json()["detail"]["code"] == "workflow_invalid"


def test_repository_validation_includes_disabled_workflow_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_main_agent_id = "00000000-0000-4000-8000-000000000077"
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        wrong_type_id = capability_reference_id(main_agent, "model-requirement")
        workflow = create_workflow(client, name="Reference integrity draft")
        document = {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {
                        "id": "missing",
                        "type": "agent",
                        "type_version": 1,
                        "config": {"main_agent_id": missing_main_agent_id},
                    },
                    {
                        "id": "wrong-type",
                        "type": "agent",
                        "type_version": 1,
                        "config": {"main_agent_id": wrong_type_id},
                    },
                ],
                "edges": [],
            },
            "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        }
        saved = client.put(
            f"/api/workflows/{workflow['id']}/draft",
            json=document,
        )
        report = client.get("/api/validation/repository")

    assert saved.status_code == 200, saved.text
    assert report.status_code == 200, report.text
    issues = {
        (issue["code"], issue["path"])
        for issue in report.json()["issues"]
        if issue["owner_id"] == workflow["id"]
    }
    assert issues == {
        (
            "storage.reference_not_found",
            "definition.nodes[0].config.main_agent_id",
        ),
        (
            "storage.reference_type_mismatch",
            "definition.nodes[1].config.main_agent_id",
        ),
    }


def test_repository_validation_includes_workflow_graph_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(client, name="Invalid graph admission")

    repository = FileConfigRepository(tmp_path / "data")

    def add_unsupported_node(config: dict) -> None:
        stored = next(
            item
            for item in config["workflows"]
            if item["id"] == workflow["id"]
        )
        stored["definition"]["nodes"] = [
            {
                "id": "unsupported",
                "type": "removed-node",
                "type_version": 1,
                "config": {},
            }
        ]

    repository.update_config(add_unsupported_node)

    with make_client(tmp_path, monkeypatch) as client:
        report = client.get("/api/validation/repository")

    assert report.status_code == 200, report.text
    assert any(
        issue["code"] == "workflow.node_type_unsupported"
        and issue["owner_id"] == "unsupported"
        for issue in report.json()["issues"]
    )


def test_workflow_draft_publish_and_validation_share_one_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Draft and publish")
        assert workflow["enabled"] is False

        published = save_linear_workflow_graph(client, workflow, main_agent)
        assert client.get(f"/api/workflows/{workflow['id']}").json()["enabled"] is True
        metadata = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                "name": workflow["name"],
                "workflow_role": workflow["workflow_role"],
                "description": "Metadata cannot demote a published graph.",
            },
        )
        assert metadata.status_code == 200, metadata.text
        assert metadata.json()["enabled"] is True

        invalid = deepcopy(published)
        invalid["definition"]["nodes"].insert(
            2,
            {
                "id": "agent-two",
                "type": "agent",
                "type_version": 1,
                "config": {"main_agent_id": main_agent["id"]},
            },
        )
        invalid["definition"]["edges"] = []
        rejected = client.put(
            f"/api/workflows/{workflow['id']}/graph",
            json=invalid,
        )
        after_rejection = client.get(f"/api/workflows/{workflow['id']}/graph").json()
        still_published = client.get(f"/api/workflows/{workflow['id']}").json()

        report = client.post(
            f"/api/workflows/{workflow['id']}/validate",
            json=invalid,
        )
        draft = client.put(
            f"/api/workflows/{workflow['id']}/draft",
            json=invalid,
        )
        saved_draft = client.get(f"/api/workflows/{workflow['id']}").json()

    assert rejected.status_code == 422
    assert after_rejection == published
    assert still_published["enabled"] is True
    assert report.status_code == 200
    assert report.json()["valid"] is False
    assert [issue["code"] for issue in report.json()["issues"]] == [
        "workflow.start_outgoing_required",
        "workflow.node_unreachable_from_start",
        "workflow.node_unreachable_from_start",
    ]
    assert draft.status_code == 200, draft.text
    assert draft.json() == invalid
    assert saved_draft["enabled"] is False


def test_workflow_draft_accepts_graphs_beyond_removed_size_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(client, name="Large draft")
        nodes = [
            {"id": "start", "type": "start", "type_version": 1, "config": {}},
            {"id": "end", "type": "end", "type_version": 1, "config": {}},
        ]
        edges = []
        for index in range(5000):
            node_id = f"agent{index}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "agent",
                    "type_version": 1,
                    "config": {"main_agent_id": "11111111-1111-4111-8111-111111111111"},
                }
            )
            edges.append(
                {
                    "id": f"start-{node_id}",
                    "source": "start",
                    "source_handle": "next",
                    "target": node_id,
                    "target_handle": "in",
                }
            )
        document = {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": nodes,
                "edges": edges,
            },
            "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        }
        assert len(nodes) > 100
        assert len(edges) > 200
        assert len(json.dumps(document).encode("utf-8")) > 1_000_000

        saved = client.put(
            f"/api/workflows/{workflow['id']}/draft",
            json=document,
        )

    assert saved.status_code == 200, saved.text
    assert len(saved.json()["definition"]["nodes"]) == len(nodes)


def test_workflow_publish_reports_broken_router_package_without_missing_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = (
        tmp_path
        / "data"
        / "templates"
        / "workflow"
        / "command"
        / "test-router"
    )
    package_dir.mkdir(parents=True)
    (package_dir / "main.py").write_text(
        "def create_command():\n"
        "    async def route(state, runtime):\n"
        "        return {'activate': [], 'update': {}}\n"
        "    return route\n",
        encoding="utf-8",
    )
    with make_client(tmp_path, monkeypatch) as client:
        selected = client.get(
            "/api/python-package-templates/command"
        ).json()["catalog"][0]
        router = client.post(
            "/api/blocks/command",
            json={
                "name": "Broken router package",
                "python_package": {"folder": ""},
                "python_package_template": {
                    "key": selected["key"],
                    "revision": selected["revision"],
                },
            },
        )
        assert router.status_code == 200, router.text
        folder = router.json()["python_package"]["folder"]
        shutil.rmtree(
            FileConfigRepository(tmp_path / "data").python_package_instances_root
            / "command"
            / folder
        )
        workflow = create_workflow(client, name="Broken package workflow")
        document = {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {
                        "id": "router",
                        "type": "command",
                        "type_version": 1,
                        "config": {"command_id": router.json()["id"]},
                    },
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": [
                    {"id": "start-router", "source": "start", "source_handle": "next", "target": "router", "target_handle": "in"},
                    {"id": "command-end", "source": "router", "source_handle": "branch", "target": "end", "target_handle": "in", "branch_key": "finish"},
                ],
            },
            "layout": {"nodes": {}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
        }

        draft = client.put(f"/api/workflows/{workflow['id']}/draft", json=document)
        report = client.post(f"/api/workflows/{workflow['id']}/validate", json=document)
        published = client.put(f"/api/workflows/{workflow['id']}/graph", json=document)

    assert draft.status_code == 200, draft.text
    assert report.status_code == 200, report.text
    codes = {issue["code"] for issue in report.json()["issues"]}
    assert "python_package.not_found" in codes
    assert "workflow.command_not_found" not in codes
    assert published.status_code == 422


def test_workflow_save_failure_returns_controlled_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Missing during save")
        document = save_linear_workflow_graph(client, workflow, main_agent)
        monkeypatch.setattr(
            WorkflowStore,
            "save_graph_and_enabled",
            lambda *_args, **_kwargs: False,
        )

        published = client.put(
            f"/api/workflows/{workflow['id']}/graph",
            json=document,
        )
        draft = client.put(
            f"/api/workflows/{workflow['id']}/draft",
            json=document,
        )

    assert published.status_code == 404
    assert published.json()["detail"]["code"] == "workflow_not_found"
    assert draft.status_code == 404
    assert draft.json()["detail"]["code"] == "workflow_not_found"


def test_workflow_graph_catalog_save_and_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Canvas Workflow")
        graph_url = f"/api/workflows/{workflow['id']}/graph"

        empty = client.get(graph_url)
        catalog = client.get("/api/workflow-node-catalog")
        document = {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "type_version": 1,
                        "config": {
                            "main_agent_id": main_agent["id"],
                            "defer": False,
                        },
                    },
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": [
                    {
                        "id": "start-agent",
                        "source": "start",
                        "source_handle": "next",
                        "target": "agent",
                        "target_handle": "in",
                        "branch_key": None,
                        "dispatch_key": None,
                    },
                    {
                        "id": "agent-end",
                        "source": "agent",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                        "branch_key": None,
                        "dispatch_key": None,
                    },
                ],
            },
            "layout": {
                "nodes": {
                    "start": {"x": 80, "y": 160},
                    "agent": {"x": 360, "y": 160},
                    "end": {"x": 640, "y": 160},
                },
                "viewport": {"x": 10, "y": 20, "zoom": 1.25},
            },
        }
        saved = client.put(graph_url, json=document)
        metadata = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                "name": workflow["name"],
                "workflow_role": workflow["workflow_role"],
                "description": "Metadata changed without touching the graph.",
            },
        )
        reloaded = client.get(graph_url)

    assert empty.status_code == 200
    assert empty.json()["definition"]["nodes"] == []
    assert [item["type"] for item in catalog.json()] == [
        "start",
        "agent",
        "command",
        "task-dispatcher",
        "end",
    ]
    assert saved.status_code == 200, saved.text
    assert saved.json() == document
    assert metadata.status_code == 200, metadata.text
    assert reloaded.json() == document


def test_graph_save_rejects_background_action_as_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        child = create_workflow(client, name="Child", workflow_role="child")
        save_linear_workflow_graph(client, child, main_agent)
        graph_url = f"/api/workflows/{child['id']}/graph"
        document = client.get(graph_url).json()
        document["definition"]["nodes"].insert(
            1,
            {
                "id": "background-start",
                "type": "background-workflow-start",
                "type_version": 1,
                "config": {"child_workflow_id": child["id"]},
            },
        )
        document["definition"]["edges"][0]["target"] = "background-start"
        document["definition"]["edges"].insert(
            1,
            {
                "id": "background-agent",
                "source": "background-start",
                "source_handle": "next",
                "target": "agent",
                "target_handle": "in",
            },
        )

        response = client.put(graph_url, json=document)

    assert response.status_code == 422
    assert response.json()["detail"]["validation"]["issues"][0]["code"] == (
        "workflow.node_type_unsupported"
    )
