"""Route to a Command Node ID selected from the service-local current time."""

from datetime import datetime

from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        del state, runtime
        now = datetime.now()
        second_unit = now.second % 10
        target = "first" if second_unit <= 3 else "second" if second_unit <= 6 else "last"
        return Command(
            update={
                "shared_vars": {
                    "current_time": now.isoformat(timespec="seconds"),
                }
            },
            goto=target,
        )

    return command
