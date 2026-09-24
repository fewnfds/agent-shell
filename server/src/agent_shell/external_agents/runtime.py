"""Run one Antigravity CLI process per conversation and record its evidence.

The runner owns subprocess creation, stream normalization, the timeout ladder,
and the in-process guard that keeps two writers out of one conversation. It
never talks to a model API directly: everything goes through the pinned CLI
binary inside the Lifecycle's isolated HOME.
"""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from agent_shell.configuration.identity import is_configuration_id
from agent_shell.contracts import ExternalAgentProfile
from agent_shell.external_agents.binary import resolved_antigravity_cli
from agent_shell.external_agents.contracts import (
    CONTINUE_LATEST_CONVERSATION,
    NEW_CONVERSATION,
    ExternalAgentRunEvent,
    ExternalAgentRunResult,
    ExternalAgentRunStatus,
)
from agent_shell.external_agents.errors import (
    conversation_busy,
    conversation_invalid,
    system_prompt_changed,
)
from agent_shell.external_agents.layout import (
    AntigravityLifecycleLayout,
    AntigravitySessionLayout,
    antigravity_lifecycle_layout,
    new_session_id,
)
from agent_shell.external_agents.materialize import (
    MaterializedExternalAgent,
    materialize_external_agent,
)
from agent_shell.storage.atomic_files import write_text_atomic


TIMEOUT_PATTERN = re.compile(r"^([1-9][0-9]*)(s|m|h)$")
TIMEOUT_UNITS = {"s": 1, "m": 60, "h": 3600}
# 1.2.4 prints this to stderr when ``--print-timeout`` truncates a turn while
# still exiting 0 with ``status=SUCCESS``.
TRUNCATION_MARKER = "returning partial output"
# 1.2.4 prints this to stderr when headless mode auto-denies a tool. It is the
# only denial signal the ``text`` output format carries.
DENIAL_MARKER = "headless mode cannot prompt for, so it was auto-denied"
DENIAL_PERMISSION_PATTERN = re.compile(r'required the "([^"]+)" permission')
WATCHDOG_GRACE_SECONDS = 60
LATEST_CLAIM = "continue-latest"
READ_CHUNK_BYTES = 4096
PROCESS_EXIT_WAIT_SECONDS = 15


@dataclass(frozen=True)
class ConversationSelection:
    """What the caller asked for, before the CLI resolves a real id."""

    requested: str
    explicit_id: str | None = None

    @classmethod
    def parse(cls, value: str) -> "ConversationSelection":
        if value == NEW_CONVERSATION:
            return cls(requested=NEW_CONVERSATION)
        if value == CONTINUE_LATEST_CONVERSATION:
            return cls(requested=CONTINUE_LATEST_CONVERSATION)
        if not is_configuration_id(value):
            raise conversation_invalid(
                "conversation must be 'new', 'continue-latest', or a "
                f"conversation id returned by a previous run; received {value!r}."
            )
        return cls(requested=value, explicit_id=value)

    @property
    def claim(self) -> str | None:
        if self.explicit_id is not None:
            return f"conversation:{self.explicit_id}"
        if self.requested == CONTINUE_LATEST_CONVERSATION:
            return LATEST_CLAIM
        return None


@dataclass
class _StreamState:
    status: str | None = None
    result_response: str = ""
    text_parts: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    denied_actions: tuple[str, ...] = ()
    error_message: str | None = None

    @property
    def response(self) -> str:
        return self.result_response or "".join(self.text_parts)


@dataclass(frozen=True)
class _ProcessOutcome:
    exit_code: int | None
    timed_out: bool
    stderr_text: str
    status: str | None
    response: str
    conversation_id: str | None
    usage: Mapping[str, int]
    denied_actions: tuple[str, ...]
    error_message: str | None


