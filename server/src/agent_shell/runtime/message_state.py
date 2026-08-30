from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class MessageRun:
    message_id: str
    main_agent_ai: bool
    public_ai: bool


class MessageRunRegistry:
    """Own message-shape state needed to deduplicate v3 stream projections."""

    def __init__(self) -> None:
        self._runs: dict[str, MessageRun] = {}
        self._active_main_runs: set[str] = set()
        self._streamed_run_keys: set[str] = set()

    @property
    def active_main_runs(self) -> frozenset[str]:
        return frozenset(self._active_main_runs)

    def begin(
        self,
        run_key: str,
        *,
        message_id: str,
        main_agent_ai: bool,
        public_ai: bool,
    ) -> None:
        self._runs[run_key] = MessageRun(
            message_id=message_id,
            main_agent_ai=main_agent_ai,
            public_ai=public_ai,
        )
        self._streamed_run_keys.add(run_key)
        if main_agent_ai:
            self._active_main_runs.add(run_key)

    def get(self, run_key: str) -> MessageRun | None:
        return self._runs.get(run_key)

    def was_streamed(self, run_key: str) -> bool:
        return run_key in self._streamed_run_keys

    def discard(self, run_key: str) -> None:
        self._runs.pop(run_key, None)
        self._active_main_runs.discard(run_key)


__all__ = ["MessageRun", "MessageRunRegistry"]
