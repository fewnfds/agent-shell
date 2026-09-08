"""Start, inspect, list, join, or cancel independent Workflow Runs."""

from langgraph.types import Command


_ACTIONS = {"start", "check", "list", "join", "cancel"}
_STATUSES = {"pending", "running", "error", "success", "timeout", "interrupted"}
_RESULT_FIELDS = (
    "operation_id",
    "caller_run_id",
    "workflow_id",
    "workflow_name",
    "assistant_id",
    "thread_id",
    "run_id",
    "status",
    "output",
)


def _required_text(request, key):
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"shared_vars.workflow_run.{key} must be a non-empty string")
    return value.strip()


def _run_ids(request):
    values = request.get("run_ids")
    if not isinstance(values, list) or not values:
        raise ValueError("shared_vars.workflow_run.run_ids must be a non-empty list")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("each shared_vars.workflow_run.run_ids entry must be a string")
    return [value.strip() for value in values]


def _project(result):
    return {
        field: getattr(result, field)
        for field in _RESULT_FIELDS
        if hasattr(result, field)
    }


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        request = (
            shared_vars.get("workflow_run") if isinstance(shared_vars, dict) else None
        )
        if not isinstance(request, dict):
            raise ValueError("shared_vars.workflow_run must be an object")
        target = _required_text(request, "target_node_id")
        action = _required_text(request, "action")
        if action not in _ACTIONS:
            raise ValueError("shared_vars.workflow_run.action is unsupported")

        facade = getattr(runtime.context, "workflow_runs", None)
        if facade is None:
            raise RuntimeError("runtime.context.workflow_runs is not configured")

        if action == "start":
            workflow_id = _required_text(request, "workflow_id")
            operation_id = _required_text(request, "operation_id")
            child_shared_vars = request.get("input_shared_vars", {})
            if not isinstance(child_shared_vars, dict):
                raise ValueError(
                    "shared_vars.workflow_run.input_shared_vars must be an object"
                )
            results = [
                await facade.start_workflow(
                    workflow_id,
                    operation_id=operation_id,
                    shared_vars=child_shared_vars,
                )
            ]
        elif action == "list":
            statuses = request.get("statuses")
            if statuses is not None:
                if not isinstance(statuses, list) or any(
                    not isinstance(status, str) or status not in _STATUSES
                    for status in statuses
                ):
                    raise ValueError(
                        "shared_vars.workflow_run.statuses contains an unsupported status"
                    )
                status_filter = frozenset(statuses)
            else:
                status_filter = None
            results = await facade.list(statuses=status_filter)
        else:
            results = await getattr(facade, action)(_run_ids(request))

        return Command(
            update={
                "shared_vars": {
                    "workflow_run_result": {
                        "action": action,
                        "runs": [_project(result) for result in results],
                    }
                }
            },
            goto=target,
        )

    return command
