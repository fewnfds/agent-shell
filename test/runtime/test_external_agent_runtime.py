from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from agent_shell.contracts import ExternalAgentProfile
from agent_shell.external_agents import runtime as runtime_module
from agent_shell.external_agents.binary import AntigravityCliBinary
from agent_shell.external_agents.runtime import (
    WATCHDOG_GRACE_SECONDS,
    AntigravityRunner,
    ConversationRegistry,
    ConversationSelection,
    build_antigravity_argv,
    classify_run,
    cli_timeout_seconds,
    denied_permissions_from_stderr,
    normalize_cli_event,
    watchdog_seconds,
)
from agent_shell.runtime.errors import AgentRuntimeError


HEADLESS_DENIAL = (
    "jetski: no output produced - a tool required the \"command\" permission "
    "that headless mode cannot prompt for, so it was auto-denied. Add an "
    "allow-rule under permissions.allow in settings.json."
)
PRINT_TIMEOUT_NOTICE = (
    "[agy] print timeout after 1s with turn in progress; returning partial output"
)


def external_agent_profile(**overrides: object) -> ExternalAgentProfile:
    payload: dict[str, object] = {
        "name": "Antigravity Reviewer",
        "description": "Reviews a diff and returns findings.",
        "provider": "antigravity-cli",
        "agent_name": "antigravity-reviewer",
        "system_prompt": "Answer with the single word PONG.",
        "model": None,
        "effort": "low",
        "print_timeout": "5m",
        "output_format": "stream-json",
        "conversation": "new",
        "exclude_default_components": True,
        "tools": [],
        "tool_guidance": "",
        "tool_permission": "request-review",
        "permission_allow": [],
        "env": {},
        **overrides,
    }
    return ExternalAgentProfile.model_validate(payload)


def stream_envelope(event: str, body: dict[str, object]) -> str:
    return json.dumps({"event": event, event: body})


def init_envelope(conversation_id: str) -> str:
    return stream_envelope(
        "init",
        {
            "conversation_id": conversation_id,
            "cwd": "C:/workspace",
            "permission_mode": "request-review",
        },
    )


def result_envelope(
    conversation_id: str,
    *,
    response: str = "PONG",
    status: str = "SUCCESS",
    denied_actions: list[dict[str, str]] | None = None,
) -> str:
    body: dict[str, object] = {
        "conversation_id": conversation_id,
        "status": status,
        "response": response,
        "num_turns": 1,
        "duration_seconds": 1.5,
        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }
    if denied_actions:
        body["denied_actions"] = denied_actions
    return stream_envelope("result", body)


def write_fake_cli(
    directory: Path,
    *,
    stdout_lines: list[str],
    stderr_lines: list[str] | None = None,
    exit_code: int = 0,
    sleep_seconds: int = 0,
) -> Path:
    stderr_lines = stderr_lines or []
    if os.name == "nt":
        script = ["@echo off"]
        script.extend(f"echo {line}" for line in stdout_lines)
        if sleep_seconds:
            script.append(f"ping -n {sleep_seconds + 1} 127.0.0.1 >nul")
        script.extend(f"echo {line} 1>&2" for line in stderr_lines)
        script.append(f"exit /b {exit_code}")
        path = directory / "agy.cmd"
        path.write_text("\r\n".join(script) + "\r\n", encoding="utf-8")
        return path
    script = ["#!/bin/sh"]
    for line in stdout_lines:
        script.append(f"printf '%s\\n' '{line}'")
    for line in stderr_lines:
        script.append(f"printf '%s\\n' '{line}' 1>&2")
    if sleep_seconds:
        script.append(f"sleep {sleep_seconds}")
    script.append(f"exit {exit_code}")
    path = directory / "agy"
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def fake_binary(path: Path) -> AntigravityCliBinary:
    return AntigravityCliBinary(path=path, version="test", sha256="0" * 64)


