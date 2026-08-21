"""Built-in rule-based Command example.

This editable example reads ``state["shared_vars"]["score"]`` and activates
``matched`` when the numeric score is at least 60, otherwise
``below_threshold``. It also writes ``shared_vars.last_route`` and emits a
custom stream event before returning. Connect Branch Edges with those two
branch keys; the names, score field, threshold, and State update are example
policy rather than platform requirements.

The stable package contract is a synchronous no-argument ``create_command()``
factory returning an async ``command(state, runtime)``. The callable may use
Workflow State, ``runtime.context``, ``runtime.store``, and
``get_stream_writer()``. It returns ``activate`` and ``update`` data, not a
LangGraph ``Command`` object. This package has no third-party dependencies, so
``requirements.txt`` stays empty.
"""

from langgraph.config import get_stream_writer


MATCHED_BRANCH = "matched"
BELOW_THRESHOLD_BRANCH = "below_threshold"
SCORE_THRESHOLD = 60


def create_command():
    async def command(state, runtime):
        # Example only: replace this selection and rule with the Workflow's
        # actual State and Runtime Context inputs.
        shared_vars = state.get("shared_vars", {})
        score = shared_vars.get("score") if isinstance(shared_vars, dict) else None
        is_number = isinstance(score, (int, float)) and not isinstance(score, bool)
        branch = (
            MATCHED_BRANCH
            if is_number and score >= SCORE_THRESHOLD
            else BELOW_THRESHOLD_BRANCH
        )
        get_stream_writer()(f"Command selected branch {branch}.\n")
        return {
            "activate": [branch],
            # Command may update any top-level channel declared by WorkflowState.
            "update": {"shared_vars": {"last_route": branch}},
        }

    return command
