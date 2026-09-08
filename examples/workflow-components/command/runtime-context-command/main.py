"""Project Shell context and official LangGraph execution info into Workflow State."""

from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        if not isinstance(shared_vars, dict):
            raise ValueError("state.shared_vars must be an object")
        target = shared_vars.get("runtime_target_node_id")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(
                "shared_vars.runtime_target_node_id must be a non-empty Canvas Node ID"
            )

        context = runtime.context
        if context is None:
            raise RuntimeError("runtime.context is unavailable")
        execution = runtime.execution_info
        if execution is None:
            raise RuntimeError("runtime.execution_info is unavailable")

        return Command(
            update={
                "shared_vars": {
                    "command_runtime": {
                        "context": {
                            "request_id": context.request_id,
                            "lifecycle_id": context.lifecycle_id,
                            "caller_run_id": context.caller_run_id,
                            "operation_id": context.operation_id,
                            "run_id": context.run_id,
                            "workflow_id": context.workflow_id,
                            "workflow_node_id": context.workflow_node_id,
                            "node_invocation_id": context.node_invocation_id,
                        },
                        "execution_info": {
                            "checkpoint_id": execution.checkpoint_id,
                            "checkpoint_ns": execution.checkpoint_ns,
                            "task_id": execution.task_id,
                            "thread_id": execution.thread_id,
                            "run_id": execution.run_id,
                            "node_attempt": execution.node_attempt,
                            "node_first_attempt_time": execution.node_first_attempt_time,
                        },
                    }
                }
            },
            goto=target.strip(),
        )

    return command
