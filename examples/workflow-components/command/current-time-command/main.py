"""Built-in Command example.

This Command reads the service-local current time once, activates one Branch
Edge by the seconds digit, and writes the same ISO-8601 value to
``shared_vars.current_time``. Connect Branch Edges with keys ``first`` for
digits 0-3, ``second`` for digits 4-6, and ``last`` for digits 7-9. The value
is kept to second precision and uses the runtime host's local timezone.

The platform contract is ``create_command()`` returning an async
``command(state, runtime)``. The branch names and State field in this example
are application choices and should be changed to match the Workflow. The
package uses only the Python standard library, so ``requirements.txt`` stays
empty.
"""

from datetime import datetime


def create_command():
    current_time_key = "current_time"

    async def command(state, runtime):
        # 取一次本地时间，保证路由判断和写入 State 使用同一个时间点。
        now = datetime.now()
        second_unit = now.second % 10

        if second_unit <= 3:
            branch = "first"
        elif second_unit <= 6:
            branch = "second"
        else:
            branch = "last"

        return {
            "activate": [branch],
            "update": {
                "shared_vars": {
                    current_time_key: now.isoformat(timespec="seconds"),
                }
            },
        }

    return command