def make_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binary: AntigravityCliBinary,
) -> AntigravityRunner:
    monkeypatch.setattr(
        runtime_module,
        "resolved_antigravity_cli",
        lambda _runtime_root: binary,
    )
    return AntigravityRunner(
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
        host_environment={"PATH": os.environ.get("PATH", "")},
    )


def run_agent(
    runner: AntigravityRunner,
    profile: ExternalAgentProfile,
    **overrides: object,
):
    arguments: dict[str, object] = {
        "external_agent_id": str(uuid4()),
        "lifecycle_id": str(uuid4()),
        "prompt": "ping",
    }
    arguments.update(overrides)
    return asyncio.run(runner.run(profile, **arguments))  # type: ignore[arg-type]


def test_conversation_selection_and_timeout_scale() -> None:
    assert ConversationSelection.parse("new").claim is None
    assert ConversationSelection.parse("continue-latest").claim == "continue-latest"
    explicit = ConversationSelection.parse(str(uuid4()))
    assert explicit.claim == f"conversation:{explicit.explicit_id}"
    with pytest.raises(AgentRuntimeError) as raised:
        ConversationSelection.parse("--dangerously-skip-permissions")
    assert raised.value.code == "external_agent_conversation_invalid"
    assert cli_timeout_seconds("90s") == 90
    assert cli_timeout_seconds("5m") == 300
    assert watchdog_seconds("5m") == 300 + WATCHDOG_GRACE_SECONDS


def test_argv_carries_isolation_and_conversation_selection(tmp_path: Path) -> None:
    profile = external_agent_profile(model="gemini-3-pro", effort="high")
    workspace = tmp_path / "workspace"
    argv = build_antigravity_argv(
        binary_path=tmp_path / "agy.exe",
        profile=profile,
        definition_name="antigravity-reviewer-1234abcd",
        workspace=workspace,
        prompt="review it",
        selection=ConversationSelection.parse("new"),
    )
    assert argv == [
        str(tmp_path / "agy.exe"),
        "-p",
        "review it",
        "--output-format",
        "stream-json",
        "--agent",
        "antigravity-reviewer-1234abcd",
        "--add-dir",
        str(workspace),
        "--print-timeout",
        "5m",
        "--model",
        "gemini-3-pro",
        "--effort",
        "high",
    ]

    conversation_id = str(uuid4())
    resumed = build_antigravity_argv(
        binary_path=tmp_path / "agy.exe",
        profile=external_agent_profile(),
        definition_name="antigravity-reviewer-1234abcd",
        workspace=workspace,
        prompt="continue",
        selection=ConversationSelection.parse(conversation_id),
    )
    assert resumed[-2:] == ["--conversation", conversation_id]

    latest = build_antigravity_argv(
        binary_path=tmp_path / "agy.exe",
        profile=external_agent_profile(),
        definition_name="antigravity-reviewer-1234abcd",
        workspace=workspace,
        prompt="continue",
        selection=ConversationSelection.parse("continue-latest"),
    )
    assert latest[-1] == "-c"


