from __future__ import annotations

from pathlib import Path

import pytest

from agent_shell.runtime.workflow_lifecycle import lifecycle_invocations_namespace
from agent_shell.workflow import admit_workflow_document

from .support import make_client


AGENT_ID = "11111111-1111-4111-8111-111111111111"
COMMAND_ID = "22222222-2222-4222-8222-222222222222"


def _monitoring_document():
    admission, document = admit_workflow_document(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {
                        "id": "command",
                        "type": "command",
                        "type_version": 1,
                        "config": {"command_id": COMMAND_ID},
                    },
                    {
                        "id": "agent",
                        "type": "agent",
                        "type_version": 1,
                        "config": {"main_agent_id": AGENT_ID},
                    },
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": [
                    {
                        "id": "start-command",
                        "source": "start",
                        "source_handle": "next",
                        "target": "command",
                        "target_handle": "in",
                    },
                    {
                        "id": "command-agent",
                        "source": "command",
                        "source_handle": "branch",
                        "target": "agent",
                        "target_handle": "in",
                        "branch_key": "continue",
                    },
                    {
                        "id": "agent-end",
                        "source": "agent",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                    },
                ],
            },
            "layout": {
                "nodes": {
                    "start": {"x": 0, "y": 0},
                    "command": {"x": 200, "y": 0},
                    "agent": {"x": 400, "y": 0},
                    "end": {"x": 600, "y": 0},
                },
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        }
    )
    assert admission.valid and document is not None
    return document


async def _prepare(client) -> tuple[str, str]:
    lifecycle = client.app.state.workflow_lifecycle
    enabled_id = await lifecycle.create(
        [{"role": "user", "content": "enabled"}],
        request_id="request-enabled",
        run_id="run-enabled",
        checkpoint_thread_id=None,
        workflow_id="workflow-enabled",
        workflow_name="Enabled Workflow",
        workflow_document=_monitoring_document(),
        monitoring_capture_enabled=True,
    )
    lifecycle.start_node_attempt(
        {
            "lifecycle_id": enabled_id,
            "run_id": "run-enabled",
            "workflow_node_id": "agent",
            "invocation_id": "agent-invocation",
            "attempt": 1,
            "node_first_attempt_time": None,
            "started_at": "2026-01-01T00:00:00.000+00:00",
        }
    )
    lifecycle.finish_node_attempt(
        "run-enabled",
        "agent-invocation",
        1,
        status="completed",
    )
    lifecycle.start_model_request(
        {
            "lifecycle_id": enabled_id,
            "run_id": "run-enabled",
            "model_run_id": "model-request",
            "started_at": "2026-01-01T00:00:00.000+00:00",
            "request": {"model": "test-model"},
        }
    )
    lifecycle.finish_model_request(
        "model-request",
        status="completed",
        usage={"total_tokens": 3},
    )
    for phase in ("started", "completed"):
        lifecycle.append_command_observation(
            {
                "lifecycle_id": enabled_id,
                "run_id": "run-enabled",
                "invocation_id": "command-invocation",
                "workflow_node_id": "command",
                "attempt": 1,
                "occurred_at": "2026-01-01T00:00:00.000+00:00",
                "phase": phase,
                "payload": {"phase": phase},
            }
        )
    await lifecycle.store.aput(
        lifecycle_invocations_namespace(enabled_id, "run-enabled"),
        "agent-invocation",
        {
            "invocation_id": "agent-invocation",
            "workflow_id": "workflow-enabled",
            "workflow_node_id": "agent",
            "agent_id": AGENT_ID,
            "invoked_at": None,
            "messages": [{"role": "assistant", "content": "done"}],
        },
        index=False,
    )
    lifecycle.append_protocol_event(
        enabled_id,
        "run-enabled",
        {
            "jsonrpc": "2.0",
            "method": "messages",
            "seq": 1,
            "params": {"data": [{"text": "first"}]},
        },
        source_type="agent",
        workflow_node_id="agent",
        node_invocation_id="agent-invocation",
        agent_profile_id=AGENT_ID,
        subagent_profile_id="",
    )
    lifecycle.append_protocol_event(
        enabled_id,
        "run-enabled",
        {
            "jsonrpc": "2.0",
            "method": "messages",
            "seq": 2,
            "params": {"data": [{"text": "second"}]},
        },
        source_type="non_agent",
        workflow_node_id="",
        node_invocation_id="",
        agent_profile_id="",
        subagent_profile_id="",
    )
    disabled_id = await lifecycle.create(
        [{"role": "user", "content": "disabled"}],
        request_id="request-disabled",
        run_id="run-disabled",
        checkpoint_thread_id=None,
        workflow_id="workflow-disabled",
        workflow_name="Disabled Workflow",
        workflow_document=_monitoring_document(),
        monitoring_capture_enabled=False,
    )
    return enabled_id, disabled_id