def cli_timeout_seconds(duration: str) -> int:
    match = TIMEOUT_PATTERN.fullmatch(duration)
    if match is None:
        raise conversation_invalid(
            f"print_timeout must look like 90s, 5m, or 1h; received {duration!r}."
        )
    return int(match.group(1)) * TIMEOUT_UNITS[match.group(2)]


def watchdog_seconds(duration: str) -> int:
    """Outer process guard, one grace period after the CLI's own timeout."""

    return cli_timeout_seconds(duration) + WATCHDOG_GRACE_SECONDS


def build_antigravity_argv(
    *,
    binary_path: Path,
    profile: ExternalAgentProfile,
    definition_name: str,
    workspace: Path,
    prompt: str,
    selection: ConversationSelection,
) -> list[str]:
    argv = [
        str(binary_path),
        "-p",
        prompt,
        "--output-format",
        profile.output_format,
        "--agent",
        definition_name,
        "--add-dir",
        str(workspace),
        "--print-timeout",
        profile.print_timeout,
    ]
    if profile.model:
        argv.extend(["--model", profile.model])
    if profile.effort:
        argv.extend(["--effort", profile.effort])
    if selection.explicit_id is not None:
        argv.extend(["--conversation", selection.explicit_id])
    elif selection.requested == CONTINUE_LATEST_CONVERSATION:
        argv.append("-c")
    return argv


def denied_action_labels(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    labels: list[str] = []
    for entry in value:
        if isinstance(entry, Mapping):
            label = entry.get("display_name") or entry.get("action")
            labels.append(
                label if isinstance(label, str) and label else json.dumps(entry)
            )
        elif isinstance(entry, str):
            labels.append(entry)
        else:
            labels.append(json.dumps(entry, default=str))
    return tuple(labels)


def denied_permissions_from_stderr(text: str) -> tuple[str, ...]:
    """Recover denied permission kinds from the CLI's headless denial notice."""

    if DENIAL_MARKER not in text:
        return ()
    permissions = DENIAL_PERMISSION_PATTERN.findall(text)
    if not permissions:
        return ("unknown",)
    return tuple(dict.fromkeys(permissions))


def _usage_fields(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(item, int) and not isinstance(item, bool)
    }


def _normalize_step(body: Mapping[str, object]) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    state = body.get("state")
    text = body.get("text_delta")
    if isinstance(text, str) and text:
        events.append(("text_delta", {"text": text}))
    subagent = body.get("subagent_info")
    if isinstance(subagent, Mapping):
        events.append(("subagent", dict(subagent)))
    tool_info = body.get("tool_info")
    tool_name = body.get("tool_name")
    if isinstance(tool_info, Mapping) or isinstance(tool_name, str):
        info = tool_info if isinstance(tool_info, Mapping) else {}
        name = tool_name if isinstance(tool_name, str) else str(info.get("name") or "")
        if state == "ACTIVE":
            events.append(
                (
                    "tool_call",
                    {
                        "name": name,
                        "step_index": body.get("step_index"),
                        "parameters": info.get("parameters"),
                    },
                )
            )
        elif state in {"DONE", "ERROR"}:
            error = info.get("error")
            message = error.get("message") if isinstance(error, Mapping) else None
            events.append(
                (
                    "tool_result",
                    {
                        "name": name,
                        "step_index": body.get("step_index"),
                        "ok": state == "DONE",
                        "error": message,
                        "has_output": "output" in info,
                    },
                )
            )
    usage = _usage_fields(body.get("usage"))
    if usage:
        events.append(("usage", dict(usage)))
    return events


def _normalize_result(body: Mapping[str, object]) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = [
        (
            "result",
            {
                "conversation_id": body.get("conversation_id"),
                "status": body.get("status"),
                "response": body.get("response"),
                "num_turns": body.get("num_turns"),
                "duration_seconds": body.get("duration_seconds"),
                "error": body.get("error"),
                "usage": _usage_fields(body.get("usage")),
            },
        )
    ]
    actions = denied_action_labels(body.get("denied_actions"))
    if actions:
        events.append(("denied_actions", {"actions": list(actions)}))
    return events


def normalize_cli_event(
    payload: Mapping[str, object],
) -> list[tuple[str, dict[str, object]]]:
    """Translate one ``stream-json`` envelope into our event vocabulary."""

    name = payload.get("event")
    body = payload.get(name) if isinstance(name, str) else None
    if not isinstance(body, Mapping):
        return []
    if name == "init":
        return [
            (
                "session_initialized",
                {
                    "conversation_id": body.get("conversation_id"),
                    "cwd": body.get("cwd"),
                    "permission_mode": body.get("permission_mode"),
                },
            )
        ]
    if name == "step_update":
        return _normalize_step(body)
    if name == "result":
        return _normalize_result(body)
    return []


def classify_run(
    *,
    exit_code: int | None,
    status: str | None,
    denied_actions: tuple[str, ...],
    timed_out: bool,
    truncated: bool,
) -> ExternalAgentRunStatus:
    """Distinguish the four terminal states the caller must act on."""

    if timed_out or truncated:
        return "timeout"
    if exit_code != 0:
        return "failed"
    if status is not None and status != "SUCCESS":
        return "failed"
    if denied_actions:
        return "denied"
    return "success"


class _EventRecorder:
    def __init__(
        self,
        session: AntigravitySessionLayout,
        on_event: Callable[[ExternalAgentRunEvent], None] | None,
    ) -> None:
        self._session = session
        self._on_event = on_event
        self._stream = None

    def __enter__(self) -> "_EventRecorder":
        self._stream = self._session.event_log.open("a", encoding="utf-8")
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def emit(self, kind: str, payload: Mapping[str, object]) -> None:
        event = ExternalAgentRunEvent(
            kind=kind,
            payload=dict(payload),
            at=datetime.now(UTC).isoformat(),
        )
        record = json.dumps(event.as_record(), ensure_ascii=False, default=str)
        if self._stream is not None:
            self._stream.write(record + "\n")
            self._stream.flush()
        if self._on_event is not None:
            self._on_event(event)


async def _collect_stderr(stream: asyncio.StreamReader, path: Path) -> str:
    chunks: list[bytes] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as log:
        while True:
            chunk = await stream.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
            log.write(chunk)
            log.flush()
    return b"".join(chunks).decode("utf-8", errors="replace")


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """Stop the CLI and everything it spawned, then reap the handle."""

    if process.returncode is not None:
        return
    if os.name == "nt":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            await killer.wait()
        except OSError:
            pass
    else:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), PROCESS_EXIT_WAIT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()