def test_normalize_cli_event_covers_real_stream_envelopes() -> None:
    conversation_id = str(uuid4())
    init = normalize_cli_event(
        json.loads(init_envelope(conversation_id))
    )
    assert init[0][0] == "session_initialized"
    assert init[0][1]["conversation_id"] == conversation_id

    step = normalize_cli_event(
        json.loads(
            stream_envelope(
                "step_update",
                {
                    "conversation_id": conversation_id,
                    "step_index": 2,
                    "state": "ACTIVE",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {
                        "name": "run_command",
                        "parameters": {"CommandLine": "echo hi"},
                    },
                },
            )
        )
    )
    assert step == [
        (
            "tool_call",
            {
                "name": "run_command",
                "step_index": 2,
                "parameters": {"CommandLine": "echo hi"},
            },
        )
    ]

    failed_tool = normalize_cli_event(
        json.loads(
            stream_envelope(
                "step_update",
                {
                    "conversation_id": conversation_id,
                    "step_index": 2,
                    "state": "ERROR",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {
                        "name": "run_command",
                        "error": {"type": "TOOL_ERROR", "message": "denied"},
                    },
                },
            )
        )
    )
    assert failed_tool[0][0] == "tool_result"
    assert failed_tool[0][1]["ok"] is False
    assert failed_tool[0][1]["error"] == "denied"

    delta = normalize_cli_event(
        json.loads(
            stream_envelope(
                "step_update",
                {
                    "conversation_id": conversation_id,
                    "step_index": 1,
                    "state": "ACTIVE",
                    "step_type": "agent_response",
                    "text_delta": "PON",
                },
            )
        )
    )
    assert delta == [("text_delta", {"text": "PON"})]

    result = normalize_cli_event(
        json.loads(
            result_envelope(
                conversation_id,
                denied_actions=[{"action": "command", "display_name": "RunCommand"}],
            )
        )
    )
    assert [kind for kind, _ in result] == ["result", "denied_actions"]
    assert result[1][1]["actions"] == ["RunCommand"]


def test_classify_run_separates_truncation_and_denial() -> None:
    assert (
        classify_run(
            exit_code=0,
            status="SUCCESS",
            denied_actions=(),
            timed_out=False,
            truncated=False,
        )
        == "success"
    )
    assert (
        classify_run(
            exit_code=0,
            status="SUCCESS",
            denied_actions=(),
            timed_out=False,
            truncated=True,
        )
        == "timeout"
    )
    assert (
        classify_run(
            exit_code=0,
            status="SUCCESS",
            denied_actions=("RunCommand",),
            timed_out=False,
            truncated=False,
        )
        == "denied"
    )
    assert (
        classify_run(
            exit_code=1,
            status="ERROR",
            denied_actions=(),
            timed_out=False,
            truncated=False,
        )
        == "failed"
    )
    assert (
        classify_run(
            exit_code=None,
            status=None,
            denied_actions=(),
            timed_out=True,
            truncated=False,
        )
        == "timeout"
    )
    assert denied_permissions_from_stderr(PRINT_TIMEOUT_NOTICE) == ()
    assert denied_permissions_from_stderr(HEADLESS_DENIAL) == ("command",)


def test_conversation_registry_serializes_one_conversation(tmp_path: Path) -> None:
    registry = ConversationRegistry()
    home = tmp_path / "home"
    named = str(uuid4())

    async def scene() -> None:
        first = await registry.acquire(
            home, ConversationSelection.parse(named), owner="preset"
        )
        assert first == f"conversation:{named}"
        with pytest.raises(AgentRuntimeError) as raised:
            await registry.acquire(
                home, ConversationSelection.parse(named), owner="preset"
            )
        assert raised.value.code == "external_agent_conversation_busy"

        # A different conversation in the same HOME runs in parallel.
        other = await registry.acquire(
            home, ConversationSelection.parse(str(uuid4())), owner="preset"
        )
        assert other is not None
        with pytest.raises(AgentRuntimeError):
            await registry.acquire(
                home, ConversationSelection.parse("continue-latest"), owner="preset"
            )

        # ``new`` never conflicts, and releasing frees the named conversation.
        assert (
            await registry.acquire(
                home, ConversationSelection.parse("new"), owner="preset"
            )
            is None
        )
        await registry.release(home, other)
        await registry.release(home, first)
        reacquired = await registry.acquire(
            home, ConversationSelection.parse(named), owner="preset"
        )
        assert reacquired == f"conversation:{named}"
        await registry.release(home, reacquired)

    asyncio.run(scene())