def test_monitoring_http_reads_snapshots_resources_and_stable_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        assert client.portal is not None
        enabled_id, disabled_id = client.portal.call(_prepare, client)
        prefix = f"/api/workflow-lifecycles/{enabled_id}/monitoring"

        snapshot = client.get(prefix + "/snapshot")
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["selector"] == {"scope": "lifecycle", "id": None}
        assert snapshot.json()["summary"]["run_count"] == 1
        assert snapshot.json()["runs"][0]["run_id"] == "run-enabled"

        workflow = client.get(
            prefix + "/snapshot",
            params={"workflow_id": "workflow-enabled"},
        )
        assert workflow.status_code == 200, workflow.text
        assert workflow.json()["selector"] == {
            "scope": "workflow",
            "id": "workflow-enabled",
        }
        exact = client.get(
            prefix + "/snapshot",
            params={"run_id": "run-enabled"},
        )
        assert exact.status_code == 200, exact.text
        assert exact.json()["selector"] == {
            "scope": "run",
            "id": "run-enabled",
        }

        graph = client.get(prefix + "/runs/run-enabled/graph")
        assert graph.status_code == 200, graph.text
        assert graph.json()["availability"] == "available"
        assert graph.json()["graph"]["workflow_id"] == "workflow-enabled"

        nodes = client.get(prefix + "/runs/run-enabled/nodes")
        assert nodes.status_code == 200, nodes.text
        assert nodes.json()["availability"] == "capturing"
        assert nodes.json()["items"][0]["workflow_node_id"] == "agent"

        attempts = client.get(
            prefix + "/runs/run-enabled/nodes/agent/attempts"
        )
        assert attempts.status_code == 200, attempts.text
        assert attempts.json()["items"][0]["attempt"] == 1

        events = client.get(
            prefix + "/runs/run-enabled/protocol-events",
            params={"after_sequence": 1, "limit": 1},
        )
        assert events.status_code == 200, events.text
        assert [item["sequence"] for item in events.json()["items"]] == [2]
        assert events.json()["next_after_sequence"] == 2

        agent_events = client.get(
            prefix + "/runs/run-enabled/protocol-events",
            params={
                "node_id": "agent",
                "invocation_id": "agent-invocation",
            },
        )
        assert agent_events.status_code == 200, agent_events.text
        assert [
            item["sequence"] for item in agent_events.json()["items"]
        ] == [1]
        assert agent_events.json()["items"][0]["origin"] == {
            "source_type": "agent",
            "workflow_node_id": "agent",
            "node_invocation_id": "agent-invocation",
            "agent_profile_id": AGENT_ID,
            "subagent_profile_id": "",
        }

        invalid_protocol_selector = client.get(
            prefix + "/runs/run-enabled/protocol-events",
            params={"invocation_id": "agent-invocation"},
        )
        assert invalid_protocol_selector.status_code == 422
        assert invalid_protocol_selector.json()["detail"]["code"] == (
            "runtime_monitoring_protocol_selector_invalid"
        )

        models = client.get(prefix + "/runs/run-enabled/model-requests")
        assert models.status_code == 200, models.text
        assert models.json()["items"][0]["model_run_id"] == "model-request"

        commands = client.get(
            prefix + "/runs/run-enabled/command-observations",
            params={"node_id": "command"},
        )
        assert commands.status_code == 200, commands.text
        assert [item["phase"] for item in commands.json()["items"]] == [
            "started",
            "completed",
        ]

        artifact = client.get(
            prefix
            + "/runs/run-enabled/agent-invocations/agent-invocation"
        )
        assert artifact.status_code == 200, artifact.text
        assert artifact.json()["artifact"]["messages"][0]["content"] == "done"

        state = client.get(prefix + "/runs/run-enabled/state")
        assert state.status_code == 200, state.text
        assert state.json()["availability"] == "not_enabled"

        conflict = client.get(
            prefix + "/snapshot",
            params={
                "workflow_id": "workflow-enabled",
                "run_id": "run-enabled",
            },
        )
        assert conflict.status_code == 422
        assert conflict.json()["detail"]["code"] == (
            "runtime_monitoring_selector_conflict"
        )

        missing = client.get(prefix + "/runs/missing/graph")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "workflow_run_not_found"

        missing_workflow = client.get(
            prefix + "/snapshot",
            params={"workflow_id": "missing-workflow"},
        )
        assert missing_workflow.status_code == 404
        assert missing_workflow.json()["detail"]["code"] == (
            "workflow_scope_not_found"
        )

        missing_node = client.get(
            prefix + "/runs/run-enabled/nodes/missing-node/attempts"
        )
        assert missing_node.status_code == 404
        assert missing_node.json()["detail"]["code"] == "workflow_node_not_found"

        missing_invocation = client.get(
            prefix + "/runs/run-enabled/agent-invocations/missing-invocation"
        )
        assert missing_invocation.status_code == 404
        assert missing_invocation.json()["detail"]["code"] == (
            "agent_invocation_not_found"
        )

        disabled = client.get(
            f"/api/workflow-lifecycles/{disabled_id}/monitoring/snapshot"
        )
        assert disabled.status_code == 409
        assert disabled.json()["detail"]["code"] == "runtime_monitoring_disabled"

        assert client.get(prefix + "/stream").status_code == 404
        assert client.get(prefix + "/delta").status_code == 404