def recorded_definition_revision(
    layout: AntigravityLifecycleLayout,
    conversation_id: str,
) -> str | None:
    """Return the definition revision that created a recorded conversation."""

    if not layout.sessions.is_dir():
        return None
    for directory in sorted(layout.sessions.iterdir()):
        meta_file = directory / "meta.json"
        if not meta_file.is_file():
            continue
        try:
            document = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(document, Mapping):
            continue
        if document.get("conversation_id") != conversation_id:
            continue
        revision = document.get("definition_revision")
        if isinstance(revision, str) and revision:
            return revision
    return None


class ConversationRegistry:
    """In-process guard: at most one writer per conversation inside one HOME.

    ``new`` calls can run together because the CLI allocates fresh conversations,
    but they still participate in the HOME-wide ``continue-latest`` claim.
    A named conversation conflicts with itself, and ``continue-latest``
    targets whichever conversation it finds, so it owns the whole HOME.
    Cross-instance sharing of one data directory is out of scope.
    """

    def __init__(self) -> None:
        self._active: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def acquire(
        self,
        home: Path,
        selection: ConversationSelection,
        *,
        owner: str,
    ) -> str | None:
        claim = selection.claim or f"new:{uuid4()}"
        key = str(home)
        async with self._lock:
            active = self._active.get(key)
            if active is None:
                active = set()
                self._active[key] = active
            conflict = (
                bool(active)
                if claim == LATEST_CLAIM
                else claim in active or LATEST_CLAIM in active
            )
            if conflict:
                raise conversation_busy(
                    f"External Agent {owner!r} is already running "
                    f"conversation {selection.requested!r} in {key}."
                )
            active.add(claim)
        return claim

    async def release(self, home: Path, claim: str | None) -> None:
        if claim is None:
            return
        key = str(home)
        async with self._lock:
            active = self._active.get(key)
            if active is None:
                return
            active.discard(claim)
            if not active:
                self._active.pop(key, None)


