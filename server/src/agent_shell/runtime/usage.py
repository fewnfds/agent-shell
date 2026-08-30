from __future__ import annotations

"""Run-local usage accumulation for LangGraph v3 message snapshots.

LangGraph can report usage more than once for a model invocation (for example
on both the whole ``AIMessage`` and ``message-finish`` events).  The protocol
payloads are snapshots, so the runtime owns one small accumulator that applies
only positive growth per model run and exposes the aggregate as a copy.
"""

from collections.abc import Mapping


class RunUsageAccumulator:
    """Accumulate token usage snapshots without double-counting a model run."""

    def __init__(self) -> None:
        self._usage_by_run: dict[str, dict[str, int]] = {}
        self._totals: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    @property
    def snapshot(self) -> dict[str, int]:
        """Return the aggregate usage without exposing mutable owner state."""

        return dict(self._totals)

    def merge(self, run_key: str, usage: object) -> None:
        """Merge a protocol usage snapshot for ``run_key``.

        Providers may omit fields or send a later snapshot with fewer fields;
        omitted values are ignored and totals never decrease.
        """

        if not isinstance(usage, Mapping):
            return
        current: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                current[key] = value
        output_details = usage.get("output_token_details")
        if isinstance(output_details, Mapping):
            reasoning = output_details.get("reasoning")
            if isinstance(reasoning, int) and reasoning >= 0:
                current["reasoning_tokens"] = reasoning

        previous = self._usage_by_run.setdefault(run_key, {})
        for key, value in current.items():
            previous_value = previous.get(key, 0)
            if value > previous_value:
                self._totals[key] = self._totals.get(key, 0) + value - previous_value
                previous[key] = value


__all__ = ["RunUsageAccumulator"]