def test_runner_records_success_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = str(uuid4())
    binary = write_fake_cli(
        tmp_path,
        stdout_lines=[
            init_envelope(conversation_id),
            stream_envelope(
                "step_update",
                {
                    "conversation_id": conversation_id,
                    "step_index": 1,
                    "state": "ACTIVE",
                    "step_type": "agent_response",
                    "text_delta": "PONG",
                },
            ),
            result_envelope(conversation_id),
        ],
    )
    runner = make_runner(tmp_path, monkeypatch, fake_binary(binary))
    seen: list[str] = []

    result = run_agent(
        runner,
        external_agent_profile(),
        on_event=lambda event: seen.append(event.kind),
    )

    assert result.status == "success"
    assert result.response == "PONG"
    assert result.conversation_id == conversation_id
    assert result.conversation_reused is False
    assert result.exit_code == 0
    assert result.usage["total_tokens"] == 12
    assert result.error_code is None
    assert seen[0] == "run_started"
    assert "session_resolved" in seen
    assert seen[-1] == "run_finished"

    session = Path(result.session_directory)
    events = [
        json.loads(line)
        for line in Path(result.event_log).read_text(encoding="utf-8").splitlines()
    ]
    assert [event["kind"] for event in events][:4] == [
        "run_started",
        "session_initialized",
        "session_resolved",
        "text_delta",
    ]
    assert events[-1]["kind"] == "run_finished"
    assert events[-1]["payload"]["status"] == "success"

    meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
    assert len(str(meta["definition_revision"])) == 8
    assert meta["conversation_reused"] is False
    assert meta["binary_version"] == "test"
    assert meta["status"] == "success"
    assert meta["conversation_id"] == conversation_id
    assert Path(str(meta["home_path"])).is_dir()
    assert Path(str(meta["workspace_path"])).is_dir()
    assert Path(result.stderr_log).read_text(encoding="utf-8") == ""
    stored = json.loads(Path(result.result_file).read_text(encoding="utf-8"))
    assert stored["response"] == "PONG"
    assert stored["status"] == "success"


def test_runner_classifies_denied_and_unknown_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = str(uuid4())
    actual = str(uuid4())
    binary = write_fake_cli(
        tmp_path,
        stdout_lines=[
            init_envelope(actual),
            result_envelope(actual, response=""),
        ],
        stderr_lines=[HEADLESS_DENIAL],
    )
    runner = make_runner(tmp_path, monkeypatch, fake_binary(binary))

    result = run_agent(
        runner,
        external_agent_profile(),
        conversation=requested,
        on_event=None,
    )

    assert result.status == "denied"
    assert result.error_code == "external_agent_permission_denied"
    assert result.denied_actions == ("command",)
    assert result.conversation_requested == requested
    assert result.conversation_id == actual
    assert result.conversation_reused is False


def test_runner_reports_print_timeout_as_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = str(uuid4())
    binary = write_fake_cli(
        tmp_path,
        stdout_lines=[
            init_envelope(conversation_id),
            result_envelope(conversation_id, response=""),
        ],
        stderr_lines=[PRINT_TIMEOUT_NOTICE],
    )
    runner = make_runner(tmp_path, monkeypatch, fake_binary(binary))

    result = run_agent(runner, external_agent_profile(), on_event=None)

    assert result.status == "timeout"
    assert result.error_code == "external_agent_print_timeout"
    assert result.exit_code == 0
    assert "returning partial output" in Path(result.stderr_log).read_text(
        encoding="utf-8"
    )


def test_runner_kills_process_at_watchdog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32" and not Path("/bin/sleep").exists():
        pytest.skip("no sleep binary for the stalling fake CLI")
    conversation_id = str(uuid4())
    binary = write_fake_cli(
        tmp_path,
        stdout_lines=[init_envelope(conversation_id)],
        sleep_seconds=30,
    )
    monkeypatch.setattr(runtime_module, "WATCHDOG_GRACE_SECONDS", 0)
    runner = make_runner(tmp_path, monkeypatch, fake_binary(binary))

    result = run_agent(
        runner,
        external_agent_profile(print_timeout="1s"),
        on_event=None,
    )

    assert result.status == "timeout"
    assert result.error_code == "external_agent_watchdog_timeout"
    assert result.exit_code is None
    assert result.usage == {}
