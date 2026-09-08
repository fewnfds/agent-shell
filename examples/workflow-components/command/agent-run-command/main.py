"""Start, inspect, join, or cancel one independent Agent Run."""

from langgraph.types import Command


_ACTIONS = {"start", "check", "get", "join", "cancel"}
_RESULT_FIELDS = (
    "operation_id",
    "caller_run_id",
    "main_agent_id",
    "main_agent_name",
    "assistant_id",
    "thread_id",
    "run_id",
    "status",
    "output",
)


def _required_text(request, key):
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"shared_vars.agent_run.{key} must be a non-empty string")
    return value.strip()


def _project(result):
    return {
        field: getattr(result, field)
        for field in _RESULT_FIELDS
        if hasattr(result, field)
    }


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        request = shared_vars.get("agent_run") if isinstance(shared_vars, dict) else None
        if not isinstance(request, dict):
            raise ValueError("shared_vars.agent_run must be an object")
        target = _required_text(request, "target_node_id")
        action = _required_text(request, "action")
        if action not in _ACTIONS:
            raise ValueError("shared_vars.agent_run.action is unsupported")

        facade = getattr(runtime.context, "agent_runs", None)
        if facade is None:
            raise RuntimeError("runtime.context.agent_runs is not configured")

        if action == "start":
            main_agent_id = _required_text(request, "main_agent_id")
            operation_id = _required_text(request, "operation_id")
            if "input" not in request:
                raise ValueError("shared_vars.agent_run.input is required")
            thread_id = request.get("thread_id")
            if thread_id is not None and (
                not isinstance(thread_id, str) or not thread_id.strip()
            ):
                raise ValueError(
                    "shared_vars.agent_run.thread_id must be a non-empty string when set"
                )
            result = await facade.start(
                main_agent_id,
                request["input"],
                operation_id=operation_id,
                thread_id=thread_id.strip() if isinstance(thread_id, str) else None,
            )
        else:
            thread_id = _required_text(request, "thread_id")
            run_id = _required_text(request, "run_id")
            result = await getattr(facade, action)(thread_id, run_id)

        return Command(
            update={
                "shared_vars": {
                    "agent_run_result": {
                        "action": action,
                        "run": _project(result),
                    }
                }
            },
            goto=target,
        )

    return command
