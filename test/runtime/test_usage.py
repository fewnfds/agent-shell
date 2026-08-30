from __future__ import annotations

from agent_shell.runtime.usage import RunUsageAccumulator


def test_run_usage_accumulator_merges_growth_once_per_model_run() -> None:
    usage = RunUsageAccumulator()

    usage.merge(
        "model-1",
        {
            "input_tokens": 2,
            "output_tokens": 1,
            "total_tokens": 3,
            "output_token_details": {"reasoning": 1},
        },
    )
    usage.merge(
        "model-1",
        {
            "input_tokens": 4,
            "output_tokens": 2,
            "total_tokens": 6,
            "output_token_details": {"reasoning": 2},
        },
    )
    usage.merge(
        "model-2",
        {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    )

    assert usage.snapshot == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "reasoning_tokens": 2,
    }


def test_run_usage_accumulator_ignores_invalid_and_decreasing_snapshots() -> None:
    usage = RunUsageAccumulator()
    usage.merge("model-1", {"input_tokens": 4, "output_tokens": 2})
    usage.merge(
        "model-1",
        {"input_tokens": 1, "output_tokens": -1, "total_tokens": "6"},
    )

    assert usage.snapshot == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 0,
    }