class AntigravityRunner:
    """Owns process execution and the in-process conversation guard."""

    def __init__(
        self,
        *,
        data_root: Path,
        runtime_root: Path,
        host_environment: Mapping[str, str] | None = None,
    ) -> None:
        self._data_root = Path(data_root)
        self._runtime_root = Path(runtime_root)
        self._host_environment = dict(
            os.environ if host_environment is None else host_environment
        )
        self._conversations = ConversationRegistry()

    async def run(
        self,
        profile: ExternalAgentProfile,
        *,
        external_agent_id: str,
        lifecycle_id: str,
        prompt: str,
        conversation: str | None = None,
        on_event: Callable[[ExternalAgentRunEvent], None] | None = None,
    ) -> ExternalAgentRunResult:
        selection = ConversationSelection.parse(conversation or profile.conversation)
        binary = await asyncio.to_thread(
            resolved_antigravity_cli, self._runtime_root
        )
        layout = antigravity_lifecycle_layout(
            self._data_root, external_agent_id, lifecycle_id
        )
        claim = await self._conversations.acquire(
            layout.home, selection, owner=profile.name
        )
        try:
            materialized = await asyncio.to_thread(
                materialize_external_agent,
                profile,
                layout,
                host_environment=self._host_environment,
            )
            self._guard_recorded_prompt(layout, selection, profile, materialized)
            return await self._execute(
                profile,
                layout=layout,
                materialized=materialized,
                binary_path=binary.path,
                binary_version=binary.version,
                binary_sha256=binary.sha256,
                external_agent_id=external_agent_id,
                prompt=prompt,
                selection=selection,
                on_event=on_event,
            )
        finally:
            await self._conversations.release(layout.home, claim)

    def _guard_recorded_prompt(
        self,
        layout: AntigravityLifecycleLayout,
        selection: ConversationSelection,
        profile: ExternalAgentProfile,
        materialized: MaterializedExternalAgent,
    ) -> None:
        if selection.explicit_id is None:
            return
        recorded = recorded_definition_revision(layout, selection.explicit_id)
        if recorded is None or recorded == materialized.definition_revision:
            return
        raise system_prompt_changed(
            f"Conversation {selection.explicit_id} was created with a different "
            f"system prompt for External Agent {profile.name!r} "
            f"({recorded} != {materialized.definition_revision}). Start a new "
            "conversation to use the edited prompt."
        )

    async def _execute(
        self,
        profile: ExternalAgentProfile,
        *,
        layout: AntigravityLifecycleLayout,
        materialized: MaterializedExternalAgent,
        binary_path: Path,
        binary_version: str,
        binary_sha256: str,
        external_agent_id: str,
        prompt: str,
        selection: ConversationSelection,
        on_event: Callable[[ExternalAgentRunEvent], None] | None,
    ) -> ExternalAgentRunResult:
        session_id = new_session_id()
        session = layout.session(session_id)
        session.create()
        argv = build_antigravity_argv(
            binary_path=binary_path,
            profile=profile,
            definition_name=materialized.definition_name,
            workspace=layout.workspace,
            prompt=prompt,
            selection=selection,
        )
        started_at = datetime.now(UTC).isoformat()
        meta: dict[str, object] = {
            "session_id": session_id,
            "external_agent_id": external_agent_id,
            "external_agent_name": profile.name,
            "provider": profile.provider,
            "agent_name": profile.agent_name,
            "definition_name": materialized.definition_name,
            "definition_revision": materialized.definition_revision,
            "model": profile.model,
            "effort": profile.effort,
            "output_format": profile.output_format,
            "conversation_requested": selection.requested,
            "conversation_id": None,
            "status": "running",
            "binary_path": str(binary_path),
            "binary_version": binary_version,
            "binary_sha256": binary_sha256,
            "home_path": str(layout.home),
            "workspace_path": str(layout.workspace),
            "started_at": started_at,
            "finished_at": None,
            "event_log": str(session.event_log),
            "stderr_log": str(session.stderr_log),
            "result_file": str(session.result_file),
        }
        started = time.monotonic()
        with _EventRecorder(session, on_event) as recorder:
            write_text_atomic(
                session.meta_file,
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            )
            recorder.emit(
                "run_started",
                {
                    "session_id": session_id,
                    "conversation_requested": selection.requested,
                    "definition_name": materialized.definition_name,
                    "workspace": str(layout.workspace),
                    "started_at": started_at,
                },
            )
            try:
                outcome = await self._stream(
                    profile,
                    argv=argv,
                    environment=materialized.environment,
                    layout=layout,
                    session=session,
                    recorder=recorder,
                    selection=selection,
                )
            except BaseException:
                self._record_failure(
                    session=session,
                    meta=meta,
                    recorder=recorder,
                    message="The Antigravity CLI process was interrupted.",
                )
                raise
            status = classify_run(
                exit_code=outcome.exit_code,
                status=outcome.status,
                denied_actions=outcome.denied_actions,
                timed_out=outcome.timed_out,
                truncated=TRUNCATION_MARKER in outcome.stderr_text,
            )
            error_code, error_message = self._describe(status, outcome)
            duration_ms = int((time.monotonic() - started) * 1000)
            result = ExternalAgentRunResult(
                status=status,
                response=outcome.response,
                conversation_id=outcome.conversation_id or "",
                conversation_requested=selection.requested,
                conversation_reused=self._reused(selection, outcome.conversation_id),
                exit_code=outcome.exit_code,
                duration_ms=duration_ms,
                usage=dict(outcome.usage),
                denied_actions=outcome.denied_actions,
                error_code=error_code,
                error_message=error_message,
                session_directory=str(session.root),
                event_log=str(session.event_log),
                stderr_log=str(session.stderr_log),
                result_file=str(session.result_file),
            )
            self._finalize(
                session=session,
                meta=meta,
                recorder=recorder,
                result=result,
            )
            return result

    def _describe(
        self,
        status: ExternalAgentRunStatus,
        outcome: _ProcessOutcome,
    ) -> tuple[str | None, str | None]:
        if status == "timeout":
            if outcome.timed_out:
                return (
                    "external_agent_watchdog_timeout",
                    "The Antigravity CLI output or process did not complete "
                    "before the process watchdog stopped it.",
                )
            return (
                "external_agent_print_timeout",
                "The Antigravity CLI returned partial output at its print "
                "timeout; the response is not a complete turn.",
            )
        if status == "failed":
            return (
                "external_agent_run_failed",
                outcome.error_message
                or f"The Antigravity CLI exited with code {outcome.exit_code}.",
            )
        if status == "denied":
            actions = ", ".join(outcome.denied_actions)
            return (
                "external_agent_permission_denied",
                f"The Antigravity CLI was denied {actions}. Add the matching "
                "permission rule to the preset to let it proceed.",
            )
        return None, None

    def _reused(
        self,
        selection: ConversationSelection,
        conversation_id: str | None,
    ) -> bool | None:
        if selection.explicit_id is not None:
            return conversation_id == selection.explicit_id
        if selection.requested == NEW_CONVERSATION:
            return False
        return None

    async def _stream(
        self,
        profile: ExternalAgentProfile,
        *,
        argv: list[str],
        environment: Mapping[str, str],
        layout: AntigravityLifecycleLayout,
        session: AntigravitySessionLayout,
        recorder: _EventRecorder,
        selection: ConversationSelection,
    ) -> _ProcessOutcome:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(layout.workspace),
            env=dict(environment),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stderr_task = asyncio.create_task(
            _collect_stderr(process.stderr, session.stderr_log)
        )
        state = _StreamState()
        buffer = b""
        timed_out = False
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            async with asyncio.timeout(watchdog_seconds(profile.print_timeout)):
                while True:
                    chunk = await process.stdout.read(READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    if profile.output_format == "text":
                        text = decoder.decode(chunk)
                        if not text:
                            continue
                        state.text_parts.append(text)
                        recorder.emit("text_delta", {"text": text})
                        continue
                    buffer += chunk
                    if profile.output_format == "json":
                        continue
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        self._consume_envelope(
                            line, state, recorder, selection
                        )
                # Process.wait() can remain pending after CLI exit if a
                # descendant still holds an inherited stderr pipe.
                while process.returncode is None:
                    await asyncio.sleep(0.1)
                exit_code = await process.wait()
                # Let the collector flush any stderr already delivered before
                # stopping it when a descendant keeps the pipe open.
                await asyncio.sleep(0)
        except TimeoutError:
            timed_out = True
            await _terminate_process(process)
            exit_code = process.returncode
        except BaseException:
            await _terminate_process(process)
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task
            raise
        if stderr_task.done() and not stderr_task.cancelled():
            stderr_text = stderr_task.result()
        else:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task
            stderr_text = await asyncio.to_thread(
                session.stderr_log.read_text, encoding="utf-8", errors="replace"
            )
        if profile.output_format == "text":
            tail = decoder.decode(b"", final=True)
            if tail:
                state.text_parts.append(tail)
                recorder.emit("text_delta", {"text": tail})
        remaining = buffer
        if not timed_out:
            if profile.output_format == "stream-json" and remaining.strip():
                self._consume_envelope(remaining, state, recorder, selection)
            elif profile.output_format == "json" and remaining.strip():
                self._consume_json_result(remaining, state, recorder, selection)
        denied_actions = state.denied_actions or denied_permissions_from_stderr(
            stderr_text
        )
        return _ProcessOutcome(
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
            stderr_text=stderr_text,
            status=state.status,
            response=state.response,
            conversation_id=state.conversation_id,
            usage=dict(state.usage),
            denied_actions=denied_actions,
            error_message=state.error_message,
        )

    def _consume_envelope(
        self,
        line: bytes,
        state: _StreamState,
        recorder: _EventRecorder,
        selection: ConversationSelection,
    ) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            payload = json.loads(text)
        except ValueError:
            recorder.emit("stdout_unparsed", {"text": text})
            return
        if not isinstance(payload, Mapping):
            recorder.emit("stdout_unparsed", {"text": text})
            return
        for kind, body in normalize_cli_event(payload):
            recorder.emit(kind, body)
            self._apply_event(kind, body, state, recorder, selection)

    def _consume_json_result(
        self,
        payload_bytes: bytes,
        state: _StreamState,
        recorder: _EventRecorder,
        selection: ConversationSelection,
    ) -> None:
        text = payload_bytes.decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(text)
        except ValueError:
            recorder.emit("stdout_unparsed", {"text": text})
            return
        if not isinstance(payload, Mapping):
            recorder.emit("stdout_unparsed", {"text": text})
            return
        for kind, body in _normalize_result(payload):
            recorder.emit(kind, body)
            self._apply_event(kind, body, state, recorder, selection)

    def _apply_event(
        self,
        kind: str,
        body: Mapping[str, object],
        state: _StreamState,
        recorder: _EventRecorder,
        selection: ConversationSelection,
    ) -> None:
        if kind in {"session_initialized", "result"}:
            conversation_id = body.get("conversation_id")
            if isinstance(conversation_id, str) and conversation_id:
                self._note_conversation(
                    conversation_id, state, recorder, selection
                )
        if kind == "result":
            status = body.get("status")
            state.status = status if isinstance(status, str) else None
            response = body.get("response")
            state.result_response = response if isinstance(response, str) else ""
            usage = _usage_fields(body.get("usage"))
            if usage:
                state.usage = usage
            error = body.get("error")
            if isinstance(error, str) and error:
                state.error_message = error
            elif isinstance(error, Mapping):
                message = error.get("message")
                if isinstance(message, str) and message:
                    state.error_message = message
        elif kind == "denied_actions":
            actions = body.get("actions")
            if isinstance(actions, (list, tuple)):
                state.denied_actions = tuple(str(action) for action in actions)
        elif kind == "usage":
            state.usage = _usage_fields(body) or state.usage
        elif kind == "text_delta":
            text = body.get("text")
            if isinstance(text, str):
                state.text_parts.append(text)

    def _note_conversation(
        self,
        conversation_id: str,
        state: _StreamState,
        recorder: _EventRecorder,
        selection: ConversationSelection,
    ) -> None:
        if state.conversation_id == conversation_id:
            return
        state.conversation_id = conversation_id
        recorder.emit(
            "session_resolved",
            {
                "conversation_id": conversation_id,
                "conversation_requested": selection.requested,
                "reused": self._reused(selection, conversation_id),
            },
        )

    def _finalize(
        self,
        *,
        session: AntigravitySessionLayout,
        meta: dict[str, object],
        recorder: _EventRecorder,
        result: ExternalAgentRunResult,
    ) -> None:
        meta.update(
            {
                "status": result.status,
                "conversation_id": result.conversation_id,
                "conversation_reused": result.conversation_reused,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "usage": dict(result.usage),
                "denied_actions": list(result.denied_actions),
                "error_code": result.error_code,
                "error_message": result.error_message,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        write_text_atomic(
            session.meta_file,
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        )
        write_text_atomic(
            session.result_file,
            json.dumps(
                {
                    "status": result.status,
                    "response": result.response,
                    "conversation_id": result.conversation_id,
                    "conversation_requested": result.conversation_requested,
                    "conversation_reused": result.conversation_reused,
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "usage": dict(result.usage),
                    "denied_actions": list(result.denied_actions),
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        if result.error_code is not None:
            recorder.emit(
                "run_failed",
                {"code": result.error_code, "message": result.error_message},
            )
        recorder.emit(
            "run_finished",
            {
                "status": result.status,
                "exit_code": result.exit_code,
                "conversation_id": result.conversation_id,
                "duration_ms": result.duration_ms,
            },
        )

    def _record_failure(
        self,
        *,
        session: AntigravitySessionLayout,
        meta: dict[str, object],
        recorder: _EventRecorder,
        message: str,
    ) -> None:
        code = "external_agent_run_interrupted"
        meta.update(
            {
                "status": "failed",
                "error_code": code,
                "error_message": message,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        write_text_atomic(
            session.meta_file,
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        )
        write_text_atomic(
            session.result_file,
            json.dumps(
                {"status": "failed", "error_code": code, "error_message": message},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        recorder.emit("run_failed", {"code": code, "message": message})
        recorder.emit("run_finished", {"status": "failed", "exit_code": None})


__all__ = [
    "AntigravityRunner",
    "ConversationRegistry",
    "ConversationSelection",
    "DENIAL_MARKER",
    "TRUNCATION_MARKER",
    "WATCHDOG_GRACE_SECONDS",
    "build_antigravity_argv",
    "classify_run",
    "cli_timeout_seconds",
    "denied_action_labels",
    "denied_permissions_from_stderr",
    "normalize_cli_event",
    "recorded_definition_revision",
    "watchdog_seconds",
]
