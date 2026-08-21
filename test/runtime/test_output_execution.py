from __future__ import annotations

from .support import *


def test_execution_yields_each_completed_semantic_event_once() -> None:
    async def scenario() -> tuple[list[str], dict[str, int]]:
        output = output_renderer({
            "assistant_text": "[T]{{message}}[/T]",
            "reasoning": "[R]{{message}}[/R]",
            "custom": "[C]{{message}}[/C]",
        })
        events = [
            message_envelope(
                {"event": "message-start", "role": "ai", "id": "message-1"}
            ),
            message_envelope(
                {
                    "event": "content-block-start",
                    "index": 0,
                    "content": {"type": "reasoning", "reasoning": ""},
                }
            ),
            message_envelope(
                {
                    "event": "content-block-delta",
                    "index": 0,
                    "delta": {
                        "type": "reasoning-delta",
                        "reasoning": "partial",
                    },
                }
            ),
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 0,
                    "content": {"type": "reasoning", "reasoning": "thought"},
                }
            ),
            {
                "method": "custom",
                "params": {"namespace": [], "timestamp": 2, "data": "working"},
            },
            message_envelope(
                {
                    "event": "content-block-finish",
                    "index": 1,
                    "content": {"type": "text", "text": "answer"},
                }
            ),
            message_envelope(
                {
                    "event": "message-finish",
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 4,
                        "total_tokens": 6,
                    },
                }
            ),
        ]
        execution = RunExecution(
            graph=EventGraph(events),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        parts = [part async for part in execution.stream_text()]
        return parts, execution.usage

    parts, usage = asyncio.run(scenario())

    assert parts == [
        "[R]thought[/R]",
        "[C]\"working\"[/C]",
        "[T]answer[/T]",
    ]
    assert usage == {"input_tokens": 2, "output_tokens": 4, "total_tokens": 6}


def test_non_string_lifecycle_output_stays_behind_the_runtime_error_boundary() -> None:
    async def scenario() -> None:
        execution = RunExecution(
            graph=EventGraph([]),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(OutputProjector(lambda event: event)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
        )
        with pytest.raises(AgentRuntimeError) as captured:
            _ = [part async for part in execution.stream_text()]
        assert captured.value.code == "event_output.execution_failed"

    asyncio.run(scenario())


def test_unguarded_event_field_failure_keeps_the_original_diagnostic() -> None:
    async def scenario() -> tuple[str, BaseException | None]:
        class RecordingDiagnostics:
            detail_exception: BaseException | None = None

            def runtime_error(
                self,
                _exc,
                *,
                detail_exception: BaseException | None = None,
                **_kwargs,
            ) -> None:
                self.detail_exception = detail_exception

        def output(event: dict[str, object]) -> str:
            return str(event["tool_name"])

        diagnostics = RecordingDiagnostics()
        execution = RunExecution(
            graph=EventGraph([]),
            input_state={"messages": []},
            rectifier=OutputEventRectifier(OutputProjector(output)),
            normalizer=V3EventNormalizer("Main Agent"),
            middleware_runtime=noop_middleware_runtime(),
            media_response=noop_media_response(),
            runtime_diagnostics=diagnostics,  # type: ignore[arg-type]
        )
        with pytest.raises(AgentRuntimeError) as captured:
            _ = [part async for part in execution.stream_text()]
        return captured.value.code, diagnostics.detail_exception

    code, detail_exception = asyncio.run(scenario())

    assert code == "event_output.execution_failed"
    assert isinstance(detail_exception, KeyError)


def test_model_response_observer_keeps_full_safe_source_data_per_call() -> None:
    responses = []
    normalizer = V3EventNormalizer(
        "Main Agent", model_response_observers=(responses.append,)
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "message-start",
                "role": "ai",
                "id": "message-1",
                "metadata": {"provider": "deepseek", "model": "reasoner"},
            }
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "reasoning", "reasoning": "full thought"},
            }
        )
    )
    normalizer.feed(
        message_envelope(
            {
                "event": "message-finish",
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                    "output_token_details": {"reasoning": 2},
                },
                "metadata": {
                    "finish_reason": "length",
                    "model_name": "reasoner",
                    "system_fingerprint": "fp-1",
                    "logprobs": {"content": []},
                },
                "additional_kwargs": {"reasoning_content": "full thought"},
            }
        )
    )

    assert len(responses) == 1
    response = responses[0]
    assert response.provider_finish_reason == "length"
    assert response.finish_reason_source == "response_metadata.finish_reason"
    assert response.usage["output_token_details"] == {"reasoning": 2}
    assert response.response_metadata["system_fingerprint"] == "fp-1"
    assert response.additional_kwargs == {"reasoning_content": "full thought"}
    assert response.content_blocks == [
        {"type": "reasoning", "reasoning": "full thought"}
    ]
    assert normalizer.finish_reason == "length"


def test_last_main_agent_model_call_owns_external_finish_reason() -> None:
    normalizer = V3EventNormalizer("Main Agent")
    for run_id, reason in (("run-tools", "tool_calls"), ("run-final", "stop")):
        normalizer.feed(
            message_envelope(
                {"event": "message-start", "role": "ai", "id": run_id},
                run_id=run_id,
            )
        )
        normalizer.feed(
            message_envelope(
                {
                    "event": "message-finish",
                    "usage": {},
                    "metadata": {"finish_reason": reason},
                },
                run_id=run_id,
            )
        )

    assert normalizer.finish_reason == "stop"
    assert normalizer.finish_reason_source == "response_metadata.finish_reason"
