"""Return an official Command that updates control state and selects a Node."""

from langgraph.config import get_stream_writer
from langgraph.types import Command


SCORE_THRESHOLD = 60


def create_command():
    async def command(state, runtime):
        del runtime
        shared_vars = state.get("shared_vars", {})
        score = shared_vars.get("score") if isinstance(shared_vars, dict) else None
        is_number = isinstance(score, (int, float)) and not isinstance(score, bool)
        target = "matched" if is_number and score >= SCORE_THRESHOLD else "below-threshold"
        get_stream_writer()(f"Command selected Node {target}.\n")
        return Command(
            update={"shared_vars": {"last_route": target}},
            goto=target,
        )

    return command
